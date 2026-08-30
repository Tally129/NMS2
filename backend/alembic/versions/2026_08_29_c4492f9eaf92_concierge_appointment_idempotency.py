"""Concierge appointment request idempotency.

Revision ID: c4492f9eaf92
Revises: 4a56de4e79c9
"""

from alembic import op
import sqlalchemy as sa


revision = "c4492f9eaf92"
down_revision = "4a56de4e79c9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "emr_appointment_requests",
        sa.Column(
            "concierge_idempotency_key",
            sa.String(length=64),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_emr_appointment_requests_concierge_idempotency_key",
        "emr_appointment_requests",
        ["concierge_idempotency_key"],
        unique=True,
    )


def downgrade():
    op.drop_index(
        "ix_emr_appointment_requests_concierge_idempotency_key",
        table_name="emr_appointment_requests",
    )

    op.drop_column(
        "emr_appointment_requests",
        "concierge_idempotency_key",
    )
