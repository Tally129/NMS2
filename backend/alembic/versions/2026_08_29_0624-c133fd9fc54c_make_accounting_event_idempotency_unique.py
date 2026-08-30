"""make accounting event idempotency unique

Revision ID: c133fd9fc54c
Revises: c4492f9eaf92
Create Date: 2026-08-29 06:24:34.969934

"""

from typing import Sequence, Union

from alembic import op


revision: str = "c133fd9fc54c"
down_revision: Union[str, Sequence[str], None] = "c4492f9eaf92"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "emr_accounting_events"
INDEX = "ix_emr_accounting_events_idempotency_key"
COLUMN = "idempotency_key"


def upgrade() -> None:
    op.drop_index(
        INDEX,
        table_name=TABLE,
    )

    op.create_index(
        INDEX,
        TABLE,
        [COLUMN],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        INDEX,
        table_name=TABLE,
    )

    op.create_index(
        INDEX,
        TABLE,
        [COLUMN],
        unique=False,
    )
