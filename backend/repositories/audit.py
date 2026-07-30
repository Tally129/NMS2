"""Audit + security-event repository.

The chain hash is computed at the service layer (`audit.log_audit`) inside a
transaction. This module only exposes the primitive operations. Deterministic
ordering is enforced by the `AuditLog.seq` autoincrementing column.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from postgres_models import AuditLog, SecurityEvent


# 63-bit portable advisory-lock key. Any constant works; must be shared by
# every worker that inserts into `auth_audit_logs` for chain correctness.
CHAIN_LOCK_KEY = 738493741


def audit_to_dict(row: AuditLog) -> Dict[str, Any]:
    return {
        "seq": row.seq,
        "id": row.id,
        "ts": row.ts,
        "user_id": row.user_id,
        "user_email": row.user_email,
        "action": row.action,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "severity": row.severity,
        "outcome": row.outcome,
        "ip": row.ip,
        "user_agent": row.user_agent,
        "metadata": row.audit_metadata,
        "prev_hash": row.prev_hash,
        "hash": row.hash,
    }


async def acquire_chain_lock(session: AsyncSession) -> None:
    """Transaction-scoped advisory lock so multiple workers can't race the
    prev_hash → hash → insert sequence. Auto-released at COMMIT/ROLLBACK."""
    await session.execute(text("SELECT pg_advisory_xact_lock(:k)")
                          .bindparams(k=CHAIN_LOCK_KEY))


async def prev_hash(session: AsyncSession) -> str:
    stmt = select(AuditLog.hash).order_by(AuditLog.seq.desc()).limit(1)
    latest = (await session.execute(stmt)).scalar_one_or_none()
    return latest or "GENESIS"


async def insert(session: AsyncSession, row: Dict[str, Any]) -> None:
    """`row` must include prev_hash + hash, computed by the caller."""
    orm_row = AuditLog(
        id=row["id"], ts=row["ts"], user_id=row.get("user_id"),
        user_email=row.get("user_email"), action=row["action"],
        resource_type=row.get("resource_type"), resource_id=row.get("resource_id"),
        severity=row.get("severity", "info"), outcome=row.get("outcome", "success"),
        ip=row.get("ip"), user_agent=row.get("user_agent"),
        audit_metadata=row.get("metadata") or {},
        prev_hash=row["prev_hash"], hash=row["hash"],
    )
    session.add(orm_row)
    await session.flush()


async def insert_security_event(session: AsyncSession, event: Dict[str, Any]) -> None:
    orm_row = SecurityEvent(
        id=event["id"], ts=event["ts"], audit_id=event["audit_id"],
        action=event["action"], severity=event["severity"], outcome=event["outcome"],
        user_id=event.get("user_id"), resource_type=event.get("resource_type"),
        resource_id=event.get("resource_id"), handled=False,
    )
    session.add(orm_row)
    await session.flush()


async def list_ordered(session: AsyncSession, limit: int = 5000) -> List[Dict[str, Any]]:
    stmt = select(AuditLog).order_by(AuditLog.seq.asc()).limit(limit)
    return [audit_to_dict(r) for r in (await session.execute(stmt)).scalars().all()]
