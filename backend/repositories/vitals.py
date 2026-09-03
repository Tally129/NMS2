"""Visit-based patient vitals repository."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from postgres_models import VitalRecord


_VITAL_FIELDS = (
    "id",
    "client_id",
    "appointment_id",
    "recorded_by_id",
    "recorded_by_name",
    "recorded_at",
    "source",
    "visit_mode",
    "systolic",
    "diastolic",
    "pulse",
    "respiratory_rate",
    "temperature_f",
    "oxygen_saturation",
    "height_in",
    "weight_lb",
    "bmi",
    "pain_score",
    "blood_glucose",
    "waist_in",
    "notes",
    "amended_at",
    "amended_by_id",
    "amended_by_name",
    "amendment_reason",
    "prior_values",
    "created_at",
    "updated_at",
)


def to_dict(row: VitalRecord) -> Dict[str, Any]:
    return {
        field: getattr(row, field)
        for field in _VITAL_FIELDS
    }


async def get_by_id(
    session: AsyncSession,
    vital_id: str,
) -> Optional[Dict[str, Any]]:
    row = (
        await session.execute(
            select(VitalRecord).where(
                VitalRecord.id == vital_id
            )
        )
    ).scalar_one_or_none()

    return to_dict(row) if row else None


async def list_for_client(
    session: AsyncSession,
    client_id: str,
    *,
    appointment_id: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    statement = select(VitalRecord).where(
        VitalRecord.client_id == client_id
    )

    if appointment_id:
        statement = statement.where(
            VitalRecord.appointment_id == appointment_id
        )

    statement = statement.order_by(
        VitalRecord.recorded_at.desc(),
        VitalRecord.created_at.desc(),
    ).limit(min(max(1, limit), 500))

    rows = (
        await session.execute(statement)
    ).scalars().all()

    return [to_dict(row) for row in rows]


async def create(
    session: AsyncSession,
    document: Dict[str, Any],
) -> Dict[str, Any]:
    valid = {
        key: value
        for key, value in document.items()
        if hasattr(VitalRecord, key)
    }

    row = VitalRecord(**valid)
    session.add(row)
    await session.flush()

    return to_dict(row)


async def amend(
    session: AsyncSession,
    vital_id: str,
    *,
    fields: Dict[str, Any],
    amended_by_id: str,
    amended_by_name: str,
    amendment_reason: str,
) -> Optional[Dict[str, Any]]:
    row = (
        await session.execute(
            select(VitalRecord).where(
                VitalRecord.id == vital_id
            )
        )
    ).scalar_one_or_none()

    if not row:
        return None

    previous = {
        key: getattr(row, key)
        for key in fields
        if hasattr(row, key)
    }

    history = list(row.prior_values or [])
    history.append(
        {
            "values": previous,
            "amended_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "amended_by_id": amended_by_id,
            "amended_by_name": amended_by_name,
            "reason": amendment_reason,
        }
    )

    for key, value in fields.items():
        if hasattr(row, key):
            setattr(row, key, value)

    now = datetime.now(timezone.utc)

    row.prior_values = history
    row.amended_at = now
    row.amended_by_id = amended_by_id
    row.amended_by_name = amended_by_name
    row.amendment_reason = amendment_reason
    row.updated_at = now

    await session.flush()

    return to_dict(row)
