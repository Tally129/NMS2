"""Harden Marketing OS execution attempt numbering.

Revision ID: e4f6a8c0d2b4
Revises: d3e4f5a6b7c8
"""

from alembic import op


revision = "e4f6a8c0d2b4"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        "uq_marketing_execution_attempt_request_number",
        "marketing_execution_attempts",
        [
            "execution_request_id",
            "attempt_number",
        ],
    )


def downgrade():
    op.drop_constraint(
        "uq_marketing_execution_attempt_request_number",
        "marketing_execution_attempts",
        type_="unique",
    )
