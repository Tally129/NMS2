"""PostgreSQL repository for the scheduling domain (Phase 3.2).

Handles the CRUD + query surface previously served by
`db.appointments`, `db.appointment_requests`, `db.availability`,
`db.reminders`, `db.reminder_settings`.

Every helper returns plain dicts (never ORM instances) so downstream
routers keep serving identical JSON payloads.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from postgres_models.scheduling import (
    Appointment,
    AppointmentRequest,
    Availability,
    Reminder,
    ReminderSettings,
)


# --------------------------------------------------------------- serializers #
_APPT_COLS = (
    "id", "client_id", "practitioner_id", "created_by", "service", "status",
    "visit_mode", "consent_telehealth", "start", "end", "notes",
    "series_id", "series_pattern",
    "telehealth", "waiting_room", "recordings",
    "transaction_id", "reminder_sent_at",
    "legacy_mongo_id", "legacy_client_id", "legacy_practitioner_id",
    "legacy_created_by",
    "created_at", "updated_at",
)


def _appt(a: Appointment) -> Dict[str, Any]:
    if a is None:
        return None
    return {k: getattr(a, k) for k in _APPT_COLS}


_REQ_COLS = (
    "id", "full_name", "email", "phone", "returning", "service", "date",
    "time", "notes", "add_ons", "status", "decline_reason", "suggested_time",
    "reviewed_by", "reviewed_at", "ip", "legacy_mongo_id", "created_at",
)


def _req(r: AppointmentRequest) -> Dict[str, Any]:
    if r is None:
        return None
    d = {k: getattr(r, k) for k in _REQ_COLS}
    # Legacy API contract used `fullName` and `addOns`. Preserve.
    d["fullName"] = d.pop("full_name")
    d["addOns"] = d.pop("add_ons") or []
    return d


def _avail(av: Availability) -> Dict[str, Any]:
    if av is None:
        return None
    return {
        "id": av.id, "practitioner_id": av.practitioner_id,
        "weekday": av.weekday, "start_time": av.start_time,
        "end_time": av.end_time, "active": av.active,
    }


def _reminder(r: Reminder) -> Dict[str, Any]:
    if r is None:
        return None
    return {
        "id": r.id, "appointment_id": r.appointment_id,
        "client_id": r.client_id, "channel": r.channel,
        "scheduled_at": r.scheduled_at, "sent_at": r.sent_at,
        "status": r.status, "created_at": r.created_at,
    }


# ============================================================ appointments #
async def get_appointment(session: AsyncSession, appt_id: str) -> Optional[Dict[str, Any]]:
    row = (await session.execute(
        select(Appointment).where(Appointment.id == appt_id)
    )).scalar_one_or_none()
    return _appt(row)


async def list_appointments(
    session: AsyncSession, *,
    client_id: Optional[str] = None,
    practitioner_id: Optional[str] = None,
    start_gte: Optional[datetime] = None,
    start_lte: Optional[datetime] = None,
    status_in: Optional[Iterable[str]] = None,
    reminder_not_sent: bool = False,
    limit: int = 1000,
    sort_desc: bool = False,
) -> List[Dict[str, Any]]:
    stmt = select(Appointment)
    conds = []
    if client_id:
        conds.append(Appointment.client_id == client_id)
    if practitioner_id:
        conds.append(Appointment.practitioner_id == practitioner_id)
    if start_gte is not None:
        conds.append(Appointment.start >= start_gte)
    if start_lte is not None:
        conds.append(Appointment.start <= start_lte)
    if status_in is not None:
        vals = [s for s in status_in if s]
        if vals:
            conds.append(Appointment.status.in_(vals))
    if reminder_not_sent:
        conds.append(Appointment.reminder_sent_at.is_(None))
    if conds:
        stmt = stmt.where(and_(*conds))
    order = Appointment.start.desc() if sort_desc else Appointment.start.asc()
    stmt = stmt.order_by(order).limit(limit)
    return [_appt(a) for a in (await session.execute(stmt)).scalars().all()]


async def create_appointment(session: AsyncSession, doc: Dict[str, Any]) -> Dict[str, Any]:
    valid = {k: v for k, v in doc.items() if hasattr(Appointment, k)}
    valid.setdefault("status", "confirmed")
    valid.setdefault("visit_mode", "in_person")
    valid.setdefault("consent_telehealth", False)
    row = Appointment(**valid)
    session.add(row)
    await session.flush()
    return _appt(row)


async def update_appointment(session: AsyncSession, appt_id: str,
                              fields: Dict[str, Any]) -> int:
    if not fields:
        return 0
    valid = {k: v for k, v in fields.items() if hasattr(Appointment, k)}
    if not valid:
        return 0
    r = await session.execute(
        update(Appointment).where(Appointment.id == appt_id).values(**valid)
    )
    return r.rowcount or 0


async def list_appointments_with_waiting_state(session: AsyncSession, *,
                                                  state: str = "requested",
                                                  limit: int = 200) -> List[Dict[str, Any]]:
    """Return appointments whose `waiting_room.state == state`, ordered by request_at asc.

    Emulates the Mongo query `{"waiting_room.state": state}` with JSONB `->>`.
    """
    stmt = (select(Appointment)
            .where(Appointment.waiting_room["state"].astext == state)
            .order_by(Appointment.waiting_room["request_at"].astext.asc())
            .limit(limit))
    return [_appt(a) for a in (await session.execute(stmt)).scalars().all()]


async def push_appointment_recording(session: AsyncSession, appt_id: str,
                                      recording: Dict[str, Any]) -> int:
    row = (await session.execute(
        select(Appointment).where(Appointment.id == appt_id)
    )).scalar_one_or_none()
    if not row:
        return 0
    existing = list(row.recordings or [])
    existing.append(recording)
    row.recordings = existing
    await session.flush()
    return 1


async def bulk_cancel_series(session: AsyncSession, series_id: str,
                              now: datetime) -> int:
    r = await session.execute(
        update(Appointment)
        .where(
            Appointment.series_id == series_id,
            Appointment.start >= now,
            Appointment.status != "completed",
        )
        .values(status="canceled")
    )
    return r.rowcount or 0


async def find_overlapping_appointments(
    session: AsyncSession, *, practitioner_id: str,
    start: datetime, end: datetime,
    statuses: Iterable[str] = ("requested", "confirmed"),
) -> List[Dict[str, Any]]:
    """Return appointments for `practitioner_id` whose [start, end) window
    overlaps [start, end). Used by /availability/slots.
    """
    stmt = select(Appointment).where(
        Appointment.practitioner_id == practitioner_id,
        Appointment.start >= start, Appointment.start < end,
        Appointment.status.in_(list(statuses)),
    )
    return [_appt(a) for a in (await session.execute(stmt)).scalars().all()]


# =================================================== appointment_requests #
async def create_appointment_request(session: AsyncSession,
                                       doc: Dict[str, Any]) -> Dict[str, Any]:
    # Map legacy Mongo camelCase to snake_case columns.
    valid = {}
    for k, v in doc.items():
        if k == "fullName":
            valid["full_name"] = v
        elif k == "addOns":
            valid["add_ons"] = v
        elif hasattr(AppointmentRequest, k):
            valid[k] = v
    valid.setdefault("status", "new")
    row = AppointmentRequest(**valid)
    session.add(row)
    await session.flush()
    return _req(row)


async def get_appointment_request(session: AsyncSession,
                                    req_id: str) -> Optional[Dict[str, Any]]:
    row = (await session.execute(
        select(AppointmentRequest).where(AppointmentRequest.id == req_id)
    )).scalar_one_or_none()
    return _req(row)


async def list_appointment_requests(
    session: AsyncSession, *, status: Optional[str] = None, limit: int = 200,
) -> List[Dict[str, Any]]:
    stmt = select(AppointmentRequest).order_by(
        AppointmentRequest.created_at.desc()
    ).limit(limit)
    if status:
        stmt = stmt.where(AppointmentRequest.status == status)
    return [_req(r) for r in (await session.execute(stmt)).scalars().all()]


async def update_appointment_request(session: AsyncSession, req_id: str,
                                       fields: Dict[str, Any]) -> int:
    valid = {k: v for k, v in fields.items() if hasattr(AppointmentRequest, k)}
    if not valid:
        return 0
    r = await session.execute(
        update(AppointmentRequest).where(AppointmentRequest.id == req_id)
        .values(**valid)
    )
    return r.rowcount or 0


async def count_appointment_requests(session: AsyncSession) -> int:
    return int((await session.execute(
        select(func.count(AppointmentRequest.id))
    )).scalar_one())


# ============================================================ availability #
async def list_availability(session: AsyncSession, *,
                              practitioner_id: Optional[str] = None,
                              weekday: Optional[int] = None,
                              active_only: bool = False,
                              limit: int = 200) -> List[Dict[str, Any]]:
    stmt = select(Availability)
    if practitioner_id:
        stmt = stmt.where(Availability.practitioner_id == practitioner_id)
    if weekday is not None:
        stmt = stmt.where(Availability.weekday == weekday)
    if active_only:
        stmt = stmt.where(Availability.active.is_(True))
    stmt = stmt.order_by(Availability.weekday.asc()).limit(limit)
    return [_avail(a) for a in (await session.execute(stmt)).scalars().all()]


async def create_availability(session: AsyncSession,
                                doc: Dict[str, Any]) -> Dict[str, Any]:
    valid = {k: v for k, v in doc.items() if hasattr(Availability, k)}
    valid.setdefault("active", True)
    row = Availability(**valid)
    session.add(row)
    await session.flush()
    return _avail(row)


async def delete_availability(session: AsyncSession, avail_id: str) -> int:
    r = await session.execute(
        delete(Availability).where(Availability.id == avail_id)
    )
    return r.rowcount or 0


# ============================================================ reminders #
async def create_reminder(session: AsyncSession,
                            doc: Dict[str, Any]) -> Dict[str, Any]:
    valid = {k: v for k, v in doc.items() if hasattr(Reminder, k)}
    valid.setdefault("status", "scheduled")
    row = Reminder(**valid)
    session.add(row)
    await session.flush()
    return _reminder(row)


async def list_due_reminders(session: AsyncSession, *, now: datetime,
                               limit: int = 200) -> List[Dict[str, Any]]:
    stmt = (select(Reminder)
            .where(Reminder.status == "scheduled",
                   Reminder.scheduled_at <= now)
            .order_by(Reminder.scheduled_at.asc())
            .limit(limit))
    return [_reminder(r) for r in (await session.execute(stmt)).scalars().all()]


async def mark_reminder_sent(session: AsyncSession, reminder_id: str,
                               sent_at: datetime) -> int:
    r = await session.execute(
        update(Reminder).where(Reminder.id == reminder_id)
        .values(status="sent", sent_at=sent_at)
    )
    return r.rowcount or 0


# ============================================================ settings #
_SETTINGS_ID = "singleton"


async def get_reminder_settings(session: AsyncSession) -> Optional[Dict[str, Any]]:
    row = (await session.execute(
        select(ReminderSettings).where(ReminderSettings.id == _SETTINGS_ID)
    )).scalar_one_or_none()
    if not row:
        return None
    return {
        "id": row.id,
        "appointment_reminder_hours_before": row.appointment_reminder_hours_before,
        "appointment_reminder_channels": row.appointment_reminder_channels or [],
        "follow_up_days_after": row.follow_up_days_after,
        "enabled": row.enabled,
    }


async def upsert_reminder_settings(session: AsyncSession,
                                     fields: Dict[str, Any]) -> Dict[str, Any]:
    row = (await session.execute(
        select(ReminderSettings).where(ReminderSettings.id == _SETTINGS_ID)
    )).scalar_one_or_none()
    if not row:
        row = ReminderSettings(id=_SETTINGS_ID)
        session.add(row)
    # Only patch known columns.
    for k in ("appointment_reminder_hours_before", "follow_up_days_after",
              "enabled", "appointment_reminder_channels"):
        if k in fields and fields[k] is not None:
            setattr(row, k, fields[k])
    await session.flush()
    return await get_reminder_settings(session)
