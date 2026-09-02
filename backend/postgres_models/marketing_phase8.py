"""Marketing OS Phase 8A — nurture sequences + appointment-recovery engine.

Privacy-minimized marketing domain only. These tables intentionally:
- do NOT reference emr_clients / patients / clinical records;
- do NOT store contact details (no email/phone recipient columns);
- use opaque ``marketing_subject_id`` values;
- store only marketing-safe, bounded, non-PHI configuration + audit data.

Only ``auth_users`` (internal staff) foreign keys are used, consistent with
the existing Marketing OS Lead CRM / funnel tables. Automatic external
outreach is disabled: the scheduler NEVER sends. Email actions are always
held pending an explicit, deliberate future dispatch boundary.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class _Phase8TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class MarketingNurtureSequence(_Phase8TimestampMixin, Base):
    __tablename__ = "marketing_nurture_sequences"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="draft",
        index=True,
    )

    # Deterministic trigger classification (8B wires event ingestion).
    trigger_type: Mapped[str] = mapped_column(
        String(48),
        nullable=False,
        server_default="manual",
        index=True,
    )
    trigger_config: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    # Lead statuses that immediately stop nurture (suppression).
    stop_on_statuses: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text(
            "'[\"booked\", \"confirmed\", \"showed\", \"won\", \"lost\"]'::jsonb"
        ),
    )

    # Marketing-safe audience filter (bounded, non-PHI).
    audience_config: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    created_by: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )


class MarketingNurtureStep(_Phase8TimestampMixin, Base):
    __tablename__ = "marketing_nurture_steps"
    __table_args__ = (
        UniqueConstraint(
            "sequence_id",
            "step_key",
            name="uq_marketing_nurture_steps_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sequence_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_nurture_sequences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    step_key: Mapped[str] = mapped_column(String(96), nullable=False)
    position: Mapped[int] = mapped_column(Integer(), nullable=False)

    # send_email | create_task | wait
    action_type: Mapped[str] = mapped_column(
        String(48),
        nullable=False,
        index=True,
    )
    # email | internal
    channel: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="internal",
    )

    # Cumulative delay from enrollment start (minutes) up to this step.
    delay_minutes: Mapped[int] = mapped_column(
        Integer(),
        nullable=False,
        server_default="0",
    )

    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # Marketing-safe email content (bounded, no PHI). Never a recipient.
    subject: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    body_html: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)

    config: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class MarketingNurtureEnrollment(_Phase8TimestampMixin, Base):
    __tablename__ = "marketing_nurture_enrollments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    sequence_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_nurture_sequences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lead_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Opaque marketing identity denormalized for audit convenience.
    marketing_subject_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )

    # active | completed | stopped | failed
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="active",
        index=True,
    )

    current_step_position: Mapped[int] = mapped_column(
        Integer(),
        nullable=False,
        server_default="0",
    )

    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    next_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    stop_reason: Mapped[Optional[str]] = mapped_column(
        String(160),
        nullable=True,
    )

    enrolled_by: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )

    metadata_json: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class MarketingNurtureAction(_Phase8TimestampMixin, Base):
    __tablename__ = "marketing_nurture_actions"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_marketing_nurture_actions_idem",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    enrollment_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_nurture_enrollments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_nurture_sequences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_nurture_steps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lead_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    marketing_subject_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )

    # send_email | create_task
    action_type: Mapped[str] = mapped_column(String(48), nullable=False)
    # email | internal
    channel: Mapped[str] = mapped_column(String(32), nullable=False)

    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    # scheduled | pending_approval | approved | held | skipped
    #   | failed | cancelled
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="pending_approval",
        index=True,
    )
    approval_required: Mapped[bool] = mapped_column(
        Boolean(),
        nullable=False,
        server_default=text("true"),
    )

    approved_by: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    executed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Outcome audit. For email in Phase 8A this is always a hold reason;
    # a real send is NEVER performed here.
    delivery_status: Mapped[Optional[str]] = mapped_column(
        String(48),
        nullable=True,
    )
    hold_reason: Mapped[Optional[str]] = mapped_column(
        String(160),
        nullable=True,
    )
    error: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)

    subject: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # Bounded, non-PHI snapshot of what would be actioned.
    preview: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    # Deterministic dedupe: enrollment_id + step position.
    idempotency_key: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
    )

    # Optional link to a created Lead CRM task (create_task actions).
    lead_task_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
