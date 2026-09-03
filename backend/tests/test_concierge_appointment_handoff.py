import pytest

from marketing_os.concierge.appointment_handoff import (
    ConciergeAppointmentRequest,
    build_appointment_document,
)


def test_builds_existing_appointment_contract():
    request = ConciergeAppointmentRequest(
        full_name="Jane Doe",
        email="jane@example.com",
        phone="7705550100",
        returning="first",
        service="Naturopathic Medicine",
        date="2026-09-10",
        time="10:30 AM",
        notes="Interested in learning more.",
        add_ons=("Thermography",),
    )

    doc = build_appointment_document(
        request,
        client_ip="127.0.0.1",
    )

    assert doc["id"]
    assert doc["fullName"] == "Jane Doe"
    assert doc["email"] == "jane@example.com"
    assert doc["phone"] == "7705550100"
    assert doc["returning"] == "first"
    assert doc["service"] == "Naturopathic Medicine"
    assert doc["date"] == "2026-09-10"
    assert doc["time"] == "10:30 AM"
    assert doc["notes"] == "Interested in learning more."
    assert doc["addOns"] == ["Thermography"]
    assert doc["status"] == "new"
    assert doc["ip"] == "127.0.0.1"


def test_requires_full_name():
    with pytest.raises(ValueError, match="full_name is required"):
        build_appointment_document(
            ConciergeAppointmentRequest(full_name="   ")
        )


def test_rejects_invalid_returning_value():
    with pytest.raises(ValueError, match="returning"):
        build_appointment_document(
            ConciergeAppointmentRequest(
                full_name="Jane Doe",
                returning="sometimes",
            )
        )


def test_does_not_include_conversation_or_clinical_context():
    request = ConciergeAppointmentRequest(
        full_name="Jane Doe",
        service="Telehealth",
    )

    doc = build_appointment_document(request)

    forbidden = {
        "conversation",
        "history",
        "messages",
        "knowledge",
        "diagnosis",
        "medications",
        "labs",
        "medical_record",
        "session_id",
    }

    assert forbidden.isdisjoint(doc.keys())


def test_optional_values_are_normalized():
    request = ConciergeAppointmentRequest(
        full_name=" Jane Doe ",
        email=" ",
        phone=" ",
        returning=None,
        service=" Telehealth ",
        add_ons=(" ", "Thermography"),
    )

    doc = build_appointment_document(request)

    assert doc["fullName"] == "Jane Doe"
    assert doc["email"] is None
    assert doc["phone"] is None
    assert doc["returning"] is None
    assert doc["service"] == "Telehealth"
    assert doc["addOns"] == ["Thermography"]


def test_limits_add_on_count():
    request = ConciergeAppointmentRequest(
        full_name="Jane Doe",
        add_ons=tuple(f"item-{i}" for i in range(21)),
    )

    with pytest.raises(ValueError, match="too many add-ons"):
        build_appointment_document(request)


@pytest.mark.asyncio
async def test_concierge_submission_uses_canonical_workflow(
    monkeypatch,
):
    """
    Concierge submission delegates to the canonical appointment workflow.

    No database write and no email occur in this test.
    """
    import appointment_requests
    import marketing_os.concierge.appointment_handoff as handoff_module

    from marketing_os.concierge.appointment_handoff import (
        ConciergeAppointmentRequest,
        create_concierge_appointment_request,
    )

    captured = {}

    async def fake_workflow(
        payload,
        *,
        client_ip=None,
        user_agent=None,
        marketing_attribution=None,
        concierge_idempotency_key=None,
    ):
        captured["payload"] = payload
        captured["client_ip"] = client_ip
        captured["user_agent"] = user_agent
        captured["marketing_attribution"] = (
            marketing_attribution
        )
        captured["concierge_idempotency_key"] = (
            concierge_idempotency_key
        )

        return {
            "ok": True,
            "id": "synthetic-concierge-request",
        }

    async def fake_find_existing(key_hash):
        captured["lookup_key_hash"] = key_hash
        return None

    monkeypatch.setattr(
        handoff_module,
        "_find_existing",
        fake_find_existing,
    )

    monkeypatch.setattr(
        appointment_requests,
        "create_appointment_request_workflow",
        fake_workflow,
    )

    request = ConciergeAppointmentRequest(
        full_name=" Jane Doe ",
        email=" jane@example.com ",
        phone=" 7705550100 ",
        returning="first",
        service=" Telehealth ",
        date="2026-09-10",
        time="10:30 AM",

        # These intentionally demonstrate that even if an internal caller
        # supplies legacy values, public Concierge submission does not
        # forward them into the canonical workflow.
        notes="This must not be forwarded.",
        add_ons=("Thermography",),
    )

    result = await create_concierge_appointment_request(
        request,
        confirmed=True,
        idempotency_key="handoff_test_key_123456789",
        client_ip="127.0.0.1",
    )

    assert result.replayed is False
    assert result.appointment_request == {
        "ok": True,
        "id": "synthetic-concierge-request",
    }

    payload = captured["payload"]

    assert payload.fullName == "Jane Doe"
    assert payload.email == "jane@example.com"
    assert payload.phone == "7705550100"
    assert payload.returning == "first"
    assert payload.service == "Telehealth"
    assert payload.date == "2026-09-10"
    assert payload.time == "10:30 AM"

    # Privacy boundary for public Concierge.
    assert payload.notes is None
    assert payload.addOns == []

    assert captured["client_ip"] == "127.0.0.1"
    assert captured["user_agent"] == "nms-ai-concierge"
    assert captured["marketing_attribution"] is None
