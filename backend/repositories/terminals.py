from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from postgres_models.terminals import (
    PaymentTerminal,
    TerminalPaymentAttempt,
)


_TERMINAL_COLS = (
    "id",
    "provider",
    "provider_device_id",
    "display_name",
    "location_id",
    "connection_type",
    "enabled",
    "is_default",
    "configured",
    "status",
    "capabilities",
    "last_seen_at",
    "created_by",
    "updated_by",
    "created_at",
    "updated_at",
    "archived_at",
)


def _terminal(row) -> Optional[Dict[str, Any]]:
    if row is None:
        return None

    result = {
        k: getattr(row, k)
        for k in _TERMINAL_COLS
    }

    result["metadata"] = dict(
        row.metadata_json or {}
    )

    return result


_ATTEMPT_COLS = (
    "id",
    "transaction_id",
    "terminal_id",
    "provider",
    "provider_request_id",
    "provider_transaction_id",
    "amount_cents",
    "currency",
    "status",
    "card_brand",
    "last4",
    "failure_code",
    "failure_message",
    "safe_response",
    "created_by",
    "created_at",
    "updated_at",
    "completed_at",
)


def _attempt(row) -> Optional[Dict[str, Any]]:
    if row is None:
        return None

    return {
        k: getattr(row, k)
        for k in _ATTEMPT_COLS
    }


async def list_terminals(
    session: AsyncSession,
    *,
    location_id: Optional[str] = None,
    provider: Optional[str] = None,
    enabled_only: bool = False,
) -> List[Dict[str, Any]]:
    stmt = select(PaymentTerminal).where(
        PaymentTerminal.archived_at.is_(None)
    )

    if location_id:
        stmt = stmt.where(
            PaymentTerminal.location_id == location_id
        )

    if provider:
        stmt = stmt.where(
            PaymentTerminal.provider == provider
        )

    if enabled_only:
        stmt = stmt.where(
            PaymentTerminal.enabled.is_(True)
        )

    stmt = stmt.order_by(
        PaymentTerminal.is_default.desc(),
        PaymentTerminal.display_name.asc(),
    )

    rows = (
        await session.execute(stmt)
    ).scalars().all()

    return [_terminal(row) for row in rows]


async def get_terminal(
    session: AsyncSession,
    terminal_id: str,
) -> Optional[Dict[str, Any]]:
    row = (
        await session.execute(
            select(PaymentTerminal).where(
                PaymentTerminal.id == terminal_id,
                PaymentTerminal.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    return _terminal(row)


async def create_terminal(
    session: AsyncSession,
    doc: Dict[str, Any],
) -> Dict[str, Any]:
    valid = {
        k: v
        for k, v in doc.items()
        if hasattr(PaymentTerminal, k)
    }

    if "metadata" in doc:
        valid["metadata_json"] = (
            doc.get("metadata") or {}
        )

    row = PaymentTerminal(**valid)
    session.add(row)
    await session.flush()

    return _terminal(row)


async def update_terminal(
    session: AsyncSession,
    terminal_id: str,
    fields: Dict[str, Any],
) -> int:
    valid = {
        k: v
        for k, v in fields.items()
        if hasattr(PaymentTerminal, k)
        and k not in {"id", "created_at"}
    }

    if "metadata" in fields:
        valid["metadata_json"] = (
            fields.get("metadata") or {}
        )

    valid["updated_at"] = datetime.now(
        timezone.utc
    )

    result = await session.execute(
        update(PaymentTerminal)
        .where(
            PaymentTerminal.id == terminal_id,
            PaymentTerminal.archived_at.is_(None),
        )
        .values(**valid)
    )

    return result.rowcount or 0


async def clear_defaults(
    session: AsyncSession,
    *,
    location_id: Optional[str],
) -> int:
    conds = [
        PaymentTerminal.archived_at.is_(None),
        PaymentTerminal.is_default.is_(True),
    ]

    if location_id is None:
        conds.append(
            PaymentTerminal.location_id.is_(None)
        )
    else:
        conds.append(
            PaymentTerminal.location_id == location_id
        )

    result = await session.execute(
        update(PaymentTerminal)
        .where(and_(*conds))
        .values(
            is_default=False,
            updated_at=datetime.now(timezone.utc),
        )
    )

    return result.rowcount or 0


async def archive_terminal(
    session: AsyncSession,
    terminal_id: str,
    *,
    updated_by: Optional[str] = None,
) -> int:
    now = datetime.now(timezone.utc)

    result = await session.execute(
        update(PaymentTerminal)
        .where(
            PaymentTerminal.id == terminal_id,
            PaymentTerminal.archived_at.is_(None),
        )
        .values(
            archived_at=now,
            enabled=False,
            is_default=False,
            updated_at=now,
            updated_by=updated_by,
        )
    )

    return result.rowcount or 0


async def create_attempt(
    session: AsyncSession,
    doc: Dict[str, Any],
) -> Dict[str, Any]:
    valid = {
        k: v
        for k, v in doc.items()
        if hasattr(TerminalPaymentAttempt, k)
    }

    row = TerminalPaymentAttempt(**valid)
    session.add(row)
    await session.flush()

    return _attempt(row)


async def get_attempt(
    session: AsyncSession,
    attempt_id: str,
) -> Optional[Dict[str, Any]]:
    row = (
        await session.execute(
            select(TerminalPaymentAttempt).where(
                TerminalPaymentAttempt.id == attempt_id
            )
        )
    ).scalar_one_or_none()

    return _attempt(row)
