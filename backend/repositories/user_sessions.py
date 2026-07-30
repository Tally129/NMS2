"""Session repository. Auth flows own the transactions; this layer just
turns SQLAlchemy rows into dicts and centralises the queries the auth code
relies on."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from postgres_models import UserSession


def session_to_dict(s: UserSession) -> Dict[str, Any]:
    return {
        "id": s.id,
        "user_id": s.user_id,
        "created_at": s.created_at,
        "last_used_at": s.last_used_at,
        "expires_at": s.expires_at,
        "idle_timeout_minutes": s.idle_timeout_minutes,
        "absolute_expires_at": s.absolute_expires_at,
        "revoked_at": s.revoked_at,
        "revoke_reason": s.revoke_reason,
        "session_version": s.session_version,
        "ip_first": s.ip_first,
        "ip_last": s.ip_last,
        "user_agent": s.user_agent,
        "mfa_satisfied_at": s.mfa_satisfied_at,
        "family_id": s.family_id,
    }


async def get(session: AsyncSession, sid: str) -> Optional[Dict[str, Any]]:
    row = await session.get(UserSession, sid)
    return session_to_dict(row) if row else None


async def create(session: AsyncSession, **fields) -> Dict[str, Any]:
    row = UserSession(**fields)
    session.add(row)
    await session.flush()
    return session_to_dict(row)


async def revoke_by_id(session: AsyncSession, sid: str, reason: str) -> int:
    result = await session.execute(
        update(UserSession)
        .where(and_(UserSession.id == sid, UserSession.revoked_at.is_(None)))
        .values(revoked_at=datetime.now(timezone.utc), revoke_reason=reason),
    )
    return result.rowcount or 0


async def revoke_all_for_user(session: AsyncSession, user_id: str, reason: str) -> int:
    result = await session.execute(
        update(UserSession)
        .where(and_(UserSession.user_id == user_id, UserSession.revoked_at.is_(None)))
        .values(revoked_at=datetime.now(timezone.utc), revoke_reason=reason),
    )
    return result.rowcount or 0


async def count_active(session: AsyncSession, user_id: str) -> int:
    stmt = select(func.count(UserSession.id)).where(
        and_(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
            UserSession.absolute_expires_at > datetime.now(timezone.utc),
        )
    )
    return int((await session.execute(stmt)).scalar_one())


async def oldest_active(session: AsyncSession, user_id: str) -> Optional[Dict[str, Any]]:
    stmt = (
        select(UserSession)
        .where(and_(UserSession.user_id == user_id, UserSession.revoked_at.is_(None)))
        .order_by(UserSession.created_at.asc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    return session_to_dict(row) if row else None


async def list_active_for_user(session: AsyncSession, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    stmt = (
        select(UserSession)
        .where(and_(UserSession.user_id == user_id, UserSession.revoked_at.is_(None)))
        .order_by(UserSession.last_used_at.desc().nullslast())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [session_to_dict(r) for r in rows]


async def touch(session: AsyncSession, sid: str, ip: Optional[str]) -> None:
    """Throttled touch is done at the sessions.py level. This just writes."""
    await session.execute(
        update(UserSession).where(UserSession.id == sid)
        .values(last_used_at=datetime.now(timezone.utc), ip_last=ip),
    )


async def set_mfa_satisfied(session: AsyncSession, sid: str) -> None:
    await session.execute(
        update(UserSession).where(UserSession.id == sid)
        .values(mfa_satisfied_at=datetime.now(timezone.utc)),
    )
