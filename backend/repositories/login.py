"""Login history + login-continuation ticket repository."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from postgres_models import LoginContinuation, LoginHistory


async def record_attempt(session: AsyncSession, *, attempt_id: str,
                         user_id: Optional[str], email_hash: Optional[str],
                         success: bool, ip: Optional[str],
                         user_agent: Optional[str]) -> None:
    session.add(LoginHistory(
        id=attempt_id, user_id=user_id, email_hash=email_hash,
        success=success, ip=ip, user_agent=user_agent,
        ts=datetime.now(timezone.utc),
    ))
    await session.flush()


async def create_continuation(session: AsyncSession, *, ticket_id: str,
                              user_id: str, expires_at: datetime,
                              mfa_satisfied_now: bool = False) -> None:
    session.add(LoginContinuation(
        ticket_id=ticket_id, user_id=user_id,
        created_at=datetime.now(timezone.utc),
        expires_at=expires_at, mfa_satisfied_now=mfa_satisfied_now,
    ))
    await session.flush()


async def consume_continuation(session: AsyncSession, ticket_id: str) -> Optional[Dict[str, Any]]:
    """Atomically consume a continuation ticket. Returns the row or None."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(LoginContinuation)
        .where(and_(
            LoginContinuation.ticket_id == ticket_id,
            LoginContinuation.consumed_at.is_(None),
            LoginContinuation.expires_at > now,
        ))
        .with_for_update(skip_locked=True)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    row.consumed_at = now
    await session.flush()
    return {
        "ticket_id": row.ticket_id, "user_id": row.user_id,
        "mfa_satisfied_now": row.mfa_satisfied_now,
        "created_at": row.created_at, "expires_at": row.expires_at,
    }
