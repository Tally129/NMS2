"""
Natural Medical Solutions PayPal / Apple Pay boundary.

SECURITY:
- PayPal credentials remain server-side.
- PayPal Wallet credentials never enter NMS storage.
- Apple Pay payment credentials never enter NMS storage.
- Do not send PHI to PayPal metadata/order descriptions.
- Browser approval is NOT proof of settlement.
- Capture/webhook confirmation controls paid status.
"""
import hashlib

import os
from typing import Any, Dict

import httpx
from fastapi import HTTPException


def paypal_environment() -> str:
    value = (
        os.environ.get("PAYPAL_ENV")
        or "sandbox"
    ).strip().lower()

    if value not in {"sandbox", "live"}:
        return "sandbox"

    return value


def paypal_api_base() -> str:
    if paypal_environment() == "live":
        return "https://api-m.paypal.com"

    return "https://api-m.sandbox.paypal.com"


def paypal_web_sdk_url() -> str:
    if paypal_environment() == "live":
        return "https://www.paypal.com/web-sdk/v6/core"

    return (
        "https://www.sandbox.paypal.com/"
        "web-sdk/v6/core"
    )


def _client_id() -> str:
    value = (
        os.environ.get("PAYPAL_CLIENT_ID")
        or ""
    ).strip()

    if not value:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "paypal_not_configured",
                "message": (
                    "PayPal payments are not configured."
                ),
            },
        )

    return value


def _client_secret() -> str:
    value = (
        os.environ.get("PAYPAL_CLIENT_SECRET")
        or ""
    ).strip()

    if not value:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "paypal_not_configured",
                "message": (
                    "PayPal payments are not configured."
                ),
            },
        )

    return value


def paypal_enabled() -> bool:
    return (
        os.environ.get(
            "PAYPAL_ENABLED",
            "false",
        ).lower()
        == "true"
    )


def apple_pay_enabled() -> bool:
    return (
        paypal_enabled()
        and os.environ.get(
            "PAYPAL_APPLE_PAY_ENABLED",
            "false",
        ).lower()
        == "true"
    )


def public_payment_config() -> Dict[str, Any]:
    """
    Browser-safe payment capability information.

    Secrets are never returned.

    Stripe owns card and Stripe-supported wallet checkout.
    PayPal remains an independent payment provider.
    """

    # Import locally to keep this PayPal boundary free of
    # Stripe initialization side effects at module import time.
    from services.payments import stripe_enabled

    stripe_ready = stripe_enabled()

    return {
        "stripe": {
            "enabled": stripe_ready,
            "card": {
                "enabled": stripe_ready,
            },
            "apple_pay": {
                "enabled": stripe_ready,
                "provider": "stripe",
            },
            "google_pay": {
                "enabled": stripe_ready,
                "provider": "stripe",
            },
        },
        "paypal": {
            "enabled": paypal_enabled(),
            "environment": paypal_environment(),
            "client_id": (
                _client_id()
                if paypal_enabled()
                else None
            ),
            "sdk_url": paypal_web_sdk_url(),
        },
        # Compatibility key for any older frontend consumer.
        # Apple Pay is no longer reported as PayPal-owned.
        "apple_pay": {
            "enabled": stripe_ready,
            "provider": "stripe",
        },
    }


async def get_access_token() -> str:
    """
    Server-side PayPal OAuth token.

    Never expose this token to application logs.
    """

    client_id = _client_id()
    secret = _client_secret()

    async with httpx.AsyncClient(
        timeout=20.0
    ) as client:
        response = await client.post(
            (
                f"{paypal_api_base()}"
                "/v1/oauth2/token"
            ),
            auth=(client_id, secret),
            data={
                "grant_type":
                    "client_credentials"
            },
            headers={
                "Accept":
                    "application/json",
                "Accept-Language":
                    "en_US",
            },
        )

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "paypal_auth_failed",
                "message": (
                    "PayPal authentication failed."
                ),
            },
        )

    data = response.json()
    token = data.get("access_token")

    if not token:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "paypal_auth_failed",
                "message": (
                    "PayPal did not return an "
                    "access token."
                ),
            },
        )

    return token


def _paypal_request_id(
    operation: str,
    resource_key: str,
) -> str:
    """
    Return a deterministic opaque PayPal idempotency key.

    The same logical NMS operation gets the same request ID on
    retries, while create and capture remain separate operations.
    """
    raw = (
        f"{operation}:{resource_key}"
    ).encode("utf-8")

    return hashlib.sha256(raw).hexdigest()[:32]


async def create_order(
    *,
    amount_cents: int,
    currency: str,
    internal_reference: str,
) -> Dict[str, Any]:
    """
    Create a CAPTURE order.

    internal_reference must be an opaque NMS identifier.
    Do not include patient names, treatments, diagnoses,
    or other PHI.
    """

    if amount_cents <= 0:
        raise HTTPException(
            status_code=400,
            detail="Invalid payment amount",
        )

    token = await get_access_token()

    amount = (
        f"{amount_cents // 100}."
        f"{amount_cents % 100:02d}"
    )

    payload = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "reference_id":
                    internal_reference,
                "amount": {
                    "currency_code":
                        currency.upper(),
                    "value": amount,
                },
            }
        ],
    }

    async with httpx.AsyncClient(
        timeout=20.0
    ) as client:
        response = await client.post(
            (
                f"{paypal_api_base()}"
                "/v2/checkout/orders"
            ),
            headers={
                "Authorization":
                    f"Bearer {token}",
                "Content-Type":
                    "application/json",
                "Prefer":
                    "return=representation",
                "PayPal-Request-Id":
                    _paypal_request_id(
                        "create-order",
                        internal_reference,
                    ),
            },
            json=payload,
        )

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "paypal_order_failed",
                "message": (
                    "Unable to create PayPal order."
                ),
            },
        )

    return response.json()


async def capture_order(
    order_id: str,
) -> Dict[str, Any]:
    """
    Capture an approved PayPal / Apple Pay order.

    The caller must still validate the returned capture
    status before changing an invoice to paid.
    """

    token = await get_access_token()

    async with httpx.AsyncClient(
        timeout=20.0
    ) as client:
        response = await client.post(
            (
                f"{paypal_api_base()}"
                f"/v2/checkout/orders/{order_id}"
                "/capture"
            ),
            headers={
                "Authorization":
                    f"Bearer {token}",
                "Content-Type":
                    "application/json",
                "Prefer":
                    "return=representation",
                "PayPal-Request-Id":
                    _paypal_request_id(
                        "capture-order",
                        order_id,
                    ),
            },
        )

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "paypal_capture_failed",
                "message": (
                    "Unable to capture PayPal payment."
                ),
            },
        )

    return response.json()


def capture_completed(
    data: Dict[str, Any],
) -> bool:
    """
    Only completed capture status counts as settlement.
    """

    units = data.get("purchase_units") or []

    for unit in units:
        payments = unit.get("payments") or {}

        for capture in (
            payments.get("captures")
            or []
        ):
            if (
                capture.get("status")
                == "COMPLETED"
            ):
                return True

    return False


def capture_reference(
    data: Dict[str, Any],
) -> str | None:
    for unit in (
        data.get("purchase_units")
        or []
    ):
        payments = unit.get("payments") or {}

        for capture in (
            payments.get("captures")
            or []
        ):
            if capture.get("id"):
                return capture["id"]

    return None




def completed_capture_details(
    data: Dict[str, Any],
) -> Dict[str, Any] | None:
    """
    Return details from the first COMPLETED PayPal capture.

    The caller must validate processor amount and currency
    against the authoritative server-side NMS invoice before
    settlement.
    """
    for unit in data.get("purchase_units") or []:
        payments = unit.get("payments") or {}

        for capture in payments.get("captures") or []:
            if capture.get("status") != "COMPLETED":
                continue

            amount = capture.get("amount") or {}

            return {
                "capture_id": capture.get("id"),
                "currency": amount.get("currency_code"),
                "value": amount.get("value"),
            }

    return None



def order_reference(
    data: Dict[str, Any],
) -> str | None:
    """
    Return the PayPal purchase-unit reference_id.

    NMS uses this to bind a processor order back to the
    exact invoice that created it.
    """

    units = data.get("purchase_units") or []

    for unit in units:
        reference = unit.get("reference_id")

        if reference:
            return str(reference)

    return None
