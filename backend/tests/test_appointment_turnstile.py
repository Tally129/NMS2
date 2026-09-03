from __future__ import annotations

import pytest

import appointment_turnstile
from appointment_turnstile import (
    TURNSTILE_SITEVERIFY_URL,
    verify_appointment_turnstile,
)


class FakeResponse:
    def __init__(
        self,
        *,
        body,
        status_code=200,
    ):
        self._body = body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            request = httpx.Request(
                "POST",
                TURNSTILE_SITEVERIFY_URL,
            )

            response = httpx.Response(
                self.status_code,
                request=request,
            )

            raise httpx.HTTPStatusError(
                "synthetic status",
                request=request,
                response=response,
            )

    def json(self):
        if isinstance(
            self._body,
            Exception,
        ):
            raise self._body

        return self._body


class FakeAsyncClient:
    response_body = {
        "success": True,
        "hostname":
            "app.natmedsol.org",
        "action":
            "appointment_request",
        "error-codes": [],
    }

    response_status = 200

    captured = None

    def __init__(
        self,
        *,
        timeout,
    ):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        return False

    async def post(
        self,
        url,
        *,
        json,
        headers,
    ):
        type(self).captured = {
            "url": url,
            "json": json,
            "headers": headers,
            "timeout": self.timeout,
        }

        return FakeResponse(
            body=type(
                self
            ).response_body,
            status_code=type(
                self
            ).response_status,
        )


@pytest.fixture(autouse=True)
def install_fake_client(
    monkeypatch,
):
    FakeAsyncClient.response_body = {
        "success": True,
        "hostname":
            "app.natmedsol.org",
        "action":
            "appointment_request",
        "error-codes": [],
    }

    FakeAsyncClient.response_status = (
        200
    )

    FakeAsyncClient.captured = None

    monkeypatch.setattr(
        appointment_turnstile.httpx,
        "AsyncClient",
        FakeAsyncClient,
    )


@pytest.mark.asyncio
async def test_successful_validation():
    result = (
        await verify_appointment_turnstile(
            token="valid-test-token",
            remote_ip="203.0.113.10",
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action=(
                "appointment_request"
            ),
            secret="server-secret",
        )
    )

    assert result.verified is True
    assert result.reason == "verified"

    assert (
        result.hostname
        == "app.natmedsol.org"
    )

    assert (
        result.action
        == "appointment_request"
    )


@pytest.mark.asyncio
async def test_request_contract():
    await verify_appointment_turnstile(
        token="valid-test-token",
        remote_ip="203.0.113.10",
        expected_hostnames={
            "app.natmedsol.org",
        },
        expected_action=(
            "appointment_request"
        ),
        secret="server-secret",
    )

    captured = (
        FakeAsyncClient.captured
    )

    assert captured is not None

    assert (
        captured["url"]
        == TURNSTILE_SITEVERIFY_URL
    )

    payload = captured["json"]

    assert (
        payload["secret"]
        == "server-secret"
    )

    assert (
        payload["response"]
        == "valid-test-token"
    )

    assert (
        payload["remoteip"]
        == "203.0.113.10"
    )

    # Cloudflare documents this optional
    # field as a UUID.
    import uuid

    uuid.UUID(
        payload["idempotency_key"]
    )


@pytest.mark.asyncio
async def test_missing_secret_fails_closed(
    monkeypatch,
):
    monkeypatch.delenv(
        "NMS_APPOINTMENT_TURNSTILE_SECRET_KEY",
        raising=False,
    )

    result = (
        await verify_appointment_turnstile(
            token="valid-test-token",
            remote_ip=None,
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action=(
                "appointment_request"
            ),
        )
    )

    assert result.verified is False
    assert (
        result.reason
        == "not_configured"
    )

    assert (
        FakeAsyncClient.captured
        is None
    )


@pytest.mark.asyncio
async def test_empty_token_rejected_without_network():
    result = (
        await verify_appointment_turnstile(
            token="",
            remote_ip=None,
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action=(
                "appointment_request"
            ),
            secret="server-secret",
        )
    )

    assert result.verified is False
    assert result.reason == "invalid_token"

    assert (
        FakeAsyncClient.captured
        is None
    )


@pytest.mark.asyncio
async def test_oversize_token_rejected_without_network():
    result = (
        await verify_appointment_turnstile(
            token="x" * 2049,
            remote_ip=None,
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action=(
                "appointment_request"
            ),
            secret="server-secret",
        )
    )

    assert result.verified is False
    assert result.reason == "invalid_token"

    assert (
        FakeAsyncClient.captured
        is None
    )


@pytest.mark.asyncio
async def test_cloudflare_failure_fails_closed():
    FakeAsyncClient.response_body = {
        "success": False,
        "error-codes": [
            "invalid-input-response",
        ],
    }

    result = (
        await verify_appointment_turnstile(
            token="bad-test-token",
            remote_ip=None,
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action=(
                "appointment_request"
            ),
            secret="server-secret",
        )
    )

    assert result.verified is False

    assert (
        result.reason
        == "turnstile_failed"
    )

    assert result.error_codes == (
        "invalid-input-response",
    )


@pytest.mark.asyncio
async def test_replayed_token_failure_is_not_accepted():
    FakeAsyncClient.response_body = {
        "success": False,
        "error-codes": [
            "timeout-or-duplicate",
        ],
    }

    result = (
        await verify_appointment_turnstile(
            token="replayed-token",
            remote_ip=None,
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action=(
                "appointment_request"
            ),
            secret="server-secret",
        )
    )

    assert result.verified is False

    assert (
        "timeout-or-duplicate"
        in result.error_codes
    )


@pytest.mark.asyncio
async def test_hostname_mismatch_fails_closed():
    FakeAsyncClient.response_body = {
        "success": True,
        "hostname":
            "attacker.example",
        "action":
            "appointment_request",
        "error-codes": [],
    }

    result = (
        await verify_appointment_turnstile(
            token="valid-test-token",
            remote_ip=None,
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action=(
                "appointment_request"
            ),
            secret="server-secret",
        )
    )

    assert result.verified is False

    assert (
        result.reason
        == "hostname_mismatch"
    )


@pytest.mark.asyncio
async def test_hostname_comparison_normalizes_case():
    FakeAsyncClient.response_body = {
        "success": True,
        "hostname":
            "APP.NATMEDSOL.ORG",
        "action":
            "appointment_request",
        "error-codes": [],
    }

    result = (
        await verify_appointment_turnstile(
            token="valid-test-token",
            remote_ip=None,
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action=(
                "appointment_request"
            ),
            secret="server-secret",
        )
    )

    assert result.verified is True


@pytest.mark.asyncio
async def test_action_mismatch_fails_closed():
    FakeAsyncClient.response_body = {
        "success": True,
        "hostname":
            "app.natmedsol.org",
        "action":
            "login",
        "error-codes": [],
    }

    result = (
        await verify_appointment_turnstile(
            token="valid-test-token",
            remote_ip=None,
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action=(
                "appointment_request"
            ),
            secret="server-secret",
        )
    )

    assert result.verified is False

    assert (
        result.reason
        == "action_mismatch"
    )


@pytest.mark.asyncio
async def test_http_failure_fails_closed():
    FakeAsyncClient.response_status = (
        503
    )

    result = (
        await verify_appointment_turnstile(
            token="valid-test-token",
            remote_ip=None,
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action=(
                "appointment_request"
            ),
            secret="server-secret",
        )
    )

    assert result.verified is False

    assert (
        result.reason
        == "verification_unavailable"
    )


@pytest.mark.asyncio
async def test_invalid_json_fails_closed():
    FakeAsyncClient.response_body = (
        ValueError(
            "synthetic invalid JSON"
        )
    )

    result = (
        await verify_appointment_turnstile(
            token="valid-test-token",
            remote_ip=None,
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action=(
                "appointment_request"
            ),
            secret="server-secret",
        )
    )

    assert result.verified is False

    assert (
        result.reason
        == "verification_unavailable"
    )


@pytest.mark.asyncio
async def test_non_object_response_fails_closed():
    FakeAsyncClient.response_body = [
        "unexpected"
    ]

    result = (
        await verify_appointment_turnstile(
            token="valid-test-token",
            remote_ip=None,
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action=(
                "appointment_request"
            ),
            secret="server-secret",
        )
    )

    assert result.verified is False
    assert (
        result.reason
        == "invalid_response"
    )


@pytest.mark.asyncio
async def test_missing_expected_hosts_fails_closed():
    result = (
        await verify_appointment_turnstile(
            token="valid-test-token",
            remote_ip=None,
            expected_hostnames=set(),
            expected_action=(
                "appointment_request"
            ),
            secret="server-secret",
        )
    )

    assert result.verified is False

    assert (
        result.reason
        == "invalid_configuration"
    )

    assert (
        FakeAsyncClient.captured
        is None
    )


@pytest.mark.asyncio
async def test_missing_action_configuration_fails_closed():
    result = (
        await verify_appointment_turnstile(
            token="valid-test-token",
            remote_ip=None,
            expected_hostnames={
                "app.natmedsol.org",
            },
            expected_action="",
            secret="server-secret",
        )
    )

    assert result.verified is False

    assert (
        result.reason
        == "invalid_configuration"
    )

    assert (
        FakeAsyncClient.captured
        is None
    )


def test_verification_object_does_not_contain_secret_or_token():
    import inspect

    source = inspect.getsource(
        appointment_turnstile
        .TurnstileVerification
    ).lower()

    assert "secret" not in source
    assert "token" not in source
