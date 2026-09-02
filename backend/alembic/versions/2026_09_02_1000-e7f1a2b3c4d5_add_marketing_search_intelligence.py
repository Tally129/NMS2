"""add marketing search intelligence

Revision ID: e7f1a2b3c4d5
Revises: c133fd9fc54c
Create Date: 2026-09-02 10:00:00.000000

Search Intelligence foundation (marketing-only, non-PHI):
- marketing_search_sites
- marketing_search_keywords
- marketing_keyword_rank_snapshots
- marketing_site_audit_runs
- marketing_site_audit_issues
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "e7f1a2b3c4d5"
down_revision = "c133fd9fc54c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketing_search_sites",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("site_url", sa.String(length=512), nullable=False),
        sa.Column("normalized_url", sa.String(length=512), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_by",
            sa.String(length=64),
            sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        sa.UniqueConstraint(
            "normalized_url",
            name="uq_marketing_search_sites_normalized_url",
        ),
    )
    op.create_index(
        "ix_marketing_search_sites_normalized_url",
        "marketing_search_sites",
        ["normalized_url"],
    )

    op.create_table(
        "marketing_search_keywords",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "site_id",
            sa.String(length=64),
            sa.ForeignKey("marketing_search_sites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("keyword", sa.String(length=255), nullable=False),
        sa.Column(
            "normalized_keyword", sa.String(length=255), nullable=False
        ),
        sa.Column(
            "intent",
            sa.String(length=32),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("search_volume", sa.BigInteger(), nullable=True),
        sa.Column("keyword_difficulty", sa.Integer(), nullable=True),
        sa.Column("cpc", sa.Numeric(18, 4), nullable=True),
        sa.Column(
            "location",
            sa.String(length=128),
            nullable=False,
            server_default="global",
        ),
        sa.Column(
            "device",
            sa.String(length=32),
            nullable=False,
            server_default="desktop",
        ),
        sa.Column(
            "source",
            sa.String(length=64),
            nullable=False,
            server_default="manual",
        ),
        sa.Column(
            "is_tracked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_by",
            sa.String(length=64),
            sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        sa.UniqueConstraint(
            "site_id",
            "normalized_keyword",
            "location",
            "device",
            name="uq_marketing_search_keyword_scope",
        ),
        sa.CheckConstraint(
            "keyword_difficulty IS NULL OR "
            "(keyword_difficulty >= 0 AND keyword_difficulty <= 100)",
            name="ck_marketing_search_keyword_difficulty",
        ),
    )
    op.create_index(
        "ix_marketing_search_keywords_site_id",
        "marketing_search_keywords",
        ["site_id"],
    )
    op.create_index(
        "ix_marketing_search_keywords_normalized_keyword",
        "marketing_search_keywords",
        ["normalized_keyword"],
    )
    op.create_index(
        "ix_marketing_search_keywords_intent",
        "marketing_search_keywords",
        ["intent"],
    )
    op.create_index(
        "ix_marketing_search_keywords_source",
        "marketing_search_keywords",
        ["source"],
    )
    op.create_index(
        "ix_marketing_search_keywords_is_tracked",
        "marketing_search_keywords",
        ["is_tracked"],
    )

    op.create_table(
        "marketing_keyword_rank_snapshots",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "keyword_id",
            sa.String(length=64),
            sa.ForeignKey(
                "marketing_search_keywords.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column("current_rank", sa.Integer(), nullable=True),
        sa.Column("ranking_url", sa.Text(), nullable=True),
        sa.Column(
            "serp_features",
            JSONB,
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "source",
            sa.String(length=64),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("captured_date", sa.Date(), nullable=False),
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
        sa.UniqueConstraint(
            "keyword_id",
            "captured_date",
            "source",
            name="uq_marketing_keyword_rank_snapshot_scope",
        ),
        sa.CheckConstraint(
            "current_rank IS NULL OR current_rank >= 1",
            name="ck_marketing_keyword_rank_positive",
        ),
    )
    op.create_index(
        "ix_marketing_keyword_rank_snapshots_keyword_id",
        "marketing_keyword_rank_snapshots",
        ["keyword_id"],
    )
    op.create_index(
        "ix_marketing_keyword_rank_snapshots_captured_date",
        "marketing_keyword_rank_snapshots",
        ["captured_date"],
    )

    op.create_table(
        "marketing_site_audit_runs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "site_id",
            sa.String(length=64),
            sa.ForeignKey("marketing_search_sites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="completed",
        ),
        sa.Column(
            "pages_scanned",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "issues_total",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "critical_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "warning_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "opportunity_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "informational_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "summary",
            JSONB,
            nullable=False,
            server_default="{}",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by",
            sa.String(length=64),
            sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
    op.create_index(
        "ix_marketing_site_audit_runs_site_id",
        "marketing_site_audit_runs",
        ["site_id"],
    )
    op.create_index(
        "ix_marketing_site_audit_runs_status",
        "marketing_site_audit_runs",
        ["status"],
    )

    op.create_table(
        "marketing_site_audit_issues",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey(
                "marketing_site_audit_runs.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("issue_code", sa.String(length=64), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column(
            "details",
            JSONB,
            nullable=False,
            server_default="{}",
        ),
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
        sa.CheckConstraint(
            "severity IN "
            "('critical', 'warning', 'opportunity', 'informational')",
            name="ck_marketing_site_audit_issue_severity",
        ),
    )
    op.create_index(
        "ix_marketing_site_audit_issues_run_id",
        "marketing_site_audit_issues",
        ["run_id"],
    )
    op.create_index(
        "ix_marketing_site_audit_issues_severity",
        "marketing_site_audit_issues",
        ["severity"],
    )
    op.create_index(
        "ix_marketing_site_audit_issues_issue_code",
        "marketing_site_audit_issues",
        ["issue_code"],
    )


def downgrade() -> None:
    op.drop_table("marketing_site_audit_issues")
    op.drop_table("marketing_site_audit_runs")
    op.drop_table("marketing_keyword_rank_snapshots")
    op.drop_table("marketing_search_keywords")
    op.drop_table("marketing_search_sites")
