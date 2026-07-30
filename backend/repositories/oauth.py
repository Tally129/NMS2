"""OAuth state + handoff repository.

Sensitive: the caller MUST NEVER log the raw access_token or
refresh_cookie_value stored in a handoff row. `consume_handoff` returns them
exactly once and deletes the row inside the same transaction.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from postgres_models import OAuthHandoff, OAuthState


async def create_state(session: AsyncSession, *, state: str,
                       expires_at: datetime) -> None:
    session.add(OAuthState(state=state, expires_at=expires_at,
                           created_at=datetime.now(timezone.utc)))
    await session.flush()


async def consume_state(session: AsyncSession, state: str) -> bool:
    """Atomically consume an OAuth state. Returns True on success."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(OAuthState)
        .where(and_(OAuthState.state == state,
                    OAuthState.consumed.is_(False),
                    OAuthState.expires_at > now))
        .with_for_update(skip_locked=True)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return False
    row.consumed = True
    row.consumed_at = now
    await session.flush()
    return True


async def create_handoff(session: AsyncSession, *, handoff_id: str, user_id: str,
                         access_token: str, refresh_cookie_value: str) -> None:
    session.add(OAuthHandoff(
        handoff_id=handoff_id, user_id=user_id,
        access_token=access_token, refresh_cookie_value=refresh_cookie_value,
        created_at=datetime.now(timezone.utc),
    ))
    await session.flush()


async def consume_handoff(session: AsyncSession, handoff_id: str,
                          max_age_seconds: int = 120) -> Optional[Dict[str, Any]]:
    """One-shot: return the payload and DELETE the row inside the same tx.

    A handoff older than `max_age_seconds` is treated as expired — deleted
    without being returned so an attacker who scraped one from a slow
    redirect cannot replay it.
    """
    stmt = (
        select(OAuthHandoff)
        .where(and_(OAuthHandoff.handoff_id == handoff_id,
                    OAuthHandoff.consumed.is_(False)))
        .with_for_update(skip_locked=True)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    now = datetime.now(timezone.utc)
    age = (now - row.created_at.replace(tzinfo=timezone.utc)
           if row.created_at.tzinfo is None else now - row.created_at).total_seconds()
    payload = None
    if age <= max_age_seconds:
        payload = {
            "user_id": row.user_id,
            "access_token": row.access_token,
            "refresh_cookie_value": row.refresh_cookie_value,
        }
    # Delete the row unconditionally so it can never be replayed.
    await session.execute(delete(OAuthHandoff).where(
        OAuthHandoff.handoff_id == handoff_id
    ))
    await session.flush()
    return payload
