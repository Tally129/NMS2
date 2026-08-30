from ..base import TerminalProvider


class GenericTerminalProvider(
    TerminalProvider
):
    """
    Future adapter for another semi-integrated
    terminal provider.

    This intentionally makes new vendors plug-ins
    rather than POS rewrites.
    """

    name = "generic"

    async def list_devices(self):
        raise RuntimeError(
            "Generic terminal not configured"
        )

    async def device_status(
        self,
        provider_device_id,
    ):
        raise RuntimeError(
            "Generic terminal not configured"
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
            "Generic terminal not configured"
        )

    async def get_payment(
        self,
        provider_request_id,
    ):
        raise RuntimeError(
            "Generic terminal not configured"
        )

    async def cancel_payment(
        self,
        provider_request_id,
    ):
        raise RuntimeError(
            "Generic terminal not configured"
        )
