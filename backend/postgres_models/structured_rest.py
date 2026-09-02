"""Phase 3.6 — Remaining structured-data tables.

Twenty-eight tables covering accounting/banking/payroll/inventory/legal/
security/ops. Every table follows the same shape: `id` PK, `created_at`
typed column (for sort/range filters), and a JSONB `payload` for the
arbitrary router-shaped document. Selected fields are promoted to typed
indexed columns only where router filters demand it.

Router edits: none. All access flows through
`motor_compat_pg.MotorCompatDb`, which routes each name to its model.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class _Ph36Base:
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=_utcnow, server_default=func.now(), index=True,
    )
    payload: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}",
    )
    legacy_mongo_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


# =========================================================== Accounting
class ChartOfAccount(_Ph36Base, Base):
    __tablename__ = "emr_chart_of_accounts"
    code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    active: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, index=True)


class JournalEntry(_Ph36Base, Base):
    __tablename__ = "emr_journal_entries"


class TransactionRow(_Ph36Base, Base):
    __tablename__ = "emr_transactions"
    client_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)


class Expense(_Ph36Base, Base):
    __tablename__ = "emr_expenses"


class Invoice(_Ph36Base, Base):
    __tablename__ = "emr_invoices"


class VendorBill(_Ph36Base, Base):
    __tablename__ = "emr_vendor_bills"


class Vendor(_Ph36Base, Base):
    __tablename__ = "emr_vendors"


class AccountingBackfillRun(_Ph36Base, Base):
    __tablename__ = "emr_accounting_backfill_runs"


class AccountingEvent(_Ph36Base, Base):
    __tablename__ = "emr_accounting_events"
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True, index=True,
    )


# ============================================================= Banking
class BankAccount(_Ph36Base, Base):
    __tablename__ = "emr_bank_accounts"
    active: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, index=True)


class BankImportBatch(_Ph36Base, Base):
    __tablename__ = "emr_bank_import_batches"


class BankTransaction(_Ph36Base, Base):
    __tablename__ = "emr_bank_transactions"
    bank_account_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True,
    )
    reconciliation_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True,
    )


class BankTransfer(_Ph36Base, Base):
    __tablename__ = "emr_bank_transfers"


class ImportedBatch(_Ph36Base, Base):
    __tablename__ = "emr_imported_batches"


class Reconciliation(_Ph36Base, Base):
    __tablename__ = "emr_reconciliations"
    bank_account_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True,
    )


# ============================================================= Payroll
class Employee(_Ph36Base, Base):
    __tablename__ = "emr_employees"


class PayrollRun(_Ph36Base, Base):
    __tablename__ = "emr_payroll_runs"


class TimeEntry(_Ph36Base, Base):
    __tablename__ = "emr_time_entries"
    user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)


# =========================================================== Inventory
class InventoryItem(_Ph36Base, Base):
    __tablename__ = "emr_inventory_items"


class InventoryTransaction(_Ph36Base, Base):
    __tablename__ = "emr_inventory_transactions"


# ============================================================ Legal
class BaaRecord(_Ph36Base, Base):
    __tablename__ = "emr_baa_records"


class LegalAcceptance(_Ph36Base, Base):
    __tablename__ = "emr_legal_acceptances"
    user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)


class LegalPolicy(_Ph36Base, Base):
    __tablename__ = "emr_legal_policies"
    slug: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)


# =========================================================== Security
class BreakglassSession(_Ph36Base, Base):
    __tablename__ = "emr_breakglass_sessions"
    user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)


# ================================================ Ops / Infrastructure
class PostingDeadLetter(_Ph36Base, Base):
    __tablename__ = "emr_posting_dead_letters"


class VipListEntry(_Ph36Base, Base):
    __tablename__ = "emr_vip_list"


class WsTicket(_Ph36Base, Base):
    __tablename__ = "emr_ws_tickets"
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )


class UserSessionCompat(_Ph36Base, Base):
    """Legacy `user_sessions` collection. The auth-runtime `UserSession`
    model lives on `auth_user_sessions` (Phase 3.1 identity cutover); this
    table only receives writes from any leftover Mongo callers via the
    adapter."""
    __tablename__ = "emr_user_sessions_legacy"
    user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)


# ============================================ Phase 3.7 (final stragglers)
class Membership(_Ph36Base, Base):
    __tablename__ = "emr_memberships"
    client_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)


class CampaignTemplate(_Ph36Base, Base):
    __tablename__ = "emr_campaign_templates"


class CampaignUnsubscribe(_Ph36Base, Base):
    __tablename__ = "emr_campaign_unsubscribes"


class LegacyForm(_Ph36Base, Base):
    """Very old `forms` collection — only used by ops.py dashboard count."""
    __tablename__ = "emr_forms_legacy"


class SymptomLog(_Ph36Base, Base):
    __tablename__ = "emr_symptom_logs"
    client_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
