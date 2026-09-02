from abc import ABC, abstractmethod

from .types import (
    TerminalDevice,
    TerminalPaymentResult,
)


class TerminalProvider(ABC):
    """
    Provider-neutral terminal interface.

    Implementations may use:
    - local terminal APIs
    - cloud terminal APIs
    - webhooks
    - polling
    - LAN connections

    NMS does not care which transport is used.
    """

    name: str

    @abstractmethod
    async def list_devices(
        self,
    ) -> list[TerminalDevice]:
        raise NotImplementedError

    @abstractmethod
    async def device_status(
        self,
        provider_device_id: str,
    ) -> TerminalDevice:
        raise NotImplementedError

    @abstractmethod
    async def create_payment(
        self,
        *,
        provider_device_id: str,
        amount_cents: int,
        currency: str,
        reference_id: str,
    ) -> TerminalPaymentResult:
        raise NotImplementedError

    @abstractmethod
    async def get_payment(
        self,
        provider_request_id: str,
    ) -> TerminalPaymentResult:
        raise NotImplementedError

    @abstractmethod
    async def cancel_payment(
        self,
        provider_request_id: str,
    ) -> TerminalPaymentResult:
        raise NotImplementedError

    async def refund_payment(
        self,
        *,
        provider_transaction_id: str,
        amount_cents: int | None = None,
    ) -> TerminalPaymentResult:
        raise NotImplementedError(
            f"{self.name} refund not implemented"
        )

    async def void_payment(
        self,
        *,
        provider_transaction_id: str,
    ) -> TerminalPaymentResult:
        raise NotImplementedError(
            f"{self.name} void not implemented"
        )
