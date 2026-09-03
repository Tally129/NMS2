"""add marketing phase14 controlled execution

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "marketing_execution_requests",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("action_type", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=100), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=True),
        sa.Column(
            "idempotency_key",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "request_payload",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "dry_run",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "human_approval_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "approved_by",
            sa.String(),
            sa.ForeignKey("auth_users.id"),
            nullable=True,
        ),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "executed_by",
            sa.String(),
            sa.ForeignKey("auth_users.id"),
            nullable=True,
        ),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_by",
            sa.String(),
            sa.ForeignKey("auth_users.id"),
            nullable=True,
        ),
        sa.Column(
            "failure_code",
            sa.String(length=100),
            nullable=True,
        ),
        sa.Column(
            "failure_message",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_marketing_execution_requests_idempotency_key",
        ),
    )

    op.create_table(
        "marketing_execution_approvals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "execution_request_id",
            sa.String(),
            sa.ForeignKey(
                "marketing_execution_requests.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "decision",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "decided_by",
            sa.String(),
            sa.ForeignKey("auth_users.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_index(
        "ix_marketing_execution_approvals_request",
        "marketing_execution_approvals",
        ["execution_request_id"],
    )

    op.create_table(
        "marketing_execution_attempts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "execution_request_id",
            sa.String(),
            sa.ForeignKey(
                "marketing_execution_requests.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "attempt_number",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "provider",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "dry_run",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "request_snapshot",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "response_snapshot",
            postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column(
            "error_code",
            sa.String(length=100),
            nullable=True,
        ),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_marketing_execution_attempts_request",
        "marketing_execution_attempts",
        ["execution_request_id"],
    )

    op.create_table(
        "marketing_provider_execution_policies",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "provider",
            sa.String(length=64),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "dry_run_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "human_approval_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "allowed_actions",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            sa.String(),
            sa.ForeignKey("auth_users.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade():
    op.drop_table("marketing_provider_execution_policies")

    op.drop_index(
        "ix_marketing_execution_attempts_request",
        table_name="marketing_execution_attempts",
    )
    op.drop_table("marketing_execution_attempts")

    op.drop_index(
        "ix_marketing_execution_approvals_request",
        table_name="marketing_execution_approvals",
    )
    op.drop_table("marketing_execution_approvals")

    op.drop_table("marketing_execution_requests")
