"""add terminal registry

Revision ID: f1a2b3c4d5e6
Revises: eb3cd86482e7
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f1a2b3c4d5e6"
down_revision = "eb3cd86482e7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payment_terminals",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("provider_device_id", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("location_id", sa.String(64), nullable=True),
        sa.Column("connection_type", sa.String(64), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("configured", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column(
            "capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "provider_device_id",
            name="uq_payment_terminal_provider_device",
        ),
    )

    op.create_index(
        "ix_payment_terminals_provider",
        "payment_terminals",
        ["provider"],
    )

    op.create_index(
        "ix_payment_terminals_location_id",
        "payment_terminals",
        ["location_id"],
    )

    op.create_index(
        "ix_payment_terminals_active",
        "payment_terminals",
        ["enabled", "archived_at"],
    )

    op.create_index(
        "ix_payment_terminals_location_provider",
        "payment_terminals",
        ["location_id", "provider"],
    )

    op.create_table(
        "terminal_payment_attempts",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("transaction_id", sa.String(64), nullable=False),
        sa.Column("terminal_id", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column(
            "provider_request_id",
            sa.String(255),
            nullable=True,
        ),
        sa.Column(
            "provider_transaction_id",
            sa.String(255),
            nullable=True,
        ),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("card_brand", sa.String(64), nullable=True),
        sa.Column("last4", sa.String(4), nullable=True),
        sa.Column("failure_code", sa.String(128), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column(
            "safe_response",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_terminal_payment_attempts_transaction_id",
        "terminal_payment_attempts",
        ["transaction_id"],
    )

    op.create_index(
        "ix_terminal_payment_attempts_terminal_id",
        "terminal_payment_attempts",
        ["terminal_id"],
    )

    op.create_index(
        "ix_terminal_payment_attempts_provider",
        "terminal_payment_attempts",
        ["provider"],
    )

    op.create_index(
        "ix_terminal_payment_attempts_provider_request_id",
        "terminal_payment_attempts",
        ["provider_request_id"],
    )

    op.create_index(
        "ix_terminal_payment_attempts_provider_transaction_id",
        "terminal_payment_attempts",
        ["provider_transaction_id"],
    )

    op.create_index(
        "ix_terminal_payment_attempts_status",
        "terminal_payment_attempts",
        ["status"],
    )

    op.create_index(
        "ix_terminal_attempt_transaction_status",
        "terminal_payment_attempts",
        ["transaction_id", "status"],
    )


def downgrade():
    op.drop_table("terminal_payment_attempts")
    op.drop_table("payment_terminals")
