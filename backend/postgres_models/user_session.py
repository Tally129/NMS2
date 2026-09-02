"""UserSession — server-side session row, one per active login."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class UserSession(Base):
    """Persistent record of one authenticated session.

    Access tokens embed `sid = UserSession.id`. Every authenticated request
    revalidates the session against this row (`sessions.check_and_touch_session`).
    Deleting the user row cascades — a purged user cannot leave orphan sessions.
    """
    __tablename__ = "auth_user_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now(),
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Legacy field kept for backwards-compat readers. Mirrors absolute_expires_at.
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    idle_timeout_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    absolute_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    revoke_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    ip_first: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ip_last: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    mfa_satisfied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Refresh-token family this session belongs to. Rotating a family bumps
    # this on the row so the new family is discoverable from the session.
    family_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    __table_args__ = (
        Index("ix_auth_user_sessions_user_active", "user_id", "revoked_at"),
    )
