from ..base import TerminalProvider


class SquareTerminalProvider(
    TerminalProvider
):
    """
    Future Square Terminal adapter.

    Square-specific pairing, OAuth, device IDs,
    checkout API, and webhook logic belong here.
    """

    name = "square"

    async def list_devices(self):
        raise RuntimeError(
            "Square Terminal is not configured"
        )

    async def device_status(
        self,
        provider_device_id,
    ):
        raise RuntimeError(
            "Square Terminal is not configured"
        )

    async def create_payment(
        self,
        *,
        provider_device_id,
        amount_cents,
        currency,
        reference_id,
    ):
        raise RuntimeError(
            "Square Terminal is not configured"
        )

    async def get_payment(
        self,
        provider_request_id,
    ):
        raise RuntimeError(
            "Square Terminal is not configured"
        )

    async def cancel_payment(
        self,
        provider_request_id,
    ):
        raise RuntimeError(
            "Square Terminal is not configured"
        )
