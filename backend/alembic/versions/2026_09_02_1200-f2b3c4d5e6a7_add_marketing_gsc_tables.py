"""add marketing gsc (search console) tables

Revision ID: f2b3c4d5e6a7
Revises: e7f1a2b3c4d5
Create Date: 2026-09-02 12:00:00.000000

Google Search Console (read-only) normalized metrics + sync state
(marketing-only, non-PHI):
- marketing_gsc_sync_runs
- marketing_gsc_daily_metrics
- marketing_gsc_query_metrics
- marketing_gsc_page_metrics
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f2b3c4d5e6a7"
down_revision = "e7f1a2b3c4d5"
branch_labels = None
depends_on = None


def _ts_cols():
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )


def _metric_cols():
    return (
        sa.Column("clicks", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("impressions", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("ctr", sa.Numeric(9, 6), nullable=False,
                  server_default="0"),
        sa.Column("position", sa.Numeric(9, 3), nullable=True),
        sa.Column("device", sa.String(length=32), nullable=False,
                  server_default="all"),
        sa.Column("country", sa.String(length=16), nullable=False,
                  server_default="all"),
        sa.Column("source", sa.String(length=64), nullable=False,
                  server_default="google_search_console"),
    )


def upgrade() -> None:
    op.create_table(
        "marketing_gsc_sync_runs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("site_id", sa.String(length=64),
                  sa.ForeignKey("marketing_search_sites.id",
                                ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False,
                  server_default="completed"),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("rows_synced", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("source", sa.String(length=64), nullable=False,
                  server_default="google_search_console"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=64),
                  sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
                  nullable=True),
        *_ts_cols(),
    )
    op.create_index("ix_marketing_gsc_sync_runs_site_id",
                    "marketing_gsc_sync_runs", ["site_id"])
    op.create_index("ix_marketing_gsc_sync_runs_status",
                    "marketing_gsc_sync_runs", ["status"])

    op.create_table(
        "marketing_gsc_daily_metrics",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("site_id", sa.String(length=64),
                  sa.ForeignKey("marketing_search_sites.id",
                                ondelete="CASCADE"), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        *_metric_cols(),
        *_ts_cols(),
        sa.UniqueConstraint("site_id", "metric_date", "device", "country",
                            "source", name="uq_marketing_gsc_daily_scope"),
    )
    op.create_index("ix_marketing_gsc_daily_metrics_site_id",
                    "marketing_gsc_daily_metrics", ["site_id"])
    op.create_index("ix_marketing_gsc_daily_metrics_metric_date",
                    "marketing_gsc_daily_metrics", ["metric_date"])

    op.create_table(
        "marketing_gsc_query_metrics",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("site_id", sa.String(length=64),
                  sa.ForeignKey("marketing_search_sites.id",
                                ondelete="CASCADE"), nullable=False),
        sa.Column("captured_date", sa.Date(), nullable=False),
        sa.Column("query", sa.String(length=512), nullable=False),
        sa.Column("normalized_query", sa.String(length=512), nullable=False),
        *_metric_cols(),
        *_ts_cols(),
        sa.UniqueConstraint("site_id", "captured_date", "normalized_query",
                            "device", "country", "source",
                            name="uq_marketing_gsc_query_scope"),
    )
    op.create_index("ix_marketing_gsc_query_metrics_site_id",
                    "marketing_gsc_query_metrics", ["site_id"])
    op.create_index("ix_marketing_gsc_query_metrics_captured_date",
                    "marketing_gsc_query_metrics", ["captured_date"])
    op.create_index("ix_marketing_gsc_query_metrics_normalized_query",
                    "marketing_gsc_query_metrics", ["normalized_query"])

    op.create_table(
        "marketing_gsc_page_metrics",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("site_id", sa.String(length=64),
                  sa.ForeignKey("marketing_search_sites.id",
                                ondelete="CASCADE"), nullable=False),
        sa.Column("captured_date", sa.Date(), nullable=False),
        sa.Column("page", sa.Text(), nullable=False),
        *_metric_cols(),
        *_ts_cols(),
        sa.UniqueConstraint("site_id", "captured_date", "page", "device",
                            "country", "source",
                            name="uq_marketing_gsc_page_scope"),
    )
    op.create_index("ix_marketing_gsc_page_metrics_site_id",
                    "marketing_gsc_page_metrics", ["site_id"])
    op.create_index("ix_marketing_gsc_page_metrics_captured_date",
                    "marketing_gsc_page_metrics", ["captured_date"])


def downgrade() -> None:
    op.drop_table("marketing_gsc_page_metrics")
    op.drop_table("marketing_gsc_query_metrics")
    op.drop_table("marketing_gsc_daily_metrics")
    op.drop_table("marketing_gsc_sync_runs")
