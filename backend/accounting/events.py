"""
AccountingEvent model + canonical event catalog + append-only bus.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from deps import db
from models import new_id


# Canonical event names. New event types must be added HERE, not in operational code.
EVENT_TYPES = {
    "SaleCompleted", "SaleRefunded",
    "InvoiceIssued", "InvoicePaid", "InvoiceVoided",
    "MembershipStarted", "MembershipRenewed", "MembershipCanceled",
    "InventoryConsumed", "InventoryAdjusted", "InventoryPurchased",
    "ManualExpenseRecorded",
    "VendorBillCreated", "VendorBillPaid",
    "StripePaymentReceived", "StripeRefundIssued", "StripeFeeCharged",
    "PayrollAccrued", "PayrollPaid",
    "TaxLiabilityAccrued", "TaxLiabilityPaid",
    "BankDepositMade", "BankTransferMade",
    "ManualJournal",
}


class AccountingEvent(BaseModel):
    id: str = Field(default_factory=new_id)
    event_type: str
    schema_version: int = 1
    occurred_at: datetime
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_module: str
    source_ref_type: str
    source_ref_id: str
    idempotency_key: str
    amount_cents: int
    currency: str = "USD"
    context: dict = {}
    actor_id: Optional[str] = None
    actor_role: Optional[str] = None
    reverses_event_id: Optional[str] = None


async def emit(event: AccountingEvent) -> tuple[str, str]:
    """Persist an event and immediately post it through the rules engine.

    Returns (event_id, status) where status ∈ {"posted", "duplicate",
    "dead_letter"}. Duplicate emissions (same idempotency_key) are silent.
    """
    from .posting_engine import post_event
    existing = await db.accounting_events.find_one({"idempotency_key": event.idempotency_key})
    if existing:
        return existing["id"], "duplicate"
    doc = event.dict()
    await db.accounting_events.insert_one(doc)
    status = await post_event(doc)
    return event.id, status
