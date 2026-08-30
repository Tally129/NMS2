from ..base import TerminalProvider


class ChaseTerminalProvider(
    TerminalProvider
):
    """
    J.P. Morgan / Chase semi-integrated terminal adapter.

    Actual protocol implementation is intentionally deferred
    until J.P. Morgan provides the integration environment,
    HWVENDORID, test terminals, and production validation data.
    """

    name = "chase"

    async def list_devices(self):
        raise RuntimeError(
            "Chase terminal integration "
            "is not configured"
        )

    async def device_status(
        self,
        provider_device_id,
    ):
        raise RuntimeError(
            "Chase terminal integration "
            "is not configured"
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
            "Chase terminal integration "
            "is not configured"
        )

    async def get_payment(
        self,
        provider_request_id,
    ):
        raise RuntimeError(
            "Chase terminal integration "
            "is not configured"
        )

    async def cancel_payment(
        self,
        provider_request_id,
    ):
        raise RuntimeError(
            "Chase terminal integration "
            "is not configured"
        )
