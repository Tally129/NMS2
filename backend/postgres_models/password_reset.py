"""Password-reset attempts and single-use reset tokens."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class PasswordResetAttempt(Base):
    """One row per `/auth/forgot-password` submission — for rate limiting.

    Compound indexes support:
        SELECT COUNT(*) WHERE email_hash = ? AND ts >= window_start
        SELECT COUNT(*) WHERE ip = ? AND ts >= window_start
    """
    __tablename__ = "auth_password_reset_attempts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_pra_email_ts", "email_hash", "ts"),
        Index("ix_pra_ip_ts", "ip", "ts"),
        Index("ix_pra_ts", "ts"),
    )


class PasswordResetToken(Base):
    """Single-use reset token. Never store raw values — only `sha256(raw)`."""
    __tablename__ = "auth_password_reset_tokens"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    email_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
