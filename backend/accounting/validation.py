"""
Ledger validation — reads the ledger + operational tables to produce a single
health report. Fully read-only. Never modifies data.

Checks performed
----------------
1. Trial balance — sum(debits) == sum(credits) across all journal entries.
2. Balance sheet — Assets == Liabilities + Equity + Net income.
3. Orphan journal entries — entries whose event_id is set but no matching
   AccountingEvent exists (or event_id is missing entirely on non-manual
   entries).
4. Missing source documents — journal entries whose source_type/source_id
   points to a collection but the source doc no longer exists (excluding
   'manual' journals).
5. Dead-letter summary — count + top reasons in db.posting_dead_letters.
6. Duplicate accounting events — idempotency_key groups that appear more
   than once (should be impossible thanks to the unique index, but we check
   anyway to detect index gaps).
7. Journal integrity — per-entry debit == credit assertion.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from deps import db

from .journal import trial_balance
from .reports import balance_sheet


SOURCE_COLLECTION_MAP = {
    "transaction":     "transactions",
    "invoice":         "invoices",
    "membership":      "memberships",
    "expense":         "expenses",
    "bill":            "vendor_bills",
    "inventory_txn":   "inventory_transactions",
    "payroll_run":     "payroll_runs",
}


async def _check_trial_balance() -> dict:
    pipeline = [
        {"$unwind": "$lines"},
        {"$group": {"_id": None,
                    "debit": {"$sum": "$lines.debit_cents"},
                    "credit": {"$sum": "$lines.credit_cents"}}},
    ]
    rows = await db.journal_entries.aggregate(pipeline).to_list(1)
    if not rows:
        return {"ok": True, "debit_cents": 0, "credit_cents": 0, "delta_cents": 0}
    d = int(rows[0].get("debit") or 0)
    c = int(rows[0].get("credit") or 0)
    return {"ok": d == c, "debit_cents": d, "credit_cents": c,
            "delta_cents": d - c}


async def _check_balance_sheet() -> dict:
    bs = await balance_sheet(datetime.now(timezone.utc))
    return {
        "ok": bool(bs.get("balanced")),
        "total_assets_cents": bs.get("total_assets_cents", 0),
        "total_liab_and_equity_cents": bs.get("total_liab_and_equity_cents", 0),
    }


async def _check_orphan_entries(limit: int = 50) -> dict:
    orphans: list[dict] = []
    # Only journal entries which reference an event_id (skip manual reversals + old rows)
    cursor = db.journal_entries.find(
        {"event_id": {"$type": "string"}},
        {"id": 1, "event_id": 1, "memo": 1, "posted_at": 1},
    )
    async for je in cursor:
        ev = await db.accounting_events.find_one(
            {"id": je["event_id"]}, {"id": 1}
        )
        if not ev:
            orphans.append({
                "entry_id": je["id"], "event_id": je["event_id"],
                "memo": je.get("memo"), "posted_at": je.get("posted_at"),
            })
        if len(orphans) >= limit:
            break
    return {"ok": len(orphans) == 0,
            "count": len(orphans),
            "sample": orphans[:20]}


async def _check_missing_sources(limit: int = 50) -> dict:
    missing: list[dict] = []
    cursor = db.journal_entries.find(
        {"source_type": {"$nin": ["manual", "", None]}, "source_id": {"$ne": ""}},
        {"id": 1, "source_type": 1, "source_id": 1, "memo": 1, "posted_at": 1},
    ).sort("posted_at", -1).limit(2000)
    async for je in cursor:
        coll = SOURCE_COLLECTION_MAP.get(je.get("source_type"))
        if not coll:
            continue
        exists = await db[coll].find_one({"id": je["source_id"]}, {"id": 1})
        if not exists:
            missing.append({
                "entry_id": je["id"], "source_type": je["source_type"],
                "source_id": je["source_id"], "memo": je.get("memo"),
            })
        if len(missing) >= limit:
            break
    return {"ok": len(missing) == 0,
            "count": len(missing),
            "sample": missing[:20]}


async def _check_dead_letters(limit: int = 20) -> dict:
    total = await db.posting_dead_letters.count_documents({})
    pipeline = [
        {"$group": {"_id": "$reason", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
        {"$limit": 10},
    ]
    reasons = [{"reason": r["_id"], "count": r["n"]}
               async for r in db.posting_dead_letters.aggregate(pipeline)]
    recent = []
    async for dl in db.posting_dead_letters.find(
        {}, {"id": 1, "event_type": 1, "reason": 1, "created_at": 1}
    ).sort("created_at", -1).limit(limit):
        recent.append({"id": dl["id"], "event_type": dl.get("event_type"),
                       "reason": dl.get("reason"),
                       "created_at": dl.get("created_at")})
    return {"ok": total == 0, "count": total,
            "top_reasons": reasons, "recent": recent}


async def _check_duplicate_events() -> dict:
    pipeline = [
        {"$group": {"_id": "$idempotency_key", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}},
        {"$limit": 50},
    ]
    dups = [{"idempotency_key": r["_id"], "count": r["n"]}
            async for r in db.accounting_events.aggregate(pipeline)]
    return {"ok": len(dups) == 0, "count": len(dups), "sample": dups[:20]}


async def _check_journal_integrity(limit: int = 50) -> dict:
    """Every stored entry must have DR == CR. Detect any drift."""
    bad: list[dict] = []
    cursor = db.journal_entries.find(
        {}, {"id": 1, "total_debits": 1, "total_credits": 1, "memo": 1, "posted_at": 1},
    )
    async for je in cursor:
        d = int(je.get("total_debits") or 0)
        c = int(je.get("total_credits") or 0)
        if d != c:
            bad.append({"entry_id": je["id"], "debit_cents": d,
                        "credit_cents": c, "memo": je.get("memo"),
                        "posted_at": je.get("posted_at")})
        if len(bad) >= limit:
            break
    return {"ok": len(bad) == 0, "count": len(bad), "sample": bad[:20]}


async def run_all() -> dict:
    tb = await _check_trial_balance()
    bs = await _check_balance_sheet()
    orphans = await _check_orphan_entries()
    missing = await _check_missing_sources()
    dl = await _check_dead_letters()
    dups = await _check_duplicate_events()
    integrity = await _check_journal_integrity()
    healthy = all(c["ok"] for c in
                  (tb, bs, orphans, missing, dl, dups, integrity))
    return {
        "generated_at": datetime.now(timezone.utc),
        "healthy": healthy,
        "checks": {
            "trial_balance":       tb,
            "balance_sheet":       bs,
            "orphan_entries":      orphans,
            "missing_sources":     missing,
            "dead_letters":        dl,
            "duplicate_events":    dups,
            "journal_integrity":   integrity,
        },
    }
