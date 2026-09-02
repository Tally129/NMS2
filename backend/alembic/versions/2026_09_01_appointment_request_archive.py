"""add appointment request archive fields

Revision ID: apptreqarchive0901
Revises: c133fd9fc54c
Create Date: 2026-09-01
"""

from alembic import op
import sqlalchemy as sa


revision = "apptreqarchive0901"
down_revision = "c133fd9fc54c"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "emr_appointment_requests",
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "emr_appointment_requests",
        sa.Column(
            "archived_by",
            sa.String(length=64),
            nullable=True,
        ),
    )

    op.create_foreign_key(
        "fk_emr_appointment_requests_archived_by_auth_users",
        "emr_appointment_requests",
        "auth_users",
        ["archived_by"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "ix_emr_appointment_requests_archived_at",
        "emr_appointment_requests",
        ["archived_at"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_emr_appointment_requests_archived_at",
        table_name="emr_appointment_requests",
    )

    op.drop_constraint(
        "fk_emr_appointment_requests_archived_by_auth_users",
        "emr_appointment_requests",
        type_="foreignkey",
    )

    op.drop_column(
        "emr_appointment_requests",
        "archived_by",
    )

    op.drop_column(
        "emr_appointment_requests",
        "archived_at",
    )
