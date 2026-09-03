import json

import pytest
from pydantic import ValidationError

from marketing_os.concierge.public_boundary import (
    PublicBoundaryError,
    parse_public_appointment_body,
)
from marketing_os.concierge.schemas import (
    ConciergePublicAppointmentRequest,
)


def valid_payload():
    return {
        "first_name": "Test",
        "last_name": "Visitor",
        "email": "visitor@example.com",
        "phone": "7705550100",
        "returning": "first",
        "date": "2099-12-31",
        "time": "10:30",
        "confirmed": True,
        "idempotency_key":
            "opaque_test_key_123456789",
    }


def parse(payload):
    return parse_public_appointment_body(
        json.dumps(payload).encode(
            "utf-8"
        )
    )


def test_valid_contract():
    payload = parse(
        valid_payload()
    )

    assert payload.first_name == "Test"
    assert payload.last_name == "Visitor"
    assert payload.confirmed is True


@pytest.mark.parametrize(
    "field",
    [
        "notes",
        "addOns",
        "add_ons",
        "medical_history",
        "medications",
        "labs",
        "diagnosis",
        "dob",
        "insurance_id",
        "message",
    ],
)
def test_sensitive_or_free_text_fields_forbidden(
    field,
):
    body = valid_payload()
    body[field] = "must not be accepted"

    with pytest.raises(
        PublicBoundaryError
    ) as exc:
        parse(body)

    assert exc.value.status_code == 422
    assert (
        exc.value.code
        == "concierge_invalid_request"
    )


def test_confirmation_must_be_literal_true():
    body = valid_payload()
    body["confirmed"] = False

    with pytest.raises(
        PublicBoundaryError
    ):
        parse(body)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "short",
        "contains spaces 123456",
        "contains@email.example",
        "bad/slash/key/123456789",
    ],
)
def test_idempotency_key_is_strict(
    value,
):
    body = valid_payload()
    body["idempotency_key"] = value

    with pytest.raises(
        PublicBoundaryError
    ):
        parse(body)


def test_extra_fields_forbidden_at_model_level():
    body = valid_payload()
    body["unexpected"] = "x"

    with pytest.raises(
        ValidationError
    ):
        (
            ConciergePublicAppointmentRequest
            .model_validate(body)
        )


def test_body_must_be_json_object():
    with pytest.raises(
        PublicBoundaryError
    ) as exc:
        parse_public_appointment_body(
            b'["not", "an", "object"]'
        )

    assert exc.value.status_code == 400


def test_body_size_is_limited():
    huge = (
        b"{"
        + b"x" * (16 * 1024 + 1)
        + b"}"
    )

    with pytest.raises(
        PublicBoundaryError
    ) as exc:
        parse_public_appointment_body(
            huge
        )

    assert exc.value.status_code == 413
