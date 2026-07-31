"""Patient-profile side tables (Phase 3.1).

Intake forms, supplement assignments/sheets, and the legacy staff-side
password-reset-token table used by `portal_ops.py`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class IntakeForm(Base):
    __tablename__ = "emr_intake_forms"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("emr_clients.id", ondelete="CASCADE"),
        nullable=False, index=True, unique=True,
    )
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    signed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    demographics: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    health_history: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    lifestyle: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    symptoms: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    consent: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    legacy_mongo_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now(),
    )


class SupplementSheet(Base):
    __tablename__ = "emr_supplement_sheets"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    items: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_by_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    legacy_mongo_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now(),
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ClientSupplementAssignment(Base):
    __tablename__ = "emr_client_supplement_assignments"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("emr_clients.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    sheet_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("emr_supplement_sheets.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    sheet_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sheet_summary: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    items_snapshot: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    note_ids: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    assigned_by_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True,
    )
    assigned_by_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_referenced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_by_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    legacy_mongo_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now(),
    )


class LegacyPasswordResetToken(Base):
    """Session 3.1 rehome of the `password_reset_tokens` collection used by
    `portal_ops.py`'s staff-side reset flow (separate from the client-side
    /auth/forgot-password which was migrated in Session 2b)."""
    __tablename__ = "emr_legacy_password_reset_tokens"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now(),
    )
