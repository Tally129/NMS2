from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


TERMINAL_STATES = {
    "created",
    "waiting_for_terminal",
    "customer_present",
    "processing",
    "approved",
    "declined",
    "canceled",
    "failed",
    "timed_out",
}


@dataclass
class TerminalDevice:
    id: str
    provider: str
    provider_device_id: str
    display_name: str
    status: str = "unknown"
    location_id: Optional[str] = None
    connection_type: Optional[str] = None
    is_default: bool = False
    capabilities: Dict[str, Any] = field(
        default_factory=dict
    )
    metadata: Dict[str, Any] = field(
        default_factory=dict
    )


@dataclass
class TerminalPaymentResult:
    provider: str
    status: str
    amount_cents: int
    currency: str = "USD"

    provider_request_id: Optional[str] = None
    provider_transaction_id: Optional[str] = None

    card_brand: Optional[str] = None
    last4: Optional[str] = None

    failure_code: Optional[str] = None
    failure_message: Optional[str] = None

    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    raw_safe: Dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def approved(self) -> bool:
        return self.status == "approved"
