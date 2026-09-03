"""
Server-side Cloudflare Turnstile verification for public
appointment requests.

This adapter:
- validates token shape before network access;
- reads the secret only from server-side configuration;
- calls Cloudflare Siteverify only from the backend;
- validates Cloudflare success, hostname, and action;
- never returns or logs the Turnstile secret or visitor token;
- fails closed on malformed responses and network failures.

It does not:
- create appointments;
- write to the database;
- emit marketing events;
- persist IP addresses;
- make risk-policy decisions.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Iterable, Tuple

import httpx


TURNSTILE_SITEVERIFY_URL = (
    "https://challenges.cloudflare.com/"
    "turnstile/v0/siteverify"
)

TURNSTILE_SECRET_ENV = (
    "NMS_APPOINTMENT_TURNSTILE_SECRET_KEY"
)

TURNSTILE_MAX_TOKEN_LENGTH = 2048

DEFAULT_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class TurnstileVerification:
    verified: bool
    reason: str
    error_codes: Tuple[str, ...] = ()
    hostname: str | None = None
    action: str | None = None


def _clean_text(
    value,
    *,
    max_length: int,
) -> str | None:
    if not isinstance(
        value,
        str,
    ):
        return None

    cleaned = value.strip()

    if (
        not cleaned
        or len(cleaned) > max_length
    ):
        return None

    return cleaned


def _normalize_hostnames(
    hostnames: Iterable[str],
) -> frozenset[str]:
    return frozenset(
        str(hostname)
        .strip()
        .lower()
        for hostname in hostnames
        if str(hostname).strip()
    )


def _safe_error_codes(
    value,
) -> Tuple[str, ...]:
    if not isinstance(
        value,
        list,
    ):
        return ()

    safe = []

    for item in value[:20]:
        if not isinstance(
            item,
            str,
        ):
            continue

        cleaned = item.strip()

        if (
            cleaned
            and len(cleaned) <= 128
        ):
            safe.append(cleaned)

    return tuple(safe)


async def verify_appointment_turnstile(
    *,
    token: str,
    remote_ip: str | None,
    expected_hostnames: Iterable[str],
    expected_action: str,
    secret: str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> TurnstileVerification:
    """
    Verify one Turnstile token against Cloudflare Siteverify.

    A Turnstile token must never be accepted based only on the
    browser-side widget response.
    """

    safe_token = _clean_text(
        token,
        max_length=(
            TURNSTILE_MAX_TOKEN_LENGTH
        ),
    )

    if safe_token is None:
        return TurnstileVerification(
            verified=False,
            reason="invalid_token",
        )

    configured_secret = (
        secret
        if secret is not None
        else os.environ.get(
            TURNSTILE_SECRET_ENV,
            "",
        )
    )

    configured_secret = (
        configured_secret.strip()
        if isinstance(
            configured_secret,
            str,
        )
        else ""
    )

    if not configured_secret:
        return TurnstileVerification(
            verified=False,
            reason="not_configured",
        )

    allowed_hostnames = (
        _normalize_hostnames(
            expected_hostnames
        )
    )

    if not allowed_hostnames:
        return TurnstileVerification(
            verified=False,
            reason="invalid_configuration",
        )

    safe_action = _clean_text(
        expected_action,
        max_length=64,
    )

    if safe_action is None:
        return TurnstileVerification(
            verified=False,
            reason="invalid_configuration",
        )

    payload = {
        "secret": configured_secret,
        "response": safe_token,
        "idempotency_key": str(
            uuid.uuid4()
        ),
    }

    safe_remote_ip = _clean_text(
        remote_ip,
        max_length=64,
    )

    if safe_remote_ip is not None:
        payload["remoteip"] = (
            safe_remote_ip
        )

    try:
        async with httpx.AsyncClient(
            timeout=timeout_seconds,
        ) as client:
            response = await client.post(
                TURNSTILE_SITEVERIFY_URL,
                json=payload,
                headers={
                    "Accept":
                        "application/json",
                },
            )

            response.raise_for_status()

            body = response.json()

    except (
        httpx.HTTPError,
        ValueError,
        TypeError,
    ):
        return TurnstileVerification(
            verified=False,
            reason="verification_unavailable",
        )

    if not isinstance(
        body,
        dict,
    ):
        return TurnstileVerification(
            verified=False,
            reason="invalid_response",
        )

    error_codes = _safe_error_codes(
        body.get(
            "error-codes"
        )
    )

    if body.get("success") is not True:
        return TurnstileVerification(
            verified=False,
            reason="turnstile_failed",
            error_codes=error_codes,
        )

    hostname = _clean_text(
        body.get("hostname"),
        max_length=253,
    )

    if (
        hostname is None
        or hostname.lower()
        not in allowed_hostnames
    ):
        return TurnstileVerification(
            verified=False,
            reason="hostname_mismatch",
            error_codes=error_codes,
            hostname=hostname,
        )

    action = _clean_text(
        body.get("action"),
        max_length=64,
    )

    if action != safe_action:
        return TurnstileVerification(
            verified=False,
            reason="action_mismatch",
            error_codes=error_codes,
            hostname=hostname,
            action=action,
        )

    return TurnstileVerification(
        verified=True,
        reason="verified",
        error_codes=error_codes,
        hostname=hostname,
        action=action,
    )
