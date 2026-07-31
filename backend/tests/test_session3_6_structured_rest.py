"""Session 3.6 — smoke tests for the remaining structured-data cutover.

Drives representative flows through each migrated domain. Where a full
HTTP endpoint exists we use it; where the surface is deep (accounting
posting engine, payroll accrual, reconciliation), we exercise the adapter
directly to prove reads + writes land in PostgreSQL.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pymongo
import pytest
import requests
from sqlalchemy import create_engine, text

from tests.smoketest_bootstrap import (
    ADMIN_EMAIL, PRACTITIONER_EMAIL, PRACTITIONER_PASSWORD,
    FIXTURE_TOTP_SECRET, ensure_smoketest_admin_and_practitioner,
    login_smoketest_admin,
)


BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8001") + "/api"


def _mongo():
    c = pymongo.MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    return c[os.environ.get("DB_NAME", "test_database")]


def _pg():
    dsn = os.environ["DATABASE_URL"]
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    return create_engine(dsn, future=True)


@pytest.fixture(scope="module")
def admin_token():
    ensure_smoketest_admin_and_practitioner()
    return login_smoketest_admin(BASE_URL)


def _b(tok):
    return {"Authorization": f"Bearer {tok}"}


async def _adapter():
    from deps import db as _db
    return _db


# =========================================================== Accounting
def test_chart_of_accounts_and_journal_entry_lands_in_pg(admin_token):
    """Direct-write through the adapter proves reads + writes hit PG."""
    async def _work():
        db = await _adapter()
        code = f"9{uuid.uuid4().hex[:3]}"
        await db.chart_of_accounts.insert_one({
            "id": uuid.uuid4().hex, "code": code, "name": "Smoke Account",
            "type": "asset", "active": True, "system_locked": False,
        })
        await db.journal_entries.insert_one({
            "id": uuid.uuid4().hex,
            "posted_at": datetime.now(timezone.utc).isoformat(),
            "event_id": uuid.uuid4().hex,
            "lines": [{"code": code, "debit_cents": 100, "credit_cents": 0},
                       {"code": "1100", "debit_cents": 0, "credit_cents": 100}],
        })
        return code

    code = asyncio.run(_work())
    with _pg().begin() as conn:
        n_coa = conn.execute(text(
            "SELECT count(*) FROM emr_chart_of_accounts WHERE code = :c"
        ), {"c": code}).scalar_one()
        n_je = conn.execute(text(
            "SELECT count(*) FROM emr_journal_entries"
        )).scalar_one()
    assert n_coa == 1
    assert n_je >= 1

    # Mongo silent
    assert _mongo().chart_of_accounts.find_one({"code": code}) is None


def test_transactions_and_expense_flow(admin_token):
    async def _work():
        db = await _adapter()
        tid = uuid.uuid4().hex
        await db.transactions.insert_one({
            "id": tid, "client_id": None, "status": "paid",
            "total": 42.50, "payment_method": "cash", "lines": [],
        })
        eid = uuid.uuid4().hex
        await db.expenses.insert_one({
            "id": eid, "category": "supplies", "amount_cents": 1500,
        })
        return tid, eid

    tid, eid = asyncio.run(_work())
    with _pg().begin() as conn:
        assert conn.execute(text(
            "SELECT count(*) FROM emr_transactions WHERE id = :i"
        ), {"i": tid}).scalar_one() == 1
        assert conn.execute(text(
            "SELECT count(*) FROM emr_expenses WHERE id = :i"
        ), {"i": eid}).scalar_one() == 1
    assert _mongo().transactions.find_one({"id": tid}) is None


def test_invoice_and_vendor_bill_flow(admin_token):
    async def _work():
        db = await _adapter()
        vid = uuid.uuid4().hex
        await db.vendors.insert_one({
            "id": vid, "name": "Smoke Vendor", "active": True,
        })
        iid = uuid.uuid4().hex
        await db.invoices.insert_one({
            "id": iid, "client_id": None, "total_cents": 5000,
            "status": "sent",
        })
        bid = uuid.uuid4().hex
        await db.vendor_bills.insert_one({
            "id": bid, "vendor_id": vid, "amount_cents": 12500,
            "status": "accrued",
        })
        return vid, iid, bid

    vid, iid, bid = asyncio.run(_work())
    with _pg().begin() as conn:
        for table, ident in (("emr_vendors", vid),
                              ("emr_invoices", iid),
                              ("emr_vendor_bills", bid)):
            n = conn.execute(text(
                f"SELECT count(*) FROM {table} WHERE id = :i"
            ), {"i": ident}).scalar_one()
            assert n == 1, table


# ============================================================= Banking
def test_bank_account_txn_and_reconciliation_flow(admin_token):
    async def _work():
        db = await _adapter()
        ba_id = uuid.uuid4().hex
        await db.bank_accounts.insert_one({
            "id": ba_id, "name": "Smoke Bank", "kind": "checking",
            "gl_code": "1100", "active": True, "system_seeded": False,
        })
        # Import batch
        batch_id = uuid.uuid4().hex
        await db.bank_import_batches.insert_one({
            "id": batch_id, "bank_account_id": ba_id, "filename": "smoke.csv",
            "row_count": 2, "created_at": datetime.now(timezone.utc).isoformat(),
        })
        # Bank transactions
        bt_ids = []
        for amt in (100_00, -50_00):
            t = {"id": uuid.uuid4().hex, "bank_account_id": ba_id,
                 "amount_cents": amt, "batch_id": batch_id,
                 "posted_at": datetime.now(timezone.utc).isoformat(),
                 "description": "Smoke txn"}
            await db.bank_transactions.insert_one(t)
            bt_ids.append(t["id"])
        # Reconciliation
        rec_id = uuid.uuid4().hex
        await db.reconciliations.insert_one({
            "id": rec_id, "bank_account_id": ba_id, "status": "in_progress",
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
        # Transfer
        xfer_id = uuid.uuid4().hex
        await db.bank_transfers.insert_one({
            "id": xfer_id, "from_account_id": ba_id, "to_account_id": ba_id,
            "amount_cents": 5000, "status": "posted",
        })
        # Filtered read: find bank transactions for this account
        found = await db.bank_transactions.find(
            {"bank_account_id": ba_id}
        ).sort("posted_at", 1).to_list(10)
        return ba_id, bt_ids, rec_id, xfer_id, found

    ba_id, bt_ids, rec_id, xfer_id, found = asyncio.run(_work())
    assert len(found) == 2
    with _pg().begin() as conn:
        assert conn.execute(text(
            "SELECT count(*) FROM emr_bank_accounts WHERE id = :i"
        ), {"i": ba_id}).scalar_one() == 1
        assert conn.execute(text(
            "SELECT count(*) FROM emr_bank_transactions WHERE bank_account_id = :i"
        ), {"i": ba_id}).scalar_one() == 2
        assert conn.execute(text(
            "SELECT count(*) FROM emr_reconciliations WHERE id = :i"
        ), {"i": rec_id}).scalar_one() == 1
        assert conn.execute(text(
            "SELECT count(*) FROM emr_bank_transfers WHERE id = :i"
        ), {"i": xfer_id}).scalar_one() == 1
    assert _mongo().bank_accounts.find_one({"id": ba_id}) is None
    assert _mongo().bank_transactions.find_one({"bank_account_id": ba_id}) is None


# ============================================================= Payroll
def test_employee_payroll_and_timeclock(admin_token):
    async def _work():
        db = await _adapter()
        emp_id = uuid.uuid4().hex
        await db.employees.insert_one({
            "id": emp_id, "user_id": None, "name": "Smoke Employee",
            "pay_rate_cents": 5000, "active": True,
        })
        run_id = uuid.uuid4().hex
        await db.payroll_runs.insert_one({
            "id": run_id, "period_start": "2026-08-01",
            "period_end": "2026-08-15", "status": "accrued",
            "gross_cents": 50000,
        })
        te_id = uuid.uuid4().hex
        await db.time_entries.insert_one({
            "id": te_id, "user_id": emp_id,
            "clock_in": datetime.now(timezone.utc).isoformat(),
            "clock_out": None, "breaks": [],
        })
        # Query time_entries by user_id (uses typed column index)
        entries = await db.time_entries.find({"user_id": emp_id}).to_list(10)
        return emp_id, run_id, te_id, entries

    emp_id, run_id, te_id, entries = asyncio.run(_work())
    assert len(entries) == 1 and entries[0]["id"] == te_id
    with _pg().begin() as conn:
        for table, ident in (("emr_employees", emp_id),
                              ("emr_payroll_runs", run_id),
                              ("emr_time_entries", te_id)):
            n = conn.execute(text(
                f"SELECT count(*) FROM {table} WHERE id = :i"
            ), {"i": ident}).scalar_one()
            assert n == 1, table


# =========================================================== Inventory
def test_inventory_adjust_lands_in_pg(admin_token):
    """Uses the real /inventory HTTP surface to exercise both
    inventory_items + inventory_transactions in one flow."""
    rc = requests.post(f"{BASE_URL}/inventory", headers=_b(admin_token),
                        json={"name": f"Smoke Item {uuid.uuid4().hex[:6]}",
                              "sku": None, "stock": 10, "unit_price": 5.0,
                              "low_stock_threshold": 3, "active": True})
    assert rc.status_code == 200, rc.text
    iid = rc.json()["id"]

    ra = requests.post(f"{BASE_URL}/inventory/{iid}/adjust",
                        headers=_b(admin_token),
                        json={"delta": -2, "reason": "smoke",
                              "note": "adapter test"})
    assert ra.status_code == 200
    assert ra.json()["stock"] == 8

    with _pg().begin() as conn:
        n_item = conn.execute(text(
            "SELECT count(*) FROM emr_inventory_items WHERE id = :i"
        ), {"i": iid}).scalar_one()
        n_tx = conn.execute(text(
            "SELECT count(*) FROM emr_inventory_transactions "
            "WHERE payload->>'item_id' = :i"
        ), {"i": iid}).scalar_one()
    assert n_item == 1 and n_tx >= 1

    # Mongo silent
    assert _mongo().inventory_items.find_one({"id": iid}) is None


# =============================================================== Legal
def test_legal_policy_and_acceptance(admin_token):
    async def _work():
        db = await _adapter()
        # Seed a temp policy
        pol_id = uuid.uuid4().hex
        await db.legal_policies.insert_one({
            "id": pol_id,
            "slug": f"smoke-policy-{uuid.uuid4().hex[:6]}",
            "name": "Smoke Policy",
            "current_version": "1.0",
            "versions": [{"version": "1.0", "body_html": "<p>hi</p>"}],
        })
        # Acceptance
        acc_id = uuid.uuid4().hex
        await db.legal_acceptances.insert_one({
            "id": acc_id, "user_id": "user-42", "policy_id": pol_id,
            "version_accepted": "1.0",
            "accepted_at": datetime.now(timezone.utc).isoformat(),
        })
        # BAA record
        baa_id = uuid.uuid4().hex
        await db.baa_records.insert_one({
            "id": baa_id, "counterparty": "Vendor X",
            "signed_at": datetime.now(timezone.utc).isoformat(),
        })
        return pol_id, acc_id, baa_id

    pol_id, acc_id, baa_id = asyncio.run(_work())
    with _pg().begin() as conn:
        for table, ident in (("emr_legal_policies", pol_id),
                              ("emr_legal_acceptances", acc_id),
                              ("emr_baa_records", baa_id)):
            n = conn.execute(text(
                f"SELECT count(*) FROM {table} WHERE id = :i"
            ), {"i": ident}).scalar_one()
            assert n == 1, table
    assert _mongo().legal_policies.find_one({"id": pol_id}) is None


# ============================================================ Security
def test_breakglass_and_ws_ticket_persistence(admin_token):
    async def _work():
        db = await _adapter()
        bg_id = uuid.uuid4().hex
        await db.breakglass_sessions.insert_one({
            "id": bg_id, "user_id": "auditor-42",
            "reason": "smoke session",
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
            "active": True,
        })
        # ws_tickets (routers/telehealth: find_one_and_update + insert_one)
        wt_id = uuid.uuid4().hex
        await db.ws_tickets.insert_one({
            "id": wt_id, "user_id": "u1", "appointment_id": "a1",
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
        })
        # find_one_and_update with return_document semantics
        upd = await db.ws_tickets.find_one_and_update(
            {"id": wt_id}, {"$set": {"consumed": True}},
            return_document=True,
        )
        return bg_id, wt_id, upd

    bg_id, wt_id, upd = asyncio.run(_work())
    assert upd["consumed"] is True
    with _pg().begin() as conn:
        assert conn.execute(text(
            "SELECT count(*) FROM emr_breakglass_sessions WHERE id = :i"
        ), {"i": bg_id}).scalar_one() == 1
        assert conn.execute(text(
            "SELECT count(*) FROM emr_ws_tickets WHERE id = :i"
        ), {"i": wt_id}).scalar_one() == 1

    # Mongo silent
    assert _mongo().breakglass_sessions.find_one({"id": bg_id}) is None
    assert _mongo().ws_tickets.find_one({"id": wt_id}) is None


# =========================================== Ops / accounting infrastructure
def test_accounting_events_and_dead_letter_and_backfill(admin_token):
    async def _work():
        db = await _adapter()
        ev_id = uuid.uuid4().hex
        idem = f"smoke:{uuid.uuid4().hex}"
        await db.accounting_events.insert_one({
            "id": ev_id, "idempotency_key": idem,
            "event_type": "SaleCompleted", "source_module": "smoke",
            "amount_cents": 100,
        })
        # dedupe check
        existing = await db.accounting_events.find_one({"idempotency_key": idem})
        assert existing and existing["id"] == ev_id

        dl_id = uuid.uuid4().hex
        await db.posting_dead_letters.insert_one({
            "id": dl_id, "event_id": ev_id, "reason": "smoke rejection",
        })
        run_id = uuid.uuid4().hex
        await db.accounting_backfill_runs.insert_one({
            "id": run_id, "sources": ["pos"], "status": "completed",
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
        vip_id = uuid.uuid4().hex
        await db.vip_list.insert_one({
            "id": vip_id, "email": "vip@example.test",
        })
        imp_id = uuid.uuid4().hex
        await db.imported_batches.insert_one({
            "id": imp_id, "filename": "smoke.csv", "imported": 5,
        })
        return ev_id, dl_id, run_id, vip_id, imp_id

    ev_id, dl_id, run_id, vip_id, imp_id = asyncio.run(_work())
    with _pg().begin() as conn:
        for table, ident in (("emr_accounting_events", ev_id),
                              ("emr_posting_dead_letters", dl_id),
                              ("emr_accounting_backfill_runs", run_id),
                              ("emr_vip_list", vip_id),
                              ("emr_imported_batches", imp_id)):
            n = conn.execute(text(
                f"SELECT count(*) FROM {table} WHERE id = :i"
            ), {"i": ident}).scalar_one()
            assert n == 1, table
