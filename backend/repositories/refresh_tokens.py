"""Refresh-token repository.

Rotation invariants (mirroring the pre-migration Motor code):
  * `claim_for_rotation()` uses `SELECT ... FOR UPDATE` to atomically claim
    a token that is unused, unrevoked, and unexpired. Concurrent callers
    on the same row will serialise, so at most one succeeds.
  * The service layer (`sessions.rotate_refresh`) is responsible for
    creating the successor + updating `replaced_by_id` in the same
    transaction as the claim.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from postgres_models import RefreshToken


def token_to_dict(t: RefreshToken) -> Dict[str, Any]:
    return {
        "id": t.id,
        "token_hash": t.token_hash,
        "session_id": t.session_id,
        "user_id": t.user_id,
        "family_id": t.family_id,
        "generation": t.generation,
        "parent_token_id": t.parent_token_id,
        "replaced_by_id": t.replaced_by_id,
        "created_at": t.created_at,
        "last_used_at": t.last_used_at,
        "expires_at": t.expires_at,
        "used_at": t.used_at,
        "revoked_at": t.revoked_at,
        "revoke_reason": t.revoke_reason,
        "ip_created": t.ip_created,
        "ip_last_used": t.ip_last_used,
        "user_agent_created": t.user_agent_created,
    }


async def insert(session: AsyncSession, **fields) -> Dict[str, Any]:
    row = RefreshToken(**fields)
    session.add(row)
    await session.flush()
    return token_to_dict(row)


async def get_by_hash(session: AsyncSession, token_hash: str) -> Optional[Dict[str, Any]]:
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    row = (await session.execute(stmt)).scalar_one_or_none()
    return token_to_dict(row) if row else None


async def claim_for_rotation(session: AsyncSession, token_hash: str,
                             now_ts: datetime, ip: Optional[str]) -> Optional[Dict[str, Any]]:
    """Atomically claim a refresh token and mark it used.

    Uses `SELECT ... FOR UPDATE SKIP LOCKED` so a concurrent second caller
    against the same row sees no row (which is the correct "already used"
    outcome — the caller then classifies grace vs. reuse from the row's
    `used_at` timestamp).
    """
    stmt = (
        select(RefreshToken)
        .where(
            and_(
                RefreshToken.token_hash == token_hash,
                RefreshToken.used_at.is_(None),
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > now_ts,
            )
        )
        .with_for_update(skip_locked=True)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    row.used_at = now_ts
    row.last_used_at = now_ts
    row.ip_last_used = ip
    await session.flush()
    return token_to_dict(row)


async def set_replaced_by(session: AsyncSession, token_id: str, successor_id: str) -> None:
    await session.execute(
        update(RefreshToken).where(RefreshToken.id == token_id)
        .values(replaced_by_id=successor_id),
    )


async def revoke_family(session: AsyncSession, family_id: str, reason: str) -> int:
    result = await session.execute(
        update(RefreshToken)
        .where(and_(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None)))
        .values(revoked_at=datetime.now(timezone.utc), revoke_reason=reason),
    )
    return result.rowcount or 0


async def revoke_all_for_user(session: AsyncSession, user_id: str, reason: str) -> int:
    result = await session.execute(
        update(RefreshToken)
        .where(and_(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)))
        .values(revoked_at=datetime.now(timezone.utc), revoke_reason=reason),
    )
    return result.rowcount or 0


async def revoke_by_session(session: AsyncSession, session_id: str, reason: str) -> int:
    result = await session.execute(
        update(RefreshToken)
        .where(and_(RefreshToken.session_id == session_id, RefreshToken.revoked_at.is_(None)))
        .values(revoked_at=datetime.now(timezone.utc), revoke_reason=reason),
    )
    return result.rowcount or 0
