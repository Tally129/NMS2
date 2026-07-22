"""
Banking & cash reports + dashboard.

Derived entirely from journal_entries + bank_transactions + reconciliations.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from deps import db

from .journal import trial_balance


async def _bank_account(bank_account_id: str) -> dict:
    ba = await db.bank_accounts.find_one({"id": bank_account_id})
    if not ba:
        raise ValueError("bank account not found")
    return ba


# ---------------------------------------------------------------- registers #
async def bank_register(
    bank_account_id: str,
    start: Optional[datetime] = None, end: Optional[datetime] = None,
    limit: int = 500,
) -> dict:
    ba = await _bank_account(bank_account_id)
    gl_code = ba["gl_account_code"]
    q: dict = {"lines.account_code": gl_code}
    if start or end:
        q["posted_at"] = {}
        if start: q["posted_at"]["$gte"] = start
        if end: q["posted_at"]["$lte"] = end
    rows = await db.journal_entries.find(q).sort("posted_at", 1).to_list(limit)
    activity = []
    running = 0
    for r in rows:
        for ln in r.get("lines", []):
            if ln["account_code"] != gl_code:
                continue
            d = int(ln.get("debit_cents") or 0)
            c = int(ln.get("credit_cents") or 0)
            running += d - c
            activity.append({
                "entry_id": r["id"],
                "posted_at": r["posted_at"],
                "memo": r.get("memo"),
                "debit_cents": d,
                "credit_cents": c,
                "running_cents": running,
                "reconciliation_id": r.get("reconciliation_id"),
                "matched_bank_transaction_id": r.get("matched_bank_transaction_id"),
            })
    return {"bank_account": ba, "rows": activity,
            "closing_balance_cents": running}


# ---------------------------------------------------------------- outstanding #
async def outstanding_deposits(
    bank_account_id: Optional[str] = None,
) -> dict:
    """Ledger deposits (positive amount on this account) that are NOT yet
    reconciled or matched to a bank transaction."""
    accounts = ([await _bank_account(bank_account_id)] if bank_account_id
                else await db.bank_accounts.find({"active": True}).to_list(200))
    out = []
    total = 0
    for ba in accounts:
        gl_code = ba["gl_account_code"]
        cursor = db.journal_entries.find({
            "lines.account_code": gl_code,
            "reconciliation_id": {"$in": [None]},
        }).sort("posted_at", -1).limit(500)
        async for je in cursor:
            for ln in je.get("lines", []):
                if ln["account_code"] == gl_code and int(ln.get("debit_cents") or 0) > 0:
                    amt = int(ln["debit_cents"])
                    total += amt
                    out.append({
                        "bank_account_id": ba["id"],
                        "bank_account_name": ba["name"],
                        "entry_id": je["id"], "posted_at": je["posted_at"],
                        "memo": je.get("memo"), "amount_cents": amt,
                    })
                    break
    return {"rows": out, "total_cents": total}


async def outstanding_checks(
    bank_account_id: Optional[str] = None,
) -> dict:
    """Ledger withdrawals (credits on this account) not yet reconciled."""
    accounts = ([await _bank_account(bank_account_id)] if bank_account_id
                else await db.bank_accounts.find({"active": True}).to_list(200))
    out = []
    total = 0
    for ba in accounts:
        gl_code = ba["gl_account_code"]
        cursor = db.journal_entries.find({
            "lines.account_code": gl_code,
            "reconciliation_id": {"$in": [None]},
        }).sort("posted_at", -1).limit(500)
        async for je in cursor:
            for ln in je.get("lines", []):
                if ln["account_code"] == gl_code and int(ln.get("credit_cents") or 0) > 0:
                    amt = int(ln["credit_cents"])
                    total += amt
                    out.append({
                        "bank_account_id": ba["id"],
                        "bank_account_name": ba["name"],
                        "entry_id": je["id"], "posted_at": je["posted_at"],
                        "memo": je.get("memo"), "amount_cents": amt,
                    })
                    break
    return {"rows": out, "total_cents": total}


# ---------------------------------------------------------------- recon reports #
async def reconciliation_report(reconciliation_id: str) -> dict:
    rec = await db.reconciliations.find_one({"id": reconciliation_id})
    if not rec:
        raise ValueError("reconciliation not found")
    ba = await db.bank_accounts.find_one({"id": rec["bank_account_id"]})
    txns = await db.bank_transactions.find(
        {"id": {"$in": rec["bank_txn_ids"]}}
    ).to_list(2000)
    jes = await db.journal_entries.find(
        {"id": {"$in": rec["journal_entry_ids"]}}
    ).to_list(2000)
    return {"reconciliation": rec, "bank_account": ba,
            "bank_transactions": txns, "journal_entries": jes}


async def outstanding_reconciliation_report(
    as_of: Optional[datetime] = None,
) -> dict:
    now = as_of or datetime.now(timezone.utc)
    from .reconciliation import _amount_from_gl_line, _candidate_journal_entries, AUTO_MATCH_DATE_WINDOW_DAYS

    def _tz(d):
        if not isinstance(d, datetime):
            return now
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

    accounts = await db.bank_accounts.find({"active": True}).to_list(200)
    per_account = []
    grand_bank = 0
    grand_ledger = 0
    for ba in accounts:
        gl_code = ba["gl_account_code"]
        bank_rows = await db.bank_transactions.find({
            "bank_account_id": ba["id"], "status": "unmatched",
        }).sort("posted_at", -1).to_list(500)
        for row in bank_rows:
            posted = _tz(row.get("posted_at"))
            row["days_outstanding"] = max(0, (now - posted).days)
            # Attempt a best-effort match confidence
            window_start = posted - timedelta(days=AUTO_MATCH_DATE_WINDOW_DAYS)
            window_end = posted + timedelta(days=AUTO_MATCH_DATE_WINDOW_DAYS)
            candidates = await _candidate_journal_entries(
                gl_code, window_start, window_end)
            best = 0
            for je in candidates:
                for ln in je.get("lines", []):
                    if ln["account_code"] == gl_code and \
                            _amount_from_gl_line(ln) == row["amount_cents"]:
                        best = 70    # exact amount = strong candidate
                        break
                if best:
                    break
            row["suggested_confidence"] = best
        ledger_rows = await db.journal_entries.find({
            "lines.account_code": gl_code,
            "reconciliation_id": {"$in": [None]},
            "matched_bank_transaction_id": {"$in": [None]},
        }).sort("posted_at", -1).to_list(500)
        for je in ledger_rows:
            posted = _tz(je.get("posted_at"))
            je["days_outstanding"] = max(0, (now - posted).days)
            for ln in je.get("lines", []):
                if ln["account_code"] == gl_code:
                    je["bank_amount_cents"] = _amount_from_gl_line(ln)
                    break
        per_account.append({
            "bank_account": ba,
            "unmatched_bank_transactions": bank_rows,
            "unmatched_ledger_entries": ledger_rows,
            "count_bank": len(bank_rows),
            "count_ledger": len(ledger_rows),
        })
        grand_bank += sum(int(r.get("amount_cents") or 0) for r in bank_rows)
        grand_ledger += sum(int(j.get("bank_amount_cents") or 0)
                             for j in ledger_rows)
    return {
        "as_of": now, "accounts": per_account,
        "totals": {
            "unmatched_bank_cents": grand_bank,
            "unmatched_ledger_cents": grand_ledger,
        },
    }


# ---------------------------------------------------------------- cash dashboard #
CASH_LIKE_KINDS = ("checking", "savings", "payroll", "petty_cash",
                    "merchant_clearing")


async def cash_dashboard() -> dict:
    accounts = await db.bank_accounts.find({"active": True}).to_list(200)
    tb = await trial_balance()
    per_account = []
    total_ledger = 0
    total_cleared = 0
    total_out_deposits = 0
    total_out_checks = 0
    for ba in accounts:
        gl_code = ba["gl_account_code"]
        ledger = int(tb.get(gl_code, {"net_cents": 0})["net_cents"])
        # For liability accounts (credit-normal), invert sign for display.
        coa = await db.chart_of_accounts.find_one({"code": gl_code})
        if coa and coa.get("normal_balance") == "credit":
            ledger = -ledger
        # Cleared balance = sum of debit-credit for lines that ARE reconciled
        cleared = 0
        async for je in db.journal_entries.find(
            {"lines.account_code": gl_code,
             "reconciliation_id": {"$ne": None}},
            {"lines": 1},
        ):
            for ln in je.get("lines", []):
                if ln["account_code"] == gl_code:
                    d = int(ln.get("debit_cents") or 0)
                    c = int(ln.get("credit_cents") or 0)
                    cleared += d - c
        if coa and coa.get("normal_balance") == "credit":
            cleared = -cleared

        out_deposit = 0
        out_check = 0
        async for je in db.journal_entries.find(
            {"lines.account_code": gl_code,
             "reconciliation_id": {"$in": [None]}},
            {"lines": 1},
        ):
            for ln in je.get("lines", []):
                if ln["account_code"] != gl_code:
                    continue
                d = int(ln.get("debit_cents") or 0)
                c = int(ln.get("credit_cents") or 0)
                if d > 0:
                    out_deposit += d
                if c > 0:
                    out_check += c
                break

        bank_balance = ba.get("last_reconciled_ending_balance_cents") or 0
        difference = ledger - bank_balance

        per_account.append({
            "id": ba["id"], "name": ba["name"], "kind": ba["kind"],
            "gl_code": gl_code, "institution": ba.get("institution"),
            "last_four": ba.get("last_four"),
            "ledger_balance_cents": ledger,
            "cleared_balance_cents": cleared,
            "outstanding_deposits_cents": out_deposit,
            "outstanding_checks_cents": out_check,
            "bank_balance_cents": bank_balance,
            "difference_cents": difference,
            "last_reconciled_at": ba.get("last_reconciled_at"),
        })
        if ba.get("kind") in CASH_LIKE_KINDS:
            total_ledger += ledger
            total_cleared += cleared
            total_out_deposits += out_deposit
            total_out_checks += out_check
    return {
        "accounts": per_account,
        "totals": {
            "current_cash_cents": total_ledger,
            "cleared_cash_cents": total_cleared,
            "outstanding_deposits_cents": total_out_deposits,
            "outstanding_checks_cents": total_out_checks,
        },
        "generated_at": datetime.now(timezone.utc),
    }


# ---------------------------------------------------------------- cash flow #
async def cash_flow_summary(start: datetime, end: datetime) -> dict:
    """Simple direct-method cash flow: net change per cash-like GL code in period."""
    ba_docs = await db.bank_accounts.find({"active": True}).to_list(200)
    per_account = []
    grand_in = 0
    grand_out = 0
    for ba in ba_docs:
        gl_code = ba["gl_account_code"]
        in_c = 0
        out_c = 0
        async for je in db.journal_entries.find({
            "lines.account_code": gl_code,
            "posted_at": {"$gte": start, "$lte": end},
        }, {"lines": 1}):
            for ln in je.get("lines", []):
                if ln["account_code"] != gl_code:
                    continue
                in_c += int(ln.get("debit_cents") or 0)
                out_c += int(ln.get("credit_cents") or 0)
                break
        per_account.append({
            "bank_account_id": ba["id"], "name": ba["name"],
            "gl_code": gl_code,
            "inflow_cents": in_c, "outflow_cents": out_c,
            "net_cents": in_c - out_c,
        })
        if ba.get("kind") in CASH_LIKE_KINDS:
            grand_in += in_c
            grand_out += out_c
    return {"period": {"start": start, "end": end},
            "per_account": per_account,
            "totals": {"inflow_cents": grand_in, "outflow_cents": grand_out,
                        "net_cents": grand_in - grand_out}}


# ---------------------------------------------------------------- Stripe settlement #
async def stripe_settlement_summary(
    start: datetime, end: datetime,
) -> dict:
    """Read-only aggregation using ledger + Stripe integration_log entries.
    Gross deposits = 1200 credits paired with 1100 debits (or 5200 fees).
    """
    tb_end = await trial_balance(as_of=end)
    tb_start = await trial_balance(as_of=start - timedelta(seconds=1))

    def delta(code: str, sign: int = 1) -> int:
        e = tb_end.get(code, {"debit_cents": 0, "credit_cents": 0})
        s = tb_start.get(code, {"debit_cents": 0, "credit_cents": 0})
        d = (int(e.get("debit_cents") or 0) - int(s.get("debit_cents") or 0)) \
            - (int(e.get("credit_cents") or 0) - int(s.get("credit_cents") or 0))
        return d * sign

    # Stripe clearing (1200) — debits are gross receipts, credits are payouts + fees
    receipts_gross = 0
    fees_charged = 0
    refunds_issued = 0
    async for je in db.journal_entries.find({
        "lines.account_code": "1200",
        "posted_at": {"$gte": start, "$lte": end},
    }, {"lines": 1, "source_type": 1}):
        for ln in je.get("lines", []):
            if ln["account_code"] == "1200":
                receipts_gross += int(ln.get("debit_cents") or 0)
                fees_charged += 0     # separate rule counts these
        # StripeFeeCharged has a CR to 1200 and DR to 5200 — captured separately
        for ln in je.get("lines", []):
            if ln["account_code"] == "5200":
                fees_charged += int(ln.get("debit_cents") or 0)

    # Refunds — SaleRefunded events (rule not built yet) would credit 4100 & debit cash
    # Best-effort: negative-amount events tagged as refund
    async for ev in db.accounting_events.find({
        "event_type": {"$in": ["SaleRefunded", "StripeRefundIssued"]},
        "recorded_at": {"$gte": start, "$lte": end},
    }, {"amount_cents": 1}):
        refunds_issued += int(ev.get("amount_cents") or 0)

    payouts_from_stripe = -delta("1200", sign=1) if delta("1200", sign=1) < 0 else 0
    net_deposit = receipts_gross - fees_charged - refunds_issued
    return {
        "period": {"start": start, "end": end},
        "gross_deposits_cents": receipts_gross,
        "fees_cents": fees_charged,
        "refunds_cents": refunds_issued,
        "net_cents": net_deposit,
    }
