"""Password-reset attempts (rate limiting) + reset tokens."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from postgres_models import PasswordResetAttempt, PasswordResetToken


async def record_attempt(session: AsyncSession, *, attempt_id: str,
                         email_hash: Optional[str], ip: Optional[str]) -> None:
    session.add(PasswordResetAttempt(
        id=attempt_id, email_hash=email_hash, ip=ip,
        ts=datetime.now(timezone.utc),
    ))
    await session.flush()


async def count_recent_by_email(session: AsyncSession, email_hash: str,
                                since: datetime) -> int:
    stmt = select(func.count(PasswordResetAttempt.id)).where(
        and_(PasswordResetAttempt.email_hash == email_hash,
             PasswordResetAttempt.ts >= since)
    )
    return int((await session.execute(stmt)).scalar_one())


async def count_recent_by_ip(session: AsyncSession, ip: str, since: datetime) -> int:
    stmt = select(func.count(PasswordResetAttempt.id)).where(
        and_(PasswordResetAttempt.ip == ip, PasswordResetAttempt.ts >= since)
    )
    return int((await session.execute(stmt)).scalar_one())


async def create_token(session: AsyncSession, *, token_id: str, token_hash: str,
                       user_id: str, email_hash: Optional[str],
                       expires_at: datetime, ip: Optional[str]) -> None:
    session.add(PasswordResetToken(
        id=token_id, token_hash=token_hash, user_id=user_id,
        email_hash=email_hash, expires_at=expires_at,
        created_at=datetime.now(timezone.utc), ip=ip,
    ))
    await session.flush()


async def consume_token(session: AsyncSession, token_hash: str,
                        ip: Optional[str]) -> Optional[Dict[str, Any]]:
    """Atomically consume a single-use reset token."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(PasswordResetToken)
        .where(and_(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.consumed_at.is_(None),
            PasswordResetToken.expires_at > now,
        ))
        .with_for_update(skip_locked=True)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    row.consumed_at = now
    row.consumed_ip = ip
    await session.flush()
    return {"id": row.id, "user_id": row.user_id, "email_hash": row.email_hash}
