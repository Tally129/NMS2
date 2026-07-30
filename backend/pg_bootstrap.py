"""One-shot migration/sync helpers used by application startup (Session 2b).

On boot, we ensure every existing MongoDB `users` document is represented in
PostgreSQL so the PG-backed auth stack can authenticate them. Existing PG
rows are left untouched — only missing accounts get copied over.

Idempotent: safe to call on every boot.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from postgres_db import AsyncSessionLocal
from repositories import users as users_repo

logger = logging.getLogger("nms.emr")


def _mongo_row_to_kwargs(u: Dict[str, Any]) -> Dict[str, Any]:
    return dict(
        user_id=u["id"],
        email=(u.get("email") or "").lower().strip(),
        password_hash=u.get("password_hash"),
        full_name=u.get("full_name") or "",
        phone=u.get("phone"),
        role=u.get("role") or "client",
        is_active=bool(u.get("is_active", True)),
        mfa_enabled=bool(u.get("mfa_enabled", False)),
        mfa_secret=u.get("mfa_secret"),
        mfa_bypass=bool(u.get("mfa_bypass", False)),
        must_change_password=bool(u.get("must_change_password", False)),
        session_version=int(u.get("session_version") or 1),
        auth_provider=u.get("auth_provider"),
        picture_url=u.get("picture_url"),
        created_at=u.get("created_at"),
        last_login_at=u.get("last_login_at"),
        password_changed_at=u.get("password_changed_at"),
    )


async def sync_mongo_users_to_pg(mongo_db) -> int:
    """Copy any MongoDB user rows not already present in PostgreSQL. Returns
    the count of freshly-inserted rows. Also refreshes password_hash /
    mfa_enabled / mfa_secret on existing PG rows so tests that mutate the
    Mongo row (e.g. `conftest.py` enrolling MFA) continue to work while the
    dual-store transition period lasts."""
    try:
        mongo_users = await mongo_db.users.find({}).to_list(10000)
    except Exception as e:
        logger.warning("startup PG sync: mongo users read failed: %s", e)
        return 0

    inserted = 0
    updated = 0
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            for u in mongo_users:
                email = (u.get("email") or "").strip().lower()
                if not u.get("id") or not email:
                    continue
                existing = await users_repo.get_by_id(pg, u["id"])
                if existing is None:
                    # Fall back to email match — legacy rows may collide by email.
                    if await users_repo.get_by_email(pg, email) is not None:
                        continue
                    await users_repo.create_user(pg, **_mongo_row_to_kwargs(u))
                    inserted += 1
                else:
                    # Refresh transient columns tests / admin tooling mutate on
                    # the Mongo side. Keep the PG password_changed_at intact.
                    fields = {}
                    if existing.get("password_hash") != u.get("password_hash"):
                        fields["password_hash"] = u.get("password_hash")
                    if bool(existing.get("mfa_enabled")) != bool(u.get("mfa_enabled")):
                        fields["mfa_enabled"] = bool(u.get("mfa_enabled", False))
                    if (existing.get("mfa_secret") or None) != (u.get("mfa_secret") or None):
                        fields["mfa_secret"] = u.get("mfa_secret")
                    if bool(existing.get("is_active", True)) != bool(u.get("is_active", True)):
                        fields["is_active"] = bool(u.get("is_active", True))
                    if fields:
                        await users_repo.update_fields(pg, u["id"], fields)
                        updated += 1
    if inserted or updated:
        logger.info(
            "PG auth sync: inserted=%d, refreshed=%d (of %d Mongo users)",
            inserted, updated, len(mongo_users),
        )
    return inserted
