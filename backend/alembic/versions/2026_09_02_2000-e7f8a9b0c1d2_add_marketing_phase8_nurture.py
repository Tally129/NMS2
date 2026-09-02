"""add marketing phase8 nurture + appointment recovery engine

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-09-02 20:00:00.000000

Phase 8A. Privacy-minimized marketing domain only:
- no emr_clients / patient / clinical foreign keys;
- no recipient (email/phone) columns;
- opaque marketing_subject_id only;
- auth_users FKs only (internal staff), consistent with existing Marketing OS.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision = "e7f8a9b0c1d2"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def _ts():
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
    # ------------------------------------------------------------------ #
    # marketing_nurture_sequences
    # ------------------------------------------------------------------ #
    op.create_table(
        "marketing_nurture_sequences",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(160), nullable=False),
        sa.Column(
            "status", sa.String(32), nullable=False, server_default="draft"
        ),
        sa.Column(
            "trigger_type",
            sa.String(48),
            nullable=False,
            server_default="manual",
        ),
        sa.Column(
            "trigger_config",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "stop_on_statuses",
            JSONB,
            nullable=False,
            server_default=sa.text(
                "'[\"booked\", \"confirmed\", \"showed\", \"won\", "
                "\"lost\"]'::jsonb"
            ),
        ),
        sa.Column(
            "audience_config",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_by",
            sa.String(64),
            sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_ts(),
    )
    op.create_index(
        "ix_marketing_nurture_sequences_slug",
        "marketing_nurture_sequences",
        ["slug"],
        unique=True,
    )
    op.create_index(
        "ix_marketing_nurture_sequences_status",
        "marketing_nurture_sequences",
        ["status"],
    )
    op.create_index(
        "ix_marketing_nurture_sequences_trigger_type",
        "marketing_nurture_sequences",
        ["trigger_type"],
    )

    # ------------------------------------------------------------------ #
    # marketing_nurture_steps
    # ------------------------------------------------------------------ #
    op.create_table(
        "marketing_nurture_steps",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "sequence_id",
            sa.String(64),
            sa.ForeignKey(
                "marketing_nurture_sequences.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column("step_key", sa.String(96), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(48), nullable=False),
        sa.Column(
            "channel", sa.String(32), nullable=False, server_default="internal"
        ),
        sa.Column(
            "delay_minutes", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("subject", sa.String(200), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column(
            "config",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *_ts(),
        sa.UniqueConstraint(
            "sequence_id", "step_key", name="uq_marketing_nurture_steps_key"
        ),
    )
    op.create_index(
        "ix_marketing_nurture_steps_sequence_id",
        "marketing_nurture_steps",
        ["sequence_id"],
    )
    op.create_index(
        "ix_marketing_nurture_steps_action_type",
        "marketing_nurture_steps",
        ["action_type"],
    )

    # ------------------------------------------------------------------ #
    # marketing_nurture_enrollments
    # ------------------------------------------------------------------ #
    op.create_table(
        "marketing_nurture_enrollments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "sequence_id",
            sa.String(64),
            sa.ForeignKey(
                "marketing_nurture_sequences.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            sa.String(64),
            sa.ForeignKey("marketing_leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("marketing_subject_id", sa.String(128), nullable=False),
        sa.Column(
            "status", sa.String(32), nullable=False, server_default="active"
        ),
        sa.Column(
            "current_step_position",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "enrolled_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stop_reason", sa.String(160), nullable=True),
        sa.Column(
            "enrolled_by",
            sa.String(64),
            sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "metadata",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *_ts(),
    )
    op.create_index(
        "ix_marketing_nurture_enrollments_sequence_id",
        "marketing_nurture_enrollments",
        ["sequence_id"],
    )
    op.create_index(
        "ix_marketing_nurture_enrollments_lead_id",
        "marketing_nurture_enrollments",
        ["lead_id"],
    )
    op.create_index(
        "ix_marketing_nurture_enrollments_subject",
        "marketing_nurture_enrollments",
        ["marketing_subject_id"],
    )
    op.create_index(
        "ix_marketing_nurture_enrollments_status",
        "marketing_nurture_enrollments",
        ["status"],
    )
    op.create_index(
        "ix_marketing_nurture_enrollments_next_run_at",
        "marketing_nurture_enrollments",
        ["next_run_at"],
    )
    # Only one ACTIVE enrollment per (sequence, lead).
    op.create_index(
        "uq_marketing_nurture_enrollments_active",
        "marketing_nurture_enrollments",
        ["sequence_id", "lead_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    # ------------------------------------------------------------------ #
    # marketing_nurture_actions
    # ------------------------------------------------------------------ #
    op.create_table(
        "marketing_nurture_actions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "enrollment_id",
            sa.String(64),
            sa.ForeignKey(
                "marketing_nurture_enrollments.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column(
            "sequence_id",
            sa.String(64),
            sa.ForeignKey(
                "marketing_nurture_sequences.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column(
            "step_id",
            sa.String(64),
            sa.ForeignKey("marketing_nurture_steps.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            sa.String(64),
            sa.ForeignKey("marketing_leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("marketing_subject_id", sa.String(128), nullable=False),
        sa.Column("action_type", sa.String(48), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="pending_approval",
        ),
        sa.Column(
            "approval_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "approved_by",
            sa.String(64),
            sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_status", sa.String(48), nullable=True),
        sa.Column("hold_reason", sa.String(160), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("subject", sa.String(200), nullable=True),
        sa.Column(
            "preview",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("lead_task_id", sa.String(64), nullable=True),
        *_ts(),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_marketing_nurture_actions_idem"
        ),
    )
    op.create_index(
        "ix_marketing_nurture_actions_enrollment_id",
        "marketing_nurture_actions",
        ["enrollment_id"],
    )
    op.create_index(
        "ix_marketing_nurture_actions_sequence_id",
        "marketing_nurture_actions",
        ["sequence_id"],
    )
    op.create_index(
        "ix_marketing_nurture_actions_step_id",
        "marketing_nurture_actions",
        ["step_id"],
    )
    op.create_index(
        "ix_marketing_nurture_actions_lead_id",
        "marketing_nurture_actions",
        ["lead_id"],
    )
    op.create_index(
        "ix_marketing_nurture_actions_subject",
        "marketing_nurture_actions",
        ["marketing_subject_id"],
    )
    op.create_index(
        "ix_marketing_nurture_actions_status",
        "marketing_nurture_actions",
        ["status"],
    )
    op.create_index(
        "ix_marketing_nurture_actions_scheduled_at",
        "marketing_nurture_actions",
        ["scheduled_at"],
    )


def downgrade() -> None:
    op.drop_table("marketing_nurture_actions")
    op.drop_table("marketing_nurture_enrollments")
    op.drop_table("marketing_nurture_steps")
    op.drop_table("marketing_nurture_sequences")
