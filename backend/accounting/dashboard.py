"""
Accounting Health Dashboard aggregator.

Everything here is derived from the ledger + a small set of read-only counts.
No writes, no side effects. All amounts in integer cents.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from deps import db

from .journal import trial_balance
from .reports import ar_aging


CASH_ACCOUNT_CODES = ("1000", "1050", "1100", "1200")
AP_ACCOUNT_CODES = ("2000",)
SALES_TAX_ACCOUNT = "2200"
PAYROLL_LIABILITY_CODES = ("2400", "2410")
REVENUE_TYPES = ("revenue",)


def _start_of_day(d: datetime) -> datetime:
    return datetime.combine(d.date(), time.min, tzinfo=timezone.utc)


def _start_of_month(d: datetime) -> datetime:
    return datetime(d.year, d.month, 1, tzinfo=timezone.utc)


async def _sum_type(tb: dict, type_: str) -> int:
    rows = await db.chart_of_accounts.find({"type": type_, "active": True}).to_list(500)
    total = 0
    for a in rows:
        b = tb.get(a["code"], {"net_cents": 0})["net_cents"]
        # revenue is a credit-normal account, invert to show positive
        if a["normal_balance"] == "credit":
            total += -b
        else:
            total += b
    return total


async def _revenue_between(start: datetime, end: datetime) -> int:
    tb_end = await trial_balance(as_of=end)
    tb_start = await trial_balance(as_of=start - timedelta(seconds=1))
    accounts = await db.chart_of_accounts.find(
        {"type": "revenue", "active": True}
    ).to_list(500)
    total = 0
    for a in accounts:
        end_b = tb_end.get(a["code"], {"net_cents": 0})["net_cents"]
        start_b = tb_start.get(a["code"], {"net_cents": 0})["net_cents"]
        delta = end_b - start_b
        # revenue accounts carry credit balances
        total += -delta if a["normal_balance"] == "credit" else delta
    return total


async def snapshot() -> dict:
    """Return the full dashboard payload."""
    now = datetime.now(timezone.utc)
    tb = await trial_balance(as_of=now)

    # Cash across all cash-type accounts
    cash_cents = sum(
        int(tb.get(code, {"net_cents": 0})["net_cents"])
        for code in CASH_ACCOUNT_CODES
    )

    # A/R + A/P from ledger + aging detail
    ar_aging_data = await ar_aging(now)
    ar_cents = int(ar_aging_data.get("total_cents") or 0)
    ap_cents = 0
    for code in AP_ACCOUNT_CODES:
        # AP is credit-normal; positive balance = we owe
        ap_cents += -int(tb.get(code, {"net_cents": 0})["net_cents"])

    # Revenue windows
    som = _start_of_month(now)
    sod = _start_of_day(now)
    revenue_mtd = await _revenue_between(som, now)
    revenue_today = await _revenue_between(sod, now)

    # Liabilities: sales tax + payroll
    sales_tax_liability = -int(tb.get(SALES_TAX_ACCOUNT,
                                       {"net_cents": 0})["net_cents"])
    payroll_liability = 0
    for code in PAYROLL_LIABILITY_CODES:
        payroll_liability += -int(tb.get(code, {"net_cents": 0})["net_cents"])

    # Ledger health counters
    dead_letter_count = await db.posting_dead_letters.count_documents({})
    posted_event_ids = await db.journal_entries.distinct(
        "event_id", {"event_id": {"$type": "string"}}
    )
    total_events = await db.accounting_events.count_documents({})
    posted_events = len(posted_event_ids)
    unposted_events = max(0, total_events - posted_events)

    # Trial balance status
    tb_debit = 0
    tb_credit = 0
    for _code, row in tb.items():
        tb_debit += int(row.get("debit_cents") or 0)
        tb_credit += int(row.get("credit_cents") or 0)
    tb_balanced = tb_debit == tb_credit

    return {
        "as_of": now,
        "cash_position_cents": cash_cents,
        "accounts_receivable_cents": ar_cents,
        "accounts_payable_cents": ap_cents,
        "revenue_mtd_cents": revenue_mtd,
        "revenue_today_cents": revenue_today,
        "sales_tax_liability_cents": sales_tax_liability,
        "payroll_liability_cents": payroll_liability,
        "dead_letter_count": dead_letter_count,
        "unposted_event_count": unposted_events,
        "total_event_count": total_events,
        "trial_balance": {
            "balanced": tb_balanced,
            "debit_cents": tb_debit,
            "credit_cents": tb_credit,
            "delta_cents": tb_debit - tb_credit,
        },
        "ar_aging": ar_aging_data.get("buckets", {}),
    }
