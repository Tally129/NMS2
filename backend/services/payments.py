"""
Natural Medical Solutions Stripe payment boundary.

SECURITY RULES
--------------
- Never accept or store PAN/card numbers.
- Never accept or store CVC/CVV.
- Never log Stripe client secrets.
- Never place PHI in Stripe metadata.
- Amounts are calculated by the NMS backend.
- Stripe is authoritative for processor payment state.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import stripe
from fastapi import HTTPException


def _secret_key() -> str:
    key = (os.environ.get("STRIPE_SECRET_KEY") or "").strip()

    if not key:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "payments_not_configured",
                "message": "Online card payments are not configured.",
            },
        )

    return key


def publishable_key() -> str:
    key = (
        os.environ.get("STRIPE_PUBLISHABLE_KEY")
        or ""
    ).strip()

    if not key:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "payments_not_configured",
                "message": "Online card payments are not configured.",
            },
        )

    return key


def webhook_secret() -> str:
    secret = (
        os.environ.get("STRIPE_WEBHOOK_SECRET")
        or ""
    ).strip()

    if not secret:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "payments_not_configured",
                "message": "Stripe webhooks are not configured.",
            },
        )

    return secret


def stripe_enabled() -> bool:
    return bool(
        (os.environ.get("STRIPE_SECRET_KEY") or "").strip()
        and
        (os.environ.get("STRIPE_PUBLISHABLE_KEY") or "").strip()
    )


def configure_stripe() -> None:
    stripe.api_key = _secret_key()


async def create_customer(
    *,
    internal_client_id: str,
    email: Optional[str] = None,
) -> stripe.Customer:
    """
    Create a Stripe customer.

    Do not send diagnoses, treatment names, appointment information,
    clinical information, or other PHI to Stripe.
    """

    configure_stripe()

    params: dict[str, Any] = {
        "metadata": {
            "nms_client_ref": str(internal_client_id),
        }
    }

    if email:
        params["email"] = email

    return stripe.Customer.create(**params)


async def create_setup_intent(
    *,
    stripe_customer_id: str,
) -> stripe.SetupIntent:
    """
    Stripe-hosted collection for a reusable payment method.

    PAN/CVC are collected by Stripe Elements, not by NMS.
    """

    configure_stripe()

    return stripe.SetupIntent.create(
        customer=stripe_customer_id,
        usage="off_session",
        payment_method_types=["card"],
    )


async def retrieve_payment_method(
    payment_method_id: str,
) -> stripe.PaymentMethod:
    configure_stripe()

    return stripe.PaymentMethod.retrieve(
        payment_method_id
    )


async def create_invoice_payment_intent(
    *,
    invoice_id: str,
    amount_cents: int,
    currency: str = "usd",
    stripe_customer_id: Optional[str] = None,
) -> stripe.PaymentIntent:
    """
    Create the processor-side payment object for one NMS invoice.

    IMPORTANT:
    - amount_cents must come from the server-side invoice.
    - metadata intentionally contains only an opaque invoice reference.
    - no patient name, treatment, appointment or clinical data.
    """

    if not invoice_id:
        raise ValueError("invoice_id is required")

    if amount_cents <= 0:
        raise ValueError("amount_cents must be greater than zero")

    configure_stripe()

    params: dict[str, Any] = {
        "amount": int(amount_cents),
        "currency": currency.lower(),
        "payment_method_types": ["card"],
        "metadata": {
            "nms_invoice_ref": str(invoice_id),
        },
    }

    if stripe_customer_id:
        params["customer"] = stripe_customer_id

    return stripe.PaymentIntent.create(
        **params,
        idempotency_key=f"nms-invoice-{invoice_id}",
    )


async def retrieve_payment_intent(
    payment_intent_id: str,
) -> stripe.PaymentIntent:
    configure_stripe()

    return stripe.PaymentIntent.retrieve(
        payment_intent_id
    )


def construct_webhook_event(
    *,
    payload: bytes,
    signature: str,
):
    """
    Verify and construct a Stripe webhook event.

    The event must never be trusted until Stripe signature
    verification succeeds.
    """

    if not signature:
        raise ValueError("Missing Stripe-Signature header")

    return stripe.Webhook.construct_event(
        payload=payload,
        sig_header=signature,
        secret=webhook_secret(),
    )


def object_value(obj: Any, key: str, default=None):
    """
    Safely read StripeObject or dict values without depending on
    one Stripe SDK representation.
    """

    if obj is None:
        return default

    if isinstance(obj, dict):
        return obj.get(key, default)

    try:
        return obj.get(key, default)
    except Exception:
        return getattr(obj, key, default)


def safe_payment_intent_summary(
    payment_intent: Any,
) -> dict[str, Any]:
    """
    Processor-safe fields only.

    Never add client_secret or raw processor objects here.
    """

    return {
        "payment_intent_id":
            object_value(payment_intent, "id"),
        "status":
            object_value(payment_intent, "status"),
        "amount":
            object_value(payment_intent, "amount"),
        "currency":
            object_value(payment_intent, "currency"),
        "payment_method_id":
            object_value(payment_intent, "payment_method"),
    }
