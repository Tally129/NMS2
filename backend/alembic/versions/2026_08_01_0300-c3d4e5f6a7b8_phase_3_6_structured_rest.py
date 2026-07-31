"""phase 3.6 remaining structured-data tables

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-01 03:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_generic(name: str, extra_cols=(), extra_indexes=()):
    cols = [
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                    server_default=sa.text("now()"), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()),
                    nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("legacy_mongo_id", sa.String(length=64), nullable=True),
    ]
    cols.extend(extra_cols)
    op.create_table(name, *cols)
    op.create_index(f"ix_{name}_created_at", name, ["created_at"])
    for idx_col in extra_indexes:
        op.create_index(f"ix_{name}_{idx_col}", name, [idx_col])


def upgrade() -> None:
    # Accounting
    _create_generic(
        "emr_chart_of_accounts",
        (sa.Column("code", sa.String(length=32), nullable=True),
         sa.Column("active", sa.Boolean(), nullable=True)),
        extra_indexes=("code", "active"),
    )
    _create_generic("emr_journal_entries")
    _create_generic(
        "emr_transactions",
        (sa.Column("client_id", sa.String(length=64), nullable=True),
         sa.Column("status", sa.String(length=32), nullable=True)),
        extra_indexes=("client_id", "status"),
    )
    _create_generic("emr_expenses")
    _create_generic("emr_invoices")
    _create_generic("emr_vendor_bills")
    _create_generic("emr_vendors")
    _create_generic("emr_accounting_backfill_runs")
    _create_generic(
        "emr_accounting_events",
        (sa.Column("idempotency_key", sa.String(length=200), nullable=True),),
        extra_indexes=("idempotency_key",),
    )

    # Banking
    _create_generic(
        "emr_bank_accounts",
        (sa.Column("active", sa.Boolean(), nullable=True),),
        extra_indexes=("active",),
    )
    _create_generic("emr_bank_import_batches")
    _create_generic(
        "emr_bank_transactions",
        (sa.Column("bank_account_id", sa.String(length=64), nullable=True),
         sa.Column("reconciliation_id", sa.String(length=64), nullable=True)),
        extra_indexes=("bank_account_id", "reconciliation_id"),
    )
    _create_generic("emr_bank_transfers")
    _create_generic("emr_imported_batches")
    _create_generic(
        "emr_reconciliations",
        (sa.Column("bank_account_id", sa.String(length=64), nullable=True),),
        extra_indexes=("bank_account_id",),
    )

    # Payroll
    _create_generic("emr_employees")
    _create_generic("emr_payroll_runs")
    _create_generic(
        "emr_time_entries",
        (sa.Column("user_id", sa.String(length=64), nullable=True),),
        extra_indexes=("user_id",),
    )

    # Inventory
    _create_generic("emr_inventory_items")
    _create_generic("emr_inventory_transactions")

    # Legal
    _create_generic("emr_baa_records")
    _create_generic(
        "emr_legal_acceptances",
        (sa.Column("user_id", sa.String(length=64), nullable=True),),
        extra_indexes=("user_id",),
    )
    _create_generic(
        "emr_legal_policies",
        (sa.Column("slug", sa.String(length=120), nullable=True),),
        extra_indexes=("slug",),
    )

    # Security
    _create_generic(
        "emr_breakglass_sessions",
        (sa.Column("user_id", sa.String(length=64), nullable=True),),
        extra_indexes=("user_id",),
    )

    # Ops / Infra
    _create_generic("emr_posting_dead_letters")
    _create_generic("emr_vip_list")
    _create_generic(
        "emr_ws_tickets",
        (sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),),
        extra_indexes=("expires_at",),
    )
    _create_generic(
        "emr_user_sessions_legacy",
        (sa.Column("user_id", sa.String(length=64), nullable=True),),
        extra_indexes=("user_id",),
    )


def downgrade() -> None:
    for name in (
        "emr_user_sessions_legacy", "emr_ws_tickets", "emr_vip_list",
        "emr_posting_dead_letters", "emr_breakglass_sessions",
        "emr_legal_policies", "emr_legal_acceptances", "emr_baa_records",
        "emr_inventory_transactions", "emr_inventory_items",
        "emr_time_entries", "emr_payroll_runs", "emr_employees",
        "emr_reconciliations", "emr_imported_batches", "emr_bank_transfers",
        "emr_bank_transactions", "emr_bank_import_batches",
        "emr_bank_accounts",
        "emr_accounting_events", "emr_accounting_backfill_runs",
        "emr_vendors", "emr_vendor_bills", "emr_invoices", "emr_expenses",
        "emr_transactions", "emr_journal_entries", "emr_chart_of_accounts",
    ):
        op.drop_table(name)
