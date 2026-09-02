"""Marketing OS Phase 7 — funnels, qualification forms, and offer library.

Privacy-minimized marketing domain only.

These tables intentionally:
- do NOT reference emr_clients;
- do NOT reference patient/clinical records;
- do NOT store contact details;
- use opaque marketing_subject_id values;
- store only marketing-safe qualification answers.

Clinical intake remains isolated in the EMR form system.
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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class _MarketingPhase7TimestampMixin:
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


class MarketingOffer(_MarketingPhase7TimestampMixin, Base):
    __tablename__ = "marketing_offers"

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

    service_interest: Mapped[Optional[str]] = mapped_column(
        String(160),
        nullable=True,
        index=True,
    )
    description: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)

    min_qualification_score: Mapped[int] = mapped_column(
        Integer(),
        nullable=False,
        server_default="0",
    )

    eligible_locations: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    match_config: Mapped[dict] = mapped_column(
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


class MarketingQualificationForm(_MarketingPhase7TimestampMixin, Base):
    __tablename__ = "marketing_qualification_forms"

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

    form_schema: Mapped[dict] = mapped_column(
        "schema",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    scoring_rules: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    qualification_config: Mapped[dict] = mapped_column(
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


class MarketingFunnel(_MarketingPhase7TimestampMixin, Base):
    __tablename__ = "marketing_funnels"

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

    landing_page: Mapped[Optional[str]] = mapped_column(
        String(512),
        nullable=True,
    )

    qualification_form_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey(
            "marketing_qualification_forms.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    default_offer_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("marketing_offers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    config: Mapped[dict] = mapped_column(
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


class MarketingFunnelStep(_MarketingPhase7TimestampMixin, Base):
    __tablename__ = "marketing_funnel_steps"
    __table_args__ = (
        UniqueConstraint(
            "funnel_id",
            "step_key",
            name="uq_marketing_funnel_steps_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    funnel_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_funnels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    step_key: Mapped[str] = mapped_column(String(96), nullable=False)
    step_type: Mapped[str] = mapped_column(
        String(48),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer(), nullable=False)

    title: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
    )

    config: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class MarketingQualificationSubmission(Base):
    __tablename__ = "marketing_qualification_submissions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Opaque marketing identity only — never a patient/client FK.
    marketing_subject_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )

    funnel_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("marketing_funnels.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    qualification_form_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "marketing_qualification_forms.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    answers: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    qualification_score: Mapped[int] = mapped_column(
        Integer(),
        nullable=False,
    )

    qualification_status: Mapped[str] = mapped_column(
        String(48),
        nullable=False,
        index=True,
    )

    matched_offer_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("marketing_offers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    normalized_fields: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
