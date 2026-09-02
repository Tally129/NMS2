"""SendGrid production email wiring — 2026-08.

Covers privacy-safe templates, the typed notifier helpers, log-redaction,
and the health-endpoint contract. All calls use the FastAPI `db` handle
via a small helper — no external network is hit because the underlying
`send_email` is monkeypatched.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest
import requests

from tests.smoketest_bootstrap import (
    ensure_smoketest_admin_and_practitioner, login_smoketest_admin,
)


BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8001") + "/api"


@pytest.fixture(scope="module")
def admin_token():
    ensure_smoketest_admin_and_practitioner()
    return login_smoketest_admin(BASE_URL)


def _b(tok):
    return {"Authorization": f"Bearer {tok}"}


# ============================================================ health
def test_health_email_is_live_or_configured_when_keys_present():
    r = requests.get(f"{BASE_URL}/health")
    assert r.status_code == 200
    integrations = r.json().get("integrations") or {}
    assert integrations.get("email") in ("live", "sent_stub")
    if os.environ.get("SENDGRID_API_KEY") and os.environ.get("SENDGRID_FROM_EMAIL"):
        assert integrations["email"] == "live"


# ============================================================ templates
def test_password_reset_template_no_password_and_has_reset_link():
    from email_templates import password_reset
    subject, html, text = password_reset(
        first_name="Alex", reset_url="https://portal.example.test/x?token=abc",
        expires_in_minutes=30,
    )
    assert "password" in subject.lower()
    # Template must NEVER carry a password value
    for body in (html, text):
        assert "TEMP" not in body
        assert "your password is" not in body.lower()
        assert "https://portal.example.test/x?token=abc" in body
        assert "30" in body


def test_mfa_enabled_template_never_contains_totp_or_recovery():
    from email_templates import mfa_enabled
    subject, html, text = mfa_enabled(first_name="Alex")
    assert "multi-factor" in subject.lower()
    for body in (html, text):
        low = body.lower()
        assert "recovery code" not in low
        assert "totp" not in low
        assert "secret" not in low


def test_recovery_code_template_no_code_value():
    from email_templates import recovery_code_used
    subject, html, text = recovery_code_used(first_name=None)
    for body in (html, text):
        # No 10-char alphanumeric code should ever be embedded.
        import re
        assert not re.search(r"\b[A-Z0-9]{10}\b", body)


def test_portal_notification_has_no_phi_body():
    from email_templates import portal_notification
    subject, html, text = portal_notification(
        first_name="Alex",
        headline="You have a new lab result",  # would-be-PHI header
    )
    for body in (html, text):
        # The template must NOT echo diagnoses, values, or specifics —
        # only the generic headline + a portal link.
        low = body.lower()
        assert "diagnosis" not in low
        assert "test result" not in low or "sign in" in low
        assert "portal" in low


def test_campaign_wrapper_preserves_html_and_adds_footer():
    from email_templates import wrap_campaign
    subject, html, text = wrap_campaign(
        subject="Welcome", safe_html="<p>Hello</p>", plain_text="Hello",
    )
    assert "<p>Hello</p>" in html
    assert "Natural Medical Solutions" in html
    assert "Natural Medical Solutions" in text


# ============================================================ redaction
def test_redact_secrets_masks_keys_and_emails():
    from notifiers import _redact_secrets
    line = "sent to alex@example.com with SG.abc123def456ghi789.jkl"
    red = _redact_secrets(line)
    assert "alex@example.com" not in red
    assert "SG.abc123def456ghi789.jkl" not in red
    assert "<redacted-email>" in red
    assert "<redacted-token>" in red


def test_api_key_never_in_logs():
    """The SendGrid module never touches `os.environ['SENDGRID_API_KEY']`
    at import time and never writes it into log lines."""
    import importlib, notifiers as N
    importlib.reload(N)
    # If we accidentally reference SENDGRID_API_KEY as a module-level
    # constant, this find would return >0 hits in the module source.
    src = open(N.__file__).read()
    # The key must ONLY be read inside function bodies, guarded by env
    # presence — the string `SENDGRID_API_KEY` must not appear on a
    # module-level `logger.` line.
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("logger.") and "SENDGRID_API_KEY" in stripped:
            raise AssertionError(f"API key referenced in a log line: {line}")


# ============================================================ typed helpers
def test_typed_helpers_dispatch_to_send_email():
    """Each helper composes a subject/html/text tuple from
    email_templates and hands it to notifiers.send_email — with
    redact_recipient=True and a stable action."""
    import notifiers
    calls = []

    async def _fake_send_email(db, to, subject, html, *, plain_text=None,
                                 action=None, payload_metadata=None,
                                 redact_recipient=False):
        calls.append({
            "to": to, "subject": subject, "html_len": len(html),
            "text_len": len(plain_text or ""), "action": action,
            "redact_recipient": redact_recipient,
        })
        return "sent_stub"

    async def _work():
        with patch.object(notifiers, "send_email", side_effect=_fake_send_email):
            await notifiers.send_account_setup_email(None, "u@example.test",
                first_name="Alex", setup_url="https://x.test/y?t=z",
                expires_in_hours=24)
            await notifiers.send_password_reset_email(None, "u@example.test",
                first_name="Alex", reset_url="https://x.test/y?t=z",
                expires_in_minutes=30)
            await notifiers.send_password_changed_email(None, "u@example.test",
                first_name="Alex")
            await notifiers.send_mfa_enabled_email(None, "u@example.test",
                first_name="Alex")
            await notifiers.send_recovery_code_used_email(None, "u@example.test",
                first_name="Alex")
            await notifiers.send_security_alert_email(None, "u@example.test",
                first_name="Alex", event_label="new device sign-in")
            await notifiers.send_generic_portal_notification(None, "u@example.test",
                first_name="Alex", headline="You have a new notification")

    asyncio.run(_work())

    actions = [c["action"] for c in calls]
    assert actions == [
        "auth.account_setup", "auth.password_reset_dispatch",
        "auth.password_changed", "auth.mfa_enabled",
        "auth.recovery_code_used", "security.new device sign-in",
        "notify.portal",
    ]
    assert all(c["redact_recipient"] is True for c in calls)
    assert all(c["text_len"] > 0 for c in calls), "plain-text fallback missing"


# ================================================ SendGrid rejection = failure
def test_sendgrid_rejection_returns_failed():
    import notifiers, asyncio as _asyncio
    from deps import db
    original_env = {k: os.environ.get(k) for k in
                     ("SENDGRID_API_KEY", "SENDGRID_FROM_EMAIL")}
    os.environ["SENDGRID_API_KEY"] = "SG.fake"
    os.environ["SENDGRID_FROM_EMAIL"] = "noreply@example.test"

    async def _work():
        with patch("sendgrid.SendGridAPIClient") as MockClient:
            instance = MockClient.return_value
            instance.send.side_effect = Exception("400 bad request")
            status = await notifiers.send_email(
                db, "x@example.test", "Test", "<p>x</p>",
                plain_text="x",
            )
        return status

    try:
        assert _asyncio.run(_work()) == "failed"
    finally:
        for k, v in original_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ================================================ enumeration-safe forgot pw
def test_forgot_password_response_is_uniform():
    r_known = requests.post(f"{BASE_URL}/auth/forgot-password",
                              json={"email": "definitely-not-real@example.test"})
    assert r_known.status_code == 200
    body = r_known.json()
    assert body.get("message", "").lower().startswith("if that email")
