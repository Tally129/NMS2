"""Tamper-evident audit log + security events.

`AuditLog.seq` is the source of truth for chain ordering — it is an
autoincrementing bigint, guaranteed monotonically increasing by PostgreSQL,
so `SELECT ... ORDER BY seq DESC LIMIT 1` gives us the previous chain link
without racing on the timestamp column.

`AuditLog.id` (UUID string) is the stable public identifier retained from
the Mongo era so audit search results referenced by other systems still
resolve after cutover.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, Index, String, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class AuditLog(Base):
    __tablename__ = "auth_audit_logs"

    # Autoincrementing sequence — deterministic ordering for chain verify.
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        server_default=func.now(), index=True,
    )
    user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    user_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="success")
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    audit_metadata: Mapped[Dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict,
    )
    prev_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    hash: Mapped[str] = mapped_column(String(128), nullable=False)

    __table_args__ = (
        Index("ix_auth_audit_action_ts", "action", "ts"),
    )


class SecurityEvent(Base):
    """High/critical-severity mirror of audit rows, for alerting review."""
    __tablename__ = "auth_security_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now(),
    )
    audit_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    resource_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    handled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
