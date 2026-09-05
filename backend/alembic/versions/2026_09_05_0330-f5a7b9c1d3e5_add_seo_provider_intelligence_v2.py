"""add SEO provider intelligence v2 persistence

Revision ID: f5a7b9c1d3e5
Revises: e4f6a8c0d2b4
Create Date: 2026-09-05 03:30:00.000000

Marketing-only, non-PHI persistence for external SEO intelligence providers.

Adds:
- marketing_seo_provider_runs
- marketing_seo_domain_snapshots
- marketing_seo_organic_keyword_snapshots
- marketing_seo_competitor_snapshots

Important semantics:
- provider-discovered organic keywords remain separate from intentionally
  tracked marketing_search_keywords
- automatically discovered competitors remain separate from curated
  marketing_search_competitors
- Google Search Console remains separate first-party search evidence
- no credentials or raw provider authentication material are persisted
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = "f5a7b9c1d3e5"
down_revision = "e4f6a8c0d2b4"
branch_labels = None
depends_on = None


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
    # Paid/read-provider request ledger.
    # ------------------------------------------------------------------
    op.create_table(
        "marketing_seo_provider_runs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "site_id",
            sa.String(length=64),
            sa.ForeignKey(
                "marketing_search_sites.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "provider",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "report_type",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="completed",
        ),
        sa.Column(
            "target",
            sa.String(length=512),
            nullable=False,
        ),
        sa.Column(
            "location",
            sa.String(length=128),
            nullable=False,
            server_default="United States",
        ),
        sa.Column(
            "language",
            sa.String(length=32),
            nullable=False,
            server_default="English",
        ),
        sa.Column(
            "device",
            sa.String(length=32),
            nullable=False,
            server_default="desktop",
        ),
        sa.Column(
            "requested_limit",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "requested_offset",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "provider_total_count",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column(
            "provider_items_count",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column(
            "rows_normalized",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "provider_cost",
            sa.Numeric(18, 6),
            nullable=True,
        ),
        sa.Column(
            "provider_task_cost",
            sa.Numeric(18, 6),
            nullable=True,
        ),
        sa.Column(
            "complete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "next_offset",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "provider_status_code",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "provider_task_status_code",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "error",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "requested_limit IS NULL OR requested_limit >= 1",
            name="ck_marketing_seo_provider_run_limit_positive",
        ),
        sa.CheckConstraint(
            "requested_offset IS NULL OR requested_offset >= 0",
            name="ck_marketing_seo_provider_run_offset_nonnegative",
        ),
        sa.CheckConstraint(
            "next_offset IS NULL OR next_offset >= 0",
            name="ck_marketing_seo_provider_run_next_offset_nonnegative",
        ),
        sa.CheckConstraint(
            "provider_cost IS NULL OR provider_cost >= 0",
            name="ck_marketing_seo_provider_run_cost_nonnegative",
        ),
        sa.CheckConstraint(
            "provider_task_cost IS NULL OR provider_task_cost >= 0",
            name="ck_marketing_seo_provider_task_cost_nonnegative",
        ),
        sa.CheckConstraint(
            "provider_total_count IS NULL OR provider_total_count >= 0",
            name="ck_marketing_seo_provider_total_count_nonnegative",
        ),
        sa.CheckConstraint(
            "provider_items_count IS NULL OR provider_items_count >= 0",
            name="ck_marketing_seo_provider_items_count_nonnegative",
        ),
        sa.CheckConstraint(
            "rows_normalized >= 0",
            name="ck_marketing_seo_provider_rows_normalized_nonnegative",
        ),
    )

    op.create_index(
        "ix_marketing_seo_provider_runs_site_id",
        "marketing_seo_provider_runs",
        ["site_id"],
    )
    op.create_index(
        "ix_marketing_seo_provider_runs_provider",
        "marketing_seo_provider_runs",
        ["provider"],
    )
    op.create_index(
        "ix_marketing_seo_provider_runs_report_type",
        "marketing_seo_provider_runs",
        ["report_type"],
    )
    op.create_index(
        "ix_marketing_seo_provider_runs_status",
        "marketing_seo_provider_runs",
        ["status"],
    )
    op.create_index(
        "ix_marketing_seo_provider_runs_finished_at",
        "marketing_seo_provider_runs",
        ["finished_at"],
    )

    # ------------------------------------------------------------------
    # Semrush-style historical domain overview.
    # ------------------------------------------------------------------
    op.create_table(
        "marketing_seo_domain_snapshots",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "site_id",
            sa.String(length=64),
            sa.ForeignKey(
                "marketing_search_sites.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "provider_run_id",
            sa.String(length=64),
            sa.ForeignKey(
                "marketing_seo_provider_runs.id",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column(
            "provider",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "captured_date",
            sa.Date(),
            nullable=False,
        ),
        sa.Column(
            "location",
            sa.String(length=128),
            nullable=False,
            server_default="United States",
        ),
        sa.Column(
            "language",
            sa.String(length=32),
            nullable=False,
            server_default="English",
        ),
        sa.Column(
            "device",
            sa.String(length=32),
            nullable=False,
            server_default="desktop",
        ),
        sa.Column(
            "organic_keywords",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column(
            "estimated_organic_traffic",
            sa.Numeric(18, 6),
            nullable=True,
        ),
        sa.Column(
            "estimated_paid_traffic_cost",
            sa.Numeric(18, 6),
            nullable=True,
        ),
        sa.Column("pos_1", sa.BigInteger(), nullable=True),
        sa.Column("pos_2_3", sa.BigInteger(), nullable=True),
        sa.Column("pos_4_10", sa.BigInteger(), nullable=True),
        sa.Column("pos_11_20", sa.BigInteger(), nullable=True),
        sa.Column("pos_21_30", sa.BigInteger(), nullable=True),
        sa.Column("pos_31_40", sa.BigInteger(), nullable=True),
        sa.Column("pos_41_50", sa.BigInteger(), nullable=True),
        sa.Column("pos_51_60", sa.BigInteger(), nullable=True),
        sa.Column("pos_61_70", sa.BigInteger(), nullable=True),
        sa.Column("pos_71_80", sa.BigInteger(), nullable=True),
        sa.Column("pos_81_90", sa.BigInteger(), nullable=True),
        sa.Column("pos_91_100", sa.BigInteger(), nullable=True),
        sa.Column(
            "new_keywords",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column(
            "up_keywords",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column(
            "down_keywords",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column(
            "lost_keywords",
            sa.BigInteger(),
            nullable=True,
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "site_id",
            "captured_date",
            "provider",
            "location",
            "language",
            "device",
            name="uq_marketing_seo_domain_snapshot_scope",
        ),
        sa.CheckConstraint(
            "organic_keywords IS NULL OR organic_keywords >= 0",
            name="ck_marketing_seo_domain_keywords_nonnegative",
        ),
        sa.CheckConstraint(
            "estimated_organic_traffic IS NULL "
            "OR estimated_organic_traffic >= 0",
            name="ck_marketing_seo_domain_traffic_nonnegative",
        ),
        sa.CheckConstraint(
            "estimated_paid_traffic_cost IS NULL "
            "OR estimated_paid_traffic_cost >= 0",
            name="ck_marketing_seo_domain_traffic_cost_nonnegative",
        ),
    )

    op.create_index(
        "ix_marketing_seo_domain_snapshots_site_id",
        "marketing_seo_domain_snapshots",
        ["site_id"],
    )
    op.create_index(
        "ix_marketing_seo_domain_snapshots_captured_date",
        "marketing_seo_domain_snapshots",
        ["captured_date"],
    )
    op.create_index(
        "ix_marketing_seo_domain_snapshots_provider",
        "marketing_seo_domain_snapshots",
        ["provider"],
    )

    # ------------------------------------------------------------------
    # Provider-discovered organic ranking universe.
    #
    # Deliberately NOT marketing_search_keywords. Those rows represent
    # intentionally tracked keywords.
    # ------------------------------------------------------------------
    op.create_table(
        "marketing_seo_organic_keyword_snapshots",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "site_id",
            sa.String(length=64),
            sa.ForeignKey(
                "marketing_search_sites.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "provider_run_id",
            sa.String(length=64),
            sa.ForeignKey(
                "marketing_seo_provider_runs.id",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column(
            "keyword",
            sa.String(length=512),
            nullable=False,
        ),
        sa.Column(
            "normalized_keyword",
            sa.String(length=512),
            nullable=False,
        ),
        sa.Column(
            "intent",
            sa.String(length=32),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "search_volume",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column(
            "keyword_difficulty",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "cpc",
            sa.Numeric(18, 4),
            nullable=True,
        ),
        sa.Column(
            "current_rank",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "ranking_url",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "serp_features",
            JSONB,
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "location",
            sa.String(length=128),
            nullable=False,
            server_default="United States",
        ),
        sa.Column(
            "language",
            sa.String(length=32),
            nullable=False,
            server_default="English",
        ),
        sa.Column(
            "device",
            sa.String(length=32),
            nullable=False,
            server_default="desktop",
        ),
        sa.Column(
            "provider",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "captured_date",
            sa.Date(),
            nullable=False,
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "site_id",
            "normalized_keyword",
            "location",
            "language",
            "device",
            "captured_date",
            "provider",
            name="uq_marketing_seo_organic_keyword_snapshot_scope",
        ),
        sa.CheckConstraint(
            "keyword_difficulty IS NULL OR "
            "(keyword_difficulty >= 0 AND keyword_difficulty <= 100)",
            name="ck_marketing_seo_keyword_difficulty",
        ),
        sa.CheckConstraint(
            "current_rank IS NULL OR current_rank >= 1",
            name="ck_marketing_seo_keyword_rank_positive",
        ),
        sa.CheckConstraint(
            "search_volume IS NULL OR search_volume >= 0",
            name="ck_marketing_seo_keyword_volume_nonnegative",
        ),
        sa.CheckConstraint(
            "cpc IS NULL OR cpc >= 0",
            name="ck_marketing_seo_keyword_cpc_nonnegative",
        ),
    )

    op.create_index(
        "ix_marketing_seo_organic_keywords_site_id",
        "marketing_seo_organic_keyword_snapshots",
        ["site_id"],
    )
    op.create_index(
        "ix_marketing_seo_organic_keywords_normalized_keyword",
        "marketing_seo_organic_keyword_snapshots",
        ["normalized_keyword"],
    )
    op.create_index(
        "ix_marketing_seo_organic_keywords_captured_date",
        "marketing_seo_organic_keyword_snapshots",
        ["captured_date"],
    )
    op.create_index(
        "ix_marketing_seo_organic_keywords_current_rank",
        "marketing_seo_organic_keyword_snapshots",
        ["current_rank"],
    )
    op.create_index(
        "ix_marketing_seo_organic_keywords_provider",
        "marketing_seo_organic_keyword_snapshots",
        ["provider"],
    )

    # ------------------------------------------------------------------
    # Automatically discovered organic competitors.
    #
    # Deliberately separate from marketing_search_competitors, which is
    # the curated/selected competitor registry.
    # ------------------------------------------------------------------
    op.create_table(
        "marketing_seo_competitor_snapshots",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "site_id",
            sa.String(length=64),
            sa.ForeignKey(
                "marketing_search_sites.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "provider_run_id",
            sa.String(length=64),
            sa.ForeignKey(
                "marketing_seo_provider_runs.id",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column(
            "domain",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "normalized_domain",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "avg_position",
            sa.Numeric(12, 4),
            nullable=True,
        ),
        sa.Column(
            "sum_position",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column(
            "intersections",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column(
            "target_overlap_keywords",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column(
            "competitor_overlap_keywords",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column(
            "competitor_total_organic_keywords",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column(
            "competitor_estimated_traffic",
            sa.Numeric(18, 6),
            nullable=True,
        ),
        sa.Column(
            "location",
            sa.String(length=128),
            nullable=False,
            server_default="United States",
        ),
        sa.Column(
            "language",
            sa.String(length=32),
            nullable=False,
            server_default="English",
        ),
        sa.Column(
            "device",
            sa.String(length=32),
            nullable=False,
            server_default="desktop",
        ),
        sa.Column(
            "provider",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "captured_date",
            sa.Date(),
            nullable=False,
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "site_id",
            "normalized_domain",
            "captured_date",
            "provider",
            "location",
            "language",
            "device",
            name="uq_marketing_seo_competitor_snapshot_scope",
        ),
        sa.CheckConstraint(
            "avg_position IS NULL OR avg_position >= 0",
            name="ck_marketing_seo_competitor_avg_position_nonnegative",
        ),
        sa.CheckConstraint(
            "sum_position IS NULL OR sum_position >= 0",
            name="ck_marketing_seo_competitor_sum_position_nonnegative",
        ),
        sa.CheckConstraint(
            "intersections IS NULL OR intersections >= 0",
            name="ck_marketing_seo_competitor_intersections_nonnegative",
        ),
        sa.CheckConstraint(
            "competitor_total_organic_keywords IS NULL "
            "OR competitor_total_organic_keywords >= 0",
            name="ck_marketing_seo_competitor_keywords_nonnegative",
        ),
        sa.CheckConstraint(
            "competitor_estimated_traffic IS NULL "
            "OR competitor_estimated_traffic >= 0",
            name="ck_marketing_seo_competitor_traffic_nonnegative",
        ),
    )

    op.create_index(
        "ix_marketing_seo_competitor_snapshots_site_id",
        "marketing_seo_competitor_snapshots",
        ["site_id"],
    )
    op.create_index(
        "ix_marketing_seo_competitor_snapshots_domain",
        "marketing_seo_competitor_snapshots",
        ["normalized_domain"],
    )
    op.create_index(
        "ix_marketing_seo_competitor_snapshots_captured_date",
        "marketing_seo_competitor_snapshots",
        ["captured_date"],
    )
    op.create_index(
        "ix_marketing_seo_competitor_snapshots_provider",
        "marketing_seo_competitor_snapshots",
        ["provider"],
    )


def downgrade() -> None:
    op.drop_table("marketing_seo_competitor_snapshots")
    op.drop_table("marketing_seo_organic_keyword_snapshots")
    op.drop_table("marketing_seo_domain_snapshots")
    op.drop_table("marketing_seo_provider_runs")
