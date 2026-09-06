"""SEO intelligence phase 2: GSC completeness, keyword gap, backlinks, SERP
rank tracking, governed refresh schedules, organic keyword rank-change/ETV.

ADDITIVE ONLY. No table is dropped, truncated or rewritten. Existing GSC
metric snapshots and SEO provider snapshots are untouched. New nullable
columns on existing tables default to NULL (= unknown for historical rows).

Revision ID: a7c9e1f3b5d7
Revises: f5a7b9c1d3e5
Create Date: 2026-09-06 07:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a7c9e1f3b5d7"
down_revision = "f5a7b9c1d3e5"
branch_labels = None
depends_on = None


def _ts(name: str, **kw):
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
        **kw,
    )


def upgrade() -> None:
    # ---- 1. GSC sync-run completeness (historical rows stay NULL=unknown)
    op.add_column(
        "marketing_gsc_sync_runs",
        sa.Column("complete", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "marketing_gsc_sync_runs",
        sa.Column("pagination", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "marketing_gsc_sync_runs",
        sa.Column("pages_consumed", sa.Integer(), nullable=True),
    )
    op.add_column(
        "marketing_gsc_sync_runs",
        sa.Column("safety_ceiling_reached", sa.Boolean(), nullable=True),
    )

    # ---- 2. Organic keyword snapshots: provider rank change + per-keyword ETV
    op.add_column(
        "marketing_seo_organic_keyword_snapshots",
        sa.Column("previous_rank", sa.Integer(), nullable=True),
    )
    op.add_column(
        "marketing_seo_organic_keyword_snapshots",
        sa.Column("rank_change", sa.Integer(), nullable=True),
    )
    op.add_column(
        "marketing_seo_organic_keyword_snapshots",
        sa.Column("estimated_traffic", sa.Numeric(14, 4), nullable=True),
    )

    # ---- 3. Keyword gap (DataForSEO Labs domain_intersection)
    op.create_table(
        "marketing_seo_keyword_gap_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "site_id", sa.String(length=36),
            sa.ForeignKey("marketing_search_sites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "provider_run_id", sa.String(length=36),
            sa.ForeignKey("marketing_seo_provider_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(length=64), nullable=False,
                  server_default="dataforseo"),
        sa.Column("captured_date", sa.Date(), nullable=False),
        sa.Column("target_domain", sa.String(length=255), nullable=False),
        sa.Column("competitor_domain", sa.String(length=255), nullable=False),
        sa.Column("keyword", sa.String(length=512), nullable=False),
        sa.Column("normalized_keyword", sa.String(length=512), nullable=False),
        sa.Column("gap_type", sa.String(length=32), nullable=False),
        sa.Column("target_rank", sa.Integer(), nullable=True),
        sa.Column("competitor_rank", sa.Integer(), nullable=True),
        sa.Column("target_url", sa.Text(), nullable=True),
        sa.Column("competitor_url", sa.Text(), nullable=True),
        sa.Column("target_etv", sa.Numeric(14, 4), nullable=True),
        sa.Column("competitor_etv", sa.Numeric(14, 4), nullable=True),
        sa.Column("search_volume", sa.Integer(), nullable=True),
        sa.Column("cpc", sa.Numeric(12, 4), nullable=True),
        sa.Column("intent", sa.String(length=32), nullable=True),
        sa.Column("keyword_difficulty", sa.Integer(), nullable=True),
        sa.Column("location", sa.String(length=128), nullable=False,
                  server_default="United States"),
        sa.Column("language", sa.String(length=64), nullable=False,
                  server_default="English"),
        sa.Column("device", sa.String(length=32), nullable=False,
                  server_default="desktop"),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint(
            "site_id", "competitor_domain", "normalized_keyword",
            "captured_date", "provider", "location", "language", "device",
            name="uq_seo_keyword_gap_snapshot",
        ),
        sa.CheckConstraint(
            "gap_type IN ('shared','missing','untapped','weak','strong')",
            name="ck_seo_keyword_gap_type",
        ),
    )
    op.create_index(
        "ix_seo_keyword_gap_site_comp_date",
        "marketing_seo_keyword_gap_snapshots",
        ["site_id", "competitor_domain", "captured_date"],
    )
    op.create_index(
        "ix_seo_keyword_gap_site_type",
        "marketing_seo_keyword_gap_snapshots",
        ["site_id", "gap_type"],
    )

    # ---- 4. Backlink summary snapshots (DataForSEO Backlinks summary)
    op.create_table(
        "marketing_seo_backlink_summary_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "site_id", sa.String(length=36),
            sa.ForeignKey("marketing_search_sites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "provider_run_id", sa.String(length=36),
            sa.ForeignKey("marketing_seo_provider_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(length=64), nullable=False,
                  server_default="dataforseo"),
        sa.Column("captured_date", sa.Date(), nullable=False),
        sa.Column("target", sa.String(length=255), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("backlinks", sa.BigInteger(), nullable=True),
        sa.Column("referring_domains", sa.BigInteger(), nullable=True),
        sa.Column("referring_main_domains", sa.BigInteger(), nullable=True),
        sa.Column("referring_pages", sa.BigInteger(), nullable=True),
        sa.Column("referring_ips", sa.BigInteger(), nullable=True),
        sa.Column("referring_domains_nofollow", sa.BigInteger(), nullable=True),
        sa.Column("dofollow_links", sa.BigInteger(), nullable=True),
        sa.Column("nofollow_links", sa.BigInteger(), nullable=True),
        sa.Column("broken_backlinks", sa.BigInteger(), nullable=True),
        sa.Column("broken_pages", sa.BigInteger(), nullable=True),
        sa.Column("backlinks_spam_score", sa.Integer(), nullable=True),
        sa.Column("crawled_pages", sa.BigInteger(), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lost_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("referring_links_types", postgresql.JSONB(), nullable=True),
        sa.Column("referring_links_attributes", postgresql.JSONB(), nullable=True),
        sa.Column("referring_links_tld", postgresql.JSONB(), nullable=True),
        sa.Column("referring_links_countries", postgresql.JSONB(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint(
            "site_id", "target", "captured_date", "provider",
            name="uq_seo_backlink_summary_snapshot",
        ),
    )

    # ---- 5. Individual backlink snapshots (sampled pages of backlinks/live)
    op.create_table(
        "marketing_seo_backlink_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "site_id", sa.String(length=36),
            sa.ForeignKey("marketing_search_sites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "provider_run_id", sa.String(length=36),
            sa.ForeignKey("marketing_seo_provider_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(length=64), nullable=False,
                  server_default="dataforseo"),
        sa.Column("captured_date", sa.Date(), nullable=False),
        sa.Column("target", sa.String(length=255), nullable=False),
        sa.Column("backlink_key", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_domain", sa.String(length=255), nullable=True),
        sa.Column("target_url", sa.Text(), nullable=True),
        sa.Column("anchor", sa.Text(), nullable=True),
        sa.Column("item_type", sa.String(length=32), nullable=True),
        sa.Column("dofollow", sa.Boolean(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(), nullable=True),
        sa.Column("is_new", sa.Boolean(), nullable=True),
        sa.Column("is_lost", sa.Boolean(), nullable=True),
        sa.Column("is_broken", sa.Boolean(), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prev_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("domain_from_rank", sa.Integer(), nullable=True),
        sa.Column("page_from_rank", sa.Integer(), nullable=True),
        sa.Column("backlink_spam_score", sa.Integer(), nullable=True),
        sa.Column("domain_from_platform_type", postgresql.JSONB(), nullable=True),
        sa.Column("semantic_location", sa.String(length=64), nullable=True),
        sa.Column("url_to_status_code", sa.Integer(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint(
            "site_id", "target", "backlink_key", "captured_date", "provider",
            name="uq_seo_backlink_snapshot",
        ),
    )
    op.create_index(
        "ix_seo_backlink_site_date",
        "marketing_seo_backlink_snapshots",
        ["site_id", "captured_date"],
    )

    # ---- 6. Tracked keywords for live SERP position tracking
    op.create_table(
        "marketing_seo_tracked_keywords",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "site_id", sa.String(length=36),
            sa.ForeignKey("marketing_search_sites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("keyword", sa.String(length=512), nullable=False),
        sa.Column("normalized_keyword", sa.String(length=512), nullable=False),
        sa.Column("target_domain", sa.String(length=255), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=True),
        sa.Column("location", sa.String(length=128), nullable=False,
                  server_default="United States"),
        sa.Column("language", sa.String(length=64), nullable=False,
                  server_default="English"),
        sa.Column("device", sa.String(length=32), nullable=False,
                  server_default="desktop"),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("tags", postgresql.JSONB(), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint(
            "site_id", "normalized_keyword", "location", "language", "device",
            name="uq_seo_tracked_keyword",
        ),
        sa.CheckConstraint(
            "device IN ('desktop','mobile')", name="ck_seo_tracked_device"
        ),
    )

    # ---- 7. Rank observations (one row per live SERP check; historical)
    op.create_table(
        "marketing_seo_rank_observations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "site_id", sa.String(length=36),
            sa.ForeignKey("marketing_search_sites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tracked_keyword_id", sa.String(length=36),
            sa.ForeignKey("marketing_seo_tracked_keywords.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "provider_run_id", sa.String(length=36),
            sa.ForeignKey("marketing_seo_provider_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(length=64), nullable=False,
                  server_default="dataforseo"),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_date", sa.Date(), nullable=False),
        sa.Column("keyword", sa.String(length=512), nullable=False),
        sa.Column("location", sa.String(length=128), nullable=False),
        sa.Column("language", sa.String(length=64), nullable=False),
        sa.Column("device", sa.String(length=32), nullable=False),
        sa.Column("found", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("rank_group", sa.Integer(), nullable=True),
        sa.Column("ranking_url", sa.Text(), nullable=True),
        sa.Column("ranking_domain", sa.String(length=255), nullable=True),
        sa.Column("serp_item_type", sa.String(length=64), nullable=True),
        sa.Column("serp_features", postgresql.JSONB(), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=True),
        sa.Column("se_results_count", sa.BigInteger(), nullable=True),
        sa.Column("check_url", sa.Text(), nullable=True),
        sa.Column("provider_datetime", sa.String(length=64), nullable=True),
        _ts("created_at"),
    )
    op.create_index(
        "ix_seo_rank_obs_keyword_time",
        "marketing_seo_rank_observations",
        ["tracked_keyword_id", "observed_at"],
    )
    op.create_index(
        "ix_seo_rank_obs_site_date",
        "marketing_seo_rank_observations",
        ["site_id", "captured_date"],
    )

    # ---- 8. Governed automatic refresh schedules (disabled by default)
    op.create_table(
        "marketing_seo_refresh_schedules",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "site_id", sa.String(length=36),
            sa.ForeignKey("marketing_search_sites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=64), nullable=False,
                  server_default="dataforseo"),
        sa.Column("report_type", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("cadence_hours", sa.Integer(), nullable=False,
                  server_default="168"),
        sa.Column("limit_per_page", sa.Integer(), nullable=False,
                  server_default="1000"),
        sa.Column("max_pages", sa.Integer(), nullable=False,
                  server_default="2"),
        sa.Column("max_requests", sa.Integer(), nullable=False,
                  server_default="2"),
        sa.Column("max_total_cost", sa.Numeric(10, 4), nullable=False,
                  server_default="0.50"),
        sa.Column("retry_ceiling", sa.Integer(), nullable=False,
                  server_default="2"),
        sa.Column("options", postgresql.JSONB(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=32), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_provider_run_id", sa.String(length=36), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint(
            "site_id", "provider", "report_type",
            name="uq_seo_refresh_schedule",
        ),
        sa.CheckConstraint("cadence_hours >= 24", name="ck_seo_sched_cadence"),
        sa.CheckConstraint(
            "max_pages >= 1 AND max_pages <= 20", name="ck_seo_sched_pages"
        ),
        sa.CheckConstraint(
            "max_total_cost > 0 AND max_total_cost <= 25",
            name="ck_seo_sched_cost",
        ),
    )


def downgrade() -> None:
    op.drop_table("marketing_seo_refresh_schedules")
    op.drop_index("ix_seo_rank_obs_site_date", "marketing_seo_rank_observations")
    op.drop_index("ix_seo_rank_obs_keyword_time", "marketing_seo_rank_observations")
    op.drop_table("marketing_seo_rank_observations")
    op.drop_table("marketing_seo_tracked_keywords")
    op.drop_index("ix_seo_backlink_site_date", "marketing_seo_backlink_snapshots")
    op.drop_table("marketing_seo_backlink_snapshots")
    op.drop_table("marketing_seo_backlink_summary_snapshots")
    op.drop_index("ix_seo_keyword_gap_site_type", "marketing_seo_keyword_gap_snapshots")
    op.drop_index("ix_seo_keyword_gap_site_comp_date", "marketing_seo_keyword_gap_snapshots")
    op.drop_table("marketing_seo_keyword_gap_snapshots")
    for col in ("estimated_traffic", "rank_change", "previous_rank"):
        op.drop_column("marketing_seo_organic_keyword_snapshots", col)
    for col in ("safety_ceiling_reached", "pages_consumed", "pagination", "complete"):
        op.drop_column("marketing_gsc_sync_runs", col)
