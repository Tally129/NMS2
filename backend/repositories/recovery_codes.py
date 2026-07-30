"""Recovery code repository — Session 2c.

Codes are stored as sha256(uppercased_code) hex. Atomic single-use redemption
is enforced by UPDATE ... WHERE used_at IS NULL RETURNING id, which lets us
serialize concurrent claim attempts through PostgreSQL row locking.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from postgres_models import RecoveryCode


async def replace_all_for_user(session: AsyncSession, *, user_id: str,
                                items: List[dict]) -> None:
    """Wipe any existing codes for the user and insert the new batch.
    Called on MFA enrollment completion + explicit regeneration."""
    await session.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user_id))
    if not items:
        return
    await session.execute(insert(RecoveryCode), items)


async def unused_count(session: AsyncSession, user_id: str) -> int:
    stmt = select(RecoveryCode.id).where(
        RecoveryCode.user_id == user_id, RecoveryCode.used_at.is_(None),
    )
    return len((await session.execute(stmt)).all())


async def claim_by_hash(session: AsyncSession, *, user_id: str,
                         code_hash: str) -> Optional[str]:
    """Atomically consume a matching unused code for the given user. Returns
    the code row id on success, None if no such unused code exists. Uses
    ``UPDATE ... RETURNING`` for single-round-trip atomicity so two
    simultaneous consumers cannot both succeed."""
    stmt = (
        update(RecoveryCode)
        .where(
            RecoveryCode.user_id == user_id,
            RecoveryCode.code_hash == code_hash,
            RecoveryCode.used_at.is_(None),
        )
        .values(used_at=datetime.now(timezone.utc))
        .returning(RecoveryCode.id)
    )
    result = await session.execute(stmt)
    row = result.first()
    return row[0] if row else None
