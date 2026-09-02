"""phase 3.2 scheduling

Revision ID: c8f4a2e7b3d1
Revises: b7e2c4d9a1f8
Create Date: 2026-07-31 04:40:00.000000

Creates Phase 3.2 scheduling tables. Every user/client FK is nullable so
legacy Mongo rows with orphaned refs can still be preserved via the
`legacy_*` breadcrumb columns.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c8f4a2e7b3d1"
down_revision: Union[str, Sequence[str], None] = "b7e2c4d9a1f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "emr_appointments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("client_id", sa.String(64),
                  sa.ForeignKey("emr_clients.id", ondelete="SET NULL"),
                  nullable=True, index=True),
        sa.Column("practitioner_id", sa.String(64),
                  sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
                  nullable=True, index=True),
        sa.Column("created_by", sa.String(64),
                  sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("service", sa.String(200), nullable=True),
        sa.Column("status", sa.String(32), nullable=False,
                  server_default="confirmed"),
        sa.Column("visit_mode", sa.String(32), nullable=False,
                  server_default="in_person"),
        sa.Column("consent_telehealth", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("series_id", sa.String(64), nullable=True),
        sa.Column("series_pattern", sa.String(32), nullable=True),
        sa.Column("telehealth", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True),
        sa.Column("waiting_room", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True),
        sa.Column("recordings", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True),
        sa.Column("transaction_id", sa.String(64), nullable=True),
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("legacy_mongo_id", sa.String(64), nullable=True),
        sa.Column("legacy_client_id", sa.String(64), nullable=True),
        sa.Column("legacy_practitioner_id", sa.String(64), nullable=True),
        sa.Column("legacy_created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_emr_appointments_start", "emr_appointments", ["start"])
    op.create_index("ix_emr_appointments_status", "emr_appointments", ["status"])
    op.create_index("ix_emr_appointments_series", "emr_appointments", ["series_id"])
    op.create_index("ix_emr_appointments_prac_start", "emr_appointments",
                     ["practitioner_id", "start"])
    op.create_index("ix_emr_appointments_client_start", "emr_appointments",
                     ["client_id", "start"])

    op.create_table(
        "emr_appointment_requests",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(320), nullable=True, index=True),
        sa.Column("phone", sa.String(40), nullable=True),
        sa.Column("returning", sa.String(16), nullable=True),
        sa.Column("service", sa.String(200), nullable=True),
        sa.Column("date", sa.String(32), nullable=True),
        sa.Column("time", sa.String(32), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("add_ons", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True),
        sa.Column("status", sa.String(32), nullable=False,
                  server_default="new"),
        sa.Column("decline_reason", sa.String(), nullable=True),
        sa.Column("suggested_time", sa.String(64), nullable=True),
        sa.Column("reviewed_by", sa.String(64),
                  sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("legacy_mongo_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_emr_appointment_requests_status",
                     "emr_appointment_requests", ["status"])
    op.create_index("ix_emr_appointment_requests_created_at",
                     "emr_appointment_requests", ["created_at"])

    op.create_table(
        "emr_availability",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("practitioner_id", sa.String(64),
                  sa.ForeignKey("auth_users.id", ondelete="CASCADE"),
                  nullable=True, index=True),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.String(8), nullable=False),
        sa.Column("end_time", sa.String(8), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("legacy_mongo_id", sa.String(64), nullable=True),
        sa.Column("legacy_practitioner_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_emr_availability_prac_wd",
                     "emr_availability", ["practitioner_id", "weekday"])

    op.create_table(
        "emr_reminders",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("appointment_id", sa.String(64),
                  sa.ForeignKey("emr_appointments.id", ondelete="CASCADE"),
                  nullable=True, index=True),
        sa.Column("client_id", sa.String(64),
                  sa.ForeignKey("emr_clients.id", ondelete="SET NULL"),
                  nullable=True, index=True),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default="scheduled"),
        sa.Column("legacy_mongo_id", sa.String(64), nullable=True),
        sa.Column("legacy_appointment_id", sa.String(64), nullable=True),
        sa.Column("legacy_client_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_emr_reminders_status_due",
                     "emr_reminders", ["status", "scheduled_at"])

    op.create_table(
        "emr_reminder_settings",
        sa.Column("id", sa.String(32), primary_key=True,
                  server_default="singleton"),
        sa.Column("appointment_reminder_hours_before", sa.Integer(),
                  nullable=False, server_default="24"),
        sa.Column("appointment_reminder_channels",
                  postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("follow_up_days_after", sa.Integer(), nullable=False,
                  server_default="7"),
        sa.Column("enabled", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("emr_reminder_settings")
    op.drop_table("emr_reminders")
    op.drop_table("emr_availability")
    op.drop_table("emr_appointment_requests")
    op.drop_table("emr_appointments")
