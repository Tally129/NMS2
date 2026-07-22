"""
Sprint 1 — Accounting foundation focused tests.
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


class TestFoundation:
    def test_coa_seeded(self, tok):
        r = requests.get(f"{API}/accounting/accounts", headers=_h(tok), timeout=10)
        assert r.status_code == 200
        codes = [a["code"] for a in r.json()]
        # Every critical account must exist
        for c in ("1000", "1100", "1200", "1300", "1400", "2000",
                  "2200", "2300", "2400", "4100", "4200", "4300",
                  "5100", "6200", "6900"):
            assert c in codes, f"missing seed account {c}"

    def test_system_locked_cannot_delete_type(self, tok):
        r = requests.patch(f"{API}/accounting/accounts/1100",
                            headers=_h(tok), json={"type": "expense"}, timeout=10)
        assert r.status_code == 200
        acct = r.json()
        assert acct["type"] == "asset", "system-locked account type must not change"

    def test_manual_journal_balanced(self, tok):
        r = requests.post(f"{API}/accounting/journal/manual",
                           headers=_h(tok),
                           json={"memo": "test balanced",
                                 "lines": [
                                    {"account_code": "1000", "debit_cents": 5000},
                                    {"account_code": "4400", "credit_cents": 5000},
                                 ]},
                           timeout=10)
        assert r.status_code == 200
        assert r.json()["status"] == "posted"

    def test_manual_journal_unbalanced_dead_letter(self, tok, dbm):
        before = dbm.posting_dead_letters.count_documents({})
        r = requests.post(f"{API}/accounting/journal/manual",
                           headers=_h(tok),
                           json={"memo": "unbalanced test",
                                 "lines": [
                                    {"account_code": "1000", "debit_cents": 100},
                                    {"account_code": "4400", "credit_cents": 200},
                                 ]},
                           timeout=10)
        assert r.status_code == 400
        assert dbm.posting_dead_letters.count_documents({}) == before + 1


class TestPosSaleAutoPost:
    def test_pos_checkout_emits_and_posts(self, tok, dbm):
        # Trigger a real POS checkout (not a demo — reuses the production endpoint)
        r = requests.post(
            f"{API}/pos/checkout", headers=_h(tok),
            json={"lines": [{"type": "custom", "name": "Test service",
                             "qty": 1, "unit_price": 150.00}],
                  "tax_rate": 0.08, "tip": 20.0,
                  "payment_method": "stripe"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        txn = r.json()
        # Should have created an accounting event + journal entry
        ev = dbm.accounting_events.find_one(
            {"source_ref_type": "transaction", "source_ref_id": txn["id"]})
        assert ev is not None
        assert ev["event_type"] == "SaleCompleted"
        assert ev["amount_cents"] == 18200      # 150 + 12 tax + 20 tip
        je = dbm.journal_entries.find_one({"event_id": ev["id"]})
        assert je is not None
        assert je["total_debits"] == je["total_credits"]
        # Verify 4 lines: stripe clearing DR + service revenue CR + sales tax CR + tips CR
        codes = {l["account_code"] for l in je["lines"]}
        assert "1200" in codes and "4100" in codes and "2200" in codes and "2300" in codes


class TestIdempotency:
    def test_duplicate_emission_no_double_post(self, tok, dbm):
        # Directly emit the same event twice via manual journal is the only route,
        # so we test the underlying idempotency by inserting an accounting_event
        # with the same idempotency_key and confirming only one journal_entry.
        key = f"idempotency_test:{int(time.time())}"
        for _ in range(2):
            r = requests.post(f"{API}/accounting/journal/manual",
                              headers=_h(tok),
                              json={"memo": "idempotent test",
                                    "lines": [
                                        {"account_code": "1000", "debit_cents": 700},
                                        {"account_code": "4400", "credit_cents": 700},
                                    ]}, timeout=10)
            assert r.status_code == 200
        # ManualJournal uses unique idempotency_key per call, so there ARE 2 entries.
        # Confirm idempotency at the DB layer: duplicate insert on accounting_events
        # with same key is silently rejected by the unique index.
        try:
            dbm.accounting_events.insert_one({
                "id": "test-dup-a", "idempotency_key": key,
                "event_type": "SaleCompleted", "recorded_at": datetime.now(timezone.utc),
                "amount_cents": 1000, "source_ref_id": "x", "source_ref_type": "x",
                "source_module": "test",
            })
            dbm.accounting_events.insert_one({
                "id": "test-dup-b", "idempotency_key": key,
                "event_type": "SaleCompleted", "recorded_at": datetime.now(timezone.utc),
                "amount_cents": 1000, "source_ref_id": "x", "source_ref_type": "x",
                "source_module": "test",
            })
            pytest.fail("Duplicate idempotency_key should have raised")
        except pymongo.errors.DuplicateKeyError:
            pass
        finally:
            dbm.accounting_events.delete_many({"idempotency_key": key})


class TestExpensesAndBills:
    def test_expense_records_and_posts(self, tok, dbm):
        r = requests.post(f"{API}/accounting/expenses", headers=_h(tok),
                          json={"amount_cents": 12500,
                                "expense_account": "6000",
                                "payment_method": "check",
                                "memo": "Monthly rent"}, timeout=10)
        assert r.status_code == 200
        exp = r.json()
        je = dbm.journal_entries.find_one({"event_id": exp["event_id"]})
        assert je is not None
        # DR 6000 CR 1100
        codes = {l["account_code"]: (l["debit_cents"], l["credit_cents"]) for l in je["lines"]}
        assert codes["6000"] == (12500, 0)
        assert codes["1100"] == (0, 12500)

    def test_vendor_bill_lifecycle(self, tok, dbm):
        # Create vendor
        v = requests.post(f"{API}/accounting/vendors", headers=_h(tok),
                          json={"name": "Acme Supplies", "is_1099": False,
                                "default_expense_account": "6400"}, timeout=10).json()
        b = requests.post(f"{API}/accounting/bills", headers=_h(tok),
                          json={"vendor_id": v["id"], "amount_cents": 30000,
                                "expense_account": "6400",
                                "memo": "office supplies"}, timeout=10).json()
        # Accrue: DR 6400 CR 2000
        je1 = dbm.journal_entries.find_one({"event_id": b["event_id"]})
        codes1 = {l["account_code"] for l in je1["lines"]}
        assert "6400" in codes1 and "2000" in codes1
        # Pay
        r = requests.post(f"{API}/accounting/bills/{b['id']}/pay",
                          headers=_h(tok), params={"payment_method": "check"},
                          timeout=10)
        assert r.status_code == 200
        je2 = dbm.journal_entries.find_one({"event_id": r.json()["event_id"]})
        codes2 = {l["account_code"] for l in je2["lines"]}
        assert "2000" in codes2 and "1100" in codes2   # DR AP / CR bank


class TestPayroll:
    def test_payroll_accrue_and_pay(self, tok, dbm):
        # employee
        e = requests.post(f"{API}/accounting/employees", headers=_h(tok),
                          json={"full_name": "Test Payroll Emp",
                                "kind": "hourly", "hourly_rate_cents": 3000}, timeout=10).json()
        now = datetime.now(timezone.utc)
        payload = {
            "period_start": (now - timedelta(days=14)).isoformat(),
            "period_end": now.isoformat(),
            "memo": "biweekly",
            "lines": [{
                "employee_id": e["id"],
                "gross_cents": 240000, "taxes_cents": 20000,
                "commission_cents": 0, "bonus_cents": 0,
                "pto_hours_used": 0, "pto_hours_accrued": 4,
            }],
        }
        r = requests.post(f"{API}/accounting/payroll/runs", headers=_h(tok),
                          json=payload, timeout=15)
        assert r.status_code == 200, r.text
        run = r.json()
        # PayrollAccrued: DR 6200 + 6210, CR 2400 + 2410
        je = dbm.journal_entries.find_one({"event_id": run["event_id"]})
        codes = {l["account_code"] for l in je["lines"]}
        assert {"6200", "6210", "2400", "2410"}.issubset(codes)
        assert je["total_debits"] == je["total_credits"]
        # Pay
        rp = requests.post(f"{API}/accounting/payroll/runs/{run['run_id']}/pay",
                           headers=_h(tok), params={"payment_method": "check"},
                           timeout=10)
        assert rp.status_code == 200


class TestReports:
    def test_reports_all_return(self, tok):
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=90)).isoformat()
        end = now.isoformat()
        for path, params in [
            ("/accounting/reports/profit-and-loss", {"start": start, "end": end}),
            ("/accounting/reports/balance-sheet", {"as_of": end}),
            ("/accounting/reports/trial-balance", {}),
            ("/accounting/reports/ar-aging", {}),
        ]:
            r = requests.get(f"{API}{path}", headers=_h(tok),
                             params=params, timeout=15)
            assert r.status_code == 200, f"{path}: {r.text[:200]}"

    def test_trial_balance_is_balanced(self, tok):
        r = requests.get(f"{API}/accounting/reports/trial-balance",
                          headers=_h(tok), timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert j["balanced"] is True, \
            f"TB unbalanced: DR={j['total_debit_cents']} CR={j['total_credit_cents']}"

    def test_balance_sheet_is_balanced(self, tok):
        r = requests.get(f"{API}/accounting/reports/balance-sheet",
                          headers=_h(tok), timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert j["balanced"] is True, "Balance Sheet must balance"


class TestReversal:
    def test_reverse_creates_mirror(self, tok, dbm):
        r = requests.post(f"{API}/accounting/journal/manual", headers=_h(tok),
                          json={"memo": "reversal src",
                                "lines": [
                                    {"account_code": "1000", "debit_cents": 1234},
                                    {"account_code": "4400", "credit_cents": 1234},
                                ]}, timeout=10)
        assert r.status_code == 200
        original = dbm.journal_entries.find_one({"event_id": r.json()["event_id"]})
        rr = requests.post(f"{API}/accounting/journal/{original['id']}/reverse",
                           headers=_h(tok), params={"memo": "reversing"}, timeout=10)
        assert rr.status_code == 200
        mirror = rr.json()
        assert mirror["reverses_entry_id"] == original["id"]
        # sides swapped
        for orig_ln, mir_ln in zip(original["lines"], mirror["lines"]):
            assert orig_ln["debit_cents"] == mir_ln["credit_cents"]
            assert orig_ln["credit_cents"] == mir_ln["debit_cents"]


class TestOneOhNineNine:
    def test_1099_csv_export(self, tok, dbm):
        # Ensure at least one 1099 vendor with >= $600 paid
        v = dbm.vendors.find_one({"is_1099": True})
        if not v:
            v = {"id": f"v-1099-{int(time.time())}", "name": "Contractor Bob",
                 "is_1099": True, "tax_id": "12-3456789", "address": "1 Main",
                 "default_expense_account": "6600", "active": True,
                 "created_at": datetime.now(timezone.utc)}
            dbm.vendors.insert_one(v)
        year = datetime.now(timezone.utc).year
        # ensure paid bill totalling > $600
        dbm.vendor_bills.insert_one({
            "id": f"bill-1099-{int(time.time())}",
            "vendor_id": v["id"], "amount_cents": 75000,
            "status": "paid", "paid_at": datetime(year, 6, 1, tzinfo=timezone.utc),
            "created_at": datetime(year, 6, 1, tzinfo=timezone.utc),
        })
        r = requests.get(f"{API}/accounting/1099/csv", headers=_h(tok),
                         params={"year": year}, timeout=15)
        assert r.status_code == 200
        body = r.text
        assert "1099-NEC" in body
        assert "Contractor Bob" in body or v["name"] in body
