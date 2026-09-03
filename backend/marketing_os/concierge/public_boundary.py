"""
HTTP-independent security boundary for the public NMS AI Concierge.

This module owns validation that must happen before the grounded engine
is invoked by a browser-facing route.

The route remains disabled by policy until the production boundary is
fully hardened and deliberately enabled.
"""

from __future__ import annotations

import os
import hmac

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from marketing_os.concierge.policy import (
    DEFAULT_CONCIERGE_POLICY,
)
from marketing_os.concierge.schemas import (
    ConciergeChatRequest,
    ConciergePublicAppointmentRequest,
)


CONCIERGE_BFF_KEY_ENV = "NMS_CONCIERGE_BFF_KEY"
PUBLIC_CHAT_ENV = "NMS_CONCIERGE_PUBLIC_CHAT_ENABLED"
PUBLIC_APPOINTMENT_ENV = (
    "NMS_CONCIERGE_PUBLIC_APPOINTMENT_ENABLED"
)


def _strict_publication_flag(name: str) -> bool:
    """Fail closed unless value is exactly lowercase true."""
    return os.environ.get(name) == "true"


MAX_PUBLIC_CHAT_BODY_BYTES = 16 * 1024

# Exact browser origins only. No wildcard origins and no suffix matching.
#
# Preview is explicitly included for controlled staging.
# Production website origins are included now so enabling later does not
# require weakening validation.
ALLOWED_CONCIERGE_ORIGINS = frozenset(
    {
        "https://preview.natmedsol.org",
        "https://www.natmedsol.com",
        "https://natmedsol.com",
    }
)


@dataclass(frozen=True)
class PublicBoundaryError(Exception):
    status_code: int
    code: str



def require_concierge_bff_key(
    supplied_key: str | None,
) -> None:
    """
    Authenticate the trusted website BFF before processing visitor input.

    The key is server-to-server only and must never be exposed to browser
    JavaScript. Missing backend configuration fails closed.
    """
    expected = os.environ.get(
        CONCIERGE_BFF_KEY_ENV,
        "",
    )

    supplied = str(
        supplied_key or ""
    )

    # Require substantial entropy in the configured credential.
    if len(expected) < 32:
        raise PublicBoundaryError(
            status_code=404,
            code="concierge_not_available",
        )

    if not supplied:
        raise PublicBoundaryError(
            status_code=404,
            code="concierge_not_available",
        )

    if not hmac.compare_digest(
        supplied,
        expected,
    ):
        raise PublicBoundaryError(
            status_code=404,
            code="concierge_not_available",
        )


def public_appointment_enabled() -> bool:
    """Independent fail-closed appointment publication gate."""
    return _strict_publication_flag(
        PUBLIC_APPOINTMENT_ENV
    )


def public_chat_enabled() -> bool:
    """Independent fail-closed public chat publication gate."""
    return _strict_publication_flag(
        PUBLIC_CHAT_ENV
    )


def normalize_origin(
    value: str | None,
) -> str | None:
    raw = str(value or "").strip()

    if not raw:
        return None

    try:
        parsed = urlparse(raw)
    except (TypeError, ValueError):
        return None

    if parsed.scheme != "https":
        return None

    if (
        parsed.username is not None
        or parsed.password is not None
    ):
        return None

    try:
        port = parsed.port
    except ValueError:
        return None

    # Browser Origin values for these production HTTPS origins should
    # not contain an explicit port.
    if port is not None:
        return None

    if parsed.path not in ("", "/"):
        return None

    if parsed.params or parsed.query or parsed.fragment:
        return None

    host = (
        parsed.hostname or ""
    ).lower()

    if not host:
        return None

    return f"https://{host}"


def require_allowed_origin(
    value: str | None,
) -> str:
    normalized = normalize_origin(
        value
    )

    if (
        normalized is None
        or normalized
        not in ALLOWED_CONCIERGE_ORIGINS
    ):
        raise PublicBoundaryError(
            status_code=403,
            code="concierge_origin_not_allowed",
        )

    return normalized


def parse_public_chat_body(
    raw_body: bytes,
) -> ConciergeChatRequest:
    if len(raw_body) > MAX_PUBLIC_CHAT_BODY_BYTES:
        raise PublicBoundaryError(
            status_code=413,
            code="concierge_request_too_large",
        )

    if not raw_body:
        raise PublicBoundaryError(
            status_code=400,
            code="concierge_request_body_required",
        )

    try:
        decoded = raw_body.decode(
            "utf-8"
        )
        parsed: Any = json.loads(
            decoded
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        raise PublicBoundaryError(
            status_code=400,
            code="concierge_invalid_json",
        )

    if not isinstance(
        parsed,
        dict,
    ):
        raise PublicBoundaryError(
            status_code=400,
            code="concierge_json_object_required",
        )

    try:
        return ConciergeChatRequest.model_validate(
            parsed
        )
    except Exception:
        # Do not reflect visitor content or detailed validation internals
        # from this public boundary.
        raise PublicBoundaryError(
            status_code=422,
            code="concierge_invalid_request",
        )


def parse_public_appointment_body(
    raw_body: bytes,
) -> ConciergePublicAppointmentRequest:
    """
    Parse the browser-facing Concierge appointment body.

    Uses the same small public request ceiling as chat and never
    reflects detailed Pydantic validation information to visitors.
    """
    if len(raw_body) > MAX_PUBLIC_CHAT_BODY_BYTES:
        raise PublicBoundaryError(
            status_code=413,
            code="concierge_request_too_large",
        )

    if not raw_body:
        raise PublicBoundaryError(
            status_code=400,
            code="concierge_request_body_required",
        )

    try:
        decoded = raw_body.decode(
            "utf-8"
        )
        parsed: Any = json.loads(
            decoded
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        raise PublicBoundaryError(
            status_code=400,
            code="concierge_invalid_json",
        )

    if not isinstance(
        parsed,
        dict,
    ):
        raise PublicBoundaryError(
            status_code=400,
            code="concierge_json_object_required",
        )

    try:
        return (
            ConciergePublicAppointmentRequest
            .model_validate(parsed)
        )
    except Exception:
        raise PublicBoundaryError(
            status_code=422,
            code="concierge_invalid_request",
        )

