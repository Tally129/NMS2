import importlib
import json
import os


def _load_app(monkeypatch):

    monkeypatch.setenv(
        "CAMPAIGN_SCHEDULER_MODE",
        "disabled",
    )

    monkeypatch.setenv(
        "PUBLISHING_SCHEDULER_MODE",
        "disabled",
    )

    monkeypatch.setenv(
        "MARKETING_INGEST_KEY",
        "57cd3-test-secret",
    )

    import server

    return server


def test_valid_event_contract(
    monkeypatch,
):

    server = _load_app(
        monkeypatch
    )

    import marketing_os.routers.ingestion as ingestion

    async def fake_persist(
        session,
        *,
        payload,
        idempotency_key,
        occurred_at=None,
        provider=None,
        external_campaign_id=None,
        nms_campaign_id=None,
    ):

        assert (
            idempotency_key
            == "event-001"
        )

        assert (
            payload["event_type"]
            == "appointment_intent"
        )

        assert (
            payload["properties"][
                "page_path"
            ]
            == "/adrenal"
        )

        return {
            "conversion_event_id":
                "mconv_test",

            "attribution_id":
                "mattr_test",

            "conversion_inserted":
                True,

            "attribution_inserted":
                True,

            "idempotent":
                True,

            "external_write":
                False,

            "phi_required":
                False,
        }

    monkeypatch.setattr(
        ingestion,
        "persist_conversion_and_attribution",
        fake_persist,
    )

    from fastapi.testclient import TestClient

    with TestClient(
        server.app,
        base_url="https://app.natmedsol.org",
    ) as client:

        response = client.post(
            "/api/marketing-os/events",
            headers={
                "X-Forwarded-Proto":
                    "https",

                "X-NMS-Marketing-Ingest-Key":
                    "57cd3-test-secret",

                "Idempotency-Key":
                    "event-001",
            },
            json={
                "event_type":
                    "appointment_intent",

                "session_id":
                    "anon-session-001",

                "source":
                    "google",

                "medium":
                    "organic",

                "campaign":
                    "adrenal",

                "provider":
                    "organic_search",

                "properties": {
                    "page_path":
                        "/adrenal",

                    "cta":
                        "request-appointment",
                },
            },
        )

    assert response.status_code == 202

    data = response.json()

    assert data["accepted"] is True
    assert data["external_write"] is False
    assert data["phi_required"] is False
    assert (
        data["conversion_event_id"]
        == "mconv_test"
    )


def test_bad_secret_rejected(
    monkeypatch,
):

    server = _load_app(
        monkeypatch
    )

    from fastapi.testclient import TestClient

    with TestClient(
        server.app,
        base_url="https://app.natmedsol.org",
    ) as client:

        response = client.post(
            "/api/marketing-os/events",
            headers={
                "X-Forwarded-Proto":
                    "https",

                "X-NMS-Marketing-Ingest-Key":
                    "wrong",

                "Idempotency-Key":
                    "event-002",
            },
            json={
                "event_type":
                    "cta_click",
            },
        )

    assert response.status_code == 401


def test_missing_idempotency_rejected(
    monkeypatch,
):

    server = _load_app(
        monkeypatch
    )

    from fastapi.testclient import TestClient

    with TestClient(
        server.app,
        base_url="https://app.natmedsol.org",
    ) as client:

        response = client.post(
            "/api/marketing-os/events",
            headers={
                "X-Forwarded-Proto":
                    "https",

                "X-NMS-Marketing-Ingest-Key":
                    "57cd3-test-secret",
            },
            json={
                "event_type":
                    "cta_click",
            },
        )

    assert response.status_code == 400

    assert (
        response.json()["detail"]["code"]
        == "missing_idempotency_key"
    )


def test_oversized_body_rejected(
    monkeypatch,
):

    server = _load_app(
        monkeypatch
    )

    from fastapi.testclient import TestClient

    huge = {
        "event_type":
            "content_engagement",

        "properties": {
            "blob":
                "x" * (20 * 1024),
        },
    }

    body = json.dumps(
        huge
    ).encode()

    with TestClient(
        server.app,
        base_url="https://app.natmedsol.org",
    ) as client:

        response = client.post(
            "/api/marketing-os/events",
            headers={
                "X-Forwarded-Proto":
                    "https",

                "X-NMS-Marketing-Ingest-Key":
                    "57cd3-test-secret",

                "Idempotency-Key":
                    "event-large",

                "Content-Type":
                    "application/json",
            },
            content=body,
        )

    assert response.status_code == 413


def test_policy_violation_rejected_before_write(
    monkeypatch,
):

    server = _load_app(
        monkeypatch
    )

    import marketing_os.routers.ingestion as ingestion

    called = False

    original = (
        ingestion.persist_conversion_and_attribution
    )

    async def tracking_persist(
        *args,
        **kwargs,
    ):

        nonlocal called
        called = True

        return await original(
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        ingestion,
        "persist_conversion_and_attribution",
        tracking_persist,
    )

    from fastapi.testclient import TestClient

    with TestClient(
        server.app,
        base_url="https://app.natmedsol.org",
    ) as client:

        response = client.post(
            "/api/marketing-os/events",
            headers={
                "X-Forwarded-Proto":
                    "https",

                "X-NMS-Marketing-Ingest-Key":
                    "57cd3-test-secret",

                "Idempotency-Key":
                    "event-phi",
            },
            json={
                "event_type":
                    "lead_submit",

                "properties": {
                    "patient_id":
                        "DO-NOT-STORE",
                },
            },
        )

    assert response.status_code == 400
    assert called is True

    assert (
        response.json()["detail"]["code"]
        == "marketing_data_policy_violation"
    )


def test_ingest_secret_unconfigured_fails_closed(
    monkeypatch,
):

    server = _load_app(
        monkeypatch
    )

    monkeypatch.delenv(
        "MARKETING_INGEST_KEY",
        raising=False,
    )

    from fastapi.testclient import TestClient

    with TestClient(
        server.app,
        base_url="https://app.natmedsol.org",
    ) as client:

        response = client.post(
            "/api/marketing-os/events",
            headers={
                "X-Forwarded-Proto":
                    "https",

                "X-NMS-Marketing-Ingest-Key":
                    "anything",

                "Idempotency-Key":
                    "event-003",
            },
            json={
                "event_type":
                    "cta_click",
            },
        )

    assert response.status_code == 503


def test_http_rejected(
    monkeypatch,
):

    server = _load_app(
        monkeypatch
    )

    from fastapi.testclient import TestClient

    with TestClient(
        server.app,
        base_url="http://app.natmedsol.org",
    ) as client:

        response = client.post(
            "/api/marketing-os/events",
            headers={
                "X-NMS-Marketing-Ingest-Key":
                    "57cd3-test-secret",

                "Idempotency-Key":
                    "event-http",
            },
            json={
                "event_type":
                    "cta_click",
            },
        )

    assert response.status_code == 400

    assert (
        response.json()["detail"]
        == "HTTPS required"
    )


def test_unknown_top_level_field_rejected(
    monkeypatch,
):

    server = _load_app(
        monkeypatch
    )

    from fastapi.testclient import TestClient

    with TestClient(
        server.app,
        base_url="https://app.natmedsol.org",
    ) as client:

        response = client.post(
            "/api/marketing-os/events",
            headers={
                "X-Forwarded-Proto":
                    "https",

                "X-NMS-Marketing-Ingest-Key":
                    "57cd3-test-secret",

                "Idempotency-Key":
                    "event-extra-field",
            },
            json={
                "event_type":
                    "cta_click",

                "unexpected_field":
                    "must-not-be-silently-dropped",
            },
        )

    assert response.status_code == 422

    detail = response.json()["detail"]

    assert (
        detail["code"]
        == "invalid_marketing_event"
    )

    assert any(
        item["type"] == "extra_forbidden"
        for item in detail["errors"]
    )
