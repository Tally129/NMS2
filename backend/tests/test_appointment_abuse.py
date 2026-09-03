import pytest

from appointment_abuse import (
    AppointmentAbuseSignals,
    assess_appointment_abuse,
    contact_fingerprint,
)


def test_clean_request_is_accepted():
    result = assess_appointment_abuse(
        AppointmentAbuseSignals(
            turnstile_verified=True,
            submission_age_seconds=30,
        ),
        require_turnstile=True,
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


def test_honeypot_blocks():
    result = assess_appointment_abuse(
        AppointmentAbuseSignals(
            honeypot_filled=True,
            turnstile_verified=True,
        ),
        require_turnstile=True,
    )

    assert result.action == "block"
    assert (
        "honeypot_triggered"
        in result.reason_codes
    )
    assert (
        result.allow_appointment_creation
        is False
    )
    assert (
        result.allow_marketing_event
        is False
    )


def test_failed_turnstile_blocks():
    result = assess_appointment_abuse(
        AppointmentAbuseSignals(
            turnstile_verified=False,
        )
    )

    assert result.action == "block"
    assert (
        "turnstile_failed"
        in result.reason_codes
    )


def test_required_turnstile_fails_closed_when_missing():
    result = assess_appointment_abuse(
        AppointmentAbuseSignals(
            turnstile_verified=None,
        ),
        require_turnstile=True,
    )

    assert result.action == "block"
    assert (
        "turnstile_required"
        in result.reason_codes
    )


def test_turnstile_can_be_optional_before_integration():
    result = assess_appointment_abuse(
        AppointmentAbuseSignals(
            turnstile_verified=None,
            submission_age_seconds=20,
        ),
        require_turnstile=False,
    )

    assert result.action == "accept"


def test_ip_velocity_alone_goes_to_review():
    result = assess_appointment_abuse(
        AppointmentAbuseSignals(
            turnstile_verified=True,
            ip_attempts_15m=6,
        ),
        require_turnstile=True,
    )

    assert result.action == "review"
    assert result.risk_score == 35
    assert (
        "ip_velocity"
        in result.reason_codes
    )

    # Do not automatically create an appointment
    # from a review decision.
    assert (
        result.allow_appointment_creation
        is False
    )


def test_contact_velocity_alone_goes_to_review():
    result = assess_appointment_abuse(
        AppointmentAbuseSignals(
            turnstile_verified=True,
            contact_attempts_24h=4,
        ),
        require_turnstile=True,
    )

    assert result.action == "review"
    assert result.risk_score == 40


def test_multiple_medium_signals_block():
    result = assess_appointment_abuse(
        AppointmentAbuseSignals(
            turnstile_verified=True,
            ip_attempts_15m=6,
            suspicious_user_agent=True,
            malformed_client_context=True,
        ),
        require_turnstile=True,
    )

    assert result.action == "block"

    assert result.risk_score == 70


def test_fast_submission_is_review():
    result = assess_appointment_abuse(
        AppointmentAbuseSignals(
            turnstile_verified=True,
            submission_age_seconds=1.5,
        ),
        require_turnstile=True,
    )

    assert result.action == "review"
    assert (
        "submission_too_fast"
        in result.reason_codes
    )


def test_duplicate_slot_escalates():
    result = assess_appointment_abuse(
        AppointmentAbuseSignals(
            turnstile_verified=True,
            duplicate_slot_attempts=3,
        ),
        require_turnstile=True,
    )

    assert result.action == "review"

    assert (
        "duplicate_slot"
        in result.reason_codes
    )


def test_combined_velocity_blocks():
    result = assess_appointment_abuse(
        AppointmentAbuseSignals(
            turnstile_verified=True,
            ip_attempts_15m=6,
            contact_attempts_24h=4,
        ),
        require_turnstile=True,
    )

    assert result.action == "block"
    assert result.risk_score == 75


def test_score_is_capped_at_100():
    result = assess_appointment_abuse(
        AppointmentAbuseSignals(
            honeypot_filled=True,
            turnstile_verified=False,
            ip_attempts_15m=100,
            contact_attempts_24h=100,
            subject_attempts_1h=100,
            duplicate_slot_attempts=100,
            submission_age_seconds=0,
            suspicious_user_agent=True,
            malformed_client_context=True,
            missing_marketing_subject=True,
        ),
        require_turnstile=True,
    )

    assert result.risk_score == 100


def test_fingerprint_is_stable_and_normalized():
    first = contact_fingerprint(
        email=" Jane@Example.COM ",
        phone="(404) 555-1212",
        secret="unit-test-secret",
    )

    second = contact_fingerprint(
        email="jane@example.com",
        phone="4045551212",
        secret="unit-test-secret",
    )

    assert first == second
    assert len(first) == 64


def test_fingerprint_changes_with_secret():
    first = contact_fingerprint(
        email="jane@example.com",
        phone="4045551212",
        secret="secret-one",
    )

    second = contact_fingerprint(
        email="jane@example.com",
        phone="4045551212",
        secret="secret-two",
    )

    assert first != second


def test_fingerprint_requires_server_secret():
    with pytest.raises(
        ValueError,
        match="fingerprint secret",
    ):
        contact_fingerprint(
            email="jane@example.com",
            phone="4045551212",
            secret="",
        )


def test_decision_output_contains_no_contact_data():
    result = assess_appointment_abuse(
        AppointmentAbuseSignals(
            turnstile_verified=True,
        ),
        require_turnstile=True,
    ).as_dict()

    forbidden = {
        "email",
        "phone",
        "first_name",
        "last_name",
        "patient_name",
        "diagnosis",
        "medical_history",
        "medications",
    }

    assert not (
        forbidden
        & set(result)
    )
