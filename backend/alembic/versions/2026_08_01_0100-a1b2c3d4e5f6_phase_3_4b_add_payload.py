"""phase 3.4b add payload jsonb to 8 retired-collection tables

Revision ID: a1b2c3d4e5f6
Revises: 8ae0b2901822
Create Date: 2026-08-01 01:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "8ae0b2901822"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES = (
    "emr_messages",
    "emr_message_threads",
    "emr_form_templates",
    "emr_form_submissions",
    "emr_soap_templates",
    "emr_lab_values",
    "emr_treatment_plans",
    "emr_treatments",
)


def upgrade() -> None:
    for t in _TABLES:
        op.add_column(
            t,
            sa.Column(
                "payload",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )
    # Runtime callers write `test_name` (payload) not `marker`. Relax the
    # NOT NULL so the adapter can pass through.
    op.alter_column("emr_lab_values", "marker", existing_type=sa.String(length=100),
                     nullable=True)


def downgrade() -> None:
    op.alter_column("emr_lab_values", "marker", existing_type=sa.String(length=100),
                     nullable=False)
    for t in _TABLES:
        op.drop_column(t, "payload")
