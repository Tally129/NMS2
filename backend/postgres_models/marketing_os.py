"""Typed PostgreSQL models for the NMS Marketing OS.

These tables intentionally do not use the legacy Motor-compatible
JSONB payload model. Marketing OS uses typed repositories backed by
AsyncSessionLocal.

No external advertising or publishing actions are performed here.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class _MarketingTimestampMixin:
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


class MarketingGoal(_MarketingTimestampMixin, Base):
    __tablename__ = "marketing_goals"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="active",
        index=True,
    )

    goal_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    target_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    target_unit: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )

    start_date: Mapped[Optional[date]] = mapped_column(
        Date(),
        nullable=True,
    )

    end_date: Mapped[Optional[date]] = mapped_column(
        Date(),
        nullable=True,
    )

    service_line: Mapped[Optional[str]] = mapped_column(
        String(160),
        nullable=True,
    )

    geography: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    constraints: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    metadata_json: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    created_by: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey(
            "auth_users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )


class MarketingBudget(_MarketingTimestampMixin, Base):
    __tablename__ = "marketing_budgets"

    __table_args__ = (
        CheckConstraint(
            "period_end >= period_start",
            name="ck_marketing_budgets_date_range",
        ),
        CheckConstraint(
            "approved_amount >= 0",
            name="ck_marketing_budgets_approved_nonnegative",
        ),
        CheckConstraint(
            "spent_amount >= 0",
            name="ck_marketing_budgets_spent_nonnegative",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    goal_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey(
            "marketing_goals.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    period_start: Mapped[date] = mapped_column(
        Date(),
        nullable=False,
    )

    period_end: Mapped[date] = mapped_column(
        Date(),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        server_default="USD",
    )

    approved_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        server_default="0",
    )

    spent_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        server_default="0",
    )

    daily_cap: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )

    target_cpl: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )

    target_cac: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )

    minimum_roas: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    allocation: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    rules: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="draft",
        index=True,
    )

    created_by: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey(
            "auth_users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )


class MarketingChannelAccount(
    _MarketingTimestampMixin,
    Base,
):
    __tablename__ = "marketing_channel_accounts"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "external_account_id",
            name="uq_marketing_channel_provider_account",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    provider: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    external_account_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    account_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="disconnected",
        index=True,
    )

    currency: Mapped[Optional[str]] = mapped_column(
        String(3),
        nullable=True,
    )

    timezone: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )

    read_enabled: Mapped[bool] = mapped_column(
        Boolean(),
        nullable=False,
        server_default="false",
    )

    write_enabled: Mapped[bool] = mapped_column(
        Boolean(),
        nullable=False,
        server_default="false",
    )

    last_sync_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    configuration: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    created_by: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey(
            "auth_users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )


class MarketingDailyMetric(
    _MarketingTimestampMixin,
    Base,
):
    __tablename__ = "marketing_daily_metrics"

    __table_args__ = (
        UniqueConstraint(
            "metric_date",
            "provider",
            "external_campaign_id",
            name="uq_marketing_daily_metric_campaign_day",
        ),
        CheckConstraint(
            "impressions >= 0 AND clicks >= 0 AND "
            "spend >= 0 AND leads >= 0 AND conversions >= 0",
            name="ck_marketing_daily_metrics_nonnegative",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    metric_date: Mapped[date] = mapped_column(
        Date(),
        nullable=False,
        index=True,
    )

    channel_account_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey(
            "marketing_channel_accounts.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    provider: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    external_campaign_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )

    nms_campaign_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey(
            "emr_campaigns.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    campaign_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )

    impressions: Mapped[int] = mapped_column(
        BigInteger(),
        nullable=False,
        server_default="0",
    )

    clicks: Mapped[int] = mapped_column(
        BigInteger(),
        nullable=False,
        server_default="0",
    )

    spend: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        server_default="0",
    )

    leads: Mapped[int] = mapped_column(
        BigInteger(),
        nullable=False,
        server_default="0",
    )

    conversions: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        server_default="0",
    )

    conversion_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        server_default="0",
    )

    raw_metrics: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )


class MarketingConversionEvent(
    _MarketingTimestampMixin,
    Base,
):
    __tablename__ = "marketing_conversion_events"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    event_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    marketing_subject_id: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )

    session_id: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
    )

    external_click_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    source: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
    )

    medium: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
    )

    campaign: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )

    content: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )

    term: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )

    value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    currency: Mapped[Optional[str]] = mapped_column(
        String(3),
        nullable=True,
    )

    properties: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )


class MarketingAttribution(
    _MarketingTimestampMixin,
    Base,
):
    __tablename__ = "marketing_attributions"

    __table_args__ = (
        CheckConstraint(
            "credit >= 0 AND credit <= 1",
            name="ck_marketing_attributions_credit",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    conversion_event_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "marketing_conversion_events.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    model: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default="last_touch",
    )

    provider: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )

    external_campaign_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )

    nms_campaign_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey(
            "emr_campaigns.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    source: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
    )

    medium: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
    )

    credit: Mapped[Decimal] = mapped_column(
        Numeric(8, 6),
        nullable=False,
        server_default="1",
    )

    attributed_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    reason: Mapped[Optional[str]] = mapped_column(
        Text(),
        nullable=True,
    )

    details: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )


class MarketingRecommendation(
    _MarketingTimestampMixin,
    Base,
):
    __tablename__ = "marketing_recommendations"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    goal_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey(
            "marketing_goals.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    recommendation_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    summary: Mapped[Optional[str]] = mapped_column(
        Text(),
        nullable=True,
    )

    reason: Mapped[Optional[str]] = mapped_column(
        Text(),
        nullable=True,
    )

    priority: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="medium",
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="pending",
        index=True,
    )

    provider: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )

    nms_campaign_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey(
            "emr_campaigns.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    proposed_action: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    evidence: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    model_metadata: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_by: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey(
            "auth_users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )


class MarketingApproval(
    _MarketingTimestampMixin,
    Base,
):
    __tablename__ = "marketing_approvals"

    __table_args__ = (
        CheckConstraint(
            "decision IN ('approved', 'rejected')",
            name="ck_marketing_approvals_decision",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    recommendation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "marketing_recommendations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    decision: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    decision_reason: Mapped[Optional[str]] = mapped_column(
        Text(),
        nullable=True,
    )

    decided_by: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey(
            "auth_users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    snapshot: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )


class MarketingAction(
    _MarketingTimestampMixin,
    Base,
):
    __tablename__ = "marketing_actions"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    recommendation_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey(
            "marketing_recommendations.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    approval_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey(
            "marketing_approvals.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    provider: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    action_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="blocked",
        index=True,
    )

    dry_run: Mapped[bool] = mapped_column(
        Boolean(),
        nullable=False,
        server_default="true",
    )

    request_payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    response_payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    external_action_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )

    last_error: Mapped[Optional[str]] = mapped_column(
        Text(),
        nullable=True,
    )

    executed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_by: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey(
            "auth_users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
