"""Login history + workforce-MFA continuation tickets."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class LoginHistory(Base):
    """One row per login attempt.

    `email_hash` (sha256 of normalised email) is stored so we can rate-limit
    per-account without persisting the raw address on every failed attempt.
    """
    __tablename__ = "auth_login_history"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    email_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        server_default=func.now(), index=True,
    )

    __table_args__ = (
        Index("ix_auth_login_history_email_ts", "email_hash", "ts"),
    )


class LoginContinuation(Base):
    """Short-lived ticket issued after a workforce user completes MFA.

    Consumed once by `/auth/login/continue` to establish the actual session.
    Never contains PHI; the ticket is opaque and single-use.
    """
    __tablename__ = "auth_login_continuations"

    ticket_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    mfa_satisfied_now: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
