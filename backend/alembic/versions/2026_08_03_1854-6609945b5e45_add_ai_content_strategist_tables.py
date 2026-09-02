"""add ai content strategist tables

Revision ID: 6609945b5e45
Revises: c899b401c3ac
Create Date: 2026-08-03 18:54
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "6609945b5e45"
down_revision: Union[str, Sequence[str], None] = "c899b401c3ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "emr_content_strategies",
        sa.Column(
            "id",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "legacy_mongo_id",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=True,
        ),
        sa.Column(
            "created_by",
            sa.String(length=64),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["auth_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_emr_content_strategies_created_at",
        "emr_content_strategies",
        ["created_at"],
    )
    op.create_index(
        "ix_emr_content_strategies_status",
        "emr_content_strategies",
        ["status"],
    )
    op.create_index(
        "ix_emr_content_strategies_created_by",
        "emr_content_strategies",
        ["created_by"],
    )

    op.create_table(
        "emr_content_assets",
        sa.Column(
            "id",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "legacy_mongo_id",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "strategy_id",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "content_type",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=True,
        ),
        sa.Column(
            "created_by",
            sa.String(length=64),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["emr_content_strategies.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["auth_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_emr_content_assets_created_at",
        "emr_content_assets",
        ["created_at"],
    )
    op.create_index(
        "ix_emr_content_assets_strategy_id",
        "emr_content_assets",
        ["strategy_id"],
    )
    op.create_index(
        "ix_emr_content_assets_content_type",
        "emr_content_assets",
        ["content_type"],
    )
    op.create_index(
        "ix_emr_content_assets_status",
        "emr_content_assets",
        ["status"],
    )
    op.create_index(
        "ix_emr_content_assets_created_by",
        "emr_content_assets",
        ["created_by"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_emr_content_assets_created_by",
        table_name="emr_content_assets",
    )
    op.drop_index(
        "ix_emr_content_assets_status",
        table_name="emr_content_assets",
    )
    op.drop_index(
        "ix_emr_content_assets_content_type",
        table_name="emr_content_assets",
    )
    op.drop_index(
        "ix_emr_content_assets_strategy_id",
        table_name="emr_content_assets",
    )
    op.drop_index(
        "ix_emr_content_assets_created_at",
        table_name="emr_content_assets",
    )
    op.drop_table("emr_content_assets")

    op.drop_index(
        "ix_emr_content_strategies_created_by",
        table_name="emr_content_strategies",
    )
    op.drop_index(
        "ix_emr_content_strategies_status",
        table_name="emr_content_strategies",
    )
    op.drop_index(
        "ix_emr_content_strategies_created_at",
        table_name="emr_content_strategies",
    )
    op.drop_table("emr_content_strategies")
