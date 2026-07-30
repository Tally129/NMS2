"""RefreshToken — one row per refresh token in a rotating family.

Never stores raw tokens. `token_hash` is `sha256(raw)` in hex. Rotation is
handled by `sessions.rotate_refresh` inside a `SELECT ... FOR UPDATE`
transaction so two concurrent refreshes cannot both consume the same row.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class RefreshToken(Base):
    __tablename__ = "auth_refresh_tokens"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("auth_user_sessions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    family_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parent_token_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    replaced_by_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now(),
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    revoke_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ip_created: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ip_last_used: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent_created: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    __table_args__ = (
        Index("ix_auth_refresh_tokens_family_active", "family_id", "revoked_at"),
    )
