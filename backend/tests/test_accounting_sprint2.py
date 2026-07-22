"""
Sprint 2 — Banking & Cash Management focused tests.
"""
from __future__ import annotations

import io
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


@pytest.fixture(scope="module")
def checking_account(tok):
    """The seeded Operating Checking account (gl 1100)."""
    r = requests.get(f"{API}/accounting/bank-accounts", headers=_h(tok), timeout=10)
    assert r.status_code == 200
    for a in r.json():
        if a["gl_account_code"] == "1100":
            return a
    pytest.fail("Operating Checking seeded account missing")


# --------------------------------------------------------------------------- #
# Bank accounts                                                                #
# --------------------------------------------------------------------------- #
class TestBankAccounts:
    def test_seed_5_default_accounts(self, tok):
        r = requests.get(f"{API}/accounting/bank-accounts", headers=_h(tok), timeout=10)
        assert r.status_code == 200
        accts = r.json()
        codes = {a["gl_account_code"] for a in accts if a.get("system_seeded")}
        for code in ("1000", "1050", "1100", "1200", "2500"):
            assert code in codes, f"seed missing {code}"

    def test_create_bank_account(self, tok):
        r = requests.post(f"{API}/accounting/bank-accounts", headers=_h(tok),
                          json={"name": f"Savings {int(time.time())}",
                                "kind": "savings", "gl_account_code": "1500",
                                "institution": "Ally", "last_four": "9999"},
                          timeout=10)
        assert r.status_code == 200, r.text
        assert r.json()["system_seeded"] is False


# --------------------------------------------------------------------------- #
# CSV import                                                                   #
# --------------------------------------------------------------------------- #
CSV_SAMPLE = (
    "date,description,amount,reference,balance\n"
    "2026-06-01,Client Deposit ABC,500.00,CHK-001,10500.00\n"
    "2026-06-03,Utility Bill,-125.50,UTIL-1,10374.50\n"
    "2026-06-05,Client Deposit XYZ,750.00,CHK-002,11124.50\n"
)


class TestStatementImport:
    def test_csv_import_creates_transactions(self, tok, checking_account, dbm):
        # Wipe prior test-imported rows for this account with the same refs
        dbm.bank_transactions.delete_many({
            "bank_account_id": checking_account["id"],
            "reference": {"$in": ["CHK-001", "CHK-002", "UTIL-1"]},
        })
        files = {"file": ("test.csv", CSV_SAMPLE, "text/csv")}
        r = requests.post(
            f"{API}/accounting/bank-accounts/{checking_account['id']}/import",
            headers=_h(tok), files=files, timeout=20,
        )
        assert r.status_code == 200, r.text
        batch = r.json()
        assert batch["row_count_new"] == 3
        # Re-uploading same file → all duplicates
        files = {"file": ("test.csv", CSV_SAMPLE, "text/csv")}
        r2 = requests.post(
            f"{API}/accounting/bank-accounts/{checking_account['id']}/import",
            headers=_h(tok), files=files, timeout=20,
        )
        assert r2.status_code == 200
        assert r2.json()["row_count_duplicate"] == 3
        assert r2.json()["row_count_new"] == 0

    def test_bad_ofx_falls_back_gracefully(self, tok, checking_account):
        # Malformed content served as .ofx should error cleanly, not crash.
        files = {"file": ("bad.ofx", "not-a-real-ofx", "application/x-ofx")}
        r = requests.post(
            f"{API}/accounting/bank-accounts/{checking_account['id']}/import",
            headers=_h(tok), files=files, timeout=20,
        )
        assert r.status_code == 400


# --------------------------------------------------------------------------- #
# Auto-match, manual match, split                                              #
# --------------------------------------------------------------------------- #
def _seed_je_and_bt(dbm, ba_id, gl_code, amount_cents, days_ago=0):
    """Insert one journal_entry with a line on gl_code + a matching bank_txn."""
    now = datetime.now(timezone.utc) - timedelta(days=days_ago)
    tag = f"s2-{int(time.time()*1000)}-{amount_cents}"
    je = {
        "id": f"je-{tag}", "event_id": f"ev-{tag}",
        "posted_at": now, "memo": f"S2 test {tag}",
        "source_type": "test", "source_id": tag,
        "lines": [
            {"account_code": gl_code, "debit_cents": max(0, amount_cents),
             "credit_cents": max(0, -amount_cents)},
            {"account_code": "4400", "debit_cents": max(0, -amount_cents),
             "credit_cents": max(0, amount_cents)},
        ],
        "total_debits": abs(amount_cents), "total_credits": abs(amount_cents),
        "reconciliation_id": None,
    }
    bt = {
        "id": f"bt-{tag}", "bank_account_id": ba_id, "posted_at": now,
        "description": f"Test bank {tag}", "amount_cents": amount_cents,
        "reference": None, "status": "unmatched",
        "matched_journal_entry_ids": [], "reconciliation_id": None,
        "created_at": now,
    }
    dbm.journal_entries.insert_one(je)
    dbm.bank_transactions.insert_one(bt)
    return je, bt


class TestMatching:
    def test_manual_match(self, tok, dbm, checking_account):
        je, bt = _seed_je_and_bt(dbm, checking_account["id"], "1100", 12345)
        try:
            r = requests.post(f"{API}/accounting/reconciliation/match",
                              headers=_h(tok),
                              json={"bank_transaction_id": bt["id"],
                                    "journal_entry_id": je["id"]}, timeout=10)
            assert r.status_code == 200, r.text
            bt2 = dbm.bank_transactions.find_one({"id": bt["id"]})
            assert bt2["status"] == "matched"
            assert je["id"] in bt2["matched_journal_entry_ids"]
        finally:
            dbm.bank_transactions.delete_one({"id": bt["id"]})
            dbm.journal_entries.delete_one({"id": je["id"]})

    def test_manual_match_amount_mismatch_rejected(self, tok, dbm, checking_account):
        je, bt = _seed_je_and_bt(dbm, checking_account["id"], "1100", 100)
        bt["amount_cents"] = 999
        dbm.bank_transactions.update_one({"id": bt["id"]},
                                          {"$set": {"amount_cents": 999}})
        try:
            r = requests.post(f"{API}/accounting/reconciliation/match",
                              headers=_h(tok),
                              json={"bank_transaction_id": bt["id"],
                                    "journal_entry_id": je["id"]}, timeout=10)
            assert r.status_code == 400
            assert "amount mismatch" in r.text
        finally:
            dbm.bank_transactions.delete_one({"id": bt["id"]})
            dbm.journal_entries.delete_one({"id": je["id"]})

    def test_auto_match_finds_and_scores(self, tok, dbm, checking_account):
        je, bt = _seed_je_and_bt(dbm, checking_account["id"], "1100", 87654)
        # Move JE description to increase confidence
        dbm.journal_entries.update_one({"id": je["id"]},
                                        {"$set": {"memo": bt["description"]}})
        try:
            r = requests.post(
                f"{API}/accounting/reconciliation/{checking_account['id']}/auto-match",
                headers=_h(tok), timeout=15,
            )
            assert r.status_code == 200, r.text
            props = r.json().get("proposals", [])
            found = [p for p in props if p["bank_transaction_id"] == bt["id"]]
            assert found, "auto-match must find the seeded pair"
            assert found[0]["journal_entry_id"] == je["id"]
            assert found[0]["confidence"] > 60
        finally:
            dbm.bank_transactions.delete_one({"id": bt["id"]})
            dbm.journal_entries.delete_one({"id": je["id"]})

    def test_split_across_two_journal_entries(self, tok, dbm, checking_account):
        je1, _ = _seed_je_and_bt(dbm, checking_account["id"], "1100", 3000)
        je2, _ = _seed_je_and_bt(dbm, checking_account["id"], "1100", 7000)
        # Delete the two auto-created bank txns; make one combined bank txn
        dbm.bank_transactions.delete_many({"bank_account_id": checking_account["id"],
                                            "amount_cents": {"$in": [3000, 7000]}})
        tag = f"s2split-{int(time.time()*1000)}"
        bt = {"id": f"bt-{tag}", "bank_account_id": checking_account["id"],
              "posted_at": datetime.now(timezone.utc),
              "description": "combined deposit", "amount_cents": 10000,
              "reference": None, "status": "unmatched",
              "matched_journal_entry_ids": [], "reconciliation_id": None,
              "created_at": datetime.now(timezone.utc)}
        dbm.bank_transactions.insert_one(bt)
        try:
            r = requests.post(f"{API}/accounting/reconciliation/split",
                              headers=_h(tok),
                              json={"bank_transaction_id": bt["id"],
                                    "journal_entry_ids": [je1["id"], je2["id"]]},
                              timeout=10)
            assert r.status_code == 200, r.text
            bt2 = dbm.bank_transactions.find_one({"id": bt["id"]})
            assert bt2["status"] == "split"
            assert set(bt2["matched_journal_entry_ids"]) == {je1["id"], je2["id"]}
        finally:
            dbm.bank_transactions.delete_one({"id": bt["id"]})
            dbm.journal_entries.delete_many({"id": {"$in": [je1["id"], je2["id"]]}})


# --------------------------------------------------------------------------- #
# Finalize                                                                     #
# --------------------------------------------------------------------------- #
class TestFinalize:
    def test_finalize_writes_reconciliation(self, tok, dbm, checking_account):
        je, bt = _seed_je_and_bt(dbm, checking_account["id"], "1100", 4321)
        # Match first
        r = requests.post(f"{API}/accounting/reconciliation/match",
                          headers=_h(tok),
                          json={"bank_transaction_id": bt["id"],
                                "journal_entry_id": je["id"]}, timeout=10)
        assert r.status_code == 200
        try:
            end = datetime.now(timezone.utc) + timedelta(days=1)
            r = requests.post(f"{API}/accounting/reconciliation/finalize",
                              headers=_h(tok),
                              json={"bank_account_id": checking_account["id"],
                                    "statement_end_date": end.isoformat(),
                                    "ending_balance_cents": 4321,
                                    "notes": "sprint2 test"}, timeout=15)
            assert r.status_code == 200, r.text
            rec_id = r.json()["id"]
            # Bank txn + JE both marked
            bt2 = dbm.bank_transactions.find_one({"id": bt["id"]})
            je2 = dbm.journal_entries.find_one({"id": je["id"]})
            assert bt2["status"] == "reconciled"
            assert bt2["reconciliation_id"] == rec_id
            assert je2["reconciliation_id"] == rec_id
            # Immutability: total_debits/credits/lines unchanged
            assert je2["total_debits"] == je["total_debits"]
            assert je2["total_credits"] == je["total_credits"]
            assert len(je2["lines"]) == len(je["lines"])
            # Report retrievable
            rep = requests.get(f"{API}/accounting/reconciliation/{rec_id}/report",
                               headers=_h(tok), timeout=15).json()
            assert rep["reconciliation"]["id"] == rec_id
        finally:
            dbm.reconciliations.delete_many({"bank_txn_ids": bt["id"]})
            dbm.bank_transactions.delete_one({"id": bt["id"]})
            dbm.journal_entries.delete_one({"id": je["id"]})


# --------------------------------------------------------------------------- #
# Cash transfer posting                                                        #
# --------------------------------------------------------------------------- #
class TestTransfer:
    def test_transfer_creates_balanced_journal(self, tok, dbm, checking_account):
        # Second account: petty cash 1000
        r = requests.get(f"{API}/accounting/bank-accounts",
                         headers=_h(tok), timeout=10).json()
        petty = next(a for a in r if a["gl_account_code"] == "1000")
        r = requests.post(f"{API}/accounting/transfers", headers=_h(tok),
                          json={"from_bank_account_id": checking_account["id"],
                                "to_bank_account_id": petty["id"],
                                "amount_cents": 5000,
                                "memo": "petty cash refill"}, timeout=15)
        assert r.status_code == 200, r.text
        transfer = r.json()
        # Locate the journal entry
        ev = dbm.accounting_events.find_one({"id": transfer["event_id"]})
        je = dbm.journal_entries.find_one({"event_id": ev["id"]})
        assert je is not None
        assert je["total_debits"] == je["total_credits"] == 5000
        codes = {ln["account_code"]: (ln["debit_cents"], ln["credit_cents"]) for ln in je["lines"]}
        assert codes["1000"] == (5000, 0)   # DR destination
        assert codes["1100"] == (0, 5000)   # CR source


# --------------------------------------------------------------------------- #
# Cash dashboard                                                               #
# --------------------------------------------------------------------------- #
class TestCashDashboard:
    def test_dashboard_returns_all_accounts(self, tok):
        r = requests.get(f"{API}/accounting/cash/dashboard",
                         headers=_h(tok), timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        for k in ("current_cash_cents", "cleared_cash_cents",
                  "outstanding_deposits_cents", "outstanding_checks_cents"):
            assert k in j["totals"]
        assert len(j["accounts"]) >= 5
        for a in j["accounts"]:
            for k in ("ledger_balance_cents", "cleared_balance_cents",
                      "outstanding_deposits_cents", "outstanding_checks_cents",
                      "bank_balance_cents", "difference_cents"):
                assert k in a


# --------------------------------------------------------------------------- #
# Reports                                                                      #
# --------------------------------------------------------------------------- #
class TestReports:
    def test_all_reports_respond(self, tok, checking_account):
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=30)).isoformat()
        end = now.isoformat()
        for path, params in [
            (f"/accounting/cash/register/{checking_account['id']}", {}),
            ("/accounting/cash/flow", {"start": start, "end": end}),
            ("/accounting/cash/outstanding-deposits", {}),
            ("/accounting/cash/outstanding-checks", {}),
            ("/accounting/cash/outstanding-reconciliation", {}),
            ("/accounting/reconciliation/exceptions", {}),
            ("/accounting/stripe/settlement", {"start": start, "end": end}),
        ]:
            r = requests.get(f"{API}{path}", headers=_h(tok),
                             params=params, timeout=15)
            assert r.status_code == 200, f"{path}: {r.text[:200]}"
