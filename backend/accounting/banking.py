"""
Bank accounts registry.

A bank account is a user-facing wrapper around ONE Chart-of-Accounts code.
The COA is the source of truth for the running balance. This registry stores
display metadata (name, institution, last-4) plus reconciliation state.

We never store banking credentials; imports happen via CSV or OFX file only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from deps import db
from models import new_id


BANK_ACCOUNT_TYPES = (
    "checking", "savings", "payroll", "petty_cash",
    "credit_card", "merchant_clearing",
)

# Seeded on first startup — codes must exist in chart_of_accounts.
SEED = [
    ("Operating Checking",   "checking",          "1100", True),
    ("Petty Cash",           "petty_cash",        "1000", True),
    ("Cash Drawer",          "petty_cash",        "1050", True),
    ("Stripe Merchant Clearing", "merchant_clearing", "1200", True),
    ("Credit Card",          "credit_card",       "2500", True),
]


async def ensure_indexes() -> None:
    try:
        await db.bank_accounts.create_index("gl_account_code")
        await db.bank_accounts.create_index("active")
        await db.bank_transactions.create_index("bank_account_id")
        await db.bank_transactions.create_index([("posted_at", -1)])
        await db.bank_transactions.create_index("status")
        await db.bank_transactions.create_index("import_batch_id")
        await db.reconciliations.create_index("bank_account_id")
        await db.reconciliations.create_index([("finalized_at", -1)])
    except Exception:
        pass


async def seed_if_empty() -> int:
    if await db.bank_accounts.count_documents({}) > 0:
        return 0
    now = datetime.now(timezone.utc)
    docs = []
    for name, kind, code, active in SEED:
        # verify chart-of-accounts code exists
        if not await db.chart_of_accounts.find_one({"code": code}):
            continue
        docs.append({
            "id": new_id(), "name": name, "kind": kind,
            "gl_account_code": code, "institution": None, "last_four": None,
            "active": active, "system_seeded": True,
            "last_reconciled_at": None, "last_reconciled_ending_balance_cents": None,
            "created_at": now, "updated_at": now,
        })
    if docs:
        await db.bank_accounts.insert_many(docs)
    return len(docs)


async def list_accounts(include_inactive: bool = False) -> list[dict]:
    q = {} if include_inactive else {"active": True}
    return await db.bank_accounts.find(q).sort("name", 1).to_list(200)


async def create(
    *, name: str, kind: str, gl_account_code: str,
    institution: Optional[str], last_four: Optional[str],
) -> dict:
    if kind not in BANK_ACCOUNT_TYPES:
        raise ValueError("invalid bank account kind")
    if not await db.chart_of_accounts.find_one({"code": gl_account_code}):
        raise ValueError("gl_account_code not in chart of accounts")
    now = datetime.now(timezone.utc)
    doc = {
        "id": new_id(), "name": name, "kind": kind,
        "gl_account_code": gl_account_code,
        "institution": institution, "last_four": last_four,
        "active": True, "system_seeded": False,
        "last_reconciled_at": None, "last_reconciled_ending_balance_cents": None,
        "created_at": now, "updated_at": now,
    }
    await db.bank_accounts.insert_one(doc)
    return doc


async def has_transactions(bank_account_id: str) -> bool:
    n = await db.bank_transactions.count_documents({"bank_account_id": bank_account_id})
    return n > 0


async def update(bank_account_id: str, changes: dict) -> Optional[dict]:
    allowed = {"name", "institution", "last_four", "active"}
    updates = {k: v for k, v in (changes or {}).items() if k in allowed}
    if not updates:
        return await db.bank_accounts.find_one({"id": bank_account_id})
    updates["updated_at"] = datetime.now(timezone.utc)
    await db.bank_accounts.update_one({"id": bank_account_id}, {"$set": updates})
    return await db.bank_accounts.find_one({"id": bank_account_id})


async def delete(bank_account_id: str) -> None:
    doc = await db.bank_accounts.find_one({"id": bank_account_id})
    if not doc:
        raise ValueError("not found")
    if doc.get("system_seeded"):
        raise ValueError("system-seeded account cannot be deleted")
    if await has_transactions(bank_account_id):
        raise ValueError("account has bank transactions; deactivate instead")
    await db.bank_accounts.delete_one({"id": bank_account_id})
