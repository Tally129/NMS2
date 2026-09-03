"""
Canonical appointment workflow failure-semantics tests.

All external effects are mocked.
No production database writes.
No SendGrid delivery.
"""

import pytest

import appointment_requests
import notifiers

from models import AppointmentRequestIn


def make_payload():
    return AppointmentRequestIn(
        fullName="Synthetic Workflow Test",
        email="workflow-test@example.invalid",
        phone="5555550100",
        returning="first",
        service="Telehealth",
        date="2099-01-15",
        time="10:30 AM",
        notes=None,
        addOns=[],
    )


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        return False


class FakeSession:
    def begin(self):
        return FakeTransaction()

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        return False


class FakeSessionFactory:
    def __call__(self):
        return FakeSession()


def install_storage(
    monkeypatch,
    calls,
):
    monkeypatch.setattr(
        appointment_requests,
        "AsyncSessionLocal",
        FakeSessionFactory(),
    )

    async def fake_storage(session, doc):
        calls.append("storage")
        return dict(doc)

    monkeypatch.setattr(
        appointment_requests.sched_repo,
        "create_appointment_request",
        fake_storage,
    )


def install_integration_log(
    monkeypatch,
    calls,
    *,
    fail=False,
):
    class FakeIntegrationLog:
        async def insert_one(self, doc):
            calls.append(
                (
                    "integration_log",
                    doc.get("action"),
                )
            )

            if fail:
                raise RuntimeError(
                    "synthetic integration-log failure"
                )

            return None

    class FakeDb:
        integration_log = FakeIntegrationLog()

    monkeypatch.setattr(
        appointment_requests,
        "db",
        FakeDb(),
    )


def install_audit(
    monkeypatch,
    calls,
    *,
    fail=False,
):
    async def fake_audit(*args, **kwargs):
        calls.append("audit")

        if fail:
            raise RuntimeError(
                "synthetic audit failure"
            )

        return None

    monkeypatch.setattr(
        appointment_requests,
        "log_audit",
        fake_audit,
    )


@pytest.mark.asyncio
async def test_storage_failure_stops_workflow(
    monkeypatch,
):
    calls = []

    monkeypatch.setattr(
        appointment_requests,
        "AsyncSessionLocal",
        FakeSessionFactory(),
    )

    async def fail_storage(session, doc):
        calls.append("storage")
        raise RuntimeError(
            "synthetic storage failure"
        )

    monkeypatch.setattr(
        appointment_requests.sched_repo,
        "create_appointment_request",
        fail_storage,
    )

    with pytest.raises(
        RuntimeError,
        match="synthetic storage failure",
    ):
        await (
            appointment_requests
            .create_appointment_request_workflow(
                make_payload(),
                client_ip="127.0.0.1",
                user_agent="test",
                marketing_attribution=None,
            )
        )

    assert calls == ["storage"]


@pytest.mark.asyncio
async def test_successful_workflow_contract(
    monkeypatch,
):
    calls = []

    install_storage(
        monkeypatch,
        calls,
    )

    async def fake_email(*args, **kwargs):
        calls.append("email")
        return "sent_stub"

    # IMPORTANT:
    # appointment_requests imports this symbol inside the function,
    # so patch the source module.
    monkeypatch.setattr(
        notifiers,
        "send_email",
        fake_email,
    )

    install_integration_log(
        monkeypatch,
        calls,
    )

    install_audit(
        monkeypatch,
        calls,
    )

    result = await (
        appointment_requests
        .create_appointment_request_workflow(
            make_payload(),
            client_ip="127.0.0.1",
            user_agent="test",
            marketing_attribution=None,
        )
    )

    assert result["ok"] is True
    assert result["id"]

    assert calls[0] == "storage"
    assert "email" in calls
    assert "audit" in calls

    explicit_logs = [
        item
        for item in calls
        if isinstance(item, tuple)
        and item[0] == "integration_log"
    ]

    assert explicit_logs == [
        (
            "integration_log",
            "appointment_request_notification",
        )
    ]


@pytest.mark.asyncio
async def test_notification_exception_is_nonfatal_after_storage(
    monkeypatch,
):
    calls = []

    install_storage(monkeypatch, calls)

    async def fail_email(*args, **kwargs):
        calls.append("email")
        raise RuntimeError(
            "synthetic notification failure"
        )

    monkeypatch.setattr(
        notifiers,
        "send_email",
        fail_email,
    )

    install_integration_log(
        monkeypatch,
        calls,
    )

    install_audit(
        monkeypatch,
        calls,
    )

    result = await (
        appointment_requests
        .create_appointment_request_workflow(
            make_payload(),
            client_ip="127.0.0.1",
            user_agent="test",
            marketing_attribution=None,
        )
    )

    assert result["ok"] is True
    assert result["id"]
    assert calls[:2] == [
        "storage",
        "email",
    ]


@pytest.mark.asyncio
async def test_integration_log_exception_is_nonfatal_after_storage(
    monkeypatch,
):
    calls = []

    install_storage(monkeypatch, calls)

    async def fake_email(*args, **kwargs):
        calls.append("email")
        return "sent_stub"

    monkeypatch.setattr(
        notifiers,
        "send_email",
        fake_email,
    )

    install_integration_log(
        monkeypatch,
        calls,
        fail=True,
    )

    install_audit(
        monkeypatch,
        calls,
    )

    result = await (
        appointment_requests
        .create_appointment_request_workflow(
            make_payload(),
            client_ip="127.0.0.1",
            user_agent="test",
            marketing_attribution=None,
        )
    )

    assert result["ok"] is True
    assert result["id"]
    assert calls[0] == "storage"
    assert "email" in calls


@pytest.mark.asyncio
async def test_audit_exception_is_nonfatal_after_storage(
    monkeypatch,
):
    calls = []

    install_storage(monkeypatch, calls)

    async def fake_email(*args, **kwargs):
        calls.append("email")
        return "sent_stub"

    monkeypatch.setattr(
        notifiers,
        "send_email",
        fake_email,
    )

    install_integration_log(
        monkeypatch,
        calls,
    )

    install_audit(
        monkeypatch,
        calls,
        fail=True,
    )

    result = await (
        appointment_requests
        .create_appointment_request_workflow(
            make_payload(),
            client_ip="127.0.0.1",
            user_agent="test",
            marketing_attribution=None,
        )
    )

    assert result["ok"] is True
    assert result["id"]
    assert calls[0] == "storage"
    assert "email" in calls
    assert "audit" in calls


@pytest.mark.asyncio
async def test_notification_failure_does_not_suppress_log_or_audit(
    monkeypatch,
):
    """
    Once storage succeeds, notification failure is isolated.

    The explicit operational log and audit must still be attempted.
    """
    calls = []

    install_storage(
        monkeypatch,
        calls,
    )

    async def fail_email(*args, **kwargs):
        calls.append("email")
        raise RuntimeError(
            "synthetic notification isolation failure"
        )

    monkeypatch.setattr(
        notifiers,
        "send_email",
        fail_email,
    )

    install_integration_log(
        monkeypatch,
        calls,
    )

    install_audit(
        monkeypatch,
        calls,
    )

    result = await (
        appointment_requests
        .create_appointment_request_workflow(
            make_payload(),
            client_ip="127.0.0.1",
            user_agent="test",
            marketing_attribution=None,
        )
    )

    assert result["ok"] is True
    assert result["id"]

    assert calls[0] == "storage"
    assert "email" in calls

    assert (
        "integration_log",
        "appointment_request_notification",
    ) in calls

    assert "audit" in calls


@pytest.mark.asyncio
async def test_integration_log_failure_does_not_suppress_audit(
    monkeypatch,
):
    """
    Explicit integration-log failure must not suppress audit.
    """
    calls = []

    install_storage(
        monkeypatch,
        calls,
    )

    async def fake_email(*args, **kwargs):
        calls.append("email")
        return "sent_stub"

    monkeypatch.setattr(
        notifiers,
        "send_email",
        fake_email,
    )

    install_integration_log(
        monkeypatch,
        calls,
        fail=True,
    )

    install_audit(
        monkeypatch,
        calls,
    )

    result = await (
        appointment_requests
        .create_appointment_request_workflow(
            make_payload(),
            client_ip="127.0.0.1",
            user_agent="test",
            marketing_attribution=None,
        )
    )

    assert result["ok"] is True
    assert result["id"]

    assert calls[0] == "storage"
    assert "email" in calls

    assert (
        "integration_log",
        "appointment_request_notification",
    ) in calls

    assert "audit" in calls


@pytest.mark.asyncio
async def test_audit_failure_does_not_change_success_contract(
    monkeypatch,
):
    """
    Audit failure after committed storage remains nonfatal.
    """
    calls = []

    install_storage(
        monkeypatch,
        calls,
    )

    async def fake_email(*args, **kwargs):
        calls.append("email")
        return "sent_stub"

    monkeypatch.setattr(
        notifiers,
        "send_email",
        fake_email,
    )

    install_integration_log(
        monkeypatch,
        calls,
    )

    install_audit(
        monkeypatch,
        calls,
        fail=True,
    )

    result = await (
        appointment_requests
        .create_appointment_request_workflow(
            make_payload(),
            client_ip="127.0.0.1",
            user_agent="test",
            marketing_attribution=None,
        )
    )

    assert result["ok"] is True
    assert result["id"]

    assert calls[0] == "storage"

    assert (
        "integration_log",
        "appointment_request_notification",
    ) in calls

    assert "audit" in calls
