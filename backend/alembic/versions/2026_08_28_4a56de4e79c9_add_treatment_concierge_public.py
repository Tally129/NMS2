"""add treatment concierge public publication flag

Revision ID: 4a56de4e79c9
Revises: f1a2b3c4d5e6
"""

from alembic import op
import sqlalchemy as sa


revision = "4a56de4e79c9"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "emr_treatments",
        sa.Column(
            "concierge_public",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.create_index(
        "ix_emr_treatments_concierge_public",
        "emr_treatments",
        ["concierge_public"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_emr_treatments_concierge_public",
        table_name="emr_treatments",
    )

    op.drop_column(
        "emr_treatments",
        "concierge_public",
    )
