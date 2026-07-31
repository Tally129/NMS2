"""Clinical + Messaging + Files domain models (Phases 3.3 / 3.4).

All FKs to auth_users / emr_clients are nullable with legacy_* breadcrumbs so
historical Mongo rows can survive an incomplete backfill. Every table
inherits the same Base as the rest of the schema.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow():
    return datetime.now(timezone.utc)


# =========================================================== Clinical =====
class VisitNote(Base):
    """SOAP + free-text notes for a client. Immutable once finalized;
    edits after finalize become amendments (hash-chained)."""
    __tablename__ = "emr_visit_notes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("emr_clients.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    practitioner_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    practitioner_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    drafted_by_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    drafted_by_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    drafted_by_role: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    appointment_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    subjective: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    objective: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    assessment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    plan: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    free_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default="draft", index=True)
    finalized_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    finalized_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Hash chain — SHA-256 over the canonical JSON of the finalized content.
    # `prev_hash` refers to the previously finalized note for the same
    # practitioner (or "GENESIS" for first note). Preserved from Mongo.
    prev_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    note_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Amendments + prior versions live as JSONB arrays — mirrors the Mongo
    # shape and keeps the audit trail dense.
    amendments: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    prior_versions: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    legacy_mongo_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        server_default=func.now(), onupdate=_utcnow,
    )


class _PayloadMixin:
    """Adds a JSONB `payload` column carrying router-provided fields that
    aren't first-class columns on the table. Written/read by
    `motor_compat_pg.MotorCompatCollection`."""

    payload: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}",
    )


class TreatmentPlan(_PayloadMixin, Base):
    __tablename__ = "emr_treatment_plans"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("emr_clients.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    practitioner_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    goals: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    interventions: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    starts_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    legacy_mongo_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=_utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=_utcnow, server_default=func.now(),
                                                  onupdate=_utcnow)


class Treatment(_PayloadMixin, Base):
    """Aesthetic / wellness treatments delivered at the front desk."""
    __tablename__ = "emr_treatments"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("emr_clients.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    client_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_by_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    kind: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                          default=_utcnow, server_default=func.now())
    legacy_mongo_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class LabValue(_PayloadMixin, Base):
    __tablename__ = "emr_lab_values"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("emr_clients.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    marker: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[Optional[float]] = mapped_column(Text, nullable=True)  # store as text — sometimes ranges
    unit: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    reference_range: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    collected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ordering_provider_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ordering_provider_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="new")
    tasks: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    legacy_mongo_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=_utcnow, server_default=func.now())


class LiveSoapDraft(Base):
    __tablename__ = "emr_live_soap_drafts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    appointment_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    author_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    body: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=_utcnow, server_default=func.now(),
                                                  onupdate=_utcnow)


class VisitChat(Base):
    __tablename__ = "emr_visit_chat"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    appointment_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    sender_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sender_role: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                          default=_utcnow, server_default=func.now(),
                                          index=True)


class ClinicalDelegation(Base):
    """Time-bounded authority for a non-provider (MA, admin) to draft/edit a
    provider's clinical documentation for a specific client."""
    __tablename__ = "emr_clinical_delegations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    delegate_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    client_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("emr_clients.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    scope: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # draft|full
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    revoke_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=_utcnow, server_default=func.now())
    legacy_mongo_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


# ========================================================= Messaging =====
class MessageThread(_PayloadMixin, Base):
    __tablename__ = "emr_message_threads"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("emr_clients.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    practitioner_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    subject: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    last_message_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=_utcnow, server_default=func.now())
    legacy_mongo_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class Message(_PayloadMixin, Base):
    __tablename__ = "emr_messages"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("emr_message_threads.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    sender_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sender_role: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=_utcnow, server_default=func.now(),
                                                  index=True)
    legacy_mongo_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class FormTemplate(_PayloadMixin, Base):
    __tablename__ = "emr_form_templates"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    schema: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=_utcnow, server_default=func.now())
    legacy_mongo_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class FormSubmission(_PayloadMixin, Base):
    __tablename__ = "emr_form_submissions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    token: Mapped[Optional[str]] = mapped_column(String(128), nullable=True,
                                                  unique=True, index=True)
    template_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("emr_form_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    client_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("emr_clients.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    answers: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=_utcnow, server_default=func.now())
    legacy_mongo_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class SoapTemplate(_PayloadMixin, Base):
    __tablename__ = "emr_soap_templates"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=_utcnow, server_default=func.now())
    legacy_mongo_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class PushSubscription(Base):
    __tablename__ = "emr_push_subscriptions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    keys: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=_utcnow, server_default=func.now())
