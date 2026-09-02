"""add archived_at to appointments

Revision ID: c899b401c3ac
Revises: e5f6a7b8c9d0
Create Date: 2026-08-03 07:23:12.883814

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c899b401c3ac'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "emr_appointments",
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_emr_appointments_archived_at",
        "emr_appointments",
        ["archived_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_emr_appointments_archived_at",
        table_name="emr_appointments",
    )

    op.drop_column(
        "emr_appointments",
        "archived_at",
    )
