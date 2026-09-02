"""Typed PostgreSQL models for the Marketing OS Lead CRM (Phase 6).

Privacy-minimized operational lead layer. These tables intentionally store
NO clinical/PHI data — only opaque marketing identifiers, marketing-safe
attribution, non-clinical qualification categories, and internal staff
workflow state. Direct contact details remain in existing operational
systems and are NOT duplicated here.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class _LeadTimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class MarketingLead(_LeadTimestampMixin, Base):
    __tablename__ = "marketing_leads"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    marketing_subject_id: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True,
    )

    # Attribution (marketing-safe).
    source: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    medium: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    campaign_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
    )
    campaign_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
    )
    landing_page: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True,
    )
    offer_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    attribution_source: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True,
    )
    attribution_model: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
    )

    # Pipeline + scoring.
    lead_status: Mapped[str] = mapped_column(
        String(48), nullable=False, server_default="new", index=True,
    )
    qualification_status: Mapped[str] = mapped_column(
        String(48), nullable=False, server_default="unqualified", index=True,
    )
    qualification_score: Mapped[Optional[int]] = mapped_column(
        Integer(), nullable=True,
    )
    opportunity_score: Mapped[Optional[int]] = mapped_column(
        Integer(), nullable=True,
    )
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="medium", index=True,
    )

    # Non-clinical qualification (broad marketing categories only).
    urgency: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    service_interest: Mapped[Optional[str]] = mapped_column(
        String(160), nullable=True,
    )
    preferred_location: Mapped[Optional[str]] = mapped_column(
        String(160), nullable=True,
    )
    preferred_contact_window: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
    )
    appointment_readiness: Mapped[Optional[str]] = mapped_column(
        String(48), nullable=True,
    )

    # Ownership + next action.
    assigned_owner_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    next_action_type: Mapped[Optional[str]] = mapped_column(
        String(48), nullable=True,
    )
    next_action_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Appointment state (marketing-safe; sourced from marketing events).
    appointment_status: Mapped[Optional[str]] = mapped_column(
        String(48), nullable=True, index=True,
    )

    # Speed-to-lead timestamps (never fabricated; null until observed).
    lead_created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    first_contact_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    first_contact_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    first_response_seconds: Mapped[Optional[int]] = mapped_column(
        Integer(), nullable=True,
    )
    appointment_requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    booked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}",
    )


class MarketingLeadTask(_LeadTimestampMixin, Base):
    __tablename__ = "marketing_lead_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    lead_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("marketing_leads.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    task_type: Mapped[str] = mapped_column(String(48), nullable=False)
    owner_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    due_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="open", index=True,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )


class MarketingLeadAssignment(_LeadTimestampMixin, Base):
    __tablename__ = "marketing_lead_assignments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    lead_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("marketing_leads.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    previous_owner_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    new_owner_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_by: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    note: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)


class MarketingLeadActivity(_LeadTimestampMixin, Base):
    __tablename__ = "marketing_lead_activity"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    lead_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("marketing_leads.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    activity_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        index=True,
    )
    actor_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    summary: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    details: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}",
    )
