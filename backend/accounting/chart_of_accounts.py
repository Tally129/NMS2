"""
Chart of Accounts — seed set + CRUD helpers. System accounts are locked.

The COA is medical-practice tailored; extend via admin UI.
"""
from __future__ import annotations

from datetime import datetime, timezone

from deps import db
from models import new_id


ACCOUNT_TYPES = ("asset", "liability", "equity", "revenue", "cogs", "expense")
NORMAL_BALANCE = {
    "asset": "debit", "expense": "debit", "cogs": "debit",
    "liability": "credit", "equity": "credit", "revenue": "credit",
}


# Ordered seed. `code` is the human-friendly key referenced by posting rules.
SEED = [
    # ---- Assets ----
    ("1000", "Cash on hand",              "asset",     "current_asset", True),
    ("1050", "Cash drawer clearing",      "asset",     "current_asset", True),
    ("1100", "Operating checking",        "asset",     "current_asset", True),
    ("1200", "Stripe clearing",           "asset",     "current_asset", True),
    ("1300", "Accounts receivable",       "asset",     "current_asset", True),
    ("1400", "Inventory on hand",         "asset",     "current_asset", True),
    ("1500", "Prepaid expenses",          "asset",     "current_asset", False),
    ("1600", "Fixed assets",              "asset",     "long_term",     False),
    # ---- Liabilities ----
    ("2000", "Accounts payable",          "liability", "current",       True),
    ("2100", "Deferred membership revenue","liability","current",       True),
    ("2200", "Sales tax payable",         "liability", "current",       True),
    ("2300", "Tips payable",              "liability", "current",       True),
    ("2400", "Payroll wages payable",     "liability", "current",       True),
    ("2410", "Payroll taxes payable",     "liability", "current",       True),
    ("2500", "Credit card payable",       "liability", "current",       False),
    # ---- Equity ----
    ("3000", "Owner's equity",            "equity",    "capital",       True),
    ("3100", "Retained earnings",         "equity",    "capital",       True),
    # ---- Revenue ----
    ("4100", "Service revenue",           "revenue",   "operating",     True),
    ("4200", "Product revenue",           "revenue",   "operating",     True),
    ("4300", "Membership revenue",        "revenue",   "operating",     True),
    ("4400", "Other revenue",             "revenue",   "operating",     False),
    ("4900", "Sales discounts",           "revenue",   "contra",        True),
    # ---- COGS ----
    ("5100", "Product cost of goods sold","cogs",      "operating",     True),
    ("5200", "Merchant processing fees",  "cogs",      "operating",     True),
    # ---- Expenses ----
    ("6000", "Rent",                      "expense",   "operating",     False),
    ("6100", "Utilities",                 "expense",   "operating",     False),
    ("6200", "Payroll expense",           "expense",   "operating",     True),
    ("6210", "Payroll tax expense",       "expense",   "operating",     True),
    ("6300", "Marketing",                 "expense",   "operating",     False),
    ("6400", "Supplies",                  "expense",   "operating",     False),
    ("6500", "Software subscriptions",    "expense",   "operating",     False),
    ("6600", "Contractor payments",       "expense",   "operating",     True),
    ("6700", "Insurance",                 "expense",   "operating",     False),
    ("6900", "Other operating expense",   "expense",   "operating",     True),
]


async def seed_if_empty() -> int:
    """Idempotent seed of the chart of accounts."""
    existing = await db.chart_of_accounts.count_documents({})
    if existing:
        return 0
    now = datetime.now(timezone.utc)
    docs = []
    for code, name, type_, subtype, locked in SEED:
        docs.append({
            "id": new_id(), "code": code, "name": name,
            "type": type_, "subtype": subtype,
            "normal_balance": NORMAL_BALANCE[type_],
            "currency": "USD",
            "active": True,
            "system_locked": locked,
            "created_at": now, "updated_at": now,
        })
    await db.chart_of_accounts.insert_many(docs)
    try:
        await db.chart_of_accounts.create_index("code", unique=True)
    except Exception:
        pass
    return len(docs)


async def get_by_code(code: str) -> dict | None:
    return await db.chart_of_accounts.find_one({"code": code})
