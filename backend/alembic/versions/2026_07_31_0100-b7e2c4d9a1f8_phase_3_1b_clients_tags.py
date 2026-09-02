"""phase 3.1b clients.tags column

Revision ID: b7e2c4d9a1f8
Revises: e4a80693e8d6
Create Date: 2026-07-31 01:00:00.000000

Adds a `tags` JSONB column to `emr_clients` so the portal-ops
test-patient tagger (Session 3.1b) and the campaign-segmentation
`tags` filter can move off Mongo without losing the field.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b7e2c4d9a1f8'
down_revision: Union[str, Sequence[str], None] = 'e4a80693e8d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "emr_clients",
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("emr_clients", "tags")
