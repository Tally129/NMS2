"""normalize marketing conversions numeric default

Revision ID: 89014805617c
Revises: 855a4997da61
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "89014805617c"
down_revision: Union[str, None] = "855a4997da61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "marketing_daily_metrics",
        "conversions",
        existing_type=sa.Numeric(
            precision=18,
            scale=4,
        ),
        existing_nullable=False,
        server_default=sa.text("0::numeric"),
    )


def downgrade() -> None:
    op.alter_column(
        "marketing_daily_metrics",
        "conversions",
        existing_type=sa.Numeric(
            precision=18,
            scale=4,
        ),
        existing_nullable=False,
        server_default=sa.text("0::bigint"),
    )
