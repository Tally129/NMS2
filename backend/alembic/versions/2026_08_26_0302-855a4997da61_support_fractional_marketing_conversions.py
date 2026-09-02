"""support fractional marketing conversions

Revision ID: 855a4997da61
Revises: f9359a917c24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "855a4997da61"
down_revision: Union[str, None] = "f9359a917c24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "marketing_daily_metrics",
        "conversions",
        existing_type=sa.BigInteger(),
        type_=sa.Numeric(
            precision=18,
            scale=4,
        ),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
        postgresql_using="conversions::numeric(18,4)",
    )


def downgrade() -> None:
    op.alter_column(
        "marketing_daily_metrics",
        "conversions",
        existing_type=sa.Numeric(
            precision=18,
            scale=4,
        ),
        type_=sa.BigInteger(),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
        postgresql_using="conversions::bigint",
    )
