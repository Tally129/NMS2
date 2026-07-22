"""
Single accounting router — all admin/practitioner-facing endpoints.
Every write path emits an AccountingEvent; nothing writes to journal_entries
except the posting engine.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional

from fastapi import Depends, File, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field

from audit import get_client_ip, log_audit
from deps import _strip_id, api, db, require_roles
from models import new_id

from accounting import backfill as backfill_mod
from accounting import banking as banking_mod
from accounting import cash_reports as cash_mod
from accounting import chart_of_accounts as coa_mod
from accounting import dashboard as dashboard_mod
from accounting import journal as journal_mod
from accounting import reconciliation as recon_mod
from accounting import reports as reports_mod
from accounting import statements as statements_mod
from accounting import validation as validation_mod
from accounting.events import EVENT_TYPES, AccountingEvent, emit


# =========================================================================== #
# CHART OF ACCOUNTS                                                            #
# =========================================================================== #
class AccountIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=200)
    type: str
    subtype: Optional[str] = None
    normal_balance: Optional[str] = None
    active: bool = True


@api.get("/accounting/accounts")
async def list_accounts(user=Depends(require_roles("admin", "practitioner"))):
    rows = await db.chart_of_accounts.find({}).sort("code", 1).to_list(500)
    return [_strip_id(r) for r in rows]


@api.post("/accounting/accounts")
async def create_account(payload: AccountIn, request: Request,
                         user=Depends(require_roles("admin"))):
    if payload.type not in coa_mod.ACCOUNT_TYPES:
        raise HTTPException(status_code=400, detail={"code": "invalid_type"})
    if await db.chart_of_accounts.find_one({"code": payload.code}):
        raise HTTPException(status_code=409, detail={"code": "code_exists"})
    now = datetime.now(timezone.utc)
    doc = {
        "id": new_id(), "code": payload.code, "name": payload.name,
        "type": payload.type, "subtype": payload.subtype,
        "normal_balance": payload.normal_balance or coa_mod.NORMAL_BALANCE[payload.type],
        "currency": "USD", "active": payload.active, "system_locked": False,
        "created_at": now, "updated_at": now,
    }
    await db.chart_of_accounts.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "accounting.account.create",
                    resource_type="account", resource_id=doc["id"],
                    ip=get_client_ip(request))
    return _strip_id(doc)


@api.patch("/accounting/accounts/{code}")
async def update_account(code: str, payload: dict, request: Request,
                         user=Depends(require_roles("admin"))):
    acct = await db.chart_of_accounts.find_one({"code": code})
    if not acct:
        raise HTTPException(status_code=404)
    if acct.get("system_locked"):
        # System accounts: only `active` and `name` may change
        payload = {k: v for k, v in (payload or {}).items() if k in ("active", "name")}
    updates = {k: v for k, v in payload.items()
               if k in ("name", "subtype", "active")}
    updates["updated_at"] = datetime.now(timezone.utc)
    await db.chart_of_accounts.update_one({"code": code}, {"$set": updates})
    await log_audit(db, user["id"], user["email"], "accounting.account.update",
                    resource_type="account", resource_id=code,
                    metadata={"fields": list(updates.keys())})
    return _strip_id(await db.chart_of_accounts.find_one({"code": code}))


# =========================================================================== #
# JOURNAL & LEDGER                                                             #
# =========================================================================== #
@api.get("/accounting/journal")
async def list_journal(start: Optional[datetime] = None,
                       end: Optional[datetime] = None,
                       source_type: Optional[str] = None,
                       limit: int = Query(200, le=1000),
                       user=Depends(require_roles("admin", "practitioner"))):
    q: dict = {}
    if start or end:
        q["posted_at"] = {}
        if start: q["posted_at"]["$gte"] = start
        if end: q["posted_at"]["$lte"] = end
    if source_type:
        q["source_type"] = source_type
    rows = await db.journal_entries.find(q).sort("posted_at", -1).to_list(limit)
    return [_strip_id(r) for r in rows]


@api.get("/accounting/gl/{account_code}")
async def general_ledger(account_code: str,
                         start: Optional[datetime] = None,
                         end: Optional[datetime] = None,
                         user=Depends(require_roles("admin", "practitioner"))):
    return await journal_mod.gl_activity(account_code, start, end)


class ManualJournalIn(BaseModel):
    memo: str = Field(..., min_length=2, max_length=400)
    lines: List[dict]                 # [{account_code, debit_cents, credit_cents, line_memo?}]


@api.post("/accounting/journal/manual")
async def create_manual_journal(payload: ManualJournalIn, request: Request,
                                user=Depends(require_roles("admin"))):
    """Admin manual journal entry — goes through the event bus like everything else."""
    event = AccountingEvent(
        event_type="ManualJournal",
        occurred_at=datetime.now(timezone.utc),
        source_module="accounting_admin",
        source_ref_type="manual",
        source_ref_id=new_id(),
        idempotency_key=f"manual:{new_id()}",
        amount_cents=sum(int(ln.get("debit_cents") or 0) for ln in payload.lines),
        context={"lines": payload.lines, "memo": payload.memo},
        actor_id=user["id"], actor_role=user["role"],
    )
    event_id, status = await emit(event)
    if status == "dead_letter":
        raise HTTPException(status_code=400, detail={"code": "posting_failed",
                                                       "message": "See dead-letter queue"})
    await log_audit(db, user["id"], user["email"], "accounting.manual_journal",
                    resource_type="journal_entry", resource_id=event_id)
    return {"event_id": event_id, "status": status}


@api.post("/accounting/journal/{entry_id}/reverse")
async def reverse_journal(entry_id: str, memo: str,
                          user=Depends(require_roles("admin"))):
    entry = await db.journal_entries.find_one({"id": entry_id})
    if not entry:
        raise HTTPException(status_code=404)
    new_doc = await journal_mod.reverse_entry(
        entry_id, memo=memo,
        posted_by=user["id"], posted_by_name=user.get("full_name") or user["email"],
    )
    await log_audit(db, user["id"], user["email"], "accounting.reverse",
                    resource_type="journal_entry", resource_id=new_doc["id"],
                    metadata={"reverses": entry_id})
    return _strip_id(new_doc)


# =========================================================================== #
# EVENTS + DEAD LETTERS                                                        #
# =========================================================================== #
@api.get("/accounting/events")
async def list_events(limit: int = Query(200, le=1000),
                      user=Depends(require_roles("admin"))):
    rows = await db.accounting_events.find({}).sort("recorded_at", -1).to_list(limit)
    return [_strip_id(r) for r in rows]


@api.get("/accounting/dead-letters")
async def list_dead_letters(limit: int = Query(200, le=1000),
                             user=Depends(require_roles("admin"))):
    rows = await db.posting_dead_letters.find({}).sort("created_at", -1).to_list(limit)
    return [_strip_id(r) for r in rows]


# =========================================================================== #
# REPORTS                                                                      #
# =========================================================================== #
@api.get("/accounting/reports/profit-and-loss")
async def r_profit_and_loss(start: datetime, end: datetime,
                            user=Depends(require_roles("admin", "practitioner"))):
    return await reports_mod.profit_and_loss(start, end)


@api.get("/accounting/reports/balance-sheet")
async def r_balance_sheet(as_of: Optional[datetime] = None,
                          user=Depends(require_roles("admin", "practitioner"))):
    return await reports_mod.balance_sheet(as_of or datetime.now(timezone.utc))


@api.get("/accounting/reports/trial-balance")
async def r_trial_balance(as_of: Optional[datetime] = None,
                          user=Depends(require_roles("admin", "practitioner"))):
    return await reports_mod.trial_balance_report(as_of)


@api.get("/accounting/reports/ar-aging")
async def r_ar_aging(as_of: Optional[datetime] = None,
                     user=Depends(require_roles("admin", "practitioner"))):
    return await reports_mod.ar_aging(as_of)


# =========================================================================== #
# VENDORS + EXPENSES + BILLS                                                   #
# =========================================================================== #
class VendorIn(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    tax_id: Optional[str] = None            # SSN or EIN, encrypted at rest (future)
    is_1099: bool = False
    default_expense_account: str = "6900"
    notes: Optional[str] = None


@api.post("/accounting/vendors")
async def create_vendor(payload: VendorIn, request: Request,
                        user=Depends(require_roles("admin"))):
    doc = {**payload.dict(), "id": new_id(),
           "created_at": datetime.now(timezone.utc),
           "created_by": user["id"], "active": True}
    await db.vendors.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "accounting.vendor.create",
                    resource_type="vendor", resource_id=doc["id"])
    return _strip_id(doc)


@api.get("/accounting/vendors")
async def list_vendors(user=Depends(require_roles("admin", "practitioner", "staff"))):
    rows = await db.vendors.find({}).sort("name", 1).to_list(500)
    return [_strip_id(r) for r in rows]


class ExpenseIn(BaseModel):
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None
    amount_cents: int = Field(..., gt=0)
    expense_account: str = "6900"
    payment_method: str = "check"
    memo: Optional[str] = None
    receipt_file_id: Optional[str] = None
    occurred_at: Optional[datetime] = None


@api.post("/accounting/expenses")
async def record_expense(payload: ExpenseIn, request: Request,
                         user=Depends(require_roles("admin", "practitioner"))):
    exp = {
        **payload.dict(), "id": new_id(),
        "created_at": datetime.now(timezone.utc),
        "created_by": user["id"], "created_by_name": user.get("full_name"),
    }
    await db.expenses.insert_one(exp)
    event = AccountingEvent(
        event_type="ManualExpenseRecorded",
        occurred_at=payload.occurred_at or datetime.now(timezone.utc),
        source_module="expenses", source_ref_type="expense", source_ref_id=exp["id"],
        idempotency_key=f"expense:{exp['id']}:ManualExpenseRecorded",
        amount_cents=payload.amount_cents,
        context={"payment_method": payload.payment_method,
                 "expense_account": payload.expense_account,
                 "memo": payload.memo, "vendor_id": payload.vendor_id},
        actor_id=user["id"], actor_role=user["role"],
    )
    ev_id, status = await emit(event)
    exp["event_id"] = ev_id
    await log_audit(db, user["id"], user["email"], "accounting.expense.create",
                    resource_type="expense", resource_id=exp["id"],
                    metadata={"amount_cents": payload.amount_cents, "status": status})
    return _strip_id(exp)


@api.get("/accounting/expenses")
async def list_expenses(limit: int = 200,
                        user=Depends(require_roles("admin", "practitioner", "staff"))):
    rows = await db.expenses.find({}).sort("created_at", -1).to_list(limit)
    return [_strip_id(r) for r in rows]


class VendorBillIn(BaseModel):
    vendor_id: str
    amount_cents: int
    expense_account: str = "6900"
    due_date: Optional[datetime] = None
    memo: Optional[str] = None


@api.post("/accounting/bills")
async def create_bill(payload: VendorBillIn, request: Request,
                      user=Depends(require_roles("admin"))):
    bill = {**payload.dict(), "id": new_id(), "status": "open",
            "created_at": datetime.now(timezone.utc), "created_by": user["id"]}
    await db.vendor_bills.insert_one(bill)
    event = AccountingEvent(
        event_type="VendorBillCreated",
        occurred_at=datetime.now(timezone.utc),
        source_module="bills", source_ref_type="bill", source_ref_id=bill["id"],
        idempotency_key=f"bill:{bill['id']}:VendorBillCreated",
        amount_cents=payload.amount_cents,
        context={"expense_account": payload.expense_account,
                 "vendor_id": payload.vendor_id},
        actor_id=user["id"], actor_role=user["role"],
    )
    ev_id, _ = await emit(event)
    bill["event_id"] = ev_id
    return _strip_id(bill)


@api.post("/accounting/bills/{bill_id}/pay")
async def pay_bill(bill_id: str, payment_method: str = "check",
                   user=Depends(require_roles("admin"))):
    b = await db.vendor_bills.find_one({"id": bill_id})
    if not b:
        raise HTTPException(status_code=404)
    if b.get("status") == "paid":
        raise HTTPException(status_code=409, detail="Already paid")
    await db.vendor_bills.update_one({"id": bill_id}, {"$set": {
        "status": "paid", "paid_at": datetime.now(timezone.utc),
        "payment_method": payment_method,
    }})
    event = AccountingEvent(
        event_type="VendorBillPaid",
        occurred_at=datetime.now(timezone.utc),
        source_module="bills", source_ref_type="bill", source_ref_id=bill_id,
        idempotency_key=f"bill:{bill_id}:VendorBillPaid",
        amount_cents=int(b["amount_cents"]),
        context={"payment_method": payment_method, "vendor_id": b["vendor_id"]},
        actor_id=user["id"], actor_role=user["role"],
    )
    ev_id, _ = await emit(event)
    return {"ok": True, "event_id": ev_id}


@api.get("/accounting/bills")
async def list_bills(user=Depends(require_roles("admin"))):
    rows = await db.vendor_bills.find({}).sort("created_at", -1).to_list(500)
    return [_strip_id(r) for r in rows]


# =========================================================================== #
# PAYROLL                                                                      #
# =========================================================================== #
class EmployeeIn(BaseModel):
    full_name: str
    email: Optional[str] = None
    kind: Literal["hourly", "salaried", "contractor"] = "hourly"
    hourly_rate_cents: Optional[int] = None
    annual_salary_cents: Optional[int] = None
    is_1099: bool = False
    tax_id: Optional[str] = None
    pto_balance_hours: float = 0.0
    active: bool = True


@api.post("/accounting/employees")
async def create_employee(payload: EmployeeIn,
                          user=Depends(require_roles("admin"))):
    doc = {**payload.dict(), "id": new_id(),
           "created_at": datetime.now(timezone.utc), "commission_ytd_cents": 0,
           "bonus_ytd_cents": 0, "gross_ytd_cents": 0}
    await db.employees.insert_one(doc)
    return _strip_id(doc)


@api.get("/accounting/employees")
async def list_employees(user=Depends(require_roles("admin"))):
    rows = await db.employees.find({}).sort("full_name", 1).to_list(500)
    return [_strip_id(r) for r in rows]


class PayrollRunIn(BaseModel):
    period_start: datetime
    period_end: datetime
    lines: List[dict]         # [{employee_id, gross_cents, taxes_cents,
                              #   commission_cents?, bonus_cents?,
                              #   pto_hours_used?, pto_hours_accrued?}]
    memo: Optional[str] = None


@api.post("/accounting/payroll/runs")
async def create_payroll_run(payload: PayrollRunIn, request: Request,
                             user=Depends(require_roles("admin"))):
    run_id = new_id()
    total_gross = sum(int(ln.get("gross_cents") or 0) for ln in payload.lines)
    total_taxes = sum(int(ln.get("taxes_cents") or 0) for ln in payload.lines)
    run = {
        "id": run_id,
        "period_start": payload.period_start, "period_end": payload.period_end,
        "memo": payload.memo, "status": "accrued",
        "total_gross_cents": total_gross, "total_taxes_cents": total_taxes,
        "lines": payload.lines,
        "created_at": datetime.now(timezone.utc),
        "created_by": user["id"], "created_by_name": user.get("full_name"),
    }
    await db.payroll_runs.insert_one(run)
    # Update employee YTD counters and PTO
    for ln in payload.lines:
        eid = ln.get("employee_id")
        if not eid:
            continue
        await db.employees.update_one({"id": eid}, {"$inc": {
            "gross_ytd_cents": int(ln.get("gross_cents") or 0),
            "commission_ytd_cents": int(ln.get("commission_cents") or 0),
            "bonus_ytd_cents": int(ln.get("bonus_cents") or 0),
            "pto_balance_hours": float(ln.get("pto_hours_accrued") or 0) - float(ln.get("pto_hours_used") or 0),
        }})
    event = AccountingEvent(
        event_type="PayrollAccrued",
        occurred_at=payload.period_end,
        source_module="payroll", source_ref_type="payroll_run", source_ref_id=run_id,
        idempotency_key=f"payroll:{run_id}:PayrollAccrued",
        amount_cents=total_gross + total_taxes,
        context={"gross_cents": total_gross, "employer_taxes_cents": total_taxes},
        actor_id=user["id"], actor_role=user["role"],
    )
    ev_id, _ = await emit(event)
    await log_audit(db, user["id"], user["email"], "accounting.payroll.accrue",
                    resource_type="payroll_run", resource_id=run_id,
                    metadata={"gross_cents": total_gross})
    return {"run_id": run_id, "event_id": ev_id, "total_gross_cents": total_gross}


@api.post("/accounting/payroll/runs/{run_id}/pay")
async def pay_payroll_run(run_id: str, payment_method: str = "check",
                          user=Depends(require_roles("admin"))):
    run = await db.payroll_runs.find_one({"id": run_id})
    if not run:
        raise HTTPException(status_code=404)
    if run.get("status") == "paid":
        raise HTTPException(status_code=409, detail="Already paid")
    await db.payroll_runs.update_one({"id": run_id}, {"$set": {
        "status": "paid", "paid_at": datetime.now(timezone.utc),
        "payment_method": payment_method,
    }})
    event = AccountingEvent(
        event_type="PayrollPaid",
        occurred_at=datetime.now(timezone.utc),
        source_module="payroll", source_ref_type="payroll_run", source_ref_id=run_id,
        idempotency_key=f"payroll:{run_id}:PayrollPaid",
        amount_cents=int(run["total_gross_cents"]),
        context={"payment_method": payment_method},
        actor_id=user["id"], actor_role=user["role"],
    )
    ev_id, _ = await emit(event)
    return {"ok": True, "event_id": ev_id}


@api.get("/accounting/payroll/runs")
async def list_payroll_runs(user=Depends(require_roles("admin"))):
    rows = await db.payroll_runs.find({}).sort("created_at", -1).to_list(200)
    return [_strip_id(r) for r in rows]


# =========================================================================== #
# TAX REPORTS                                                                  #
# =========================================================================== #
@api.get("/accounting/tax/sales-tax")
async def sales_tax_report(start: datetime, end: datetime,
                           user=Depends(require_roles("admin", "practitioner"))):
    tb_end = await journal_mod.trial_balance(as_of=end)
    tb_start = await journal_mod.trial_balance(
        as_of=start - timedelta(seconds=1)) if start else {}
    end_c = tb_end.get("2200", {"net_cents": 0})["net_cents"]
    start_c = tb_start.get("2200", {"net_cents": 0})["net_cents"] if tb_start else 0
    # Liability account carries a credit balance
    collected = -(end_c - start_c)
    return {"start": start, "end": end,
            "sales_tax_collected_cents": collected,
            "account_code": "2200"}


@api.get("/accounting/tax/payroll-tax")
async def payroll_tax_report(start: datetime, end: datetime,
                             user=Depends(require_roles("admin"))):
    tb_end = await journal_mod.trial_balance(as_of=end)
    tb_start = await journal_mod.trial_balance(as_of=start - timedelta(seconds=1))
    accrued = -((tb_end.get("2410", {"net_cents": 0})["net_cents"]) -
                (tb_start.get("2410", {"net_cents": 0})["net_cents"]))
    return {"start": start, "end": end,
            "payroll_tax_accrued_cents": accrued, "account_code": "2410"}


@api.get("/accounting/tax/summary")
async def tax_summary(year: int = Query(default=None),
                      user=Depends(require_roles("admin"))):
    year = year or datetime.now(timezone.utc).year
    tz = timezone.utc
    out = []
    for q in range(4):
        start_month = q * 3 + 1
        end_month = start_month + 2
        start = datetime(year, start_month, 1, tzinfo=tz)
        # last day of end_month
        next_first = datetime(year + (1 if end_month == 12 else 0),
                              (end_month % 12) + 1, 1, tzinfo=tz)
        end = next_first - timedelta(seconds=1)
        sales = await sales_tax_report(start, end, user)
        payroll = await payroll_tax_report(start, end, user)
        out.append({"quarter": f"Q{q+1} {year}",
                    "sales_tax_collected_cents": sales["sales_tax_collected_cents"],
                    "payroll_tax_accrued_cents": payroll["payroll_tax_accrued_cents"]})
    return {"year": year, "quarters": out}


# =========================================================================== #
# 1099                                                                         #
# =========================================================================== #
@api.get("/accounting/1099/vendors")
async def vendors_1099(year: int = Query(default=None),
                       user=Depends(require_roles("admin"))):
    """Aggregate payments to 1099-eligible vendors + contractors for the year."""
    year = year or datetime.now(timezone.utc).year
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    end = datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    # 1099 vendors
    vendor_totals: dict[str, int] = {}
    async for b in db.vendor_bills.find({"status": "paid",
                                          "paid_at": {"$gte": start, "$lte": end}}):
        vendor_totals[b["vendor_id"]] = vendor_totals.get(b["vendor_id"], 0) + int(b["amount_cents"])
    vendors = []
    for vid, total in vendor_totals.items():
        v = await db.vendors.find_one({"id": vid})
        if not v or not v.get("is_1099"):
            continue
        if total < 60000:   # IRS threshold $600 → 60000 cents
            continue
        vendors.append({
            "vendor_id": vid, "name": v["name"], "tax_id": v.get("tax_id"),
            "address": v.get("address"), "total_paid_cents": total,
            "kind": "vendor",
        })
    # 1099 contractors (employees marked contractor + is_1099)
    async for emp in db.employees.find({"is_1099": True}):
        emp_total = 0
        async for run in db.payroll_runs.find({"status": "paid",
                                                "paid_at": {"$gte": start, "$lte": end}}):
            for ln in run.get("lines", []):
                if ln.get("employee_id") == emp["id"]:
                    emp_total += int(ln.get("gross_cents") or 0)
        if emp_total < 60000:
            continue
        vendors.append({
            "vendor_id": emp["id"], "name": emp["full_name"],
            "tax_id": emp.get("tax_id"), "address": None,
            "total_paid_cents": emp_total, "kind": "contractor",
        })
    return {"year": year, "recipients": vendors}


@api.get("/accounting/1099/csv")
async def vendors_1099_csv(year: int = Query(default=None),
                            user=Depends(require_roles("admin"))):
    data = await vendors_1099(year, user)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["form", "tax_year", "recipient_name", "recipient_tax_id",
                "recipient_address", "box_1_nonemployee_compensation_usd", "kind"])
    for r in data["recipients"]:
        w.writerow([
            "1099-NEC", data["year"], r["name"], r.get("tax_id") or "",
            r.get("address") or "", f"{r['total_paid_cents'] / 100:.2f}",
            r["kind"],
        ])
    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=1099-NEC-{data['year']}.csv"},
    )


# =========================================================================== #
# STRIPE RECONCILIATION VIEW (reuses existing integration_log)                 #
# =========================================================================== #
@api.get("/accounting/stripe/reconciliation")
async def stripe_reconciliation(user=Depends(require_roles("admin"))):
    """Pull every Stripe hit from integration_log alongside the transaction/
    invoice that produced it. Read-only view; no card numbers touched."""
    rows = await db.integration_log.find({"service": "stripe"}).sort(
        "ts", -1).to_list(500)
    return [_strip_id(r) for r in rows]


# =========================================================================== #
# SPRINT 1.5 — DASHBOARD / VALIDATION / BACKFILL                                #
# =========================================================================== #
@api.get("/accounting/dashboard")
async def accounting_dashboard(
    user=Depends(require_roles("admin", "practitioner"))
):
    """Health widgets: cash, A/R, A/P, revenue windows, liabilities, ledger health."""
    return await dashboard_mod.snapshot()


@api.get("/accounting/validate")
async def accounting_validate(
    user=Depends(require_roles("admin", "practitioner"))
):
    """Run every ledger validation check and return a single health report."""
    return await validation_mod.run_all()


class BackfillIn(BaseModel):
    sources: List[str] = Field(default_factory=list)   # empty = all supported


@api.post("/accounting/backfill/dry-run")
async def backfill_dry_run(payload: BackfillIn,
                            user=Depends(require_roles("admin"))):
    return await backfill_mod.preview(payload.sources)


@api.post("/accounting/backfill/execute")
async def backfill_execute(payload: BackfillIn, request: Request,
                            user=Depends(require_roles("admin"))):
    run = await backfill_mod.start_run(payload.sources, user)
    # Run inline (small datasets) OR in background if you want to return early.
    # For the medical practice sizes we're targeting we execute inline so the
    # UI sees final counters. Background hook is available for very large sets.
    result = await backfill_mod.execute_run(run["id"])
    await log_audit(db, user["id"], user["email"], "accounting.backfill.execute",
                    resource_type="backfill_run", resource_id=run["id"],
                    metadata={"sources": result.get("sources"),
                              "totals": result.get("totals")},
                    ip=get_client_ip(request))
    return _strip_id(result)


@api.get("/accounting/backfill/runs")
async def backfill_list_runs(limit: int = Query(50, le=200),
                              user=Depends(require_roles("admin"))):
    rows = await db.accounting_backfill_runs.find({}).sort(
        "started_at", -1
    ).to_list(limit)
    return [_strip_id(r) for r in rows]


@api.get("/accounting/backfill/runs/{run_id}")
async def backfill_get_run(run_id: str,
                            user=Depends(require_roles("admin"))):
    row = await db.accounting_backfill_runs.find_one({"id": run_id})
    if not row:
        raise HTTPException(status_code=404)
    return _strip_id(row)


@api.post("/accounting/backfill/runs/{run_id}/resume")
async def backfill_resume(run_id: str, request: Request,
                           user=Depends(require_roles("admin"))):
    try:
        result = await backfill_mod.resume_run(run_id)
    except ValueError:
        raise HTTPException(status_code=404)
    await log_audit(db, user["id"], user["email"], "accounting.backfill.resume",
                    resource_type="backfill_run", resource_id=run_id,
                    metadata={"totals": result.get("totals")},
                    ip=get_client_ip(request))
    return _strip_id(result)


# =========================================================================== #
# SPRINT 2 — BANKING & CASH MANAGEMENT                                          #
# =========================================================================== #
class BankAccountIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    kind: str
    gl_account_code: str
    institution: Optional[str] = None
    last_four: Optional[str] = None


class BankAccountPatch(BaseModel):
    name: Optional[str] = None
    institution: Optional[str] = None
    last_four: Optional[str] = None
    active: Optional[bool] = None


@api.get("/accounting/bank-accounts")
async def list_bank_accounts(
    include_inactive: bool = False,
    user=Depends(require_roles("admin", "practitioner", "staff"))
):
    rows = await banking_mod.list_accounts(include_inactive)
    return [_strip_id(r) for r in rows]


@api.post("/accounting/bank-accounts")
async def create_bank_account(payload: BankAccountIn, request: Request,
                              user=Depends(require_roles("admin"))):
    try:
        doc = await banking_mod.create(
            name=payload.name, kind=payload.kind,
            gl_account_code=payload.gl_account_code,
            institution=payload.institution, last_four=payload.last_four,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await log_audit(db, user["id"], user["email"], "accounting.bank_account.create",
                    resource_type="bank_account", resource_id=doc["id"],
                    ip=get_client_ip(request))
    return _strip_id(doc)


@api.patch("/accounting/bank-accounts/{ba_id}")
async def patch_bank_account(ba_id: str, payload: BankAccountPatch,
                              user=Depends(require_roles("admin"))):
    doc = await banking_mod.update(ba_id, payload.dict(exclude_unset=True))
    if not doc:
        raise HTTPException(status_code=404)
    return _strip_id(doc)


@api.delete("/accounting/bank-accounts/{ba_id}")
async def delete_bank_account(ba_id: str,
                              user=Depends(require_roles("admin"))):
    try:
        await banking_mod.delete(ba_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


# ------------------------ Statement import ---------------------------------- #
@api.post("/accounting/bank-accounts/{ba_id}/import")
async def import_bank_statement(
    ba_id: str, request: Request,
    file: UploadFile = File(...),
    user=Depends(require_roles("admin"))
):
    ba = await db.bank_accounts.find_one({"id": ba_id})
    if not ba:
        raise HTTPException(status_code=404, detail="bank account not found")
    content = await file.read()
    try:
        batch = await statements_mod.import_statement(
            bank_account_id=ba_id, filename=file.filename or "upload.csv",
            content=content, actor=user,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "import_failed",
                                                       "message": str(e)})
    await log_audit(db, user["id"], user["email"], "accounting.bank_statement.import",
                    resource_type="bank_account", resource_id=ba_id,
                    metadata={"batch_id": batch["id"],
                              "new": batch["row_count_new"],
                              "duplicate": batch["row_count_duplicate"]},
                    ip=get_client_ip(request))
    return _strip_id(batch)


@api.get("/accounting/bank-accounts/{ba_id}/transactions")
async def list_bank_transactions(
    ba_id: str,
    status: Optional[str] = None,
    limit: int = Query(500, le=2000),
    user=Depends(require_roles("admin", "practitioner", "staff"))
):
    q = {"bank_account_id": ba_id}
    if status:
        q["status"] = status
    rows = await db.bank_transactions.find(q).sort("posted_at", -1).to_list(limit)
    return [_strip_id(r) for r in rows]


@api.get("/accounting/bank-accounts/{ba_id}/import-batches")
async def list_import_batches(ba_id: str,
                              user=Depends(require_roles("admin"))):
    rows = await db.bank_import_batches.find({"bank_account_id": ba_id}).sort(
        "imported_at", -1).to_list(100)
    return [_strip_id(r) for r in rows]


# ------------------------ Reconciliation workspace -------------------------- #
@api.get("/accounting/reconciliation/{ba_id}/workspace")
async def recon_workspace(ba_id: str, lookback_days: int = 90,
                          user=Depends(require_roles("admin", "practitioner"))):
    try:
        ws = await recon_mod.workspace(ba_id, lookback_days)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    ws["bank_account"] = _strip_id(ws["bank_account"])
    ws["bank_transactions"] = [_strip_id(r) for r in ws["bank_transactions"]]
    ws["journal_entries"] = [_strip_id(r) for r in ws["journal_entries"]]
    return ws


@api.post("/accounting/reconciliation/{ba_id}/auto-match")
async def recon_auto_match(ba_id: str,
                            user=Depends(require_roles("admin"))):
    return await recon_mod.auto_match(ba_id)


class ConfirmMatchesIn(BaseModel):
    proposals: List[dict]


@api.post("/accounting/reconciliation/confirm-matches")
async def recon_confirm(payload: ConfirmMatchesIn,
                        user=Depends(require_roles("admin"))):
    return await recon_mod.confirm_auto_matches(payload.proposals, user)


class MatchIn(BaseModel):
    bank_transaction_id: str
    journal_entry_id: str


@api.post("/accounting/reconciliation/match")
async def recon_match(payload: MatchIn,
                      user=Depends(require_roles("admin"))):
    try:
        return await recon_mod.match(
            bank_transaction_id=payload.bank_transaction_id,
            journal_entry_id=payload.journal_entry_id,
            actor=user,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@api.post("/accounting/reconciliation/unmatch/{bank_transaction_id}")
async def recon_unmatch(bank_transaction_id: str,
                         user=Depends(require_roles("admin"))):
    try:
        return await recon_mod.unmatch(bank_transaction_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class SplitIn(BaseModel):
    bank_transaction_id: str
    journal_entry_ids: List[str]


@api.post("/accounting/reconciliation/split")
async def recon_split(payload: SplitIn,
                      user=Depends(require_roles("admin"))):
    try:
        return await recon_mod.split_match(
            bank_transaction_id=payload.bank_transaction_id,
            journal_entry_ids=payload.journal_entry_ids,
            actor=user,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class FinalizeIn(BaseModel):
    bank_account_id: str
    statement_end_date: datetime
    ending_balance_cents: int
    notes: Optional[str] = None


@api.post("/accounting/reconciliation/finalize")
async def recon_finalize(payload: FinalizeIn, request: Request,
                          user=Depends(require_roles("admin"))):
    try:
        r = await recon_mod.finalize(
            bank_account_id=payload.bank_account_id,
            statement_end_date=payload.statement_end_date,
            ending_balance_cents=payload.ending_balance_cents,
            notes=payload.notes, actor=user,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await log_audit(db, user["id"], user["email"],
                    "accounting.reconciliation.finalize",
                    resource_type="reconciliation", resource_id=r["id"],
                    metadata={"bank_account_id": payload.bank_account_id,
                              "txns": r["txn_count"]},
                    ip=get_client_ip(request))
    return _strip_id(r)


@api.get("/accounting/reconciliation/history")
async def recon_history(bank_account_id: Optional[str] = None,
                        limit: int = Query(50, le=200),
                        user=Depends(require_roles("admin", "practitioner"))):
    q: dict = {}
    if bank_account_id:
        q["bank_account_id"] = bank_account_id
    rows = await db.reconciliations.find(q).sort("finalized_at", -1).to_list(limit)
    return [_strip_id(r) for r in rows]


@api.get("/accounting/reconciliation/{recon_id}/report")
async def recon_report(recon_id: str,
                        user=Depends(require_roles("admin", "practitioner"))):
    try:
        r = await cash_mod.reconciliation_report(recon_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    r["reconciliation"] = _strip_id(r["reconciliation"])
    r["bank_account"] = _strip_id(r["bank_account"])
    r["bank_transactions"] = [_strip_id(t) for t in r["bank_transactions"]]
    r["journal_entries"] = [_strip_id(j) for j in r["journal_entries"]]
    return r


@api.get("/accounting/reconciliation/exceptions")
async def recon_exceptions(bank_account_id: Optional[str] = None,
                            user=Depends(require_roles("admin", "practitioner"))):
    r = await recon_mod.exceptions_panel(bank_account_id)
    for k in ("unmatched_bank_transactions_sample",
              "unmatched_ledger_entries_sample"):
        r[k] = [_strip_id(x) for x in r.get(k, [])]
    return r


# ------------------------ Cash transfers ------------------------------------ #
class TransferIn(BaseModel):
    from_bank_account_id: str
    to_bank_account_id: str
    amount_cents: int = Field(..., gt=0)
    memo: Optional[str] = None
    occurred_at: Optional[datetime] = None


@api.post("/accounting/transfers")
async def create_transfer(payload: TransferIn, request: Request,
                           user=Depends(require_roles("admin"))):
    src = await db.bank_accounts.find_one({"id": payload.from_bank_account_id})
    dst = await db.bank_accounts.find_one({"id": payload.to_bank_account_id})
    if not src or not dst:
        raise HTTPException(status_code=404, detail="bank account not found")
    if payload.from_bank_account_id == payload.to_bank_account_id:
        raise HTTPException(status_code=400, detail="source == destination")
    transfer_id = new_id()
    doc = {
        "id": transfer_id,
        "from_bank_account_id": payload.from_bank_account_id,
        "to_bank_account_id": payload.to_bank_account_id,
        "amount_cents": payload.amount_cents,
        "memo": payload.memo,
        "created_by": user["id"],
        "created_at": datetime.now(timezone.utc),
    }
    await db.bank_transfers.insert_one(doc)
    event = AccountingEvent(
        event_type="BankTransferMade",
        occurred_at=payload.occurred_at or datetime.now(timezone.utc),
        source_module="banking", source_ref_type="bank_transfer",
        source_ref_id=transfer_id,
        idempotency_key=f"bank_transfer:{transfer_id}:BankTransferMade",
        amount_cents=payload.amount_cents,
        context={"from_account_code": src["gl_account_code"],
                 "to_account_code": dst["gl_account_code"],
                 "memo": payload.memo,
                 "from_bank_account_id": src["id"],
                 "to_bank_account_id": dst["id"]},
        actor_id=user["id"], actor_role=user["role"],
    )
    ev_id, status = await emit(event)
    doc["event_id"] = ev_id
    if status == "dead_letter":
        raise HTTPException(status_code=400, detail="transfer posting failed")
    await log_audit(db, user["id"], user["email"], "accounting.transfer",
                    resource_type="bank_transfer", resource_id=transfer_id,
                    metadata={"amount_cents": payload.amount_cents,
                              "from": src["name"], "to": dst["name"]},
                    ip=get_client_ip(request))
    return _strip_id(doc)


@api.get("/accounting/transfers")
async def list_transfers(limit: int = Query(100, le=500),
                          user=Depends(require_roles("admin", "practitioner"))):
    rows = await db.bank_transfers.find({}).sort("created_at", -1).to_list(limit)
    return [_strip_id(r) for r in rows]


# ------------------------ Cash dashboard & reports -------------------------- #
@api.get("/accounting/cash/dashboard")
async def cash_dashboard(user=Depends(require_roles("admin", "practitioner"))):
    return await cash_mod.cash_dashboard()


@api.get("/accounting/cash/register/{ba_id}")
async def cash_register(ba_id: str,
                         start: Optional[datetime] = None,
                         end: Optional[datetime] = None,
                         limit: int = Query(500, le=2000),
                         user=Depends(require_roles("admin", "practitioner"))):
    try:
        r = await cash_mod.bank_register(ba_id, start, end, limit)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    r["bank_account"] = _strip_id(r["bank_account"])
    return r


@api.get("/accounting/cash/flow")
async def cash_flow(start: datetime, end: datetime,
                     user=Depends(require_roles("admin", "practitioner"))):
    return await cash_mod.cash_flow_summary(start, end)


@api.get("/accounting/cash/outstanding-deposits")
async def outstanding_deposits(bank_account_id: Optional[str] = None,
                                user=Depends(require_roles("admin", "practitioner"))):
    return await cash_mod.outstanding_deposits(bank_account_id)


@api.get("/accounting/cash/outstanding-checks")
async def outstanding_checks(bank_account_id: Optional[str] = None,
                              user=Depends(require_roles("admin", "practitioner"))):
    return await cash_mod.outstanding_checks(bank_account_id)


@api.get("/accounting/cash/outstanding-reconciliation")
async def outstanding_reconciliation(user=Depends(require_roles("admin", "practitioner"))):
    r = await cash_mod.outstanding_reconciliation_report()
    for a in r["accounts"]:
        a["bank_account"] = _strip_id(a["bank_account"])
        a["unmatched_bank_transactions"] = [_strip_id(x) for x in a["unmatched_bank_transactions"]]
        a["unmatched_ledger_entries"] = [_strip_id(x) for x in a["unmatched_ledger_entries"]]
    return r


# ------------------------ Stripe settlement --------------------------------- #
@api.get("/accounting/stripe/settlement")
async def stripe_settlement(start: datetime, end: datetime,
                             user=Depends(require_roles("admin"))):
    return await cash_mod.stripe_settlement_summary(start, end)
