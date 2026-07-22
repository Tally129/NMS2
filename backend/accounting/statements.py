"""
Statement import — CSV + basic OFX. Creates unreconciled bank_transactions.

CSV format detection is heuristic; we accept common exports:
    date, description, amount [, reference, balance]
    posted_date, memo, debit, credit [, running_balance]
Column names are matched case-insensitively; extra columns are ignored.

OFX support is basic — uses `ofxparse` if installed, otherwise raises a
clean error asking the user to upload CSV.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from typing import IO, Optional

from deps import db
from models import new_id


# ---------------------------------------------------------------- helpers #
DATE_FORMATS = (
    "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y",
    "%Y/%m/%d", "%m-%d-%Y",
)


def _parse_date(v) -> datetime:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    s = str(v or "").strip().split("T")[0].split(" ")[0]
    for f in DATE_FORMATS:
        try:
            d = datetime.strptime(s, f)
            return d.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    # ISO fallback
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        raise ValueError(f"unrecognised date: {v}")


def _to_cents(v) -> int:
    if v is None or v == "":
        return 0
    s = str(v).replace("$", "").replace(",", "").strip()
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    return int(round(float(s) * 100))


def _pick(headers: list[str], row: dict, *keys) -> Optional[str]:
    for k in keys:
        for h in headers:
            if h.lower().replace(" ", "").replace("_", "") == k:
                return row.get(h)
    return None


# ---------------------------------------------------------------- CSV #
def parse_csv(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict] = []
    hdrs = reader.fieldnames or []
    for line in reader:
        raw_date = (
            _pick(hdrs, line, "date", "posteddate", "postingdate",
                  "transactiondate", "trandate")
        )
        if not raw_date:
            continue
        # amount can be a single 'amount' column OR debit/credit pair
        amt = _pick(hdrs, line, "amount", "value")
        debit = _pick(hdrs, line, "debit", "debits", "withdrawal")
        credit = _pick(hdrs, line, "credit", "credits", "deposit")
        if amt in (None, "") and (debit or credit):
            amt_cents = _to_cents(credit) - _to_cents(debit)
        else:
            amt_cents = _to_cents(amt)
        if amt_cents == 0 and not (debit or credit):
            continue
        desc = (_pick(hdrs, line, "description", "memo", "payee", "narration")
                or "").strip()
        ref = (_pick(hdrs, line, "reference", "referenceno", "checknumber",
                     "check", "chknumber", "fitid") or "").strip() or None
        bal = _pick(hdrs, line, "balance", "runningbalance", "endingbalance")
        rows.append({
            "posted_at": _parse_date(raw_date),
            "description": desc[:400],
            "amount_cents": amt_cents,
            "reference": ref[:200] if ref else None,
            "running_balance_cents": _to_cents(bal) if bal not in (None, "") else None,
        })
    return rows


# ---------------------------------------------------------------- OFX #
def parse_ofx(text: str) -> list[dict]:
    try:
        from ofxparse import OfxParser  # type: ignore
    except Exception as e:  # pragma: no cover
        raise ValueError("ofx_not_supported: install ofxparse or upload CSV") from e
    buf = io.BytesIO(text.encode("utf-8") if isinstance(text, str) else text)
    try:
        ofx = OfxParser.parse(buf)
    except Exception as e:
        raise ValueError(f"ofx_parse_failed: {e}") from e
    rows: list[dict] = []
    for acct in getattr(ofx, "accounts", []) or []:
        stmt = getattr(acct, "statement", None)
        if not stmt:
            continue
        for txn in getattr(stmt, "transactions", []) or []:
            when = getattr(txn, "date", None)
            if not when:
                continue
            amt = getattr(txn, "amount", 0)
            rows.append({
                "posted_at": when if getattr(when, "tzinfo", None)
                else when.replace(tzinfo=timezone.utc),
                "description": (getattr(txn, "memo", None) or
                                 getattr(txn, "payee", None) or "")[:400],
                "amount_cents": int(round(float(amt) * 100)),
                "reference": (getattr(txn, "id", None) or
                              getattr(txn, "checknum", None) or None),
                "running_balance_cents": None,
            })
    return rows


# ---------------------------------------------------------------- runner #
async def import_statement(
    *, bank_account_id: str, filename: str, content: bytes,
    actor: dict,
) -> dict:
    """Detect format, parse, dedupe within the same account by (date, amount, ref),
    and persist unreconciled bank_transactions."""
    text = content.decode("utf-8", errors="replace")
    lower = (filename or "").lower()
    if lower.endswith(".ofx") or lower.endswith(".qfx"):
        try:
            parsed = parse_ofx(text)
        except ValueError:
            # graceful fallback: attempt CSV as a last resort
            parsed = parse_csv(text) if "," in text and "\n" in text else []
            if not parsed:
                raise
    else:
        parsed = parse_csv(text)
    if not parsed:
        raise ValueError("no_rows_parsed")
    now = datetime.now(timezone.utc)
    batch_id = new_id()
    batch = {
        "id": batch_id,
        "bank_account_id": bank_account_id,
        "filename": filename[:200],
        "row_count_total": len(parsed),
        "row_count_new": 0,
        "row_count_duplicate": 0,
        "imported_at": now,
        "imported_by": actor.get("id"),
        "imported_by_name": actor.get("full_name") or actor.get("email"),
    }
    docs_new = []
    dup_count = 0
    for row in parsed:
        # Same (bank_account_id, posted_at, amount, reference) → duplicate.
        existing = await db.bank_transactions.find_one({
            "bank_account_id": bank_account_id,
            "posted_at": row["posted_at"],
            "amount_cents": row["amount_cents"],
            "reference": row.get("reference"),
        })
        if existing:
            dup_count += 1
            continue
        docs_new.append({
            "id": new_id(),
            "bank_account_id": bank_account_id,
            "import_batch_id": batch_id,
            "posted_at": row["posted_at"],
            "description": row.get("description") or "",
            "amount_cents": int(row.get("amount_cents") or 0),
            "reference": row.get("reference"),
            "running_balance_cents": row.get("running_balance_cents"),
            "status": "unmatched",   # unmatched | matched | reconciled | split
            "matched_journal_entry_ids": [],
            "reconciliation_id": None,
            "reconciled_at": None,
            "created_at": now,
        })
    if docs_new:
        await db.bank_transactions.insert_many(docs_new)
    batch["row_count_new"] = len(docs_new)
    batch["row_count_duplicate"] = dup_count
    await db.bank_import_batches.insert_one(batch)
    return batch
