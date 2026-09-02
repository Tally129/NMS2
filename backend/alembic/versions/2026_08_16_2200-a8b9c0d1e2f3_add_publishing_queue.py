"""add publishing queue

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-08-16 22:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "emr_publishing_queue",
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
            "content_asset_id",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "strategy_id",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=True,
        ),
        sa.Column(
            "platform",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "scheduled_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_by",
            sa.String(length=64),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["content_asset_id"],
            ["emr_content_assets.id"],
            ondelete="SET NULL",
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
        "ix_emr_publishing_queue_created_at",
        "emr_publishing_queue",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_emr_publishing_queue_content_asset_id",
        "emr_publishing_queue",
        ["content_asset_id"],
        unique=False,
    )
    op.create_index(
        "ix_emr_publishing_queue_strategy_id",
        "emr_publishing_queue",
        ["strategy_id"],
        unique=False,
    )
    op.create_index(
        "ix_emr_publishing_queue_status",
        "emr_publishing_queue",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_emr_publishing_queue_platform",
        "emr_publishing_queue",
        ["platform"],
        unique=False,
    )
    op.create_index(
        "ix_emr_publishing_queue_scheduled_at",
        "emr_publishing_queue",
        ["scheduled_at"],
        unique=False,
    )
    op.create_index(
        "ix_emr_publishing_queue_created_by",
        "emr_publishing_queue",
        ["created_by"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_emr_publishing_queue_created_by",
        table_name="emr_publishing_queue",
    )
    op.drop_index(
        "ix_emr_publishing_queue_scheduled_at",
        table_name="emr_publishing_queue",
    )
    op.drop_index(
        "ix_emr_publishing_queue_platform",
        table_name="emr_publishing_queue",
    )
    op.drop_index(
        "ix_emr_publishing_queue_status",
        table_name="emr_publishing_queue",
    )
    op.drop_index(
        "ix_emr_publishing_queue_strategy_id",
        table_name="emr_publishing_queue",
    )
    op.drop_index(
        "ix_emr_publishing_queue_content_asset_id",
        table_name="emr_publishing_queue",
    )
    op.drop_index(
        "ix_emr_publishing_queue_created_at",
        table_name="emr_publishing_queue",
    )

    op.drop_table("emr_publishing_queue")
