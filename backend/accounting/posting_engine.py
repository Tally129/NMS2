"""
Posting Rules Engine — translates AccountingEvents into balanced journal
entries via a table of rules. Rules ship as code (default set below) and
can be overridden per-tenant via `db.posting_rules` (future work).

Each rule is a Python function that receives the event dict and returns a
list of {account_code, debit_cents, credit_cents, line_memo} lines. If it
raises or returns None, the event goes to the dead-letter queue.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from deps import db
from models import new_id

from .journal import write_entry


# Payment method → cash-side account
PAY_METHOD_TO_ACCOUNT = {
    "stripe":            "1200",   # Stripe clearing
    "chase_pos":         "1050",   # Cash drawer clearing (Chase POS)
    "chase_pos_manual":  "1050",
    "cash":              "1000",   # Cash on hand
    "check":             "1100",   # Operating checking
    "card_other":        "1100",
    "ach":               "1100",
    "hsa_fsa":           "1200",
    "other":             "1100",
    "manual":            "1000",
}


def _cash_account(method: Optional[str]) -> str:
    return PAY_METHOD_TO_ACCOUNT.get((method or "other").lower(), "1100")


def _rule_sale_completed(ev: dict) -> list[dict]:
    ctx = ev.get("context", {}) or {}
    amount = int(ev.get("amount_cents") or 0)
    tax = int(ctx.get("tax_cents") or 0)
    tip = int(ctx.get("tip_cents") or 0)
    discount = int(ctx.get("discount_cents") or 0)
    cash_code = _cash_account(ctx.get("payment_method"))
    lines = [{"account_code": cash_code, "debit_cents": amount,
              "credit_cents": 0, "line_memo": "POS receipt"}]
    # Split revenue by line type
    lines_ctx = ctx.get("lines") or []
    service_rev = 0
    product_rev = 0
    cogs_total = 0
    for ln in lines_ctx:
        line_total = int(ln.get("line_total_cents") or 0)
        if ln.get("line_type") == "inventory":
            product_rev += line_total
            cogs_total += int(ln.get("unit_cost_cents") or 0) * int(ln.get("qty") or 1)
        else:
            service_rev += line_total
    revenue_gross = service_rev + product_rev
    # If ctx lines missing, fall back: everything after tax/tip -> service
    if revenue_gross == 0:
        revenue_gross = max(0, amount - tax - tip)
        service_rev = revenue_gross
    if discount > 0:
        lines.append({"account_code": "4900", "debit_cents": discount,
                      "credit_cents": 0, "line_memo": "Sales discount"})
        revenue_gross += discount   # re-inflate to preserve balance
    if service_rev > 0:
        lines.append({"account_code": "4100", "debit_cents": 0,
                      "credit_cents": service_rev, "line_memo": "Service revenue"})
    if product_rev > 0:
        lines.append({"account_code": "4200", "debit_cents": 0,
                      "credit_cents": product_rev, "line_memo": "Product revenue"})
    if tax > 0:
        lines.append({"account_code": "2200", "debit_cents": 0,
                      "credit_cents": tax, "line_memo": "Sales tax collected"})
    if tip > 0:
        lines.append({"account_code": "2300", "debit_cents": 0,
                      "credit_cents": tip, "line_memo": "Tips owed to staff"})
    if cogs_total > 0:
        lines.append({"account_code": "5100", "debit_cents": cogs_total,
                      "credit_cents": 0, "line_memo": "Product COGS"})
        lines.append({"account_code": "1400", "debit_cents": 0,
                      "credit_cents": cogs_total, "line_memo": "Inventory relieved"})
    return lines


def _rule_invoice_paid(ev: dict) -> list[dict]:
    ctx = ev.get("context", {}) or {}
    amount = int(ev.get("amount_cents") or 0)
    cash_code = _cash_account(ctx.get("payment_method"))
    return [
        {"account_code": cash_code,  "debit_cents": amount, "credit_cents": 0, "line_memo": "Invoice payment"},
        {"account_code": "1300",     "debit_cents": 0, "credit_cents": amount, "line_memo": "A/R cleared"},
    ]


def _rule_invoice_issued(ev: dict) -> list[dict]:
    """Recognise A/R when an invoice is created."""
    amount = int(ev.get("amount_cents") or 0)
    return [
        {"account_code": "1300", "debit_cents": amount, "credit_cents": 0, "line_memo": "A/R accrued"},
        {"account_code": "4100", "debit_cents": 0, "credit_cents": amount, "line_memo": "Service revenue (invoiced)"},
    ]


def _rule_membership_paid(ev: dict) -> list[dict]:
    ctx = ev.get("context", {}) or {}
    amount = int(ev.get("amount_cents") or 0)
    cash_code = _cash_account(ctx.get("payment_method"))
    return [
        {"account_code": cash_code, "debit_cents": amount, "credit_cents": 0, "line_memo": "Membership receipt"},
        {"account_code": "4300",    "debit_cents": 0, "credit_cents": amount, "line_memo": "Membership revenue"},
    ]


def _rule_inventory_adjusted(ev: dict) -> list[dict]:
    ctx = ev.get("context", {}) or {}
    delta_value = int(ev.get("amount_cents") or 0)
    reason = ctx.get("reason", "adjustment")
    qty_delta = int(ctx.get("qty_delta") or 0)
    if qty_delta > 0:
        # Received inventory: DR Inventory / CR AP-or-cash
        return [
            {"account_code": "1400", "debit_cents": abs(delta_value), "credit_cents": 0, "line_memo": f"Inventory in ({reason})"},
            {"account_code": "2000", "debit_cents": 0, "credit_cents": abs(delta_value), "line_memo": "AP or cash counterpart"},
        ]
    else:
        # Shrinkage / write-off
        return [
            {"account_code": "6900", "debit_cents": abs(delta_value), "credit_cents": 0, "line_memo": f"Inventory write-off ({reason})"},
            {"account_code": "1400", "debit_cents": 0, "credit_cents": abs(delta_value), "line_memo": "Inventory relieved"},
        ]


def _rule_manual_expense(ev: dict) -> list[dict]:
    ctx = ev.get("context", {}) or {}
    amount = int(ev.get("amount_cents") or 0)
    expense_account = ctx.get("expense_account") or "6900"
    cash_code = _cash_account(ctx.get("payment_method"))
    return [
        {"account_code": expense_account, "debit_cents": amount, "credit_cents": 0, "line_memo": ctx.get("memo") or "Expense"},
        {"account_code": cash_code,       "debit_cents": 0, "credit_cents": amount, "line_memo": "Paid from " + (ctx.get("payment_method") or "cash")},
    ]


def _rule_vendor_bill_created(ev: dict) -> list[dict]:
    ctx = ev.get("context", {}) or {}
    amount = int(ev.get("amount_cents") or 0)
    expense_account = ctx.get("expense_account") or "6900"
    return [
        {"account_code": expense_account, "debit_cents": amount, "credit_cents": 0, "line_memo": "Vendor bill expense"},
        {"account_code": "2000",          "debit_cents": 0, "credit_cents": amount, "line_memo": "A/P accrued"},
    ]


def _rule_vendor_bill_paid(ev: dict) -> list[dict]:
    ctx = ev.get("context", {}) or {}
    amount = int(ev.get("amount_cents") or 0)
    cash_code = _cash_account(ctx.get("payment_method"))
    return [
        {"account_code": "2000",     "debit_cents": amount, "credit_cents": 0, "line_memo": "A/P cleared"},
        {"account_code": cash_code,  "debit_cents": 0, "credit_cents": amount, "line_memo": "Vendor payment"},
    ]


def _rule_payroll_accrued(ev: dict) -> list[dict]:
    ctx = ev.get("context", {}) or {}
    gross = int(ctx.get("gross_cents") or ev.get("amount_cents") or 0)
    taxes = int(ctx.get("employer_taxes_cents") or 0)
    return [
        {"account_code": "6200", "debit_cents": gross, "credit_cents": 0, "line_memo": "Payroll expense"},
        {"account_code": "6210", "debit_cents": taxes, "credit_cents": 0, "line_memo": "Employer payroll taxes"},
        {"account_code": "2400", "debit_cents": 0, "credit_cents": gross, "line_memo": "Wages payable"},
        {"account_code": "2410", "debit_cents": 0, "credit_cents": taxes, "line_memo": "Payroll taxes payable"},
    ]


def _rule_payroll_paid(ev: dict) -> list[dict]:
    ctx = ev.get("context", {}) or {}
    amount = int(ev.get("amount_cents") or 0)
    cash_code = _cash_account(ctx.get("payment_method") or "check")
    return [
        {"account_code": "2400", "debit_cents": amount, "credit_cents": 0, "line_memo": "Wages paid"},
        {"account_code": cash_code, "debit_cents": 0, "credit_cents": amount, "line_memo": "Payroll disbursement"},
    ]


def _rule_stripe_fee(ev: dict) -> list[dict]:
    amount = int(ev.get("amount_cents") or 0)
    return [
        {"account_code": "5200", "debit_cents": amount, "credit_cents": 0, "line_memo": "Stripe processing fee"},
        {"account_code": "1200", "debit_cents": 0, "credit_cents": amount, "line_memo": "Fee withheld from clearing"},
    ]


def _rule_manual_journal(ev: dict) -> list[dict]:
    ctx = ev.get("context", {}) or {}
    return ctx.get("lines") or []


RULES: dict[str, Callable[[dict], list[dict]]] = {
    "SaleCompleted":       _rule_sale_completed,
    "InvoiceIssued":       _rule_invoice_issued,
    "InvoicePaid":         _rule_invoice_paid,
    "MembershipStarted":   _rule_membership_paid,
    "MembershipRenewed":   _rule_membership_paid,
    "InventoryAdjusted":   _rule_inventory_adjusted,
    "ManualExpenseRecorded": _rule_manual_expense,
    "VendorBillCreated":   _rule_vendor_bill_created,
    "VendorBillPaid":      _rule_vendor_bill_paid,
    "PayrollAccrued":      _rule_payroll_accrued,
    "PayrollPaid":         _rule_payroll_paid,
    "StripeFeeCharged":    _rule_stripe_fee,
    "ManualJournal":       _rule_manual_journal,
}


async def _dead_letter(event: dict, reason: str) -> None:
    await db.posting_dead_letters.insert_one({
        "id": new_id(),
        "event_id": event.get("id"),
        "event_type": event.get("event_type"),
        "idempotency_key": event.get("idempotency_key"),
        "reason": reason,
        "event_snapshot": event,
        "created_at": datetime.now(timezone.utc),
    })


async def post_event(event: dict) -> str:
    """Post an event through its rule. Returns status."""
    rule = RULES.get(event.get("event_type"))
    if not rule:
        await _dead_letter(event, "no_matching_rule")
        return "dead_letter"
    # Reversals — swap sides
    if event.get("reverses_event_id"):
        original = await db.journal_entries.find_one({"event_id": event["reverses_event_id"]})
        if not original:
            await _dead_letter(event, "original_event_missing_for_reversal")
            return "dead_letter"
        mirrored = []
        for ln in original["lines"]:
            mirrored.append({
                "account_code": ln["account_code"],
                "debit_cents": ln.get("credit_cents") or 0,
                "credit_cents": ln.get("debit_cents") or 0,
                "line_memo": f"Reversal: {ln.get('line_memo') or ''}",
            })
        try:
            await write_entry(
                lines=mirrored,
                memo=f"Reversal — {event.get('event_type')}",
                source_type=event.get("source_ref_type") or "",
                source_id=event.get("source_ref_id") or "",
                event_id=event.get("id"),
                reverses_entry_id=original["id"],
                context=event.get("context") or {},
            )
            return "posted"
        except Exception as e:
            await _dead_letter(event, f"reversal_write_failed: {e}")
            return "dead_letter"
    # Normal posting
    try:
        lines = rule(event)
        if not lines:
            await _dead_letter(event, "rule_returned_no_lines")
            return "dead_letter"
    except Exception as e:
        await _dead_letter(event, f"rule_exception: {e}")
        return "dead_letter"
    try:
        await write_entry(
            lines=lines,
            memo=f"{event['event_type']} — {event.get('source_ref_type')}/{event.get('source_ref_id')}",
            source_type=event.get("source_ref_type") or "",
            source_id=event.get("source_ref_id") or "",
            event_id=event.get("id"),
            context=event.get("context") or {},
        )
        return "posted"
    except Exception as e:
        await _dead_letter(event, f"unbalanced_or_write_failed: {e}")
        return "dead_letter"
