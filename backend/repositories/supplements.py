"""Supplement sheets + client-supplement assignments repository (Phase 3.1b)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from postgres_models import ClientSupplementAssignment, SupplementSheet


def _sheet(s: SupplementSheet) -> Dict[str, Any]:
    return {k: getattr(s, k) for k in (
        "id", "title", "summary", "items", "created_by", "created_by_name",
        "active", "legacy_mongo_id", "created_at", "updated_at",
    )}


def _assignment(a: ClientSupplementAssignment) -> Dict[str, Any]:
    return {k: getattr(a, k) for k in (
        "id", "client_id", "sheet_id", "sheet_title", "sheet_summary",
        "items_snapshot", "note_ids", "assigned_by_id", "assigned_by_name",
        "active", "source", "assigned_at", "last_referenced_at",
        "removed_at", "removed_by_id", "legacy_mongo_id", "created_at",
    )}


# --------------------------------------------------------------- sheets #
async def list_sheets(session: AsyncSession, *, active_only: bool = True,
                       limit: int = 200) -> List[Dict[str, Any]]:
    stmt = select(SupplementSheet)
    if active_only:
        stmt = stmt.where(SupplementSheet.active.is_(True))
    stmt = stmt.order_by(SupplementSheet.created_at.desc()).limit(limit)
    return [_sheet(s) for s in (await session.execute(stmt)).scalars().all()]


async def get_sheet(session: AsyncSession, sheet_id: str) -> Optional[Dict[str, Any]]:
    row = (await session.execute(
        select(SupplementSheet).where(SupplementSheet.id == sheet_id)
    )).scalar_one_or_none()
    return _sheet(row) if row else None


async def create_sheet(session: AsyncSession, **fields) -> Dict[str, Any]:
    fields.setdefault("created_at", datetime.now(timezone.utc))
    s = SupplementSheet(**{k: v for k, v in fields.items() if hasattr(SupplementSheet, k)})
    session.add(s)
    await session.flush()
    return _sheet(s)


async def update_sheet(session: AsyncSession, sheet_id: str, fields: Dict[str, Any]) -> int:
    if not fields:
        return 0
    fields["updated_at"] = datetime.now(timezone.utc)
    r = await session.execute(update(SupplementSheet).where(SupplementSheet.id == sheet_id).values(**fields))
    return r.rowcount or 0


# ------------------------------------------------------- assignments #
async def list_active_for_client(session: AsyncSession, client_id: str) -> List[Dict[str, Any]]:
    stmt = (select(ClientSupplementAssignment)
            .where(ClientSupplementAssignment.client_id == client_id,
                   ClientSupplementAssignment.active.is_(True))
            .order_by(ClientSupplementAssignment.assigned_at.desc().nullslast()))
    return [_assignment(a) for a in (await session.execute(stmt)).scalars().all()]


async def create_assignment(session: AsyncSession, **fields) -> Dict[str, Any]:
    fields.setdefault("created_at", datetime.now(timezone.utc))
    a = ClientSupplementAssignment(**{
        k: v for k, v in fields.items() if hasattr(ClientSupplementAssignment, k)
    })
    session.add(a)
    await session.flush()
    return _assignment(a)


async def deactivate(session: AsyncSession, assignment_id: str, *, by_id: str) -> int:
    r = await session.execute(
        update(ClientSupplementAssignment)
        .where(ClientSupplementAssignment.id == assignment_id,
               ClientSupplementAssignment.active.is_(True))
        .values(active=False,
                removed_at=datetime.now(timezone.utc),
                removed_by_id=by_id)
    )
    return r.rowcount or 0
