"""Legacy staff-side password reset token repository (Phase 3.1b).

Rehomes `db.password_reset_tokens` (used by `portal_ops.py`) into PostgreSQL.
The client-side /auth/forgot-password flow uses `repositories.password_reset`;
this module is strictly for the admin/portal-ops staff reset path.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from postgres_models import LegacyPasswordResetToken


async def create(session: AsyncSession, *, token_id: str, user_id: str,
                 token_hash: str, expires_at: datetime) -> None:
    session.add(LegacyPasswordResetToken(
        id=token_id, user_id=user_id, token_hash=token_hash,
        expires_at=expires_at, created_at=datetime.now(timezone.utc),
    ))
    await session.flush()


async def get_by_hash(session: AsyncSession, token_hash: str) -> Optional[Dict[str, Any]]:
    row = (await session.execute(
        select(LegacyPasswordResetToken).where(LegacyPasswordResetToken.token_hash == token_hash)
    )).scalar_one_or_none()
    if not row:
        return None
    return {"id": row.id, "user_id": row.user_id, "token_hash": row.token_hash,
            "expires_at": row.expires_at, "used_at": row.used_at,
            "created_at": row.created_at}


async def consume(session: AsyncSession, token_hash: str) -> Optional[Dict[str, Any]]:
    """Atomically mark a valid token used. Returns the row on success, None otherwise."""
    now = datetime.now(timezone.utc)
    stmt = (
        update(LegacyPasswordResetToken)
        .where(LegacyPasswordResetToken.token_hash == token_hash,
               LegacyPasswordResetToken.used_at.is_(None),
               LegacyPasswordResetToken.expires_at > now)
        .values(used_at=now)
        .returning(LegacyPasswordResetToken.id, LegacyPasswordResetToken.user_id)
    )
    row = (await session.execute(stmt)).first()
    if not row:
        return None
    return {"id": row[0], "user_id": row[1]}
