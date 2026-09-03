"""
Shared public-appointment security boundary.

This module composes:

1. Server-side Cloudflare Turnstile verification.
2. Deterministic appointment-abuse policy evaluation.

It intentionally does not:
- create appointment requests;
- access or mutate the database;
- emit marketing conversions;
- send email;
- persist contact data;
- expose risk details to public clients.

Route-specific persistence and public HTTP responses remain outside
this module.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from appointment_abuse import (
    AppointmentAbuseDecision,
    AppointmentAbuseSignals,
    assess_appointment_abuse,
)

from appointment_turnstile import (
    TurnstileVerification,
    verify_appointment_turnstile,
)


@dataclass(frozen=True)
class AppointmentSecurityResult:
    action: str
    risk_score: int
    reason_codes: tuple[str, ...]

    allow_appointment_creation: bool
    allow_marketing_event: bool

    turnstile_verified: bool
    turnstile_reason: str

    def as_dict(self) -> dict:
        return asdict(self)


def _merge_reasons(
    turnstile: TurnstileVerification,
    abuse: AppointmentAbuseDecision,
) -> tuple[str, ...]:
    """
    Internal reason list.

    These reason codes are suitable for internal audit/security
    handling but must not be reflected verbatim to anonymous clients.
    """

    values = []

    if not turnstile.verified:
        values.append(
            f"turnstile:{turnstile.reason}"
        )

    values.extend(
        abuse.reason_codes
    )

    # Stable, duplicate-free ordering.
    return tuple(
        dict.fromkeys(values)
    )


async def evaluate_public_appointment_security(
    *,
    turnstile_token: str,
    remote_ip: str | None,
    expected_hostnames: Iterable[str],
    expected_action: str,
    honeypot_filled: bool = False,
    ip_attempts_15m: int = 1,
    contact_attempts_24h: int = 1,
    subject_attempts_1h: int = 1,
    duplicate_slot_attempts: int = 1,
    submission_age_seconds: float | None = None,
    suspicious_user_agent: bool = False,
    malformed_client_context: bool = False,
    missing_marketing_subject: bool = False,
    require_turnstile: bool = True,
    turnstile_secret: str | None = None,
) -> AppointmentSecurityResult:
    """
    Evaluate one public appointment submission.

    When Turnstile is required, missing configuration or failed
    verification fails closed through the abuse policy.
    """

    verification = (
        await verify_appointment_turnstile(
            token=turnstile_token,
            remote_ip=remote_ip,
            expected_hostnames=(
                expected_hostnames
            ),
            expected_action=expected_action,
            secret=turnstile_secret,
        )
    )

    # The deterministic policy receives only a boolean verification
    # result. It does not receive the visitor token or server secret.
    signals = AppointmentAbuseSignals(
        honeypot_filled=(
            honeypot_filled
        ),
        turnstile_verified=(
            verification.verified
        ),
        ip_attempts_15m=(
            ip_attempts_15m
        ),
        contact_attempts_24h=(
            contact_attempts_24h
        ),
        subject_attempts_1h=(
            subject_attempts_1h
        ),
        duplicate_slot_attempts=(
            duplicate_slot_attempts
        ),
        submission_age_seconds=(
            submission_age_seconds
        ),
        suspicious_user_agent=(
            suspicious_user_agent
        ),
        malformed_client_context=(
            malformed_client_context
        ),
        missing_marketing_subject=(
            missing_marketing_subject
        ),
    )

    decision = assess_appointment_abuse(
        signals,
        require_turnstile=(
            require_turnstile
        ),
    )

    return AppointmentSecurityResult(
        action=decision.action,
        risk_score=decision.risk_score,
        reason_codes=_merge_reasons(
            verification,
            decision,
        ),
        allow_appointment_creation=(
            decision
            .allow_appointment_creation
        ),
        allow_marketing_event=(
            decision
            .allow_marketing_event
        ),
        turnstile_verified=(
            verification.verified
        ),
        turnstile_reason=(
            verification.reason
        ),
    )
