from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from marketing_os.concierge.public_boundary import (
    public_appointment_enabled,
    public_chat_enabled,
)
from marketing_os.concierge.schemas import (
    ConciergePublicAppointmentRequest,
)


def _payload(**changes):
    data = {
        "first_name": "Jane",
        "last_name": "Example",
        "email": "jane@example.com",
        "phone": "404-555-1212",
        "returning": "first",
        "date": (
            date.today()
            + timedelta(days=7)
        ).isoformat(),
        "time": "14:30",
        "confirmed": True,
        "idempotency_key":
            "abcdefghijklmnop123456",
    }

    data.update(changes)

    return data


def test_publication_gates_independent_and_closed():
    assert public_chat_enabled() is False
    assert public_appointment_enabled() is False


def test_contact_required_and_normalized():
    obj = ConciergePublicAppointmentRequest(
        **_payload(
            first_name="  Jane ",
            last_name=" Example ",
            email="JANE@EXAMPLE.COM",
            phone="(404) 555-1212",
        )
    )

    assert obj.first_name == "Jane"
    assert obj.last_name == "Example"
    assert obj.email == "jane@example.com"
    assert obj.phone == "404-555-1212"


@pytest.mark.parametrize(
    "field",
    ["email", "phone"],
)
def test_contact_cannot_be_omitted(field):
    data = _payload()
    data.pop(field)

    with pytest.raises(ValidationError):
        ConciergePublicAppointmentRequest(
            **data
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"email": "not-an-email"},
        {"phone": "123"},
        {"time": "25:99"},
        {"date": "2026-99-99"},
        {
            "date": (
                date.today()
                - timedelta(days=1)
            ).isoformat()
        },
    ],
)
def test_invalid_contact_schedule_rejected(
    changes,
):
    with pytest.raises(ValidationError):
        ConciergePublicAppointmentRequest(
            **_payload(**changes)
        )


@pytest.mark.parametrize(
    "field",
    [
        "service",
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
def test_forbidden_field_rejected(field):
    with pytest.raises(ValidationError):
        ConciergePublicAppointmentRequest(
            **_payload(
                **{field: "forbidden"}
            )
        )


def test_service_id_shape_is_narrow():
    obj = ConciergePublicAppointmentRequest(
        **_payload(
            service_id="abc_123-XYZ"
        )
    )

    assert obj.service_id == "abc_123-XYZ"

    with pytest.raises(ValidationError):
        ConciergePublicAppointmentRequest(
            **_payload(
                service_id="arbitrary service"
            )
        )
