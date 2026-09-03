"""Marketing OS Phase 9 — Conversion Optimization + Experimentation.

Privacy-minimized marketing domain only:
- no emr/patient/client/clinical foreign keys;
- opaque ``marketing_subject_id`` only (no PHI, no contact details);
- FKs only to internal/marketing tables (auth_users, marketing_offers,
  marketing_funnels, marketing_funnel_steps, marketing_conversion_events).

Experiments are advisory: deterministic A/B assignment + deterministic
reporting + a deterministic *recommended* winner. No autonomous publishing,
no provider/ad-platform writes, no budget changes, no SMS. Any external change
remains human-approval gated elsewhere.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class _Phase9TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MarketingExperiment(_Phase9TimestampMixin, Base):
    __tablename__ = "marketing_experiments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(160), nullable=False, unique=True, index=True
    )
    # landing_page | offer | funnel_step
    experiment_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    # draft | active | paused | completed | archived
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="draft", index=True
    )
    primary_metric: Mapped[str] = mapped_column(
        String(48), nullable=False, server_default="conversion"
    )
    exposure_metric: Mapped[str] = mapped_column(
        String(48), nullable=False, server_default="impression"
    )
    hypothesis: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)

    funnel_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("marketing_funnels.id", ondelete="SET NULL"),
        nullable=True,
    )

    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paused_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_by: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )


class MarketingExperimentVariant(_Phase9TimestampMixin, Base):
    __tablename__ = "marketing_experiment_variants"
    __table_args__ = (
        UniqueConstraint(
            "experiment_id", "variant_key",
            name="uq_marketing_experiment_variants_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_experiments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    variant_key: Mapped[str] = mapped_column(String(96), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_control: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, server_default=text("false")
    )
    allocation_pct: Mapped[int] = mapped_column(
        Integer(), nullable=False, server_default="0"
    )

    offer_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("marketing_offers.id", ondelete="SET NULL"),
        nullable=True,
    )
    funnel_step_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("marketing_funnel_steps.id", ondelete="SET NULL"),
        nullable=True,
    )

    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class MarketingExperimentAssignment(_Phase9TimestampMixin, Base):
    __tablename__ = "marketing_experiment_assignments"
    __table_args__ = (
        UniqueConstraint(
            "experiment_id", "marketing_subject_id",
            name="uq_marketing_experiment_assignments_subject",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_experiments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    variant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_experiment_variants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    marketing_subject_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MarketingExperimentOutcome(_Phase9TimestampMixin, Base):
    __tablename__ = "marketing_experiment_outcomes"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_marketing_experiment_outcomes_idem",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_experiments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    variant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_experiment_variants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assignment_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey(
            "marketing_experiment_assignments.id", ondelete="SET NULL"
        ),
        nullable=True,
    )
    marketing_subject_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, index=True
    )

    # impression|click|lead|appointment_request|booked|completed
    #   |conversion|spend
    metric_type: Mapped[str] = mapped_column(
        String(48), nullable=False, index=True
    )
    value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 4), nullable=True
    )
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Optional reuse of an already-sanitized Phase 5 conversion event.
    source_event_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("marketing_conversion_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(180), nullable=True
    )

    properties: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
