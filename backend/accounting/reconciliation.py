"""
Reconciliation workspace + engine.

Concepts
--------
* A **bank transaction** is a row imported from a statement (status: unmatched
  | matched | reconciled | split).
* A **journal entry** is what our ledger already wrote via the posting engine.
  We match by the SINGLE-account line that touches this bank's GL code.
* A **reconciliation** is a finalized session: it points at N bank_transactions
  + N journal_entries that have all been marked reconciled together, at a
  chosen statement end-date + ending balance.

Matching modes
--------------
* **Auto-match**: exact amount, date within ±7 days, memo/reference similarity
  breaks ties. Confidence is scored 0-100.
* **Manual-match**: user picks one journal entry.
* **Split**: user divides a single bank txn across multiple journal entries
  (e.g. one deposit clears two customer invoices).

Nothing posts new ledger entries during matching. Reconciliation only sets
`reconciliation_id` + `reconciled_at` on the journal entry and mirrors the
status on the bank transaction.
"""
from __future__ import annotations

import difflib
from datetime import datetime, timedelta, timezone
from typing import Optional

from deps import db
from models import new_id


AUTO_MATCH_DATE_WINDOW_DAYS = 7


# ---------------------------------------------------------------- helpers #
def _amount_from_gl_line(line: dict) -> int:
    """Signed amount for a line in the bank's GL account:
    debits are + (cash in), credits are - (cash out)."""
    d = int(line.get("debit_cents") or 0)
    c = int(line.get("credit_cents") or 0)
    return d - c


def _similarity(a: Optional[str], b: Optional[str]) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


async def _candidate_journal_entries(
    gl_code: str, since: datetime, until: datetime,
) -> list[dict]:
    """Journal entries in the window that touch this GL account and haven't
    been reconciled yet."""
    q = {
        "lines.account_code": gl_code,
        "posted_at": {"$gte": since, "$lte": until},
        "reconciliation_id": {"$in": [None]},
    }
    return await db.journal_entries.find(q).sort("posted_at", 1).to_list(2000)


# ---------------------------------------------------------------- workspace #
async def workspace(bank_account_id: str,
                    lookback_days: int = 90) -> dict:
    ba = await db.bank_accounts.find_one({"id": bank_account_id})
    if not ba:
        raise ValueError("bank account not found")
    gl_code = ba["gl_account_code"]
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=lookback_days)

    # Bank side
    bank_txns = await db.bank_transactions.find({
        "bank_account_id": bank_account_id,
        "posted_at": {"$gte": since},
    }).sort("posted_at", -1).to_list(2000)

    # Ledger side — every journal_entry with a line on this GL code in window.
    journal = await db.journal_entries.find({
        "lines.account_code": gl_code,
        "posted_at": {"$gte": since},
    }).sort("posted_at", -1).to_list(2000)

    # Simplify journal entries down to the bank-side line only
    for je in journal:
        for ln in je.get("lines", []):
            if ln["account_code"] == gl_code:
                je["bank_amount_cents"] = _amount_from_gl_line(ln)
                break

    return {
        "bank_account": ba,
        "gl_code": gl_code,
        "bank_transactions": bank_txns,
        "journal_entries": journal,
        "counts": {
            "bank_unmatched": sum(1 for r in bank_txns if r["status"] == "unmatched"),
            "bank_matched": sum(1 for r in bank_txns if r["status"] in ("matched", "split")),
            "bank_reconciled": sum(1 for r in bank_txns if r["status"] == "reconciled"),
            "journal_total": len(journal),
            "journal_unreconciled": sum(1 for j in journal if not j.get("reconciliation_id")),
        },
    }


# ---------------------------------------------------------------- auto-match #
async def auto_match(bank_account_id: str) -> dict:
    ba = await db.bank_accounts.find_one({"id": bank_account_id})
    if not ba:
        raise ValueError("bank account not found")
    gl_code = ba["gl_account_code"]
    now = datetime.now(timezone.utc)

    def _tz(d):
        if not isinstance(d, datetime):
            return now
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

    bank_txns = await db.bank_transactions.find({
        "bank_account_id": bank_account_id, "status": "unmatched",
    }).sort("posted_at", -1).to_list(1000)

    proposals: list[dict] = []
    used_je_ids: set[str] = set()
    for bt in bank_txns:
        bt_posted = _tz(bt.get("posted_at"))
        window_start = bt_posted - timedelta(days=AUTO_MATCH_DATE_WINDOW_DAYS)
        window_end = bt_posted + timedelta(days=AUTO_MATCH_DATE_WINDOW_DAYS)
        candidates = await _candidate_journal_entries(gl_code,
                                                     window_start, window_end)
        best = None
        best_score = 0
        for je in candidates:
            if je["id"] in used_je_ids:
                continue
            bank_amt = None
            for ln in je.get("lines", []):
                if ln["account_code"] == gl_code:
                    bank_amt = _amount_from_gl_line(ln)
                    break
            if bank_amt is None:
                continue
            if bank_amt != bt["amount_cents"]:
                continue
            je_posted = _tz(je.get("posted_at"))
            days = abs((je_posted - bt_posted).days)
            date_score = max(0, 40 - int(days * 5))            # 40..0
            memo_score = int(_similarity(bt.get("description"),
                                         je.get("memo")) * 60)  # 0..60
            score = max(0, min(100, 40 + date_score + memo_score))
            if score > best_score:
                best_score = score
                best = je
        if best:
            proposals.append({
                "bank_transaction_id": bt["id"],
                "journal_entry_id": best["id"],
                "confidence": best_score,
                "bank_amount_cents": bt["amount_cents"],
                "je_posted_at": best["posted_at"],
                "bank_posted_at": bt["posted_at"],
                "memo": best.get("memo"),
                "description": bt.get("description"),
            })
            used_je_ids.add(best["id"])
    return {"proposals": proposals, "generated_at": now}


async def confirm_auto_matches(proposals: list[dict], actor: dict) -> dict:
    posted = 0
    skipped = 0
    for p in proposals or []:
        try:
            await match(bank_transaction_id=p["bank_transaction_id"],
                        journal_entry_id=p["journal_entry_id"],
                        actor=actor)
            posted += 1
        except Exception:
            skipped += 1
    return {"matched": posted, "skipped": skipped}


# ---------------------------------------------------------------- manual match #
async def match(*, bank_transaction_id: str, journal_entry_id: str,
                actor: dict) -> dict:
    bt = await db.bank_transactions.find_one({"id": bank_transaction_id})
    je = await db.journal_entries.find_one({"id": journal_entry_id})
    if not bt or not je:
        raise ValueError("bank txn or journal entry not found")
    if bt.get("status") == "reconciled":
        raise ValueError("bank transaction already reconciled")
    if je.get("reconciliation_id"):
        raise ValueError("journal entry already reconciled")
    ba = await db.bank_accounts.find_one({"id": bt["bank_account_id"]})
    gl_code = ba["gl_account_code"]
    # Check amounts align
    bank_amt = None
    for ln in je.get("lines", []):
        if ln["account_code"] == gl_code:
            bank_amt = _amount_from_gl_line(ln)
            break
    if bank_amt is None:
        raise ValueError("journal entry does not touch this bank account")
    if bank_amt != bt["amount_cents"]:
        raise ValueError(
            f"amount mismatch: bank={bt['amount_cents']} ledger={bank_amt}"
        )
    now = datetime.now(timezone.utc)
    await db.bank_transactions.update_one(
        {"id": bank_transaction_id},
        {"$set": {"status": "matched",
                  "matched_journal_entry_ids": [journal_entry_id]}},
    )
    await db.journal_entries.update_one(
        {"id": journal_entry_id},
        {"$set": {"matched_at": now,
                  "matched_by": actor.get("id"),
                  "matched_bank_transaction_id": bank_transaction_id}},
    )
    return {"ok": True, "bank_transaction_id": bank_transaction_id,
            "journal_entry_id": journal_entry_id}


async def unmatch(bank_transaction_id: str) -> dict:
    bt = await db.bank_transactions.find_one({"id": bank_transaction_id})
    if not bt:
        raise ValueError("not found")
    if bt.get("status") == "reconciled":
        raise ValueError("cannot unmatch reconciled txn")
    for jid in bt.get("matched_journal_entry_ids", []):
        await db.journal_entries.update_one({"id": jid},
            {"$unset": {"matched_at": "", "matched_by": "",
                        "matched_bank_transaction_id": ""}})
    await db.bank_transactions.update_one(
        {"id": bank_transaction_id},
        {"$set": {"status": "unmatched", "matched_journal_entry_ids": []}},
    )
    return {"ok": True}


# ---------------------------------------------------------------- split #
async def split_match(*, bank_transaction_id: str,
                      journal_entry_ids: list[str], actor: dict) -> dict:
    bt = await db.bank_transactions.find_one({"id": bank_transaction_id})
    if not bt:
        raise ValueError("bank transaction not found")
    if bt.get("status") == "reconciled":
        raise ValueError("bank transaction already reconciled")
    if len(journal_entry_ids or []) < 2:
        raise ValueError("split requires 2+ journal entries")
    ba = await db.bank_accounts.find_one({"id": bt["bank_account_id"]})
    gl_code = ba["gl_account_code"]
    total = 0
    entries = []
    for jid in journal_entry_ids:
        je = await db.journal_entries.find_one({"id": jid})
        if not je:
            raise ValueError(f"journal entry {jid} not found")
        if je.get("reconciliation_id"):
            raise ValueError(f"journal entry {jid} already reconciled")
        bank_amt = None
        for ln in je.get("lines", []):
            if ln["account_code"] == gl_code:
                bank_amt = _amount_from_gl_line(ln)
                break
        if bank_amt is None:
            raise ValueError(f"je {jid} does not touch this bank account")
        total += bank_amt
        entries.append(je)
    if total != bt["amount_cents"]:
        raise ValueError(f"split sum {total} != bank amount {bt['amount_cents']}")
    now = datetime.now(timezone.utc)
    await db.bank_transactions.update_one(
        {"id": bank_transaction_id},
        {"$set": {"status": "split",
                  "matched_journal_entry_ids": journal_entry_ids}},
    )
    for je in entries:
        await db.journal_entries.update_one({"id": je["id"]},
            {"$set": {"matched_at": now, "matched_by": actor.get("id"),
                      "matched_bank_transaction_id": bank_transaction_id}})
    return {"ok": True, "split_count": len(entries)}


# ---------------------------------------------------------------- finalize #
async def finalize(
    *, bank_account_id: str, statement_end_date: datetime,
    ending_balance_cents: int, notes: Optional[str], actor: dict,
) -> dict:
    ba = await db.bank_accounts.find_one({"id": bank_account_id})
    if not ba:
        raise ValueError("bank account not found")
    if statement_end_date.tzinfo is None:
        statement_end_date = statement_end_date.replace(tzinfo=timezone.utc)
    matched = await db.bank_transactions.find({
        "bank_account_id": bank_account_id,
        "status": {"$in": ["matched", "split"]},
        "posted_at": {"$lte": statement_end_date},
    }).to_list(5000)
    if not matched:
        raise ValueError("nothing to reconcile — match some transactions first")

    now = datetime.now(timezone.utc)
    recon_id = new_id()
    bank_txn_ids = [bt["id"] for bt in matched]
    je_ids: list[str] = []
    for bt in matched:
        je_ids.extend(bt.get("matched_journal_entry_ids") or [])

    reconciliation = {
        "id": recon_id, "bank_account_id": bank_account_id,
        "gl_account_code": ba["gl_account_code"],
        "statement_end_date": statement_end_date,
        "ending_balance_cents": int(ending_balance_cents),
        "bank_txn_ids": bank_txn_ids, "journal_entry_ids": je_ids,
        "txn_count": len(bank_txn_ids), "je_count": len(je_ids),
        "reconciled_amount_cents": sum(int(m.get("amount_cents") or 0) for m in matched),
        "notes": (notes or "")[:400],
        "finalized_by": actor.get("id"),
        "finalized_by_name": actor.get("full_name") or actor.get("email"),
        "finalized_at": now,
    }
    await db.reconciliations.insert_one(reconciliation)
    await db.bank_transactions.update_many(
        {"id": {"$in": bank_txn_ids}},
        {"$set": {"status": "reconciled",
                  "reconciliation_id": recon_id,
                  "reconciled_at": now}},
    )
    if je_ids:
        await db.journal_entries.update_many(
            {"id": {"$in": je_ids}},
            {"$set": {"reconciliation_id": recon_id,
                      "reconciled_at": now}},
        )
    await db.bank_accounts.update_one({"id": bank_account_id}, {"$set": {
        "last_reconciled_at": now,
        "last_reconciled_ending_balance_cents": int(ending_balance_cents),
    }})
    return reconciliation


# ---------------------------------------------------------------- exceptions #
async def exceptions_panel(bank_account_id: Optional[str] = None) -> dict:
    """Group items that need staff attention across (optional) accounts."""
    q_bank = {"status": "unmatched"}
    q_je: dict = {"reconciliation_id": {"$in": [None]}}
    if bank_account_id:
        q_bank["bank_account_id"] = bank_account_id
        ba = await db.bank_accounts.find_one({"id": bank_account_id})
        if ba:
            q_je["lines.account_code"] = ba["gl_account_code"]

    unmatched_bank = await db.bank_transactions.find(q_bank).sort(
        "posted_at", -1).to_list(500)
    unmatched_ledger = await db.journal_entries.find(q_je).sort(
        "posted_at", -1).to_list(500)

    # Duplicate imports: same bank_account+posted_at+amount+reference
    dup_pipeline = [
        {"$match": q_bank if bank_account_id else {}},
        {"$group": {"_id": {"bank_account_id": "$bank_account_id",
                              "posted_at": "$posted_at",
                              "amount_cents": "$amount_cents",
                              "reference": "$reference"},
                     "n": {"$sum": 1},
                     "ids": {"$push": "$id"}}},
        {"$match": {"n": {"$gt": 1}}},
        {"$limit": 100},
    ]
    duplicate_bank = [
        {"key": r["_id"], "count": r["n"], "ids": r["ids"]}
        async for r in db.bank_transactions.aggregate(dup_pipeline)
    ]

    # Amount mismatches — bank txn whose closest ledger candidate differs
    amount_mismatches = []
    date_mismatches = []
    now = datetime.now(timezone.utc)
    for bt in unmatched_bank[:100]:
        ba = await db.bank_accounts.find_one({"id": bt["bank_account_id"]})
        if not ba:
            continue
        gl_code = ba["gl_account_code"]
        bt_posted = bt.get("posted_at")
        if isinstance(bt_posted, datetime) and not bt_posted.tzinfo:
            bt_posted = bt_posted.replace(tzinfo=timezone.utc)
        elif not isinstance(bt_posted, datetime):
            bt_posted = now
        window_start = bt_posted - timedelta(days=AUTO_MATCH_DATE_WINDOW_DAYS)
        window_end = bt_posted + timedelta(days=AUTO_MATCH_DATE_WINDOW_DAYS)
        candidates = await _candidate_journal_entries(
            gl_code, window_start, window_end)
        # amount off ±$1?
        near_amt = None
        for je in candidates:
            for ln in je.get("lines", []):
                if ln["account_code"] == gl_code:
                    a = _amount_from_gl_line(ln)
                    if a != bt["amount_cents"] and abs(a - bt["amount_cents"]) <= 100:
                        near_amt = (je, a)
                        break
            if near_amt:
                break
        if near_amt:
            je, a = near_amt
            amount_mismatches.append({
                "bank_transaction_id": bt["id"],
                "journal_entry_id": je["id"],
                "bank_amount_cents": bt["amount_cents"],
                "ledger_amount_cents": a,
                "posted_at": bt["posted_at"],
            })

    # Possible duplicate journal entries — same amount+source in short window
    je_dup_pipeline = [
        {"$match": {"source_type": {"$nin": ["", None]},
                    "source_id": {"$nin": ["", None]}}},
        {"$group": {"_id": {"source_type": "$source_type",
                             "source_id": "$source_id",
                             "total_debits": "$total_debits"},
                     "n": {"$sum": 1}, "ids": {"$push": "$id"}}},
        {"$match": {"n": {"$gt": 1}}},
        {"$limit": 100},
    ]
    duplicate_ledger = [
        {"key": r["_id"], "count": r["n"], "ids": r["ids"]}
        async for r in db.journal_entries.aggregate(je_dup_pipeline)
    ]

    return {
        "counts": {
            "unmatched_bank_transactions": len(unmatched_bank),
            "unmatched_ledger_entries": len(unmatched_ledger),
            "duplicate_bank_imports": len(duplicate_bank),
            "amount_mismatches": len(amount_mismatches),
            "date_mismatches": len(date_mismatches),
            "duplicate_ledger_entries": len(duplicate_ledger),
        },
        "unmatched_bank_transactions_sample": unmatched_bank[:20],
        "unmatched_ledger_entries_sample": unmatched_ledger[:20],
        "duplicate_bank_imports": duplicate_bank[:20],
        "amount_mismatches": amount_mismatches[:20],
        "duplicate_ledger_entries": duplicate_ledger[:20],
    }
