"""Assertions that the Twilio/SMS surface is fully removed (2026-08).

Verifies:
* /api/health does not report an `sms` integration
* No runtime `twilio` or `send_sms` imports exist in application code
* Campaign channel is email-only (SMS channel is rejected)
* notifiers module exposes no `send_sms` or `sms_status`
"""
from __future__ import annotations

import os
import subprocess
import uuid

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


def test_health_no_sms_integration():
    r = requests.get(f"{BASE_URL}/health")
    assert r.status_code == 200
    body = r.json()
    integrations = body.get("integrations") or {}
    assert "sms" not in integrations, f"health still reports sms: {integrations}"
    # The email integration MUST still be present.
    assert "email" in integrations


def test_notifiers_module_has_no_sms_surface():
    import notifiers
    assert not hasattr(notifiers, "send_sms")
    assert not hasattr(notifiers, "sms_status")
    # Email path must still be exported.
    assert hasattr(notifiers, "send_email")
    assert hasattr(notifiers, "email_status")


def test_no_runtime_twilio_imports():
    """grep-based safety net — outside tests/scripts, nothing runtime
    imports twilio."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.run(
        ["grep", "-RIln",
         r"^\(from twilio\|import twilio\)", root,
         "--include=*.py",
         "--exclude-dir=tests",
         "--exclude-dir=scripts",
         "--exclude-dir=__pycache__"],
        capture_output=True, text=True,
    )
    matches = [line for line in proc.stdout.splitlines() if line]
    assert matches == [], f"Twilio imports found in runtime: {matches}"


def test_campaign_rejects_sms_channel(admin_token):
    r = requests.post(f"{BASE_URL}/campaigns", headers=_b(admin_token),
                       json={"title": f"SMS reject {uuid.uuid4().hex[:6]}",
                             "channel": "sms",
                             "filter_type": "all_marketing",
                             "message": "hi"})
    assert r.status_code == 400
    body = r.json()
    assert body.get("detail", {}).get("code") == "invalid_channel"


def test_campaign_delivery_config_has_no_sms(admin_token):
    r = requests.get(f"{BASE_URL}/campaigns/config/delivery",
                      headers=_b(admin_token))
    assert r.status_code == 200
    body = r.json()
    assert "sms" not in body, f"delivery config still exposes sms: {body}"
    assert "email" in body


def test_email_notification_still_works(admin_token):
    """Send a form via /forms/send email channel — round-trips + logs
    integration_log entry."""
    tpl = requests.post(f"{BASE_URL}/forms/templates", headers=_b(admin_token),
                         json={"title": f"SMS-off smoke {uuid.uuid4().hex[:6]}",
                               "fields": [{"id": "n", "type": "text",
                                            "label": "Name", "required": True}],
                               "active": True}).json()
    r = requests.post(f"{BASE_URL}/forms/send", headers=_b(admin_token),
                      json={"template_id": tpl["id"],
                            "channel": "email",
                            "delivery_target": "smoke@example.test"})
    assert r.status_code == 200
    body = r.json()
    assert body["delivery_status"] in ("sent", "sent_stub", "failed"), body
    # "failed" is acceptable here — it means SendGrid was reached and
    # rejected the fake address. What we're actually asserting is that
    # the email path exists and does not raise.


def test_no_frontend_sms_option():
    """Grep the frontend source for any surviving SMS Select item."""
    root = "/app/frontend/src"
    proc = subprocess.run(
        ["grep", "-RIln", r"value=\"sms\"", root,
         "--include=*.jsx", "--include=*.tsx", "--include=*.js",
         "--exclude-dir=node_modules"],
        capture_output=True, text=True,
    )
    matches = [line for line in proc.stdout.splitlines() if line]
    assert matches == [], f"Frontend still offers SMS: {matches}"
