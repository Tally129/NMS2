"""Scheduling domain models (Phase 3.2).

Migrates the following Mongo collections to PostgreSQL:

    * appointments             → emr_appointments
    * appointment_requests     → emr_appointment_requests
    * availability             → emr_availability
    * reminders                → emr_reminders
    * reminder_settings        → emr_reminder_settings

Every FK to `auth_users` / `emr_clients` is nullable — Phase 3.1b legacy
Mongo rows may reference ids that no longer resolve, and staff-created
records may pre-date a client. Original ids are always preserved in the
`legacy_*` fields so downstream reconciliation can chase them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class Appointment(Base):
    __tablename__ = "emr_appointments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("emr_clients.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    practitioner_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )

    service: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False,
                                        default="confirmed", index=True)
    visit_mode: Mapped[str] = mapped_column(String(32), nullable=False,
                                            default="in_person")
    consent_telehealth: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                                     default=False)

    start: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                            nullable=False, index=True)
    end: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                          nullable=False)

    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Recurring series
    series_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True,
                                                     index=True)
    series_pattern: Mapped[Optional[str]] = mapped_column(String(32),
                                                          nullable=True)

    # Telehealth / waiting-room / recordings are stored as JSONB blobs — their
    # shape is owned by routers/telehealth.py and evolves independently.
    telehealth: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    waiting_room: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    recordings: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    # Cross-domain refs (kept as plain strings — Phase 3.6 will FK them).
    transaction_id: Mapped[Optional[str]] = mapped_column(String(64),
                                                          nullable=True)

    reminder_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Reconciliation breadcrumbs for the Mongo cutover.
    legacy_mongo_id: Mapped[Optional[str]] = mapped_column(String(64),
                                                            nullable=True)
    legacy_client_id: Mapped[Optional[str]] = mapped_column(String(64),
                                                             nullable=True)
    legacy_practitioner_id: Mapped[Optional[str]] = mapped_column(String(64),
                                                                    nullable=True)
    legacy_created_by: Mapped[Optional[str]] = mapped_column(String(64),
                                                              nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        server_default=func.now(), onupdate=_utcnow,
    )


class AppointmentRequest(Base):
    """Anonymous / public appointment-request submissions.

    These have NO account yet — patient contact is captured in-line. Reviewed
    by staff via `/api/appointment-requests/*` and either approved,
    rescheduled, or declined.
    """
    __tablename__ = "emr_appointment_requests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True,
                                                  index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    returning: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    service: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    time: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    add_ons: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False,
                                        default="new", index=True)
    decline_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    suggested_time: Mapped[Optional[str]] = mapped_column(String(64),
                                                           nullable=True)

    reviewed_by: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    legacy_mongo_id: Mapped[Optional[str]] = mapped_column(String(64),
                                                            nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        server_default=func.now(),
    )


class Availability(Base):
    """Recurring weekly rules per practitioner."""
    __tablename__ = "emr_availability"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    practitioner_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Mon..6=Sun
    start_time: Mapped[str] = mapped_column(String(8), nullable=False)  # HH:MM
    end_time: Mapped[str] = mapped_column(String(8), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    legacy_mongo_id: Mapped[Optional[str]] = mapped_column(String(64),
                                                            nullable=True)
    legacy_practitioner_id: Mapped[Optional[str]] = mapped_column(String(64),
                                                                    nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        server_default=func.now(),
    )


class Reminder(Base):
    """Per-appointment scheduled reminder (one row per channel per appt)."""
    __tablename__ = "emr_reminders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    appointment_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("emr_appointments.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    client_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("emr_clients.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)  # email|sms
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default="scheduled", index=True)

    legacy_mongo_id: Mapped[Optional[str]] = mapped_column(String(64),
                                                            nullable=True)
    legacy_appointment_id: Mapped[Optional[str]] = mapped_column(String(64),
                                                                   nullable=True)
    legacy_client_id: Mapped[Optional[str]] = mapped_column(String(64),
                                                             nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        server_default=func.now(),
    )


class ReminderSettings(Base):
    """Singleton row keyed by literal id='singleton'. See routers/appointments.py."""
    __tablename__ = "emr_reminder_settings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True,
                                    default="singleton")
    appointment_reminder_hours_before: Mapped[int] = mapped_column(
        Integer, nullable=False, default=24,
    )
    appointment_reminder_channels: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list,
    )
    follow_up_days_after: Mapped[int] = mapped_column(
        Integer, nullable=False, default=7,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        server_default=func.now(), onupdate=_utcnow,
    )
