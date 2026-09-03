"""add marketing phase10 reputation + local growth

Revision ID: a0b1c2d3e4f5
Revises: f8a9b0c1d2e3
Create Date: 2026-09-02 22:00:00.000000

Read-only local-growth intelligence. No emr/patient/client FKs; no review text.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "a0b1c2d3e4f5"
down_revision = "f8a9b0c1d2e3"
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
        "marketing_locations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("site_id", sa.String(64),
                  sa.ForeignKey("marketing_search_sites.id",
                                ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), nullable=False,
                  server_default="active"),
        sa.Column("address_line", sa.String(255), nullable=True),
        sa.Column("city", sa.String(128), nullable=True),
        sa.Column("state", sa.String(64), nullable=True),
        sa.Column("postal_code", sa.String(16), nullable=True),
        sa.Column("country", sa.String(64), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("website_url", sa.String(255), nullable=True),
        sa.Column("primary_category", sa.String(128), nullable=True),
        sa.Column("hours", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("config", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", sa.String(64),
                  sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
                  nullable=True),
        *_ts(),
    )
    op.create_index("ix_marketing_locations_slug", "marketing_locations",
                    ["slug"], unique=True)
    op.create_index("ix_marketing_locations_status", "marketing_locations",
                    ["status"])

    op.create_table(
        "marketing_reputation_sources",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("location_id", sa.String(64),
                  sa.ForeignKey("marketing_locations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("external_ref", sa.String(255), nullable=True),
        sa.Column("listing_url", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("config", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        *_ts(),
        sa.UniqueConstraint("location_id", "provider",
                            name="uq_marketing_reputation_sources"),
    )
    op.create_index("ix_marketing_reputation_sources_loc",
                    "marketing_reputation_sources", ["location_id"])

    op.create_table(
        "marketing_reputation_snapshots",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("location_id", sa.String(64),
                  sa.ForeignKey("marketing_locations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("source_id", sa.String(64),
                  sa.ForeignKey("marketing_reputation_sources.id",
                                ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("captured_date", sa.Date(), nullable=False),
        sa.Column("rating", sa.Numeric(3, 2), nullable=True),
        sa.Column("review_count", sa.Integer(), nullable=True),
        sa.Column("reviews_last_30d", sa.Integer(), nullable=True),
        sa.Column("response_rate", sa.Numeric(5, 4), nullable=True),
        sa.Column("avg_response_hours", sa.Numeric(10, 2), nullable=True),
        sa.Column("unanswered_count", sa.Integer(), nullable=True),
        sa.Column("metadata", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        *_ts(),
        sa.UniqueConstraint("source_id", "captured_date",
                            name="uq_marketing_reputation_snapshot"),
    )
    op.create_index("ix_marketing_reputation_snapshots_loc",
                    "marketing_reputation_snapshots", ["location_id"])
    op.create_index("ix_marketing_reputation_snapshots_src",
                    "marketing_reputation_snapshots", ["source_id"])
    op.create_index("ix_marketing_reputation_snapshots_date",
                    "marketing_reputation_snapshots", ["captured_date"])

    op.create_table(
        "marketing_local_listing_snapshots",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("location_id", sa.String(64),
                  sa.ForeignKey("marketing_locations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("source_id", sa.String(64),
                  sa.ForeignKey("marketing_reputation_sources.id",
                                ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("captured_date", sa.Date(), nullable=False),
        sa.Column("listing_status", sa.String(32), nullable=False,
                  server_default="unknown"),
        sa.Column("name_matches", sa.Boolean(), nullable=True),
        sa.Column("address_matches", sa.Boolean(), nullable=True),
        sa.Column("phone_matches", sa.Boolean(), nullable=True),
        sa.Column("category_matches", sa.Boolean(), nullable=True),
        sa.Column("website_matches", sa.Boolean(), nullable=True),
        sa.Column("hours_present", sa.Boolean(), nullable=True),
        sa.Column("fields_present", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        *_ts(),
        sa.UniqueConstraint("source_id", "captured_date",
                            name="uq_marketing_local_listing_snapshot"),
    )
    op.create_index("ix_marketing_local_listing_snapshots_loc",
                    "marketing_local_listing_snapshots", ["location_id"])
    op.create_index("ix_marketing_local_listing_snapshots_src",
                    "marketing_local_listing_snapshots", ["source_id"])
    op.create_index("ix_marketing_local_listing_snapshots_date",
                    "marketing_local_listing_snapshots", ["captured_date"])

    op.create_table(
        "marketing_local_opportunities",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("location_id", sa.String(64),
                  sa.ForeignKey("marketing_locations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("source_id", sa.String(64),
                  sa.ForeignKey("marketing_reputation_sources.id",
                                ondelete="SET NULL"), nullable=True),
        sa.Column("opportunity_key", sa.String(160), nullable=False),
        sa.Column("opportunity_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False,
                  server_default="medium"),
        sa.Column("priority", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False,
                  server_default="open"),
        sa.Column("evidence", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        *_ts(),
        sa.UniqueConstraint("location_id", "opportunity_key",
                            name="uq_marketing_local_opportunity"),
    )
    op.create_index("ix_marketing_local_opportunities_loc",
                    "marketing_local_opportunities", ["location_id"])
    op.create_index("ix_marketing_local_opportunities_type",
                    "marketing_local_opportunities", ["opportunity_type"])
    op.create_index("ix_marketing_local_opportunities_priority",
                    "marketing_local_opportunities", ["priority"])
    op.create_index("ix_marketing_local_opportunities_status",
                    "marketing_local_opportunities", ["status"])


def downgrade() -> None:
    op.drop_table("marketing_local_opportunities")
    op.drop_table("marketing_local_listing_snapshots")
    op.drop_table("marketing_reputation_snapshots")
    op.drop_table("marketing_reputation_sources")
    op.drop_table("marketing_locations")
