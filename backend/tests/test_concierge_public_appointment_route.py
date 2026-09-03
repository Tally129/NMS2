import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import marketing_os.routers.concierge as router


TEST_BFF_KEY = "T" * 64


class FakeRequest:
    def __init__(
        self,
        payload,
        *,
        origin="https://preview.natmedsol.org",
        client_host="203.0.113.10",
    ):
        self._body = json.dumps(
            payload
        ).encode("utf-8")

        self.headers = {
            "origin": origin,
            "x-nms-concierge-bff-key":
                TEST_BFF_KEY,
        }

        self.client = SimpleNamespace(
            host=client_host
        )

    async def body(self):
        return self._body


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
            "opaque_route_test_key_123456",
    }


def enable_for_process_only(
    monkeypatch,
):
    # Tests deliberately open both independent publication
    # gates in-process only. Production defaults remain closed.
    monkeypatch.setattr(
        router,
        "public_chat_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        router,
        "public_appointment_enabled",
        lambda: True,
    )

    monkeypatch.setenv(
        "NMS_CONCIERGE_BFF_KEY",
        TEST_BFF_KEY,
    )


@pytest.mark.asyncio
async def test_allowed_origin_reaches_mocked_handoff(
    monkeypatch,
):
    enable_for_process_only(
        monkeypatch
    )

    captured = {}

    async def fake_handoff(
        request,
        *,
        confirmed,
        idempotency_key,
        client_ip=None,
    ):
        captured["request"] = request
        captured["confirmed"] = confirmed
        captured["idempotency_key"] = (
            idempotency_key
        )
        captured["client_ip"] = client_ip

        return SimpleNamespace(
            appointment_request={
                "id": "synthetic-request-id",
                # These values deliberately prove that
                # the route response does not serialize
                # the internal appointment object.
                "email": "must-not-leak@example.com",
                "phone": "must-not-leak",
                "fullName": "Must Not Leak",
                "concierge_idempotency_key":
                    "must-not-leak",
            },
            replayed=False,
        )

    monkeypatch.setattr(
        router,
        "create_concierge_appointment_request",
        fake_handoff,
    )

    result = await (
        router
        .public_concierge_appointment_request(
            FakeRequest(
                valid_payload()
            )
        )
    )

    assert result.ok is True
    assert (
        result.request_id
        == "synthetic-request-id"
    )
    assert result.replayed is False

    assert (
        set(
            result.model_dump().keys()
        )
        == {
            "ok",
            "request_id",
            "replayed",
        }
    )

    assert captured["confirmed"] is True

    assert (
        captured["idempotency_key"]
        == "opaque_route_test_key_123456"
    )

    assert (
        captured["client_ip"]
        == "203.0.113.10"
    )

    appointment = captured["request"]

    assert (
        appointment.full_name
        == "Test Visitor"
    )
    assert (
        appointment.email
        == "visitor@example.com"
    )
    assert (
        appointment.phone
        == "770-555-0100"
    )
    assert (
        appointment.returning
        == "first"
    )
    assert appointment.service is None
    assert (
        appointment.date
        == "2099-12-31"
    )
    assert (
        appointment.time
        == "10:30"
    )

    assert appointment.notes is None
    assert appointment.add_ons == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "http://preview.natmedsol.org",
        "https://preview.natmedsol.org:443",
        "https://preview.natmedsol.org.evil.example",
        "https://www.natmedsol.com.evil.example",
        "https://user@www.natmedsol.com",
        "",
    ],
)
async def test_bad_origin_never_reaches_handoff(
    monkeypatch,
    origin,
):
    enable_for_process_only(
        monkeypatch
    )

    called = False

    async def exploding_handoff(
        *args,
        **kwargs,
    ):
        nonlocal called
        called = True

        raise AssertionError(
            "Forbidden origin reached handoff"
        )

    monkeypatch.setattr(
        router,
        "create_concierge_appointment_request",
        exploding_handoff,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        await (
            router
            .public_concierge_appointment_request(
                FakeRequest(
                    valid_payload(),
                    origin=origin,
                )
            )
        )

    assert exc.value.status_code == 403
    assert called is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin",
    [
        "https://preview.natmedsol.org",
        "https://www.natmedsol.com",
        "https://natmedsol.com",
    ],
)
async def test_each_approved_origin_can_reach_mock(
    monkeypatch,
    origin,
):
    enable_for_process_only(
        monkeypatch
    )

    called = False

    async def fake_handoff(
        *args,
        **kwargs,
    ):
        nonlocal called
        called = True

        return SimpleNamespace(
            appointment_request={
                "id": "approved-origin-id",
            },
            replayed=False,
        )

    monkeypatch.setattr(
        router,
        "create_concierge_appointment_request",
        fake_handoff,
    )

    result = await (
        router
        .public_concierge_appointment_request(
            FakeRequest(
                valid_payload(),
                origin=origin,
            )
        )
    )

    assert called is True
    assert (
        result.request_id
        == "approved-origin-id"
    )


@pytest.mark.asyncio
async def test_unconfirmed_request_never_reaches_handoff(
    monkeypatch,
):
    enable_for_process_only(
        monkeypatch
    )

    body = valid_payload()
    body["confirmed"] = False

    called = False

    async def exploding_handoff(
        *args,
        **kwargs,
    ):
        nonlocal called
        called = True

        raise AssertionError(
            "Unconfirmed request reached handoff"
        )

    monkeypatch.setattr(
        router,
        "create_concierge_appointment_request",
        exploding_handoff,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        await (
            router
            .public_concierge_appointment_request(
                FakeRequest(body)
            )
        )

    assert exc.value.status_code == 422
    assert called is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field",
    [
        "notes",
        "addOns",
        "medical_history",
        "medications",
        "labs",
        "diagnosis",
        "dob",
        "insurance_id",
        "message",
    ],
)
async def test_forbidden_field_never_reaches_handoff(
    monkeypatch,
    field,
):
    enable_for_process_only(
        monkeypatch
    )

    body = valid_payload()
    body[field] = "forbidden"

    called = False

    async def exploding_handoff(
        *args,
        **kwargs,
    ):
        nonlocal called
        called = True

        raise AssertionError(
            "Forbidden field reached handoff"
        )

    monkeypatch.setattr(
        router,
        "create_concierge_appointment_request",
        exploding_handoff,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        await (
            router
            .public_concierge_appointment_request(
                FakeRequest(body)
            )
        )

    assert exc.value.status_code == 422
    assert called is False


@pytest.mark.asyncio
async def test_replay_response_is_still_minimal(
    monkeypatch,
):
    enable_for_process_only(
        monkeypatch
    )

    async def fake_replay(
        *args,
        **kwargs,
    ):
        return SimpleNamespace(
            appointment_request={
                "id": "same-request-id",
                "fullName": "Private Name",
                "email": "private@example.com",
                "phone": "private-phone",
                "notes": "private",
                "addOns": ["private"],
                "concierge_idempotency_key":
                    "private-hash",
            },
            replayed=True,
        )

    monkeypatch.setattr(
        router,
        "create_concierge_appointment_request",
        fake_replay,
    )

    result = await (
        router
        .public_concierge_appointment_request(
            FakeRequest(
                valid_payload()
            )
        )
    )

    dumped = result.model_dump()

    assert dumped == {
        "ok": True,
        "request_id": "same-request-id",
        "replayed": True,
    }

    serialized = json.dumps(
        dumped
    )

    for forbidden in [
        "Private Name",
        "private@example.com",
        "private-phone",
        "private-hash",
        "notes",
        "addOns",
    ]:
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_missing_internal_request_id_fails_closed(
    monkeypatch,
):
    enable_for_process_only(
        monkeypatch
    )

    async def fake_bad_result(
        *args,
        **kwargs,
    ):
        return SimpleNamespace(
            appointment_request={},
            replayed=False,
        )

    monkeypatch.setattr(
        router,
        "create_concierge_appointment_request",
        fake_bad_result,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        await (
            router
            .public_concierge_appointment_request(
                FakeRequest(
                    valid_payload()
                )
            )
        )

    assert exc.value.status_code == 500
