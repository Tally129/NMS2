from ..base import TerminalProvider


class StripeTerminalProvider(
    TerminalProvider
):
    """
    Future Stripe Terminal adapter.

    Kept separate from the NMS online-card Stripe
    implementation because in-person readers have
    a different lifecycle.
    """

    name = "stripe_terminal"

    async def list_devices(self):
        raise RuntimeError(
            "Stripe Terminal is not configured"
        )

    async def device_status(
        self,
        provider_device_id,
    ):
        raise RuntimeError(
            "Stripe Terminal is not configured"
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
            "Stripe Terminal is not configured"
        )

    async def get_payment(
        self,
        provider_request_id,
    ):
        raise RuntimeError(
            "Stripe Terminal is not configured"
        )

    async def cancel_payment(
        self,
        provider_request_id,
    ):
        raise RuntimeError(
            "Stripe Terminal is not configured"
        )
