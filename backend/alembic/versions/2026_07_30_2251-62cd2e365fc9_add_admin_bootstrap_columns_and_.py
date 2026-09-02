"""add admin bootstrap columns and recovery codes

Revision ID: 62cd2e365fc9
Revises: af896f736c94
Create Date: 2026-07-30 22:51:08.581562

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '62cd2e365fc9'
down_revision: Union[str, Sequence[str], None] = 'af896f736c94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Session 2c — admin bootstrap + recovery codes.

    Adds forced-onboarding state columns to auth_users and creates
    auth_recovery_codes for single-use MFA fallback. Forward-only.
    """
    op.add_column(
        "auth_users",
        sa.Column("onboarding_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "auth_users",
        sa.Column("temporary_password_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "auth_recovery_codes",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["auth_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash", name="uq_auth_recovery_codes_code_hash"),
    )
    op.create_index(
        op.f("ix_auth_recovery_codes_user_id"),
        "auth_recovery_codes", ["user_id"], unique=False,
    )
    op.create_index(
        op.f("ix_auth_recovery_codes_code_hash"),
        "auth_recovery_codes", ["code_hash"], unique=False,
    )


def downgrade() -> None:
    """Rollback path — drop the recovery codes table and remove the two
    new columns from auth_users."""
    op.drop_index(op.f("ix_auth_recovery_codes_code_hash"), table_name="auth_recovery_codes")
    op.drop_index(op.f("ix_auth_recovery_codes_user_id"), table_name="auth_recovery_codes")
    op.drop_table("auth_recovery_codes")
    op.drop_column("auth_users", "temporary_password_expires_at")
    op.drop_column("auth_users", "onboarding_status")
