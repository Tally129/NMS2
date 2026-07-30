"""drop oauth tables

Revision ID: af896f736c94
Revises: 557f2e586456
Create Date: 2026-07-30 21:31:16.173454

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'af896f736c94'
down_revision: Union[str, Sequence[str], None] = '557f2e586456'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop OAuth state + handoff tables.

    Google SSO (both the Emergent-managed session exchange and the direct
    OAuth authorize/callback/exchange flow) was removed from the codebase.
    The auth_oauth_states and auth_oauth_handoffs tables are no longer
    referenced by any runtime code, so we drop them here. Forward-only
    migration; the initial revision's create_table statements remain
    untouched.
    """
    op.drop_index(op.f('ix_auth_oauth_handoffs_user_id'), table_name='auth_oauth_handoffs')
    op.drop_table('auth_oauth_handoffs')
    op.drop_index(op.f('ix_auth_oauth_states_expires_at'), table_name='auth_oauth_states')
    op.drop_table('auth_oauth_states')


def downgrade() -> None:
    """Recreate OAuth state + handoff tables (rollback path)."""
    from sqlalchemy.dialects import postgresql  # noqa: F401
    op.create_table(
        'auth_oauth_states',
        sa.Column('state', sa.String(length=128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed', sa.Boolean(), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('state'),
    )
    op.create_index(op.f('ix_auth_oauth_states_expires_at'),
                    'auth_oauth_states', ['expires_at'], unique=False)
    op.create_table(
        'auth_oauth_handoffs',
        sa.Column('handoff_id', sa.String(length=128), nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('access_token', sa.String(length=4096), nullable=False),
        sa.Column('refresh_cookie_value', sa.String(length=512), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('consumed', sa.Boolean(), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['auth_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('handoff_id'),
    )
    op.create_index(op.f('ix_auth_oauth_handoffs_user_id'),
                    'auth_oauth_handoffs', ['user_id'], unique=False)
