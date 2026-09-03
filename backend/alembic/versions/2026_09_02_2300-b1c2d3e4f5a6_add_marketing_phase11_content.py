"""add marketing phase11 content + social intelligence

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-09-02 23:00:00.000000

Draft/planning-only content + social intelligence. No emr/patient/client/
clinical FKs; no PHI. No autonomous publishing. FKs only to internal marketing
tables (auth_users, marketing_offers, marketing_funnels, and self).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "b1c2d3e4f5a6"
down_revision = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None


def _ts():
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )


def upgrade() -> None:
    op.create_table(
        "marketing_content_topics",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("topic", sa.String(300), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("target_keyword", sa.String(200), nullable=True),
        sa.Column("search_intent", sa.String(32), nullable=True),
        sa.Column("audience", sa.String(160), nullable=True),
        sa.Column("funnel_stage", sa.String(32), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("status", sa.String(24), nullable=False,
                  server_default="idea"),
        sa.Column("source_refs", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("metrics", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", sa.String(64),
                  sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
                  nullable=True),
        *_ts(),
    )
    op.create_index("ix_marketing_content_topics_slug",
                    "marketing_content_topics", ["slug"], unique=True)
    op.create_index("ix_marketing_content_topics_priority",
                    "marketing_content_topics", ["priority"])
    op.create_index("ix_marketing_content_topics_status",
                    "marketing_content_topics", ["status"])

    op.create_table(
        "marketing_content_briefs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("topic_id", sa.String(64),
                  sa.ForeignKey("marketing_content_topics.id",
                                ondelete="SET NULL"), nullable=True),
        sa.Column("channel", sa.String(24), nullable=False),
        sa.Column("content_type", sa.String(48), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("audience", sa.String(160), nullable=True),
        sa.Column("funnel_stage", sa.String(32), nullable=True),
        sa.Column("cta", sa.String(300), nullable=True),
        sa.Column("campaign_theme", sa.String(200), nullable=True),
        sa.Column("offer_id", sa.String(64),
                  sa.ForeignKey("marketing_offers.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("funnel_id", sa.String(64),
                  sa.ForeignKey("marketing_funnels.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("outline", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(24), nullable=False,
                  server_default="planned"),
        sa.Column("created_by", sa.String(64),
                  sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
                  nullable=True),
        *_ts(),
    )
    op.create_index("ix_marketing_content_briefs_topic",
                    "marketing_content_briefs", ["topic_id"])
    op.create_index("ix_marketing_content_briefs_channel",
                    "marketing_content_briefs", ["channel"])
    op.create_index("ix_marketing_content_briefs_status",
                    "marketing_content_briefs", ["status"])

    op.create_table(
        "marketing_content_drafts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("brief_id", sa.String(64),
                  sa.ForeignKey("marketing_content_briefs.id",
                                ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(24), nullable=False),
        sa.Column("headline", sa.String(300), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("cta", sa.String(300), nullable=True),
        sa.Column("hook", sa.Text(), nullable=True),
        sa.Column("script", sa.Text(), nullable=True),
        sa.Column("on_screen_text", sa.Text(), nullable=True),
        sa.Column("shot_list", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("generator", sa.String(48), nullable=False,
                  server_default="template"),
        sa.Column("status", sa.String(24), nullable=False,
                  server_default="draft"),
        sa.Column("created_by", sa.String(64),
                  sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
                  nullable=True),
        *_ts(),
    )
    op.create_index("ix_marketing_content_drafts_brief",
                    "marketing_content_drafts", ["brief_id"])
    op.create_index("ix_marketing_content_drafts_status",
                    "marketing_content_drafts", ["status"])

    op.create_table(
        "marketing_social_plans",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("channel", sa.String(24), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("campaign_theme", sa.String(200), nullable=True),
        sa.Column("audience", sa.String(160), nullable=True),
        sa.Column("cadence", sa.String(48), nullable=True),
        sa.Column("status", sa.String(24), nullable=False,
                  server_default="draft"),
        sa.Column("config", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", sa.String(64),
                  sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
                  nullable=True),
        *_ts(),
    )
    op.create_index("ix_marketing_social_plans_channel",
                    "marketing_social_plans", ["channel"])
    op.create_index("ix_marketing_social_plans_status",
                    "marketing_social_plans", ["status"])

    op.create_table(
        "marketing_content_calendar_items",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("brief_id", sa.String(64),
                  sa.ForeignKey("marketing_content_briefs.id",
                                ondelete="SET NULL"), nullable=True),
        sa.Column("social_plan_id", sa.String(64),
                  sa.ForeignKey("marketing_social_plans.id",
                                ondelete="SET NULL"), nullable=True),
        sa.Column("channel", sa.String(24), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("planned_publish_at", sa.Date(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False,
                  server_default="planned"),
        sa.Column("metadata", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        *_ts(),
        sa.UniqueConstraint("brief_id", name="uq_marketing_calendar_brief"),
    )
    op.create_index("ix_marketing_content_calendar_items_brief",
                    "marketing_content_calendar_items", ["brief_id"])
    op.create_index("ix_marketing_content_calendar_items_channel",
                    "marketing_content_calendar_items", ["channel"])
    op.create_index("ix_marketing_content_calendar_items_date",
                    "marketing_content_calendar_items", ["planned_publish_at"])
    op.create_index("ix_marketing_content_calendar_items_status",
                    "marketing_content_calendar_items", ["status"])


def downgrade() -> None:
    op.drop_table("marketing_content_calendar_items")
    op.drop_table("marketing_social_plans")
    op.drop_table("marketing_content_drafts")
    op.drop_table("marketing_content_briefs")
    op.drop_table("marketing_content_topics")
