"""Idempotent one-time script: copy staff/workforce users from MongoDB to
PostgreSQL for the auth-stack cutover.

Usage:
    python -m scripts.migrate_staff_users_to_postgres --dry-run
    python -m scripts.migrate_staff_users_to_postgres

What is copied:
    - id (opaque uuid string, preserved verbatim)
    - email (normalised lowercase)
    - password_hash
    - full_name, phone
    - role, is_active
    - mfa_enabled, mfa_secret (encrypted ciphertext preserved as-is)
    - mfa_bypass
    - must_change_password
    - session_version
    - auth_provider, picture_url
    - created_at, last_login_at, password_changed_at

Explicitly NOT copied:
    - Active user_sessions, refresh_tokens, password_reset_tokens
    - OAuth states / handoffs, login continuations
    (After cutover, users log in fresh; short-lived security material stays
    behind in Mongo and expires naturally.)

Only workforce roles are migrated by default. Pass --include-clients to
also copy patient portal users.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from sqlalchemy import select

BACKEND = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND / ".env")

import sys
sys.path.insert(0, str(BACKEND))

from postgres_db import AsyncSessionLocal  # noqa: E402
from postgres_models import User  # noqa: E402
from repositories import users as users_repo  # noqa: E402

logger = logging.getLogger("nms.migrate")

WORKFORCE_ROLES = {
    "admin", "practitioner", "staff", "front_desk", "frontdesk",
    "medical_assistant", "auditor",
}

_FIELDS = (
    "id", "email", "password_hash", "full_name", "phone", "role",
    "is_active", "mfa_enabled", "mfa_secret", "mfa_bypass",
    "must_change_password", "session_version", "auth_provider",
    "picture_url", "created_at", "last_login_at", "password_changed_at",
)


async def _upsert_one(pg_session, mongo_doc: dict) -> str:
    """Insert-or-update by email (unique). Returns "inserted"|"updated"|"skipped"."""
    email = (mongo_doc.get("email") or "").strip().lower()
    if not email or not mongo_doc.get("id"):
        return "skipped"

    existing = (await pg_session.execute(
        select(User).where(User.email == email)
    )).scalar_one_or_none()

    values = {
        "email": email,
        "password_hash": mongo_doc.get("password_hash"),
        "full_name": mongo_doc.get("full_name") or "",
        "phone": mongo_doc.get("phone"),
        "role": mongo_doc.get("role") or "client",
        "is_active": bool(mongo_doc.get("is_active", True)),
        "mfa_enabled": bool(mongo_doc.get("mfa_enabled", False)),
        "mfa_secret": mongo_doc.get("mfa_secret"),
        "mfa_bypass": bool(mongo_doc.get("mfa_bypass", False)),
        "must_change_password": bool(mongo_doc.get("must_change_password", False)),
        "session_version": int(mongo_doc.get("session_version") or 1),
        "auth_provider": mongo_doc.get("auth_provider"),
        "picture_url": mongo_doc.get("picture_url"),
        "created_at": mongo_doc.get("created_at"),
        "last_login_at": mongo_doc.get("last_login_at"),
        "password_changed_at": mongo_doc.get("password_changed_at"),
    }
    if existing:
        for k, v in values.items():
            setattr(existing, k, v)
        return "updated"
    await users_repo.create_user(pg_session, user_id=mongo_doc["id"], **{
        k: v for k, v in values.items() if k != "email"
    }, email=email)
    return "inserted"


async def main(dry_run: bool, include_clients: bool) -> None:
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    mongo = AsyncIOMotorClient(mongo_url)[db_name]

    query: dict = {} if include_clients else {"role": {"$in": list(WORKFORCE_ROLES)}}
    cursor = mongo.users.find(query, {f: 1 for f in _FIELDS} | {"_id": 0})

    counts = {"scanned": 0, "inserted": 0, "updated": 0, "skipped": 0}
    async with AsyncSessionLocal() as pg_session:
        async with pg_session.begin() if not dry_run else _no_tx(pg_session):
            async for doc in cursor:
                counts["scanned"] += 1
                if dry_run:
                    # Report only. Never touch PostgreSQL.
                    email = (doc.get("email") or "").strip().lower()
                    if not email or not doc.get("id"):
                        counts["skipped"] += 1
                    else:
                        counts["inserted"] += 1  # optimistic count
                    continue
                outcome = await _upsert_one(pg_session, doc)
                counts[outcome] += 1

    # Never log passwords, mfa_secret, or emails at INFO. Counts only.
    logger.info("migration complete counts=%s dry_run=%s", counts, dry_run)
    print(f"scanned={counts['scanned']} inserted={counts['inserted']} "
          f"updated={counts['updated']} skipped={counts['skipped']} "
          f"dry_run={dry_run}")


class _no_tx:
    def __init__(self, s): self.s = s
    async def __aenter__(self): return self.s
    async def __aexit__(self, *a): return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--include-clients", action="store_true")
    args = ap.parse_args()
    asyncio.run(main(dry_run=args.dry_run, include_clients=args.include_clients))
