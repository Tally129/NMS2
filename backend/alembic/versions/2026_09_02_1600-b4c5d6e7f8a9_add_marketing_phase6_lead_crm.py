"""add marketing phase6 lead CRM tables

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-09-02 16:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "b4c5d6e7f8a9"
down_revision = "a3b4c5d6e7f8"
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
        "marketing_leads",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("marketing_subject_id", sa.String(128), nullable=False),
        sa.Column("source", sa.String(128), nullable=True),
        sa.Column("medium", sa.String(128), nullable=True),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("campaign_id", sa.String(255), nullable=True),
        sa.Column("campaign_name", sa.String(255), nullable=True),
        sa.Column("landing_page", sa.String(512), nullable=True),
        sa.Column("offer_id", sa.String(128), nullable=True),
        sa.Column("attribution_source", sa.String(128), nullable=True),
        sa.Column("attribution_model", sa.String(64), nullable=True),
        sa.Column("lead_status", sa.String(48), nullable=False,
                  server_default="new"),
        sa.Column("qualification_status", sa.String(48), nullable=False,
                  server_default="unqualified"),
        sa.Column("qualification_score", sa.Integer(), nullable=True),
        sa.Column("opportunity_score", sa.Integer(), nullable=True),
        sa.Column("priority", sa.String(16), nullable=False,
                  server_default="medium"),
        sa.Column("urgency", sa.String(32), nullable=True),
        sa.Column("service_interest", sa.String(160), nullable=True),
        sa.Column("preferred_location", sa.String(160), nullable=True),
        sa.Column("preferred_contact_window", sa.String(64), nullable=True),
        sa.Column("appointment_readiness", sa.String(48), nullable=True),
        sa.Column("assigned_owner_id", sa.String(64),
                  sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("next_action_type", sa.String(48), nullable=True),
        sa.Column("next_action_at", sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column("appointment_status", sa.String(48), nullable=True),
        sa.Column("lead_created_at", sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column("first_contact_attempt_at", sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column("first_contact_at", sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column("first_response_seconds", sa.Integer(), nullable=True),
        sa.Column("appointment_requested_at", sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column("booked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        *_ts(),
    )
    op.create_unique_constraint(
        "uq_marketing_leads_subject", "marketing_leads",
        ["marketing_subject_id"],
    )
    op.create_index("ix_marketing_leads_status", "marketing_leads",
                    ["lead_status"])
    op.create_index("ix_marketing_leads_priority", "marketing_leads",
                    ["priority"])
    op.create_index("ix_marketing_leads_owner", "marketing_leads",
                    ["assigned_owner_id"])
    op.create_index("ix_marketing_leads_appt", "marketing_leads",
                    ["appointment_status"])

    op.create_table(
        "marketing_lead_tasks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("lead_id", sa.String(64),
                  sa.ForeignKey("marketing_leads.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("task_type", sa.String(48), nullable=False),
        sa.Column("owner_id", sa.String(64),
                  sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False,
                  server_default="open"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(64),
                  sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
                  nullable=True),
        *_ts(),
    )
    op.create_index("ix_marketing_lead_tasks_lead", "marketing_lead_tasks",
                    ["lead_id"])
    op.create_index("ix_marketing_lead_tasks_owner", "marketing_lead_tasks",
                    ["owner_id"])
    op.create_index("ix_marketing_lead_tasks_status", "marketing_lead_tasks",
                    ["status"])
    op.create_index("ix_marketing_lead_tasks_due", "marketing_lead_tasks",
                    ["due_at"])

    op.create_table(
        "marketing_lead_assignments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("lead_id", sa.String(64),
                  sa.ForeignKey("marketing_leads.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("previous_owner_id", sa.String(64),
                  sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("new_owner_id", sa.String(64),
                  sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("assigned_by", sa.String(64),
                  sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        *_ts(),
    )
    op.create_index("ix_marketing_lead_assignments_lead",
                    "marketing_lead_assignments", ["lead_id"])

    op.create_table(
        "marketing_lead_activity",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("lead_id", sa.String(64),
                  sa.ForeignKey("marketing_leads.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("activity_type", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("actor_id", sa.String(64),
                  sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("details", JSONB, nullable=False, server_default="{}"),
        *_ts(),
    )
    op.create_index("ix_marketing_lead_activity_lead",
                    "marketing_lead_activity", ["lead_id"])
    op.create_index("ix_marketing_lead_activity_type",
                    "marketing_lead_activity", ["activity_type"])


def downgrade() -> None:
    op.drop_table("marketing_lead_activity")
    op.drop_table("marketing_lead_assignments")
    op.drop_table("marketing_lead_tasks")
    op.drop_table("marketing_leads")
