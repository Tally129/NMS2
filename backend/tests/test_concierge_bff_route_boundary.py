import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import marketing_os.routers.concierge as router


GOOD_KEY = "K" * 64
WRONG_KEY = "W" * 64
GOOD_ORIGIN = "https://preview.natmedsol.org"


class ProbeRequest:
    def __init__(
        self,
        payload=None,
        *,
        origin=GOOD_ORIGIN,
        bff_key=None,
        client_host="203.0.113.10",
    ):
        if payload is None:
            payload = {}

        self._raw = json.dumps(
            payload
        ).encode("utf-8")

        self.body_called = False

        self.headers = {
            "origin": origin,
        }

        if bff_key is not None:
            self.headers[
                "x-nms-concierge-bff-key"
            ] = bff_key

        self.client = SimpleNamespace(
            host=client_host
        )

    async def body(self):
        self.body_called = True
        return self._raw


def open_in_process_only(monkeypatch):
    # Test-process only. Never modifies production env files.
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
        GOOD_KEY,
    )


def assert_generic_404(exc):
    assert isinstance(
        exc.value,
        HTTPException,
    )

    assert exc.value.status_code == 404

    detail = exc.value.detail

    if isinstance(detail, dict):
        assert (
            detail.get("code")
            == "concierge_not_available"
        )
    else:
        assert (
            "concierge_not_available"
            in str(detail)
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "supplied_key",
    [
        None,
        "",
        WRONG_KEY,
    ],
)
async def test_chat_auth_failure_occurs_before_body_and_engine(
    monkeypatch,
    supplied_key,
):
    open_in_process_only(
        monkeypatch
    )

    engine_called = False

    async def forbidden_engine(*args, **kwargs):
        nonlocal engine_called
        engine_called = True
        raise AssertionError(
            "Chat engine must not execute"
        )

    # Patch every likely engine entry reference only if present.
    for name in (
        "run_public_concierge",
        "run_concierge",
        "answer_public_concierge",
    ):
        if hasattr(router, name):
            monkeypatch.setattr(
                router,
                name,
                forbidden_engine,
            )

    request = ProbeRequest(
        {"message": "Hello"},
        bff_key=supplied_key,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        await router.public_concierge_chat(
            request
        )

    assert_generic_404(exc)

    assert request.body_called is False
    assert engine_called is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "supplied_key",
    [
        None,
        "",
        WRONG_KEY,
    ],
)
async def test_appointment_auth_failure_occurs_before_body_and_handoff(
    monkeypatch,
    supplied_key,
):
    open_in_process_only(
        monkeypatch
    )

    handoff_called = False

    async def forbidden_handoff(*args, **kwargs):
        nonlocal handoff_called
        handoff_called = True
        raise AssertionError(
            "Appointment handoff must not execute"
        )

    monkeypatch.setattr(
        router,
        "create_concierge_appointment_request",
        forbidden_handoff,
    )

    request = ProbeRequest(
        {
            "first_name": "Test",
            "last_name": "Visitor",
            "email": "visitor@example.com",
            "phone": "7705550100",
            "returning": "first",
            "date": "2099-12-31",
            "time": "10:30",
            "confirmed": True,
            "idempotency_key":
                "route_boundary_key_123456789",
        },
        bff_key=supplied_key,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        await (
            router
            .public_concierge_appointment_request(
                request
            )
        )

    assert_generic_404(exc)

    assert request.body_called is False
    assert handoff_called is False


@pytest.mark.asyncio
async def test_chat_correct_auth_reaches_origin_boundary(
    monkeypatch,
):
    open_in_process_only(
        monkeypatch
    )

    request = ProbeRequest(
        {"message": "Hello"},
        origin="https://evil.example",
        bff_key=GOOD_KEY,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        await router.public_concierge_chat(
            request
        )

    assert exc.value.status_code == 403

    # Origin is checked before body parsing.
    assert request.body_called is False


@pytest.mark.asyncio
async def test_appointment_correct_auth_reaches_origin_boundary(
    monkeypatch,
):
    open_in_process_only(
        monkeypatch
    )

    request = ProbeRequest(
        {},
        origin="https://evil.example",
        bff_key=GOOD_KEY,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        await (
            router
            .public_concierge_appointment_request(
                request
            )
        )

    assert exc.value.status_code == 403

    assert request.body_called is False
