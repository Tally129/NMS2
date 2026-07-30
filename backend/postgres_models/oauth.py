"""OAuth state + one-time handoff rows.

Sensitive values (access tokens, refresh cookie values, authorization codes)
must NEVER be written to application logs. The repository writes them here
and the auth router reads them exactly once before deletion.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class OAuthState(Base):
    """CSRF-defence state for the direct Google OAuth flow. Single-use."""
    __tablename__ = "auth_oauth_states"

    state: Mapped[str] = mapped_column(String(128), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class OAuthHandoff(Base):
    """Short-lived handoff row used by the Google OAuth callback → SPA
    exchange. Contains the newly-minted access token + refresh cookie value
    for the client to pick up exactly once. Extremely sensitive — reads
    delete the row within the same transaction."""
    __tablename__ = "auth_oauth_handoffs"

    handoff_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    access_token: Mapped[str] = mapped_column(String(4096), nullable=False)
    refresh_cookie_value: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now(),
    )
    consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
