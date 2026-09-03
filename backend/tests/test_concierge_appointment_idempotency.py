import re

import pytest

from marketing_os.concierge.appointment_handoff import (
    ConciergeAppointmentRequest,
    build_appointment_document,
    hash_idempotency_key,
)


def _request():
    return ConciergeAppointmentRequest(
        full_name="Test Visitor",
        email="visitor@example.com",
        phone="5555550100",
        returning="first",
        service="Consultation",
        date="2026-09-15",
        time="10:00 AM",
    )


def test_hash_is_sha256_and_does_not_equal_raw_key():
    raw = "browser_random_key_123456789"

    digest = hash_idempotency_key(
        raw
    )

    assert digest != raw
    assert len(digest) == 64
    assert re.fullmatch(
        r"[0-9a-f]{64}",
        digest,
    )


@pytest.mark.parametrize(
    "key",
    (
        "",
        "short",
        "contains spaces 123456",
        "contains@email.example",
        "x" * 129,
    ),
)
def test_invalid_idempotency_keys_are_rejected(
    key,
):
    with pytest.raises(ValueError):
        hash_idempotency_key(
            key
        )


def test_document_never_contains_notes_or_addons():
    digest = hash_idempotency_key(
        "browser_random_key_123456789"
    )

    doc = build_appointment_document(
        _request(),
        client_ip="127.0.0.1",
        concierge_idempotency_key=digest,
    )

    assert doc["notes"] is None
    assert doc["addOns"] == []
    assert (
        doc["concierge_idempotency_key"]
        == digest
    )


def test_request_contract_has_no_clinical_fields():
    fields = set(
        ConciergeAppointmentRequest
        .__dataclass_fields__
    )

    assert "medical_history" not in fields
    assert "medications" not in fields
    assert "diagnosis" not in fields
    assert "labs" not in fields
