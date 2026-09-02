"""Enforce one VisitNote per appointment.

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-08-20
"""

from alembic import op


revision = "b9c0d1e2f3a4"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE UNIQUE INDEX
        IF NOT EXISTS ux_emr_visit_notes_appointment_id
        ON emr_visit_notes (appointment_id)
        WHERE appointment_id IS NOT NULL
        """
    )


def downgrade():
    op.execute(
        """
        DROP INDEX IF EXISTS
        ux_emr_visit_notes_appointment_id
        """
    )
