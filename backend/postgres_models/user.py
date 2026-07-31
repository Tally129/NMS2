"""User + Client models.

Note: `id` remains a string (UUID / opaque token) to preserve compatibility
with the existing Mongo-era code that treats user["id"] as a plain string.
Storing it as `String(64)` (rather than `postgresql.UUID`) means the staff
migration script can copy Mongo `id` values verbatim without conversion.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    """Portal user (workforce or client). Mirrors the fields the current
    Mongo-era code reads and writes; unused Mongo-only fields are omitted."""
    __tablename__ = "auth_users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="client")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Stored encrypted via auth_utils (AES-GCM). Ciphertext, never plaintext.
    mfa_secret: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    mfa_bypass: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Session 2c — admin bootstrap / forced onboarding state.
    #   None                          → onboarding complete (or never required, e.g. clients)
    #   "password_change_required"    → must set a permanent password before doing anything
    #   "mfa_enrollment_required"     → workforce user needs to enroll MFA before session
    onboarding_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # UTC expiry for the temporary password issued at bootstrap. Login rejects
    # the temporary password once this timestamp is in the past.
    temporary_password_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    auth_provider: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    picture_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now(),
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Reverse links are declared but not eager-loaded to avoid N+1.
    client_profile: Mapped[Optional["Client"]] = relationship(
        back_populates="user", uselist=False,
        foreign_keys="Client.user_id",
    )


class Client(Base):
    """Patient / client profile bound to a portal user.

    Session 3.1 extended this from the minimal Session 2b skeleton to hold
    every field the MongoDB `clients` docs carried. Structured columns
    for identifiers and query-hot fields; JSONB for semi-structured
    arrays/objects (allergies, address, emergency_contact, wellness_goals,
    dietary_restrictions, current_supplements). Reads that walked
    `db.clients.find(...)` land here.
    """
    __tablename__ = "emr_clients"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    mrn: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True, index=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    alt_phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    dob: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # ISO date string
    sex: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    gender_identity: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    pronouns: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    marital_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    language: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    referral_source: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    assigned_practitioner_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    photo_file_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    primary_concern: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    intake_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    consent_marketing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consent_photo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consent_telehealth: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    comms_pref: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Semi-structured, lossless preservation of Mongo shapes:
    address: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    emergency_contact: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    allergies: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    dietary_restrictions: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    wellness_goals: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    current_supplements: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    # Legacy-id passthrough for reconciliation across the cutover.
    legacy_mongo_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now(),
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=_utcnow,
    )

    user: Mapped[Optional[User]] = relationship(
        back_populates="client_profile", foreign_keys=[user_id],
    )
