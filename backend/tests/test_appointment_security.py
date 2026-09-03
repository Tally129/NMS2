from __future__ import annotations

import pytest

import appointment_security
from appointment_turnstile import (
    TurnstileVerification,
)


async def verified_turnstile(
    **kwargs,
):
    return TurnstileVerification(
        verified=True,
        reason="verified",
        hostname="app.natmedsol.org",
        action="appointment_request",
    )


async def failed_turnstile(
    **kwargs,
):
    return TurnstileVerification(
        verified=False,
        reason="turnstile_failed",
        error_codes=(
            "invalid-input-response",
        ),
    )


async def unavailable_turnstile(
    **kwargs,
):
    return TurnstileVerification(
        verified=False,
        reason="verification_unavailable",
    )


@pytest.mark.asyncio
async def test_clean_submission_is_accepted(
    monkeypatch,
):
    monkeypatch.setattr(
        appointment_security,
        "verify_appointment_turnstile",
        verified_turnstile,
    )

    result = await (
        appointment_security
        .evaluate_public_appointment_security(
            turnstile_token="token",
            remote_ip="203.0.113.10",
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action=(
                "appointment_request"
            ),
            submission_age_seconds=20,
        )
    )

    assert result.action == "accept"
    assert result.risk_score == 0

    assert (
        result.allow_appointment_creation
        is True
    )

    assert (
        result.allow_marketing_event
        is True
    )

    assert result.turnstile_verified is True


@pytest.mark.asyncio
async def test_failed_turnstile_blocks(
    monkeypatch,
):
    monkeypatch.setattr(
        appointment_security,
        "verify_appointment_turnstile",
        failed_turnstile,
    )

    result = await (
        appointment_security
        .evaluate_public_appointment_security(
            turnstile_token="bad-token",
            remote_ip="203.0.113.10",
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action=(
                "appointment_request"
            ),
        )
    )

    assert result.action == "block"

    assert (
        result.allow_appointment_creation
        is False
    )

    assert (
        result.allow_marketing_event
        is False
    )

    assert result.turnstile_verified is False

    assert (
        "turnstile:turnstile_failed"
        in result.reason_codes
    )


@pytest.mark.asyncio
async def test_turnstile_unavailable_fails_closed(
    monkeypatch,
):
    monkeypatch.setattr(
        appointment_security,
        "verify_appointment_turnstile",
        unavailable_turnstile,
    )

    result = await (
        appointment_security
        .evaluate_public_appointment_security(
            turnstile_token="token",
            remote_ip=None,
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action=(
                "appointment_request"
            ),
        )
    )

    assert result.action == "block"

    assert (
        result.turnstile_reason
        == "verification_unavailable"
    )


@pytest.mark.asyncio
async def test_honeypot_blocks_even_with_valid_turnstile(
    monkeypatch,
):
    monkeypatch.setattr(
        appointment_security,
        "verify_appointment_turnstile",
        verified_turnstile,
    )

    result = await (
        appointment_security
        .evaluate_public_appointment_security(
            turnstile_token="token",
            remote_ip=None,
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action=(
                "appointment_request"
            ),
            honeypot_filled=True,
        )
    )

    assert result.action == "block"

    assert (
        "honeypot_triggered"
        in result.reason_codes
    )


@pytest.mark.asyncio
async def test_ip_velocity_goes_to_review(
    monkeypatch,
):
    monkeypatch.setattr(
        appointment_security,
        "verify_appointment_turnstile",
        verified_turnstile,
    )

    result = await (
        appointment_security
        .evaluate_public_appointment_security(
            turnstile_token="token",
            remote_ip=None,
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action=(
                "appointment_request"
            ),
            ip_attempts_15m=6,
        )
    )

    assert result.action == "review"

    assert (
        result.allow_appointment_creation
        is False
    )

    assert (
        result.allow_marketing_event
        is False
    )


@pytest.mark.asyncio
async def test_combined_velocity_blocks(
    monkeypatch,
):
    monkeypatch.setattr(
        appointment_security,
        "verify_appointment_turnstile",
        verified_turnstile,
    )

    result = await (
        appointment_security
        .evaluate_public_appointment_security(
            turnstile_token="token",
            remote_ip=None,
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action=(
                "appointment_request"
            ),
            ip_attempts_15m=6,
            contact_attempts_24h=4,
        )
    )

    assert result.action == "block"


@pytest.mark.asyncio
async def test_fast_submission_goes_to_review(
    monkeypatch,
):
    monkeypatch.setattr(
        appointment_security,
        "verify_appointment_turnstile",
        verified_turnstile,
    )

    result = await (
        appointment_security
        .evaluate_public_appointment_security(
            turnstile_token="token",
            remote_ip=None,
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action=(
                "appointment_request"
            ),
            submission_age_seconds=1,
        )
    )

    assert result.action == "review"


@pytest.mark.asyncio
async def test_missing_subject_is_not_block_by_itself(
    monkeypatch,
):
    monkeypatch.setattr(
        appointment_security,
        "verify_appointment_turnstile",
        verified_turnstile,
    )

    result = await (
        appointment_security
        .evaluate_public_appointment_security(
            turnstile_token="token",
            remote_ip=None,
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action=(
                "appointment_request"
            ),
            missing_marketing_subject=True,
            submission_age_seconds=20,
        )
    )

    assert result.risk_score == 15
    assert result.action == "accept"


@pytest.mark.asyncio
async def test_review_never_allows_marketing_event(
    monkeypatch,
):
    monkeypatch.setattr(
        appointment_security,
        "verify_appointment_turnstile",
        verified_turnstile,
    )

    result = await (
        appointment_security
        .evaluate_public_appointment_security(
            turnstile_token="token",
            remote_ip=None,
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action=(
                "appointment_request"
            ),
            suspicious_user_agent=True,
            malformed_client_context=True,
        )
    )

    assert result.action == "review"

    assert (
        result.allow_marketing_event
        is False
    )


@pytest.mark.asyncio
async def test_security_result_contains_no_contact_data(
    monkeypatch,
):
    monkeypatch.setattr(
        appointment_security,
        "verify_appointment_turnstile",
        verified_turnstile,
    )

    result = (
        await appointment_security
        .evaluate_public_appointment_security(
            turnstile_token="token",
            remote_ip=None,
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action=(
                "appointment_request"
            ),
        )
    ).as_dict()

    forbidden = {
        "email",
        "phone",
        "first_name",
        "last_name",
        "patient_name",
        "medical_history",
        "diagnosis",
        "medications",
        "turnstile_token",
        "turnstile_secret",
    }

    assert not (
        forbidden
        & set(result)
    )


@pytest.mark.asyncio
async def test_turnstile_inputs_forwarded_correctly(
    monkeypatch,
):
    captured = {}

    async def fake_verify(
        **kwargs,
    ):
        captured.update(kwargs)

        return TurnstileVerification(
            verified=True,
            reason="verified",
            hostname=(
                "app.natmedsol.org"
            ),
            action=(
                "appointment_request"
            ),
        )

    monkeypatch.setattr(
        appointment_security,
        "verify_appointment_turnstile",
        fake_verify,
    )

    await (
        appointment_security
        .evaluate_public_appointment_security(
            turnstile_token=(
                "browser-token"
            ),
            remote_ip="203.0.113.50",
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action=(
                "appointment_request"
            ),
            turnstile_secret=(
                "test-secret"
            ),
        )
    )

    assert (
        captured["token"]
        == "browser-token"
    )

    assert (
        captured["remote_ip"]
        == "203.0.113.50"
    )

    assert (
        captured["expected_action"]
        == "appointment_request"
    )

    assert (
        captured["secret"]
        == "test-secret"
    )
