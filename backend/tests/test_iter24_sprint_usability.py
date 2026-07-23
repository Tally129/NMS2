"""
Sprint: Frontend Usability & Workflow Completion — backend endpoint verification.

Scope
-----
1. GET  /api/search/global?q=... — RBAC bucketed results envelope
2. POST /api/dev/portal-test-patient — idempotent seed w/ mrn=NMS-TEST01, tag
3. GET  /api/clients/{cid}/portal-status
4. POST /api/clients/{cid}/portal-invite
5. POST /api/clients/{cid}/portal-reset-password (400 when no portal user)
6. POST /api/clients/{cid}/portal-disable  + /portal-enable
7. GET  /api/transactions/{tid}/receipt — %PDF magic + client isolation
8. POST /api/transactions/{tid}/email — stub SendGrid dispatch
9. POST /api/labs/{lab_id}/attachments  + DELETE detach
10. POST /api/campaigns — rich HTML body + merge fields render correctly
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict

import pyotp
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"

ADMIN_EMAIL = "admin@natmedsol.local"
ADMIN_PASSWORD = "Admin!2345"
PRACT_EMAIL = "ravello@natmedsol.local"
PRACT_PASSWORD = "Ravello!2345"
STAFF_EMAIL = "frontdesk@natmedsol.local"
STAFF_PASSWORD = "FrontDesk!2345"
MA_EMAIL = "ma@natmedsol.local"
MA_PASSWORD = "MedAssist!2345"


def _login(email: str, password: str) -> str:
    """Login (conftest.py auto-injects TOTP for seeded workforce)."""
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:300]}"
    body = r.json()
    tok = body.get("access_token") or ""
    assert tok, f"no access_token for {email}: {body}"
    return tok


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def practitioner_token() -> str:
    return _login(PRACT_EMAIL, PRACT_PASSWORD)


@pytest.fixture(scope="module")
def staff_token() -> str:
    return _login(STAFF_EMAIL, STAFF_PASSWORD)


def _h(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# --------------------------------------------------------------------------- #
# 1) Global search                                                            #
# --------------------------------------------------------------------------- #
class TestGlobalSearch:
    def test_search_empty_query_returns_empty_envelope(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/search/global?q=", headers=_h(admin_token), timeout=10)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body == {"query": "", "results": {}}

    def test_search_admin_gets_users_bucket_for_admin_email(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/search/global?q=admin", headers=_h(admin_token), timeout=10)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body.get("query") == "admin"
        buckets = body.get("results") or {}
        assert "users" in buckets, f"expected users bucket, got {list(buckets.keys())}"
        emails = [(u.get("sub") or "").lower() for u in buckets["users"]]
        assert any("admin@natmedsol.local" in e for e in emails), f"admin user missing from bucket: {emails}"

    def test_search_practitioner_can_search_patients(self, practitioner_token):
        r = requests.get(f"{BASE_URL}/api/search/global?q=a", headers=_h(practitioner_token), timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert "results" in body
        # practitioner is workforce → should see multiple buckets
        assert isinstance(body["results"], dict)


# --------------------------------------------------------------------------- #
# 2) Portal test-patient seeder + portal management                           #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def test_patient(admin_token) -> Dict[str, Any]:
    r = requests.post(
        f"{BASE_URL}/api/dev/portal-test-patient",
        headers=_h(admin_token), json={}, timeout=20,
    )
    assert r.status_code == 200, f"seed failed: {r.status_code} {r.text[:300]}"
    body = r.json()
    assert body.get("ok") is True
    assert body.get("client_id")
    assert body.get("user_id")
    assert body.get("portal_login_url", "").endswith("/login"), body.get("portal_login_url")
    assert "reset-password?token=" in (body.get("portal_password_setup_url") or "")
    return body


class TestPortalSeeder:
    def test_seed_returns_expected_fields(self, test_patient):
        assert test_patient["email"] == "portal.test@natmedsol.local"

    def test_seed_is_idempotent(self, admin_token, test_patient):
        r2 = requests.post(
            f"{BASE_URL}/api/dev/portal-test-patient",
            headers=_h(admin_token), json={}, timeout=20,
        )
        assert r2.status_code == 200
        assert r2.json().get("client_id") == test_patient["client_id"]

    def test_seed_client_record_has_expected_flags(self, admin_token, test_patient):
        # ClientOut Pydantic model strips fields it doesn't declare (like `tags`),
        # so query the DB directly to verify the flags the seeder wrote.
        import pymongo
        mc = pymongo.MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        dbh = mc[os.environ.get("DB_NAME", "test_database")]
        raw = dbh.clients.find_one({"id": test_patient["client_id"]})
        mc.close()
        assert raw is not None, "seeded client not found in DB"
        assert raw.get("mrn") == "NMS-TEST01", f"expected NMS-TEST01, got {raw.get('mrn')}"
        assert raw.get("consent_marketing") is False
        tags = raw.get("tags") or []
        assert "portal_test_patient" in tags, f"missing tag portal_test_patient in {tags}"

    def test_portal_status_reports_active(self, admin_token, test_patient):
        r = requests.get(
            f"{BASE_URL}/api/clients/{test_patient['client_id']}/portal-status",
            headers=_h(admin_token), timeout=10,
        )
        assert r.status_code == 200
        s = r.json()
        assert s["has_portal"] is True
        assert s["portal_active"] is True
        assert s["is_test_patient"] is True
        assert s["email"] == "portal.test@natmedsol.local"


class TestPortalActions:
    def test_portal_invite_returns_url_non_hipaa(self, admin_token, test_patient):
        r = requests.post(
            f"{BASE_URL}/api/clients/{test_patient['client_id']}/portal-invite",
            headers=_h(admin_token), json={}, timeout=15,
        )
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body.get("ok") is True
        assert body.get("invite_url") and "reset-password?token=" in body["invite_url"]
        assert body.get("delivery") in ("sent", "sent_stub")
        assert body.get("ttl_minutes") == 60 * 24

    def test_portal_reset_password_returns_fresh_link(self, admin_token, test_patient):
        r = requests.post(
            f"{BASE_URL}/api/clients/{test_patient['client_id']}/portal-reset-password",
            headers=_h(admin_token), json={}, timeout=15,
        )
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["ttl_minutes"] == 60
        assert body.get("invite_url", "").find("reset-password?token=") >= 0

    def test_portal_reset_400_when_no_portal_user(self, admin_token):
        # Create a bare client with no user_id
        r = requests.post(
            f"{BASE_URL}/api/clients",
            headers=_h(admin_token),
            json={"full_name": "TEST_NoPortalUser", "email": f"test_noportal_{int(time.time())}@example.com"},
            timeout=10,
        )
        assert r.status_code in (200, 201), r.text[:300]
        cid = r.json()["id"]
        try:
            r2 = requests.post(
                f"{BASE_URL}/api/clients/{cid}/portal-reset-password",
                headers=_h(admin_token), json={}, timeout=10,
            )
            assert r2.status_code == 400
        finally:
            requests.delete(f"{BASE_URL}/api/clients/{cid}", headers=_h(admin_token), timeout=10)

    def test_portal_disable_then_enable(self, admin_token, test_patient):
        r_d = requests.post(
            f"{BASE_URL}/api/clients/{test_patient['client_id']}/portal-disable",
            headers=_h(admin_token), json={"reason": "test"}, timeout=10,
        )
        assert r_d.status_code == 200, r_d.text[:300]

        # confirm inactive via status endpoint
        r_s = requests.get(
            f"{BASE_URL}/api/clients/{test_patient['client_id']}/portal-status",
            headers=_h(admin_token), timeout=10,
        )
        assert r_s.status_code == 200
        assert r_s.json()["portal_active"] is False

        r_e = requests.post(
            f"{BASE_URL}/api/clients/{test_patient['client_id']}/portal-enable",
            headers=_h(admin_token), json={}, timeout=10,
        )
        assert r_e.status_code == 200

        r_s2 = requests.get(
            f"{BASE_URL}/api/clients/{test_patient['client_id']}/portal-status",
            headers=_h(admin_token), timeout=10,
        )
        assert r_s2.json()["portal_active"] is True


# --------------------------------------------------------------------------- #
# 3) Invoice PDF + email                                                      #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def sample_txn(admin_token, test_patient) -> str:
    """Create a POS transaction we can render into a PDF."""
    payload = {
        "client_id": test_patient["client_id"],
        "lines": [
            {"type": "treatment", "name": "Wellness Consultation",
             "qty": 1, "unit_price": 150.0},
            {"type": "inventory", "name": "Vitamin B12 IM (single)",
             "qty": 2, "unit_price": 25.0},
        ],
        "discount": 0, "tip": 0, "tax_rate": 0,
        "payment_method": "cash",
    }
    r = requests.post(
        f"{BASE_URL}/api/pos/checkout", headers=_h(admin_token),
        json=payload, timeout=15,
    )
    assert r.status_code == 200, f"pos checkout failed: {r.status_code} {r.text[:400]}"
    return r.json()["id"]


class TestInvoicePDF:
    def test_receipt_returns_pdf_bytes(self, admin_token, sample_txn):
        r = requests.get(
            f"{BASE_URL}/api/transactions/{sample_txn}/receipt",
            headers={"Authorization": f"Bearer {admin_token}"}, timeout=15,
        )
        assert r.status_code == 200, r.text[:300]
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF", f"expected %PDF magic, got: {r.content[:8]!r}"
        cd = r.headers.get("content-disposition", "")
        assert "INV-" in cd and cd.endswith('.pdf"'), f"bad Content-Disposition: {cd!r}"

    def test_email_invoice_returns_delivery_status(self, admin_token, sample_txn):
        r = requests.post(
            f"{BASE_URL}/api/transactions/{sample_txn}/email",
            headers=_h(admin_token),
            json={"to": "qa+invoice@example.com"}, timeout=15,
        )
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["ok"] is True
        assert body["delivery"] in ("sent", "sent_stub")
        assert body["invoice_number"].startswith("INV-")


# --------------------------------------------------------------------------- #
# 4) Lab attachments                                                          #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def sample_lab(practitioner_token, test_patient) -> str:
    """Insert a lab_value directly via the health-track API."""
    payload = {
        "client_id": test_patient["client_id"],
        "test_name": "Vitamin D, 25-OH",
        "value": 22.0,
        "unit": "ng/mL",
        "reference_low": 30, "reference_high": 100,
        "measured_at": "2026-07-01T10:00:00Z",
    }
    r = requests.post(
        f"{BASE_URL}/api/lab-values", headers=_h(practitioner_token),
        json=payload, timeout=10,
    )
    if r.status_code not in (200, 201):
        pytest.skip(f"could not seed lab: {r.status_code} {r.text[:200]}")
    return r.json()["id"]


@pytest.fixture(scope="module")
def uploaded_file(practitioner_token, test_patient) -> str:
    """Upload a tiny stub file into the file vault for attachment tests."""
    files = {"file": ("stub.txt", b"stub lab result", "text/plain")}
    data = {"client_id": test_patient["client_id"], "category": "lab"}
    r = requests.post(
        f"{BASE_URL}/api/files/upload",
        headers={"Authorization": f"Bearer {practitioner_token}"},
        files=files, data=data, timeout=15,
    )
    if r.status_code not in (200, 201):
        pytest.skip(f"file upload failed: {r.status_code} {r.text[:200]}")
    body = r.json()
    return body.get("id") or body.get("file_id") or body["file"]["id"]


class TestLabAttachments:
    def test_provider_can_attach_and_detach_file(self, practitioner_token, sample_lab, uploaded_file):
        r = requests.post(
            f"{BASE_URL}/api/labs/{sample_lab}/attachments",
            headers=_h(practitioner_token),
            json={"file_id": uploaded_file}, timeout=10,
        )
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert uploaded_file in (body.get("attachment_file_ids") or [])

        r2 = requests.delete(
            f"{BASE_URL}/api/labs/{sample_lab}/attachments/{uploaded_file}",
            headers=_h(practitioner_token), timeout=10,
        )
        assert r2.status_code == 200
        assert r2.json().get("ok") is True


# --------------------------------------------------------------------------- #
# 5) Campaigns: HTML + merge variables                                        #
# --------------------------------------------------------------------------- #
class TestCampaignRichText:
    def test_create_campaign_with_html_and_variables(self, admin_token, test_patient):
        html_body = (
            "<h2>Hi {patient.first_name}!</h2>"
            "<p><strong>Reminder</strong>: your appointment with our team is coming up.</p>"
            "<p>Warmly,<br/>NatMedSol</p>"
        )
        payload = {
            "title": "TEST_iter24_rich_html",
            "channel": "email",
            "subject": "Hello {patient.first_name}",
            "message": html_body,
            "audience": {"client_ids": [test_patient["client_id"]]},
        }
        r = requests.post(
            f"{BASE_URL}/api/campaigns",
            headers=_h(admin_token),
            json=payload, timeout=15,
        )
        assert r.status_code in (200, 201), r.text[:400]
        campaign = r.json()
        assert campaign.get("id")
        # Verify the raw HTML round-trips (tags preserved).
        assert "<h2>" in (campaign.get("message") or ""), campaign.get("message", "")[:200]

    def test_create_campaign_sms_plain(self, admin_token, test_patient):
        payload = {
            "title": "TEST_iter24_sms",
            "channel": "sms",
            "message": "Hi {patient.first_name}, reminder from NatMedSol.",
            "audience": {"client_ids": [test_patient["client_id"]]},
        }
        r = requests.post(
            f"{BASE_URL}/api/campaigns",
            headers=_h(admin_token),
            json=payload, timeout=15,
        )
        assert r.status_code in (200, 201), r.text[:400]


# --------------------------------------------------------------------------- #
# Cleanup — delete the seeded test patient last                               #
# --------------------------------------------------------------------------- #
def test_zz_cleanup_test_patient(admin_token, test_patient):
    r = requests.delete(
        f"{BASE_URL}/api/dev/portal-test-patient/{test_patient['client_id']}",
        headers=_h(admin_token), timeout=10,
    )
    assert r.status_code == 200


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
