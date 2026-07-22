"""
Sprint 1.5 — Accounting Stabilization tests.

Covers:
    * Historic backfill dry-run + execute end-to-end.
    * Idempotency: re-running never double-posts.
    * Resume-after-interruption path.
    * Ledger validation endpoint shape + core checks.
    * Dashboard endpoint aggregates the ledger correctly.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import pymongo
import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"

ADMIN = ("admin@natmedsol.local", "Admin!2345")


def _login(email, password):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json().get("access_token")


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def tok():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def dbm():
    c = pymongo.MongoClient(os.environ["MONGO_URL"])
    yield c[os.environ["DB_NAME"]]
    c.close()


# --------------------------------------------------------------------------- #
# Dashboard                                                                    #
# --------------------------------------------------------------------------- #
class TestDashboard:
    def test_dashboard_returns_all_widgets(self, tok):
        r = requests.get(f"{API}/accounting/dashboard",
                         headers=_h(tok), timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        for key in (
            "cash_position_cents", "accounts_receivable_cents",
            "accounts_payable_cents", "revenue_mtd_cents",
            "revenue_today_cents", "sales_tax_liability_cents",
            "payroll_liability_cents", "dead_letter_count",
            "unposted_event_count", "trial_balance",
        ):
            assert key in j, f"dashboard missing {key}"
        assert "balanced" in j["trial_balance"]
        assert "debit_cents" in j["trial_balance"]

    def test_dashboard_tb_matches_reports(self, tok):
        d = requests.get(f"{API}/accounting/dashboard",
                         headers=_h(tok), timeout=15).json()
        tb = requests.get(f"{API}/accounting/reports/trial-balance",
                          headers=_h(tok), timeout=15).json()
        assert d["trial_balance"]["balanced"] == tb["balanced"]
        assert d["trial_balance"]["debit_cents"] == tb["total_debit_cents"]
        assert d["trial_balance"]["credit_cents"] == tb["total_credit_cents"]


# --------------------------------------------------------------------------- #
# Validation                                                                   #
# --------------------------------------------------------------------------- #
class TestValidation:
    def test_validate_returns_all_checks(self, tok):
        r = requests.get(f"{API}/accounting/validate",
                         headers=_h(tok), timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "healthy" in j and "checks" in j
        for name in (
            "trial_balance", "balance_sheet", "orphan_entries",
            "missing_sources", "dead_letters", "duplicate_events",
            "journal_integrity",
        ):
            assert name in j["checks"], f"missing check {name}"
            assert "ok" in j["checks"][name]

    def test_trial_balance_and_bs_are_ok(self, tok):
        j = requests.get(f"{API}/accounting/validate",
                         headers=_h(tok), timeout=30).json()
        # These must be TRUE for a healthy immutable ledger.
        assert j["checks"]["trial_balance"]["ok"] is True
        assert j["checks"]["balance_sheet"]["ok"] is True
        assert j["checks"]["duplicate_events"]["ok"] is True
        assert j["checks"]["journal_integrity"]["ok"] is True

    def test_validation_healthy_reflects_dead_letters(self, tok, dbm):
        j = requests.get(f"{API}/accounting/validate",
                         headers=_h(tok), timeout=30).json()
        dl_count = j["checks"]["dead_letters"]["count"]
        # ok == True iff no dead letters
        assert j["checks"]["dead_letters"]["ok"] is (dl_count == 0)
        # healthy field must aggregate all checks
        derived = all(c["ok"] for c in j["checks"].values())
        assert j["healthy"] is derived


# --------------------------------------------------------------------------- #
# Backfill — dry run + execute + idempotency                                    #
# --------------------------------------------------------------------------- #
class TestBackfill:
    def _seed_source_docs(self, dbm):
        """Insert synthetic source docs the backfill can walk. Uses a marker
        so tests don't pollute other suites."""
        tag = f"s15-{int(time.time())}"
        now = datetime.now(timezone.utc)
        # Client
        client_id = f"cli-{tag}"
        dbm.clients.insert_one({
            "id": client_id, "full_name": f"Backfill Test {tag}",
            "email": f"{tag}@ex.com", "created_at": now,
        })
        # POS transaction (paid) — used for SaleCompleted
        txn_id = f"txn-{tag}"
        dbm.transactions.insert_one({
            "id": txn_id, "client_id": client_id, "status": "paid",
            "created_at": now - timedelta(days=2), "created_by": "system",
            "lines": [{"type": "custom", "name": "Backfill svc",
                       "qty": 1, "unit_price": 100.0, "line_total": 100.0}],
            "subtotal": 100.0, "discount": 0.0, "tip": 0.0, "tax": 8.0,
            "total": 108.0, "payment_method": "cash",
        })
        # Invoice (paid) — used for both InvoiceIssued + InvoicePaid
        inv_id = f"inv-{tag}"
        dbm.invoices.insert_one({
            "id": inv_id, "client_id": client_id,
            "description": "Backfill invoice", "amount": 250.00,
            "status": "paid",
            "created_at": now - timedelta(days=5),
            "paid_at": now - timedelta(days=1),
            "payment_method": "check",
        })
        return {"tag": tag, "client_id": client_id, "txn_id": txn_id, "inv_id": inv_id}

    def _cleanup(self, dbm, tag):
        for coll, key in [
            ("transactions", "id"), ("invoices", "id"),
            ("clients", "id"), ("accounting_events", "idempotency_key"),
            ("journal_entries", "context.tag"),
        ]:
            try:
                if coll == "accounting_events":
                    dbm[coll].delete_many({"idempotency_key": {"$regex": tag}})
                elif coll == "journal_entries":
                    dbm[coll].delete_many({"source_id": {"$regex": tag}})
                else:
                    dbm[coll].delete_many({"id": {"$regex": tag}})
            except Exception:
                pass

    def test_dry_run_lists_candidates(self, tok, dbm):
        seed = self._seed_source_docs(dbm)
        try:
            r = requests.post(f"{API}/accounting/backfill/dry-run",
                              headers=_h(tok), json={"sources": []}, timeout=30)
            assert r.status_code == 200, r.text
            j = r.json()
            assert j["mode"] == "dry_run"
            # Each source at least reports counters
            for src in ("pos", "invoices", "invoice_payments"):
                assert src in j["per_source"]
                assert j["per_source"][src]["candidates"] >= 1
            # The seeded docs should be counted as would-be-posted
            assert j["totals"]["candidates"] >= 3
        finally:
            self._cleanup(dbm, seed["tag"])

    def test_execute_posts_journal_entries(self, tok, dbm):
        seed = self._seed_source_docs(dbm)
        try:
            r = requests.post(f"{API}/accounting/backfill/execute",
                              headers=_h(tok),
                              json={"sources": ["pos", "invoices",
                                                "invoice_payments"]},
                              timeout=60)
            assert r.status_code == 200, r.text
            run = r.json()
            assert run["status"] == "completed"
            # The 3 seeded events must be posted
            for key in (
                f"transaction:{seed['txn_id']}:SaleCompleted",
                f"invoice:{seed['inv_id']}:InvoiceIssued",
                f"invoice:{seed['inv_id']}:InvoicePaid",
            ):
                ev = dbm.accounting_events.find_one({"idempotency_key": key})
                assert ev is not None, f"missing event {key}"
                je = dbm.journal_entries.find_one({"event_id": ev["id"]})
                assert je is not None, f"missing journal for {key}"
                assert je["total_debits"] == je["total_credits"]
        finally:
            self._cleanup(dbm, seed["tag"])

    def test_execute_is_idempotent(self, tok, dbm):
        seed = self._seed_source_docs(dbm)
        try:
            # First run
            first = requests.post(f"{API}/accounting/backfill/execute",
                                  headers=_h(tok),
                                  json={"sources": ["pos", "invoices",
                                                    "invoice_payments"]},
                                  timeout=60).json()
            posted_1 = first["totals"]["posted"]
            assert posted_1 >= 3

            # Journal count snapshot AFTER first run
            key = f"transaction:{seed['txn_id']}:SaleCompleted"
            ev_id = dbm.accounting_events.find_one(
                {"idempotency_key": key})["id"]
            je_count_before = dbm.journal_entries.count_documents(
                {"event_id": ev_id})
            assert je_count_before == 1

            # Second run — every seeded event should be a duplicate now
            second = requests.post(f"{API}/accounting/backfill/execute",
                                   headers=_h(tok),
                                   json={"sources": ["pos", "invoices",
                                                     "invoice_payments"]},
                                   timeout=60).json()
            # Same seed docs → same idempotency keys → duplicates
            assert second["totals"]["duplicates"] >= 3
            je_count_after = dbm.journal_entries.count_documents(
                {"event_id": ev_id})
            assert je_count_after == je_count_before, \
                "re-running backfill must not create duplicate journal entries"
        finally:
            self._cleanup(dbm, seed["tag"])

    def test_dry_run_after_execute_shows_all_duplicates(self, tok, dbm):
        seed = self._seed_source_docs(dbm)
        try:
            requests.post(f"{API}/accounting/backfill/execute",
                          headers=_h(tok),
                          json={"sources": ["pos"]}, timeout=45)
            dry = requests.post(f"{API}/accounting/backfill/dry-run",
                                headers=_h(tok),
                                json={"sources": ["pos"]}, timeout=30).json()
            # After execute: all POS candidates are already-posted duplicates
            per = dry["per_source"]["pos"]
            assert per["candidates"] >= 1
            assert per["duplicates"] >= 1
            assert per["posted"] == per["candidates"] - per["duplicates"]
        finally:
            self._cleanup(dbm, seed["tag"])

    def test_resume_completes_run(self, tok, dbm):
        seed = self._seed_source_docs(dbm)
        try:
            # Start a run
            r = requests.post(f"{API}/accounting/backfill/execute",
                              headers=_h(tok),
                              json={"sources": ["pos"]}, timeout=60).json()
            run_id = r["id"]
            # Manually mark it as running/interrupted then resume
            dbm.accounting_backfill_runs.update_one(
                {"id": run_id},
                {"$set": {"status": "interrupted", "finished_at": None}},
            )
            resumed = requests.post(
                f"{API}/accounting/backfill/runs/{run_id}/resume",
                headers=_h(tok), timeout=45,
            )
            assert resumed.status_code == 200, resumed.text
            row = dbm.accounting_backfill_runs.find_one({"id": run_id})
            assert row["status"] == "completed"
        finally:
            self._cleanup(dbm, seed["tag"])

    def test_list_and_get_runs(self, tok, dbm):
        seed = self._seed_source_docs(dbm)
        try:
            requests.post(f"{API}/accounting/backfill/execute",
                          headers=_h(tok),
                          json={"sources": ["pos"]}, timeout=45)
            runs = requests.get(f"{API}/accounting/backfill/runs",
                                headers=_h(tok), timeout=15).json()
            assert isinstance(runs, list) and len(runs) >= 1
            rid = runs[0]["id"]
            one = requests.get(f"{API}/accounting/backfill/runs/{rid}",
                               headers=_h(tok), timeout=15).json()
            assert one["id"] == rid
            assert "counters" in one and "cursors" in one
        finally:
            self._cleanup(dbm, seed["tag"])
