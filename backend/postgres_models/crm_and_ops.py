"""CRM & Operations tables (Phase 3.5).

Seven tables for the retired collections: campaigns, front_desk_visits,
internal_tasks, integration_log, protocol_enrollments, protocol_templates,
files (metadata only — blobs live in S3/filesystem via `storage/`).

Every table follows the same shape: `id` PK, `created_at` typed column
(for sort/range filters), and a JSONB `payload` for all router-provided
fields. Selected FK-like fields are promoted to typed indexed columns
where common filters warrant it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class _Ph35Base:
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=_utcnow, server_default=func.now(), index=True,
    )
    payload: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}",
    )
    legacy_mongo_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class Campaign(_Ph35Base, Base):
    __tablename__ = "emr_campaigns"


class FrontDeskVisit(_Ph35Base, Base):
    __tablename__ = "emr_front_desk_visits"
    client_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("emr_clients.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )


class InternalTask(_Ph35Base, Base):
    __tablename__ = "emr_internal_tasks"
    status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class IntegrationLog(_Ph35Base, Base):
    __tablename__ = "emr_integration_log"


class ProtocolEnrollment(_Ph35Base, Base):
    __tablename__ = "emr_protocol_enrollments"
    client_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("emr_clients.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    practitioner_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)


class ProtocolTemplate(_Ph35Base, Base):
    __tablename__ = "emr_protocol_templates"


class FileMeta(_Ph35Base, Base):
    """File metadata only — blobs live in S3 (or filesystem in dev)."""
    __tablename__ = "emr_file_meta"
    client_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("emr_clients.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )
    # Storage-backend addressing (Phase 3.7):
    storage_backend: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    storage_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, index=True)
    bucket: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    version_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    legacy_gridfs_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    retention_hold_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
