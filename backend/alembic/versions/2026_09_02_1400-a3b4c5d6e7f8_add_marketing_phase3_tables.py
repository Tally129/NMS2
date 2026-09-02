"""add marketing phase3 tables (competitors, keyword gap, backlinks, local)

Revision ID: a3b4c5d6e7f8
Revises: f2b3c4d5e6a7
Create Date: 2026-09-02 14:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a3b4c5d6e7f8"
down_revision = "f2b3c4d5e6a7"
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
        "marketing_search_competitors",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("site_id", sa.String(64),
                  sa.ForeignKey("marketing_search_sites.id",
                                ondelete="CASCADE"), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("normalized_domain", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("last_analyzed_at", sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column("created_by", sa.String(64),
                  sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
                  nullable=True),
        *_ts(),
        sa.UniqueConstraint("site_id", "normalized_domain",
                            name="uq_marketing_competitor_scope"),
    )
    op.create_index("ix_marketing_search_competitors_site_id",
                    "marketing_search_competitors", ["site_id"])
    op.create_index("ix_marketing_search_competitors_normalized_domain",
                    "marketing_search_competitors", ["normalized_domain"])
    op.create_index("ix_marketing_search_competitors_is_active",
                    "marketing_search_competitors", ["is_active"])

    op.create_table(
        "marketing_keyword_gap_snapshots",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("site_id", sa.String(64),
                  sa.ForeignKey("marketing_search_sites.id",
                                ondelete="CASCADE"), nullable=False),
        sa.Column("competitor_id", sa.String(64),
                  sa.ForeignKey("marketing_search_competitors.id",
                                ondelete="CASCADE"), nullable=True),
        sa.Column("keyword", sa.String(255), nullable=False),
        sa.Column("normalized_keyword", sa.String(255), nullable=False),
        sa.Column("nms_position", sa.Integer(), nullable=True),
        sa.Column("nms_source", sa.String(64), nullable=True),
        sa.Column("competitor_position", sa.Integer(), nullable=True),
        sa.Column("competitor_source", sa.String(64), nullable=True),
        sa.Column("search_volume", sa.BigInteger(), nullable=True),
        sa.Column("keyword_difficulty", sa.Integer(), nullable=True),
        sa.Column("intent", sa.String(32), nullable=False,
                  server_default="unknown"),
        sa.Column("opportunity", sa.String(32), nullable=False,
                  server_default="unknown"),
        sa.Column("captured_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(64), nullable=False,
                  server_default="unknown"),
        *_ts(),
        sa.UniqueConstraint("site_id", "competitor_id", "normalized_keyword",
                            "captured_date", "source",
                            name="uq_marketing_keyword_gap_scope"),
    )
    op.create_index("ix_marketing_keyword_gap_snapshots_site_id",
                    "marketing_keyword_gap_snapshots", ["site_id"])
    op.create_index("ix_marketing_keyword_gap_snapshots_competitor_id",
                    "marketing_keyword_gap_snapshots", ["competitor_id"])
    op.create_index("ix_marketing_keyword_gap_snapshots_normalized_keyword",
                    "marketing_keyword_gap_snapshots", ["normalized_keyword"])
    op.create_index("ix_marketing_keyword_gap_snapshots_opportunity",
                    "marketing_keyword_gap_snapshots", ["opportunity"])
    op.create_index("ix_marketing_keyword_gap_snapshots_captured_date",
                    "marketing_keyword_gap_snapshots", ["captured_date"])

    op.create_table(
        "marketing_backlink_snapshots",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("site_id", sa.String(64),
                  sa.ForeignKey("marketing_search_sites.id",
                                ondelete="CASCADE"), nullable=False),
        sa.Column("referring_domain", sa.String(255), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=True),
        sa.Column("anchor_text", sa.Text(), nullable=True),
        sa.Column("first_seen", sa.Date(), nullable=True),
        sa.Column("last_seen", sa.Date(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False,
                  server_default="active"),
        sa.Column("rel_type", sa.String(16), nullable=False,
                  server_default="unknown"),
        sa.Column("authority", sa.Numeric(9, 3), nullable=True),
        sa.Column("provider", sa.String(64), nullable=False,
                  server_default="unknown"),
        sa.Column("captured_date", sa.Date(), nullable=False),
        *_ts(),
        sa.UniqueConstraint("site_id", "source_url", "target_url", "provider",
                            name="uq_marketing_backlink_scope"),
    )
    op.create_index("ix_marketing_backlink_snapshots_site_id",
                    "marketing_backlink_snapshots", ["site_id"])
    op.create_index("ix_marketing_backlink_snapshots_referring_domain",
                    "marketing_backlink_snapshots", ["referring_domain"])
    op.create_index("ix_marketing_backlink_snapshots_status",
                    "marketing_backlink_snapshots", ["status"])
    op.create_index("ix_marketing_backlink_snapshots_captured_date",
                    "marketing_backlink_snapshots", ["captured_date"])

    op.create_table(
        "marketing_local_rank_snapshots",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("site_id", sa.String(64),
                  sa.ForeignKey("marketing_search_sites.id",
                                ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", sa.String(64), nullable=False),
        sa.Column("location_name", sa.String(200), nullable=True),
        sa.Column("city", sa.String(128), nullable=True),
        sa.Column("state", sa.String(64), nullable=True),
        sa.Column("postal_code", sa.String(16), nullable=True),
        sa.Column("target_service", sa.String(200), nullable=True),
        sa.Column("target_keyword", sa.String(255), nullable=False),
        sa.Column("normalized_keyword", sa.String(255), nullable=False),
        sa.Column("local_rank", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(64), nullable=False,
                  server_default="unknown"),
        sa.Column("captured_date", sa.Date(), nullable=False),
        *_ts(),
        sa.UniqueConstraint("site_id", "location_id", "normalized_keyword",
                            "captured_date", "provider",
                            name="uq_marketing_local_rank_scope"),
    )
    op.create_index("ix_marketing_local_rank_snapshots_site_id",
                    "marketing_local_rank_snapshots", ["site_id"])
    op.create_index("ix_marketing_local_rank_snapshots_normalized_keyword",
                    "marketing_local_rank_snapshots", ["normalized_keyword"])
    op.create_index("ix_marketing_local_rank_snapshots_captured_date",
                    "marketing_local_rank_snapshots", ["captured_date"])


def downgrade() -> None:
    op.drop_table("marketing_local_rank_snapshots")
    op.drop_table("marketing_backlink_snapshots")
    op.drop_table("marketing_keyword_gap_snapshots")
    op.drop_table("marketing_search_competitors")
