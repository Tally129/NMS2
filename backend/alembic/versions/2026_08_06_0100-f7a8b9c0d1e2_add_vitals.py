"""add visit-based vitals records

Revision ID: f7a8b9c0d1e2
Revises: 6609945b5e45
Create Date: 2026-08-06 01:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "6609945b5e45"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "emr_vitals",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column(
            "appointment_id",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "recorded_by_id",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "recorded_by_name",
            sa.String(length=200),
            nullable=True,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(length=40),
            server_default="staff_measured",
            nullable=False,
        ),
        sa.Column(
            "visit_mode",
            sa.String(length=30),
            server_default="in_person",
            nullable=False,
        ),
        sa.Column("systolic", sa.Integer(), nullable=True),
        sa.Column("diastolic", sa.Integer(), nullable=True),
        sa.Column("pulse", sa.Integer(), nullable=True),
        sa.Column(
            "respiratory_rate",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "temperature_f",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "oxygen_saturation",
            sa.Float(),
            nullable=True,
        ),
        sa.Column("height_in", sa.Float(), nullable=True),
        sa.Column("weight_lb", sa.Float(), nullable=True),
        sa.Column("bmi", sa.Float(), nullable=True),
        sa.Column("pain_score", sa.Integer(), nullable=True),
        sa.Column(
            "blood_glucose",
            sa.Float(),
            nullable=True,
        ),
        sa.Column("waist_in", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "amended_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "amended_by_id",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "amended_by_name",
            sa.String(length=200),
            nullable=True,
        ),
        sa.Column(
            "amendment_reason",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "prior_values",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["appointment_id"],
            ["emr_appointments.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["emr_clients.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_id"],
            ["auth_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_emr_vitals_client_id",
        "emr_vitals",
        ["client_id"],
        unique=False,
    )
    op.create_index(
        "ix_emr_vitals_appointment_id",
        "emr_vitals",
        ["appointment_id"],
        unique=False,
    )
    op.create_index(
        "ix_emr_vitals_recorded_by_id",
        "emr_vitals",
        ["recorded_by_id"],
        unique=False,
    )
    op.create_index(
        "ix_emr_vitals_recorded_at",
        "emr_vitals",
        ["recorded_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_emr_vitals_recorded_at",
        table_name="emr_vitals",
    )
    op.drop_index(
        "ix_emr_vitals_recorded_by_id",
        table_name="emr_vitals",
    )
    op.drop_index(
        "ix_emr_vitals_appointment_id",
        table_name="emr_vitals",
    )
    op.drop_index(
        "ix_emr_vitals_client_id",
        table_name="emr_vitals",
    )
    op.drop_table("emr_vitals")
