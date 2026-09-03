"""
Deterministic appointment-abuse policy.

This module does not:
- contact Cloudflare;
- access the database;
- create appointment requests;
- emit marketing events;
- store contact information;
- send notifications.

It evaluates already-collected, privacy-minimized signals.

External verification, persistence, and rate counters belong at
the public appointment boundary and are supplied to this policy.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import asdict, dataclass
from typing import Optional, Tuple


# ---------------------------------------------------------------------------
# Policy thresholds
# ---------------------------------------------------------------------------

IP_ATTEMPTS_15M_LIMIT = 5
CONTACT_ATTEMPTS_24H_LIMIT = 3
SUBJECT_ATTEMPTS_1H_LIMIT = 3
DUPLICATE_SLOT_LIMIT = 2

FAST_SUBMISSION_SECONDS = 3.0

REVIEW_SCORE = 30
BLOCK_SCORE = 60


@dataclass(frozen=True)
class AppointmentAbuseSignals:
    """
    Privacy-minimized signals for one public appointment attempt.

    Counter values represent attempts including the current request
    if the caller's counter implementation uses hit-before-evaluate.
    """

    honeypot_filled: bool = False

    # None means Turnstile has not yet been integrated / evaluated.
    # False means verification was attempted and failed.
    # True means Cloudflare verified the challenge.
    turnstile_verified: Optional[bool] = None

    ip_attempts_15m: int = 1
    contact_attempts_24h: int = 1
    subject_attempts_1h: int = 1
    duplicate_slot_attempts: int = 1

    submission_age_seconds: Optional[float] = None

    suspicious_user_agent: bool = False
    malformed_client_context: bool = False
    missing_marketing_subject: bool = False


@dataclass(frozen=True)
class AppointmentAbuseDecision:
    action: str
    risk_score: int
    reason_codes: Tuple[str, ...]
    allow_appointment_creation: bool
    allow_marketing_event: bool

    def as_dict(self) -> dict:
        return asdict(self)


def contact_fingerprint(
    *,
    email: str,
    phone: str,
    secret: str,
) -> str:
    """
    Return a non-reversible keyed fingerprint for velocity checks.

    Raw email/phone must not be written to abuse-counter storage.

    The secret must come from server-side configuration and must never
    be exposed to the browser.
    """

    normalized_email = (
        email or ""
    ).strip().lower()

    normalized_phone = "".join(
        ch
        for ch in (phone or "")
        if ch.isdigit()
    )

    canonical = (
        normalized_email
        + "|"
        + normalized_phone
    )

    if not secret:
        raise ValueError(
            "appointment abuse fingerprint secret is required"
        )

    return hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _nonnegative(
    value: int,
) -> int:
    try:
        return max(
            0,
            int(value),
        )
    except (
        TypeError,
        ValueError,
    ):
        return 0


def assess_appointment_abuse(
    signals: AppointmentAbuseSignals,
    *,
    require_turnstile: bool = False,
) -> AppointmentAbuseDecision:
    """
    Produce a deterministic risk decision.

    Exact scoring should not be disclosed to public clients.
    Public routes should return generic responses.
    """

    score = 0
    reasons = []

    # ---------------------------------------------------------------
    # Hard-fail bot signals
    # ---------------------------------------------------------------

    if signals.honeypot_filled:
        score += 100
        reasons.append(
            "honeypot_triggered"
        )

    if signals.turnstile_verified is False:
        score += 100
        reasons.append(
            "turnstile_failed"
        )

    if (
        require_turnstile
        and signals.turnstile_verified
        is not True
    ):
        score += 100
        reasons.append(
            "turnstile_required"
        )

    # ---------------------------------------------------------------
    # Velocity
    # ---------------------------------------------------------------

    ip_attempts = _nonnegative(
        signals.ip_attempts_15m
    )

    if (
        ip_attempts
        > IP_ATTEMPTS_15M_LIMIT
    ):
        score += 35
        reasons.append(
            "ip_velocity"
        )

    contact_attempts = _nonnegative(
        signals.contact_attempts_24h
    )

    if (
        contact_attempts
        > CONTACT_ATTEMPTS_24H_LIMIT
    ):
        score += 40
        reasons.append(
            "contact_velocity"
        )

    subject_attempts = _nonnegative(
        signals.subject_attempts_1h
    )

    if (
        subject_attempts
        > SUBJECT_ATTEMPTS_1H_LIMIT
    ):
        score += 35
        reasons.append(
            "subject_velocity"
        )

    duplicates = _nonnegative(
        signals.duplicate_slot_attempts
    )

    if (
        duplicates
        > DUPLICATE_SLOT_LIMIT
    ):
        score += 40
        reasons.append(
            "duplicate_slot"
        )

    # ---------------------------------------------------------------
    # Behavioral/context signals
    # ---------------------------------------------------------------

    age = signals.submission_age_seconds

    if (
        age is not None
        and age >= 0
        and age < FAST_SUBMISSION_SECONDS
    ):
        score += 30
        reasons.append(
            "submission_too_fast"
        )

    if signals.suspicious_user_agent:
        score += 20
        reasons.append(
            "suspicious_user_agent"
        )

    if signals.malformed_client_context:
        score += 15
        reasons.append(
            "malformed_client_context"
        )

    if signals.missing_marketing_subject:
        score += 15
        reasons.append(
            "missing_marketing_subject"
        )

    score = min(
        100,
        max(
            0,
            score,
        ),
    )

    # ---------------------------------------------------------------
    # Decision
    # ---------------------------------------------------------------

    if score >= BLOCK_SCORE:
        action = "block"

    elif score >= REVIEW_SCORE:
        action = "review"

    else:
        action = "accept"

    # V1 deliberately prevents both appointment creation and the
    # high-intent marketing event for blocked attempts.
    #
    # Review may later become email verification or a staff review
    # queue. For now it is not considered safe for automatic creation.
    allow_creation = (
        action == "accept"
    )

    return AppointmentAbuseDecision(
        action=action,
        risk_score=score,
        reason_codes=tuple(
            reasons
        ),
        allow_appointment_creation=(
            allow_creation
        ),
        allow_marketing_event=(
            allow_creation
        ),
    )
