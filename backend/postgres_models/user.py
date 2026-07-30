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
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    auth_provider: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    picture_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now(),
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Reverse links are declared but not eager-loaded to avoid N+1.
    client_profile: Mapped[Optional["Client"]] = relationship(back_populates="user", uselist=False)


class Client(Base):
    """Patient / client profile bound to a portal user."""
    __tablename__ = "auth_clients"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    full_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    intake_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now(),
    )

    user: Mapped[Optional[User]] = relationship(back_populates="client_profile")
