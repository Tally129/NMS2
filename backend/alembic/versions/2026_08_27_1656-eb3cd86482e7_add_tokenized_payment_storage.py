"""add tokenized payment storage

Revision ID: eb3cd86482e7
Revises: 89014805617c
Create Date: 2026-08-27 16:56:49.535884

SECURITY:
This migration stores only opaque payment-processor identifiers
and display-safe card metadata.

It does NOT store:
- PAN / full card number
- CVV / CVC
- Stripe client_secret
- payment processor secret keys
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "eb3cd86482e7"
down_revision: Union[str, Sequence[str], None] = "89014805617c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "emr_payment_customers",
        sa.Column(
            "client_id",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "provider",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "provider_customer_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "id",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(
                astext_type=sa.Text()
            ),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "legacy_mongo_id",
            sa.String(length=64),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["emr_clients.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_emr_payment_customers_client_id",
        "emr_payment_customers",
        ["client_id"],
        unique=True,
    )

    op.create_index(
        "ix_emr_payment_customers_provider",
        "emr_payment_customers",
        ["provider"],
        unique=False,
    )

    op.create_index(
        "ix_emr_payment_customers_provider_customer_id",
        "emr_payment_customers",
        ["provider_customer_id"],
        unique=True,
    )

    op.create_table(
        "emr_saved_payment_methods",
        sa.Column(
            "client_id",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "provider",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "provider_payment_method_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "payment_type",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "brand",
            sa.String(length=32),
            nullable=True,
        ),
        sa.Column(
            "last4",
            sa.String(length=4),
            nullable=True,
        ),
        sa.Column(
            "exp_month",
            sa.String(length=2),
            nullable=True,
        ),
        sa.Column(
            "exp_year",
            sa.String(length=4),
            nullable=True,
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "id",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(
                astext_type=sa.Text()
            ),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "legacy_mongo_id",
            sa.String(length=64),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["emr_clients.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_emr_saved_payment_methods_client_id",
        "emr_saved_payment_methods",
        ["client_id"],
        unique=False,
    )

    op.create_index(
        "ix_emr_saved_payment_methods_provider",
        "emr_saved_payment_methods",
        ["provider"],
        unique=False,
    )

    op.create_index(
        "ix_emr_saved_payment_methods_provider_payment_method_id",
        "emr_saved_payment_methods",
        ["provider_payment_method_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_emr_saved_payment_methods_provider_payment_method_id",
        table_name="emr_saved_payment_methods",
    )

    op.drop_index(
        "ix_emr_saved_payment_methods_provider",
        table_name="emr_saved_payment_methods",
    )

    op.drop_index(
        "ix_emr_saved_payment_methods_client_id",
        table_name="emr_saved_payment_methods",
    )

    op.drop_table(
        "emr_saved_payment_methods"
    )

    op.drop_index(
        "ix_emr_payment_customers_provider_customer_id",
        table_name="emr_payment_customers",
    )

    op.drop_index(
        "ix_emr_payment_customers_provider",
        table_name="emr_payment_customers",
    )

    op.drop_index(
        "ix_emr_payment_customers_client_id",
        table_name="emr_payment_customers",
    )

    op.drop_table(
        "emr_payment_customers"
    )
