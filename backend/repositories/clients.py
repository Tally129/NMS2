"""Client + IntakeForm repository (Phase 3.1b)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from postgres_models import Client, IntakeForm


def _client_to_dict(c: Client) -> Dict[str, Any]:
    return {k: getattr(c, k) for k in (
        "id", "user_id", "mrn", "full_name", "email", "phone", "alt_phone",
        "dob", "sex", "gender_identity", "pronouns", "marital_status",
        "language", "referral_source", "assigned_practitioner_id",
        "photo_file_id", "primary_concern", "notes",
        "intake_completed", "consent_marketing", "consent_photo",
        "consent_telehealth", "comms_pref",
        "address", "emergency_contact", "allergies",
        "dietary_restrictions", "wellness_goals", "current_supplements",
        "legacy_mongo_id", "created_at", "updated_at",
    )}


async def get_by_id(session: AsyncSession, client_id: str) -> Optional[Dict[str, Any]]:
    row = (await session.execute(select(Client).where(Client.id == client_id))).scalar_one_or_none()
    return _client_to_dict(row) if row else None


async def get_by_user_id(session: AsyncSession, user_id: str) -> Optional[Dict[str, Any]]:
    row = (await session.execute(select(Client).where(Client.user_id == user_id))).scalar_one_or_none()
    return _client_to_dict(row) if row else None


async def list_recent(session: AsyncSession, *, limit: int = 200,
                      practitioner_id: Optional[str] = None) -> List[Dict[str, Any]]:
    stmt = select(Client)
    if practitioner_id:
        stmt = stmt.where(Client.assigned_practitioner_id == practitioner_id)
    stmt = stmt.order_by(Client.created_at.desc()).limit(min(max(1, limit), 5000))
    return [_client_to_dict(c) for c in (await session.execute(stmt)).scalars().all()]


async def create(session: AsyncSession, *, client_id: str, user_id: Optional[str],
                 full_name: Optional[str], email: Optional[str], phone: Optional[str],
                 **extra) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    c = Client(
        id=client_id, user_id=user_id,
        full_name=full_name, email=(email or "").lower() or None, phone=phone,
        intake_completed=False, created_at=now,
        **{k: v for k, v in extra.items() if hasattr(Client, k)},
    )
    session.add(c)
    await session.flush()
    return _client_to_dict(c)


async def update_fields(session: AsyncSession, client_id: str, fields: Dict[str, Any]) -> int:
    if not fields:
        return 0
    fields = dict(fields)
    fields["updated_at"] = datetime.now(timezone.utc)
    r = await session.execute(update(Client).where(Client.id == client_id).values(**fields))
    return r.rowcount or 0


async def delete_by_id(session: AsyncSession, client_id: str) -> int:
    r = await session.execute(delete(Client).where(Client.id == client_id))
    return r.rowcount or 0


async def count_all(session: AsyncSession) -> int:
    from sqlalchemy import func
    return int((await session.execute(select(func.count(Client.id)))).scalar_one())


# ---------------------------------------------------------------- intakes #
async def get_intake_for_client(session: AsyncSession, client_id: str) -> Optional[Dict[str, Any]]:
    row = (await session.execute(
        select(IntakeForm).where(IntakeForm.client_id == client_id)
    )).scalar_one_or_none()
    if not row:
        return None
    return {k: getattr(row, k) for k in (
        "id", "client_id", "completed", "completed_at", "signed_at",
        "demographics", "health_history", "lifestyle", "symptoms", "consent",
        "legacy_mongo_id", "created_at",
    )}


async def upsert_intake(session: AsyncSession, *, intake_id: str, client_id: str,
                        fields: Dict[str, Any]) -> None:
    existing = (await session.execute(
        select(IntakeForm).where(IntakeForm.client_id == client_id)
    )).scalar_one_or_none()
    if existing:
        for k, v in fields.items():
            if hasattr(IntakeForm, k):
                setattr(existing, k, v)
    else:
        session.add(IntakeForm(id=intake_id, client_id=client_id, **{
            k: v for k, v in fields.items() if hasattr(IntakeForm, k)
        }))
    await session.flush()
