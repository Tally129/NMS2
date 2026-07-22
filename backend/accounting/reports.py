"""
Financial statements — pure math on chart_of_accounts + journal_entries.
Everything below expects amounts in integer cents.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from deps import db

from .journal import trial_balance


async def _accounts_by_type() -> dict[str, list[dict]]:
    rows = await db.chart_of_accounts.find({"active": True}).sort("code", 1).to_list(500)
    grouped: dict[str, list[dict]] = {t: [] for t in
                                       ("asset", "liability", "equity",
                                        "revenue", "cogs", "expense")}
    for r in rows:
        grouped.setdefault(r["type"], []).append(r)
    return grouped


async def profit_and_loss(start: datetime, end: datetime) -> dict:
    """P&L: Revenue − COGS − Expense across a period."""
    # trial_balance is cumulative-to-date; subtract before-start to isolate window
    tb_end = await trial_balance(as_of=end)
    tb_start = await trial_balance(as_of=start - timedelta(seconds=1)) if start else {}
    accounts = await _accounts_by_type()

    def net_for(section: str) -> tuple[list, int]:
        out = []
        total = 0
        for a in accounts.get(section, []):
            end_b = tb_end.get(a["code"], {"net_cents": 0})["net_cents"]
            start_b = tb_start.get(a["code"], {"net_cents": 0})["net_cents"] if tb_start else 0
            delta = end_b - start_b
            # Revenue accounts carry credit balances → their "amount" is -delta
            if a["normal_balance"] == "credit":
                amt = -delta
            else:
                amt = delta
            if amt != 0:
                out.append({"code": a["code"], "name": a["name"], "amount_cents": amt})
                total += amt
        return out, total

    revenue, rev_total = net_for("revenue")
    cogs, cogs_total = net_for("cogs")
    expenses, exp_total = net_for("expense")
    gross_profit = rev_total - cogs_total
    net_income = gross_profit - exp_total
    return {
        "period": {"start": start, "end": end},
        "revenue": revenue, "total_revenue_cents": rev_total,
        "cogs": cogs, "total_cogs_cents": cogs_total,
        "gross_profit_cents": gross_profit,
        "expenses": expenses, "total_expenses_cents": exp_total,
        "net_income_cents": net_income,
    }


async def balance_sheet(as_of: datetime) -> dict:
    tb = await trial_balance(as_of=as_of)
    accounts = await _accounts_by_type()

    def net_for(section: str) -> tuple[list, int]:
        out = []
        total = 0
        for a in accounts.get(section, []):
            b = tb.get(a["code"], {"net_cents": 0})["net_cents"]
            if a["normal_balance"] == "credit":
                amt = -b
            else:
                amt = b
            if amt != 0:
                out.append({"code": a["code"], "name": a["name"], "amount_cents": amt})
                total += amt
        return out, total

    assets, assets_total = net_for("asset")
    liabilities, liab_total = net_for("liability")
    equity, equity_total = net_for("equity")
    # Retained earnings = cumulative net income
    rev_total = sum(-tb.get(a["code"], {"net_cents": 0})["net_cents"]
                    for a in accounts.get("revenue", []))
    cogs_total = sum(tb.get(a["code"], {"net_cents": 0})["net_cents"]
                     for a in accounts.get("cogs", []))
    exp_total = sum(tb.get(a["code"], {"net_cents": 0})["net_cents"]
                    for a in accounts.get("expense", []))
    net_income = rev_total - cogs_total - exp_total
    return {
        "as_of": as_of,
        "assets": assets, "total_assets_cents": assets_total,
        "liabilities": liabilities, "total_liabilities_cents": liab_total,
        "equity": equity, "total_equity_cents": equity_total,
        "current_period_net_income_cents": net_income,
        "total_liab_and_equity_cents": liab_total + equity_total + net_income,
        "balanced": assets_total == (liab_total + equity_total + net_income),
    }


async def trial_balance_report(as_of: Optional[datetime] = None) -> dict:
    tb = await trial_balance(as_of=as_of)
    rows = await db.chart_of_accounts.find({"active": True}).sort("code", 1).to_list(500)
    out = []
    total_dr = 0
    total_cr = 0
    for a in rows:
        b = tb.get(a["code"], {"debit_cents": 0, "credit_cents": 0})
        d = int(b.get("debit_cents") or 0)
        c = int(b.get("credit_cents") or 0)
        if d == 0 and c == 0:
            continue
        out.append({"code": a["code"], "name": a["name"], "type": a["type"],
                    "debit_cents": d, "credit_cents": c})
        total_dr += d
        total_cr += c
    return {"as_of": as_of, "rows": out,
            "total_debit_cents": total_dr, "total_credit_cents": total_cr,
            "balanced": total_dr == total_cr}


async def ar_aging(as_of: Optional[datetime] = None) -> dict:
    """A/R aging derived from existing db.invoices (status='due')."""
    now = as_of or datetime.now(timezone.utc)
    buckets = {"current": 0, "1_30": 0, "31_60": 0, "61_90": 0, "over_90": 0}
    detail: list[dict] = []
    async for inv in db.invoices.find({"status": "due"}):
        created = inv.get("created_at")
        if not created:
            continue
        if isinstance(created, str):
            try: created = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except Exception: continue
        # normalize timezone
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (now - created).days
        amount_cents = int(round(float(inv.get("amount") or 0) * 100))
        if age_days <= 0:
            bucket = "current"
        elif age_days <= 30:
            bucket = "1_30"
        elif age_days <= 60:
            bucket = "31_60"
        elif age_days <= 90:
            bucket = "61_90"
        else:
            bucket = "over_90"
        buckets[bucket] += amount_cents
        detail.append({
            "invoice_id": inv["id"], "client_id": inv.get("client_id"),
            "amount_cents": amount_cents, "age_days": age_days, "bucket": bucket,
            "created_at": created,
        })
    return {"as_of": now, "buckets": buckets, "total_cents": sum(buckets.values()),
            "detail": detail}
