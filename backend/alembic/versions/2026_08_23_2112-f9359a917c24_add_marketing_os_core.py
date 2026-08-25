"""add marketing os core

Revision ID: f9359a917c24
Revises: b9c0d1e2f3a4
Create Date: 2026-08-23 21:12:21.968081

Marketing OS operating-core tables.

This migration deliberately does not modify:
- clinical tables
- patient records
- telehealth
- authentication behavior
- existing campaigns
- existing Content Strategist tables
- existing Publishing Queue tables

External advertising/publishing execution remains disabled at the
application-policy layer.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f9359a917c24"
down_revision: Union[str, Sequence[str], None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps():
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Marketing goals
    # ------------------------------------------------------------------
    op.create_table(
        "marketing_goals",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column(
            "name",
            sa.String(length=200),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "goal_type",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "target_value",
            sa.Numeric(18, 4),
            nullable=True,
        ),
        sa.Column(
            "target_unit",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "start_date",
            sa.Date(),
            nullable=True,
        ),
        sa.Column(
            "end_date",
            sa.Date(),
            nullable=True,
        ),
        sa.Column(
            "service_line",
            sa.String(length=160),
            nullable=True,
        ),
        sa.Column(
            "geography",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "constraints",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_by",
            sa.String(length=64),
            nullable=True,
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["auth_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_marketing_goals_status",
        "marketing_goals",
        ["status"],
    )
    op.create_index(
        "ix_marketing_goals_goal_type",
        "marketing_goals",
        ["goal_type"],
    )
    op.create_index(
        "ix_marketing_goals_created_by",
        "marketing_goals",
        ["created_by"],
    )

    # ------------------------------------------------------------------
    # Marketing budgets
    # ------------------------------------------------------------------
    op.create_table(
        "marketing_budgets",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column(
            "goal_id",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "name",
            sa.String(length=200),
            nullable=False,
        ),
        sa.Column(
            "period_start",
            sa.Date(),
            nullable=False,
        ),
        sa.Column(
            "period_end",
            sa.Date(),
            nullable=False,
        ),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            server_default="USD",
        ),
        sa.Column(
            "approved_amount",
            sa.Numeric(18, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "spent_amount",
            sa.Numeric(18, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "daily_cap",
            sa.Numeric(18, 2),
            nullable=True,
        ),
        sa.Column(
            "target_cpl",
            sa.Numeric(18, 2),
            nullable=True,
        ),
        sa.Column(
            "target_cac",
            sa.Numeric(18, 2),
            nullable=True,
        ),
        sa.Column(
            "minimum_roas",
            sa.Numeric(18, 4),
            nullable=True,
        ),
        sa.Column(
            "allocation",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "rules",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "created_by",
            sa.String(length=64),
            nullable=True,
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["goal_id"],
            ["marketing_goals.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["auth_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "period_end >= period_start",
            name="ck_marketing_budgets_date_range",
        ),
        sa.CheckConstraint(
            "approved_amount >= 0",
            name="ck_marketing_budgets_approved_nonnegative",
        ),
        sa.CheckConstraint(
            "spent_amount >= 0",
            name="ck_marketing_budgets_spent_nonnegative",
        ),
    )

    op.create_index(
        "ix_marketing_budgets_goal_id",
        "marketing_budgets",
        ["goal_id"],
    )
    op.create_index(
        "ix_marketing_budgets_status",
        "marketing_budgets",
        ["status"],
    )
    op.create_index(
        "ix_marketing_budgets_period",
        "marketing_budgets",
        ["period_start", "period_end"],
    )

    # ------------------------------------------------------------------
    # Connected marketing/ad accounts
    # ------------------------------------------------------------------
    op.create_table(
        "marketing_channel_accounts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column(
            "provider",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "external_account_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "account_name",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="disconnected",
        ),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=True,
        ),
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "read_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "write_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "last_sync_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "configuration",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_by",
            sa.String(length=64),
            nullable=True,
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["auth_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "external_account_id",
            name="uq_marketing_channel_provider_account",
        ),
    )

    op.create_index(
        "ix_marketing_channel_accounts_provider",
        "marketing_channel_accounts",
        ["provider"],
    )
    op.create_index(
        "ix_marketing_channel_accounts_status",
        "marketing_channel_accounts",
        ["status"],
    )

    # ------------------------------------------------------------------
    # Daily channel/campaign performance
    # ------------------------------------------------------------------
    op.create_table(
        "marketing_daily_metrics",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column(
            "metric_date",
            sa.Date(),
            nullable=False,
        ),
        sa.Column(
            "channel_account_id",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "provider",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "external_campaign_id",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "nms_campaign_id",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "campaign_name",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "impressions",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "clicks",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "spend",
            sa.Numeric(18, 4),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "leads",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "conversions",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "conversion_value",
            sa.Numeric(18, 4),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "raw_metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["channel_account_id"],
            ["marketing_channel_accounts.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["nms_campaign_id"],
            ["emr_campaigns.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "metric_date",
            "provider",
            "external_campaign_id",
            name="uq_marketing_daily_metric_campaign_day",
        ),
        sa.CheckConstraint(
            "impressions >= 0 AND clicks >= 0 AND spend >= 0 "
            "AND leads >= 0 AND conversions >= 0",
            name="ck_marketing_daily_metrics_nonnegative",
        ),
    )

    op.create_index(
        "ix_marketing_daily_metrics_date",
        "marketing_daily_metrics",
        ["metric_date"],
    )
    op.create_index(
        "ix_marketing_daily_metrics_provider",
        "marketing_daily_metrics",
        ["provider"],
    )
    op.create_index(
        "ix_marketing_daily_metrics_nms_campaign",
        "marketing_daily_metrics",
        ["nms_campaign_id"],
    )

    # ------------------------------------------------------------------
    # Privacy-minimized conversion events
    # ------------------------------------------------------------------
    op.create_table(
        "marketing_conversion_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column(
            "event_type",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "marketing_subject_id",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "session_id",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "external_click_id",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "source",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "medium",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "campaign",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "content",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "term",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "value",
            sa.Numeric(18, 4),
            nullable=True,
        ),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=True,
        ),
        sa.Column(
            "properties",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_marketing_conversion_events_type",
        "marketing_conversion_events",
        ["event_type"],
    )
    op.create_index(
        "ix_marketing_conversion_events_occurred_at",
        "marketing_conversion_events",
        ["occurred_at"],
    )
    op.create_index(
        "ix_marketing_conversion_events_subject",
        "marketing_conversion_events",
        ["marketing_subject_id"],
    )
    op.create_index(
        "ix_marketing_conversion_events_click_id",
        "marketing_conversion_events",
        ["external_click_id"],
    )

    # ------------------------------------------------------------------
    # Attribution results
    # ------------------------------------------------------------------
    op.create_table(
        "marketing_attributions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column(
            "conversion_event_id",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "model",
            sa.String(length=64),
            nullable=False,
            server_default="last_touch",
        ),
        sa.Column(
            "provider",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "external_campaign_id",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "nms_campaign_id",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "source",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "medium",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "credit",
            sa.Numeric(8, 6),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "attributed_value",
            sa.Numeric(18, 4),
            nullable=True,
        ),
        sa.Column(
            "reason",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["conversion_event_id"],
            ["marketing_conversion_events.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["nms_campaign_id"],
            ["emr_campaigns.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "credit >= 0 AND credit <= 1",
            name="ck_marketing_attributions_credit",
        ),
    )

    op.create_index(
        "ix_marketing_attributions_conversion_event",
        "marketing_attributions",
        ["conversion_event_id"],
    )
    op.create_index(
        "ix_marketing_attributions_campaign",
        "marketing_attributions",
        ["nms_campaign_id"],
    )

    # ------------------------------------------------------------------
    # AI / system recommendations
    # ------------------------------------------------------------------
    op.create_table(
        "marketing_recommendations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column(
            "goal_id",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "recommendation_type",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "title",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "summary",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "reason",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "priority",
            sa.String(length=32),
            nullable=False,
            server_default="medium",
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "provider",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "nms_campaign_id",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "proposed_action",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "model_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_by",
            sa.String(length=64),
            nullable=True,
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["goal_id"],
            ["marketing_goals.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["nms_campaign_id"],
            ["emr_campaigns.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["auth_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_marketing_recommendations_status",
        "marketing_recommendations",
        ["status"],
    )
    op.create_index(
        "ix_marketing_recommendations_priority",
        "marketing_recommendations",
        ["priority"],
    )
    op.create_index(
        "ix_marketing_recommendations_goal",
        "marketing_recommendations",
        ["goal_id"],
    )

    # ------------------------------------------------------------------
    # Human approval/denial decisions
    # ------------------------------------------------------------------
    op.create_table(
        "marketing_approvals",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column(
            "recommendation_id",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "decision",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "decision_reason",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "decided_by",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["recommendation_id"],
            ["marketing_recommendations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["auth_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected')",
            name="ck_marketing_approvals_decision",
        ),
    )

    op.create_index(
        "ix_marketing_approvals_recommendation",
        "marketing_approvals",
        ["recommendation_id"],
    )
    op.create_index(
        "ix_marketing_approvals_decided_by",
        "marketing_approvals",
        ["decided_by"],
    )

    # ------------------------------------------------------------------
    # Controlled execution ledger
    # ------------------------------------------------------------------
    op.create_table(
        "marketing_actions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column(
            "recommendation_id",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "approval_id",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "provider",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "action_type",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="blocked",
        ),
        sa.Column(
            "dry_run",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "request_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "response_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "external_action_id",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "last_error",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_by",
            sa.String(length=64),
            nullable=True,
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["recommendation_id"],
            ["marketing_recommendations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["approval_id"],
            ["marketing_approvals.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["auth_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_marketing_actions_status",
        "marketing_actions",
        ["status"],
    )
    op.create_index(
        "ix_marketing_actions_provider",
        "marketing_actions",
        ["provider"],
    )
    op.create_index(
        "ix_marketing_actions_recommendation",
        "marketing_actions",
        ["recommendation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_marketing_actions_recommendation",
        table_name="marketing_actions",
    )
    op.drop_index(
        "ix_marketing_actions_provider",
        table_name="marketing_actions",
    )
    op.drop_index(
        "ix_marketing_actions_status",
        table_name="marketing_actions",
    )
    op.drop_table("marketing_actions")

    op.drop_index(
        "ix_marketing_approvals_decided_by",
        table_name="marketing_approvals",
    )
    op.drop_index(
        "ix_marketing_approvals_recommendation",
        table_name="marketing_approvals",
    )
    op.drop_table("marketing_approvals")

    op.drop_index(
        "ix_marketing_recommendations_goal",
        table_name="marketing_recommendations",
    )
    op.drop_index(
        "ix_marketing_recommendations_priority",
        table_name="marketing_recommendations",
    )
    op.drop_index(
        "ix_marketing_recommendations_status",
        table_name="marketing_recommendations",
    )
    op.drop_table("marketing_recommendations")

    op.drop_index(
        "ix_marketing_attributions_campaign",
        table_name="marketing_attributions",
    )
    op.drop_index(
        "ix_marketing_attributions_conversion_event",
        table_name="marketing_attributions",
    )
    op.drop_table("marketing_attributions")

    op.drop_index(
        "ix_marketing_conversion_events_click_id",
        table_name="marketing_conversion_events",
    )
    op.drop_index(
        "ix_marketing_conversion_events_subject",
        table_name="marketing_conversion_events",
    )
    op.drop_index(
        "ix_marketing_conversion_events_occurred_at",
        table_name="marketing_conversion_events",
    )
    op.drop_index(
        "ix_marketing_conversion_events_type",
        table_name="marketing_conversion_events",
    )
    op.drop_table("marketing_conversion_events")

    op.drop_index(
        "ix_marketing_daily_metrics_nms_campaign",
        table_name="marketing_daily_metrics",
    )
    op.drop_index(
        "ix_marketing_daily_metrics_provider",
        table_name="marketing_daily_metrics",
    )
    op.drop_index(
        "ix_marketing_daily_metrics_date",
        table_name="marketing_daily_metrics",
    )
    op.drop_table("marketing_daily_metrics")

    op.drop_index(
        "ix_marketing_channel_accounts_status",
        table_name="marketing_channel_accounts",
    )
    op.drop_index(
        "ix_marketing_channel_accounts_provider",
        table_name="marketing_channel_accounts",
    )
    op.drop_table("marketing_channel_accounts")

    op.drop_index(
        "ix_marketing_budgets_period",
        table_name="marketing_budgets",
    )
    op.drop_index(
        "ix_marketing_budgets_status",
        table_name="marketing_budgets",
    )
    op.drop_index(
        "ix_marketing_budgets_goal_id",
        table_name="marketing_budgets",
    )
    op.drop_table("marketing_budgets")

    op.drop_index(
        "ix_marketing_goals_created_by",
        table_name="marketing_goals",
    )
    op.drop_index(
        "ix_marketing_goals_goal_type",
        table_name="marketing_goals",
    )
    op.drop_index(
        "ix_marketing_goals_status",
        table_name="marketing_goals",
    )
    op.drop_table("marketing_goals")
