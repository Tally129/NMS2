"""Add Marketing OS Phase 12 Director signal and brief persistence.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketing_director_signals",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("signal_key", sa.String(length=200), nullable=False),
        sa.Column("snapshot_key", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("source_phase", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=24), nullable=False),
        sa.Column(
            "priority",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("recommended_action", sa.Text(), nullable=True),
        sa.Column("expected_impact", sa.String(length=32), nullable=True),
        sa.Column("confidence", sa.String(length=32), nullable=True),
        sa.Column("data_quality", sa.String(length=32), nullable=True),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default="open",
            nullable=False,
        ),
        sa.Column(
            "human_approval_required",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "external_execution_allowed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["auth_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "signal_key",
            "snapshot_key",
            name="uq_marketing_director_signal_snapshot",
        ),
    )

    op.create_index(
        "ix_marketing_director_signals_signal_key",
        "marketing_director_signals",
        ["signal_key"],
    )
    op.create_index(
        "ix_marketing_director_signals_snapshot_key",
        "marketing_director_signals",
        ["snapshot_key"],
    )
    op.create_index(
        "ix_marketing_director_signals_category",
        "marketing_director_signals",
        ["category"],
    )
    op.create_index(
        "ix_marketing_director_signals_source_phase",
        "marketing_director_signals",
        ["source_phase"],
    )
    op.create_index(
        "ix_marketing_director_signals_severity",
        "marketing_director_signals",
        ["severity"],
    )
    op.create_index(
        "ix_marketing_director_signals_priority",
        "marketing_director_signals",
        ["priority"],
    )
    op.create_index(
        "ix_marketing_director_signals_status",
        "marketing_director_signals",
        ["status"],
    )

    op.create_table(
        "marketing_director_briefs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("snapshot_key", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default="ready",
            nullable=False,
        ),
        sa.Column(
            "deterministic_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "signal_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column(
            "ai_status",
            sa.String(length=32),
            server_default="not_requested",
            nullable=False,
        ),
        sa.Column(
            "source_counts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "human_approval_required",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "external_execution_allowed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["auth_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_key"),
    )

    op.create_index(
        "ix_marketing_director_briefs_snapshot_key",
        "marketing_director_briefs",
        ["snapshot_key"],
    )
    op.create_index(
        "ix_marketing_director_briefs_status",
        "marketing_director_briefs",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_marketing_director_briefs_status",
        table_name="marketing_director_briefs",
    )
    op.drop_index(
        "ix_marketing_director_briefs_snapshot_key",
        table_name="marketing_director_briefs",
    )
    op.drop_table("marketing_director_briefs")

    op.drop_index(
        "ix_marketing_director_signals_status",
        table_name="marketing_director_signals",
    )
    op.drop_index(
        "ix_marketing_director_signals_priority",
        table_name="marketing_director_signals",
    )
    op.drop_index(
        "ix_marketing_director_signals_severity",
        table_name="marketing_director_signals",
    )
    op.drop_index(
        "ix_marketing_director_signals_source_phase",
        table_name="marketing_director_signals",
    )
    op.drop_index(
        "ix_marketing_director_signals_category",
        table_name="marketing_director_signals",
    )
    op.drop_index(
        "ix_marketing_director_signals_snapshot_key",
        table_name="marketing_director_signals",
    )
    op.drop_index(
        "ix_marketing_director_signals_signal_key",
        table_name="marketing_director_signals",
    )
    op.drop_table("marketing_director_signals")
