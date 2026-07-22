"""
Journal writer — the ONLY module that writes to `journal_entries`.
Balance is enforced at write time; entries are immutable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from deps import db
from models import new_id


async def ensure_indexes() -> None:
    try:
        # Drop legacy sparse index if present (old shape); then create partial-filter unique
        try:
            await db.journal_entries.drop_index("event_id_1")
        except Exception:
            pass
        await db.journal_entries.create_index(
            "event_id", unique=True,
            partialFilterExpression={"event_id": {"$type": "string"}},
            name="event_id_unique_when_string",
        )
        await db.journal_entries.create_index([("posted_at", -1)])
        await db.journal_entries.create_index("lines.account_code")
        await db.accounting_events.create_index("idempotency_key", unique=True)
        await db.accounting_events.create_index([("recorded_at", -1)])
    except Exception:
        pass


async def write_entry(
    *,
    lines: List[dict],
    memo: str,
    source_type: str,
    source_id: str,
    event_id: Optional[str] = None,
    posted_by: Optional[str] = None,
    posted_by_name: Optional[str] = None,
    reverses_entry_id: Optional[str] = None,
    context: Optional[dict] = None,
) -> dict:
    """Write a balanced journal entry.

    Each `line` must be {account_code, debit_cents, credit_cents} where
    exactly one of the two amounts is > 0.
    """
    if not lines:
        raise ValueError("empty journal entry")
    dr_total = 0
    cr_total = 0
    for ln in lines:
        d = int(ln.get("debit_cents") or 0)
        c = int(ln.get("credit_cents") or 0)
        if d < 0 or c < 0:
            raise ValueError("negative amount")
        if (d > 0 and c > 0) or (d == 0 and c == 0):
            raise ValueError("each line must have exactly one nonzero side")
        dr_total += d
        cr_total += c
    if dr_total != cr_total:
        raise ValueError(f"unbalanced entry: DR={dr_total} CR={cr_total}")
    now = datetime.now(timezone.utc)
    doc = {
        "id": new_id(),
        "event_id": event_id,
        "reverses_entry_id": reverses_entry_id,
        "posted_at": now,
        "posted_by": posted_by,
        "posted_by_name": posted_by_name,
        "memo": memo[:400],
        "source_type": source_type,
        "source_id": source_id,
        "context": context or {},
        "lines": [
            {
                "account_code": ln["account_code"],
                "debit_cents": int(ln.get("debit_cents") or 0),
                "credit_cents": int(ln.get("credit_cents") or 0),
                "line_memo": (ln.get("line_memo") or "")[:200] or None,
            }
            for ln in lines
        ],
        "total_debits": dr_total,
        "total_credits": cr_total,
    }
    await db.journal_entries.insert_one(doc)
    return doc


async def gl_activity(account_code: str,
                      start: Optional[datetime] = None,
                      end: Optional[datetime] = None) -> dict:
    """Return running-balance activity for one account in a date window."""
    q: dict = {"lines.account_code": account_code}
    if start or end:
        q["posted_at"] = {}
        if start: q["posted_at"]["$gte"] = start
        if end: q["posted_at"]["$lte"] = end
        if not q["posted_at"]: q.pop("posted_at")
    rows = await db.journal_entries.find(q).sort("posted_at", 1).to_list(2000)
    activity = []
    running = 0
    for r in rows:
        for ln in r["lines"]:
            if ln["account_code"] != account_code:
                continue
            debit = int(ln.get("debit_cents") or 0)
            credit = int(ln.get("credit_cents") or 0)
            running += debit - credit
            activity.append({
                "entry_id": r["id"],
                "posted_at": r["posted_at"],
                "memo": r["memo"],
                "source_type": r.get("source_type"),
                "source_id": r.get("source_id"),
                "debit_cents": debit,
                "credit_cents": credit,
                "running_cents": running,
            })
    return {"account_code": account_code, "rows": activity, "closing_balance_cents": running}


async def trial_balance(as_of: Optional[datetime] = None) -> dict:
    """Sum every account's debits & credits — foundation for P&L / BS."""
    match: dict = {}
    if as_of:
        match["posted_at"] = {"$lte": as_of}
    pipeline = [
        {"$match": match},
        {"$unwind": "$lines"},
        {"$group": {
            "_id": "$lines.account_code",
            "debit": {"$sum": "$lines.debit_cents"},
            "credit": {"$sum": "$lines.credit_cents"},
        }},
    ]
    rows = await db.journal_entries.aggregate(pipeline).to_list(1000)
    balances = {}
    for r in rows:
        d = int(r.get("debit") or 0)
        c = int(r.get("credit") or 0)
        balances[r["_id"]] = {"debit_cents": d, "credit_cents": c, "net_cents": d - c}
    return balances


async def reverse_entry(entry_id: str, memo: str, posted_by: str,
                        posted_by_name: str) -> dict:
    """Immutable-safe reversal: mirror debits & credits into a NEW entry."""
    original = await db.journal_entries.find_one({"id": entry_id})
    if not original:
        raise ValueError("original entry not found")
    if original.get("reverses_entry_id"):
        raise ValueError("cannot reverse a reversal")
    mirrored = []
    for ln in original["lines"]:
        mirrored.append({
            "account_code": ln["account_code"],
            "debit_cents": ln.get("credit_cents") or 0,
            "credit_cents": ln.get("debit_cents") or 0,
            "line_memo": f"Reversal: {ln.get('line_memo') or ''}",
        })
    return await write_entry(
        lines=mirrored, memo=memo,
        source_type=original["source_type"], source_id=original["source_id"],
        reverses_entry_id=entry_id,
        posted_by=posted_by, posted_by_name=posted_by_name,
    )
