"""add marketing phase9 experimentation

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-09-02 21:00:00.000000

Phase 9 — conversion optimization + experimentation. Marketing domain only:
no emr/patient/client/clinical FKs; opaque marketing_subject_id only; FKs to
internal/marketing tables only.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "f8a9b0c1d2e3"
down_revision = "e7f8a9b0c1d2"
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
        "marketing_experiments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(160), nullable=False),
        sa.Column("experiment_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False,
                  server_default="draft"),
        sa.Column("primary_metric", sa.String(48), nullable=False,
                  server_default="conversion"),
        sa.Column("exposure_metric", sa.String(48), nullable=False,
                  server_default="impression"),
        sa.Column("hypothesis", sa.Text(), nullable=True),
        sa.Column("funnel_id", sa.String(64),
                  sa.ForeignKey("marketing_funnels.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("config", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(64),
                  sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
                  nullable=True),
        *_ts(),
    )
    op.create_index("ix_marketing_experiments_slug", "marketing_experiments",
                    ["slug"], unique=True)
    op.create_index("ix_marketing_experiments_status", "marketing_experiments",
                    ["status"])
    op.create_index("ix_marketing_experiments_type", "marketing_experiments",
                    ["experiment_type"])

    op.create_table(
        "marketing_experiment_variants",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("experiment_id", sa.String(64),
                  sa.ForeignKey("marketing_experiments.id",
                                ondelete="CASCADE"), nullable=False),
        sa.Column("variant_key", sa.String(96), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("is_control", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("allocation_pct", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("offer_id", sa.String(64),
                  sa.ForeignKey("marketing_offers.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("funnel_step_id", sa.String(64),
                  sa.ForeignKey("marketing_funnel_steps.id",
                                ondelete="SET NULL"), nullable=True),
        sa.Column("config", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        *_ts(),
        sa.UniqueConstraint("experiment_id", "variant_key",
                            name="uq_marketing_experiment_variants_key"),
    )
    op.create_index("ix_marketing_experiment_variants_exp",
                    "marketing_experiment_variants", ["experiment_id"])

    op.create_table(
        "marketing_experiment_assignments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("experiment_id", sa.String(64),
                  sa.ForeignKey("marketing_experiments.id",
                                ondelete="CASCADE"), nullable=False),
        sa.Column("variant_id", sa.String(64),
                  sa.ForeignKey("marketing_experiment_variants.id",
                                ondelete="CASCADE"), nullable=False),
        sa.Column("marketing_subject_id", sa.String(128), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        *_ts(),
        sa.UniqueConstraint("experiment_id", "marketing_subject_id",
                            name="uq_marketing_experiment_assignments_subject"),
    )
    op.create_index("ix_marketing_experiment_assignments_exp",
                    "marketing_experiment_assignments", ["experiment_id"])
    op.create_index("ix_marketing_experiment_assignments_variant",
                    "marketing_experiment_assignments", ["variant_id"])
    op.create_index("ix_marketing_experiment_assignments_subject",
                    "marketing_experiment_assignments",
                    ["marketing_subject_id"])

    op.create_table(
        "marketing_experiment_outcomes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("experiment_id", sa.String(64),
                  sa.ForeignKey("marketing_experiments.id",
                                ondelete="CASCADE"), nullable=False),
        sa.Column("variant_id", sa.String(64),
                  sa.ForeignKey("marketing_experiment_variants.id",
                                ondelete="CASCADE"), nullable=False),
        sa.Column("assignment_id", sa.String(64),
                  sa.ForeignKey("marketing_experiment_assignments.id",
                                ondelete="SET NULL"), nullable=True),
        sa.Column("marketing_subject_id", sa.String(128), nullable=True),
        sa.Column("metric_type", sa.String(48), nullable=False),
        sa.Column("value", sa.Numeric(18, 4), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("source_event_id", sa.String(64),
                  sa.ForeignKey("marketing_conversion_events.id",
                                ondelete="SET NULL"), nullable=True),
        sa.Column("idempotency_key", sa.String(180), nullable=True),
        sa.Column("properties", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        *_ts(),
        sa.UniqueConstraint("idempotency_key",
                            name="uq_marketing_experiment_outcomes_idem"),
    )
    op.create_index("ix_marketing_experiment_outcomes_exp",
                    "marketing_experiment_outcomes", ["experiment_id"])
    op.create_index("ix_marketing_experiment_outcomes_variant",
                    "marketing_experiment_outcomes", ["variant_id"])
    op.create_index("ix_marketing_experiment_outcomes_metric",
                    "marketing_experiment_outcomes", ["metric_type"])
    op.create_index("ix_marketing_experiment_outcomes_subject",
                    "marketing_experiment_outcomes",
                    ["marketing_subject_id"])


def downgrade() -> None:
    op.drop_table("marketing_experiment_outcomes")
    op.drop_table("marketing_experiment_assignments")
    op.drop_table("marketing_experiment_variants")
    op.drop_table("marketing_experiments")
