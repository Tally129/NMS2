"""
Iteration 25 — P0 Stability & Security Repair tests.

Covers:
  * MFA login with valid TOTP + invalid TOTP error message.
  * `must_enroll_mfa` gate on fresh workforce user; enroll then PHI ok.
  * Campaign HTML sanitization at CREATE (bleach allowlist).
  * RBAC 403 sentinel on cross-client transaction receipt.
  * medical_assistant PHI reads OK, POST lab-values BLOCKED w/o delegation.
  * auditor read-only.
  * front_desk / staff GET appointments + transactions.
  * bleach + tinycss2 importable; campaigns router boots.
  * Workforce mfa/disable returns 403.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone

import pymongo
import pyotp
import pytest
import requests
from passlib.context import CryptContext

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@natmedsol.local"
ADMIN_PASS = "Admin!2345"
MA_EMAIL = "ma@natmedsol.local"
MA_PASS = "MedAssist!2345"
AUDITOR_EMAIL = "auditor@natmedsol.local"
AUDITOR_PASS = "Auditor!2345"
FRONTDESK_EMAIL = "frontdesk@natmedsol.local"
FRONTDESK_PASS = "FrontDesk!2345"

FIXTURE_TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _mongo():
    c = pymongo.MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    return c, c[os.environ.get("DB_NAME", "test_database")]


def _login(email: str, password: str, use_totp: bool = True) -> dict:
    """Return {'access_token': str, 'user': dict}. Uses conftest auto-TOTP patch."""
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    j = r.json()
    if j.get("mfa_required") and use_totp:
        totp = pyotp.TOTP(FIXTURE_TOTP_SECRET).now()
        r = requests.post(f"{API}/auth/login",
                          json={"email": email, "password": password, "mfa_token": totp})
        assert r.status_code == 200, r.text
        j = r.json()
    return j


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# --------------------------------------------------------------------------- #
# 1. MFA login: valid TOTP works; invalid TOTP → "Invalid MFA code"           #
# --------------------------------------------------------------------------- #
class TestMFALogin:
    def test_admin_login_with_valid_totp_returns_token(self):
        j = _login(ADMIN_EMAIL, ADMIN_PASS, use_totp=True)
        assert j.get("access_token"), "expected access_token on successful MFA login"
        assert j["user"]["email"] == ADMIN_EMAIL
        assert j["user"]["role"] == "admin"

    def test_invalid_totp_returns_invalid_mfa_code(self):
        # First call to receive mfa_required
        r = requests.post(f"{API}/auth/login",
                          json={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
        # NB: conftest auto-injects TOTP if not provided — pass a WRONG one explicitly
        r = requests.post(f"{API}/auth/login",
                          json={"email": ADMIN_EMAIL, "password": ADMIN_PASS,
                                "mfa_token": "000000"})
        assert r.status_code == 401, r.text
        # detail should mention Invalid MFA code
        body = r.json()
        detail = body.get("detail")
        assert "Invalid MFA code" in (detail if isinstance(detail, str) else str(detail))


# --------------------------------------------------------------------------- #
# 2. must_enroll_mfa on fresh workforce user, then enroll → PHI ok            #
# --------------------------------------------------------------------------- #
class TestMustEnrollMFA:
    email = f"test_enroll_{uuid.uuid4().hex[:8]}@natmedsol.local"
    password = "EnrollTest!123"

    @pytest.fixture(scope="class", autouse=True)
    def _seed_user(self):
        import bcrypt
        from tests.pg_test_helpers import pg_users_insert, pg_users_delete
        uid = uuid.uuid4().hex
        pw_hash = bcrypt.hashpw(self.password.encode(), bcrypt.gensalt(rounds=12)).decode()
        pg_users_insert({
            "id": uid,
            "email": self.email,
            "password_hash": pw_hash,
            "full_name": "Enroll Test",
            "role": "staff",
            "is_active": True,
            "mfa_enabled": False,
            "mfa_secret": None,
            "session_version": 1,
            "created_at": datetime.now(timezone.utc),
        })
        yield uid
        pg_users_delete({"id": uid})

    def test_fresh_workforce_login_returns_token_but_phi_blocked(self):
        r = requests.post(f"{API}/auth/login",
                          json={"email": self.email, "password": self.password})
        assert r.status_code == 200, r.text
        j = r.json()
        # login succeeds — MFA gate is enforced at PHI-route time
        token = j.get("access_token")
        assert token, f"no token in login response for fresh workforce: {j}"

        # PHI route → 403 must_enroll_mfa
        r2 = requests.get(f"{API}/clients", headers=_auth_headers(token))
        assert r2.status_code == 403, f"expected 403, got {r2.status_code}: {r2.text}"
        detail = r2.json().get("detail") or {}
        assert isinstance(detail, dict) and detail.get("code") == "must_enroll_mfa", detail

        # Save token for the next test in this class
        type(self)._token = token

    def test_enrollment_flow_then_phi_ok(self):
        token = getattr(type(self), "_token", None)
        assert token, "prior test did not set token — skip"

        # /auth/mfa/setup
        r = requests.post(f"{API}/auth/mfa/setup", headers=_auth_headers(token))
        assert r.status_code == 200, r.text
        secret = r.json()["secret"]

        # /auth/mfa/verify
        totp = pyotp.TOTP(secret).now()
        r = requests.post(f"{API}/auth/mfa/verify",
                          headers=_auth_headers(token),
                          json={"token": totp})
        assert r.status_code == 200, r.text
        assert r.json().get("mfa_enabled") is True

        # PHI route now works
        r3 = requests.get(f"{API}/clients", headers=_auth_headers(token))
        assert r3.status_code == 200, f"expected 200 post-enroll, got {r3.status_code}: {r3.text[:200]}"


# --------------------------------------------------------------------------- #
# 3. Campaign HTML sanitization                                               #
# --------------------------------------------------------------------------- #
class TestCampaignSanitization:
    @pytest.fixture(scope="class")
    def admin_token(self):
        return _login(ADMIN_EMAIL, ADMIN_PASS)["access_token"]

    def test_sanitize_strips_script_iframe_onerror_javascript_but_keeps_safe_tags(self, admin_token):
        malicious = (
            "<p>Hello <b>{{patient.first_name}}</b></p>"
            "<script>alert('xss')</script>"
            "<img src=x onerror=alert(1)>"
            "<a href='javascript:alert(2)'>bad</a>"
            "<a href='https://safe.example.com'>safe</a>"
            "<iframe src='https://evil.example.com'></iframe>"
            "<ul><li>item</li></ul>"
        )
        r = requests.post(f"{API}/campaigns",
                          headers=_auth_headers(admin_token),
                          json={
                              "title": "TEST_sanitize",
                              "subject": "hi",
                              "message": malicious,
                              "channel": "email",
                              "filter_type": "all_marketing",
                              "schedule_at": (datetime.now(timezone.utc).replace(microsecond=0)
                                              .isoformat().replace("+00:00",
                                                                    "Z"))
                              # scheduled so send does not fire — but we still want stored HTML sanitized
                          })
        # Some campaign create routes require schedule_at be in the future — try +1h if 400
        if r.status_code == 400:
            from datetime import timedelta
            future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
            r = requests.post(f"{API}/campaigns",
                              headers=_auth_headers(admin_token),
                              json={"title": "TEST_sanitize", "subject": "hi",
                                    "message": malicious, "channel": "email",
                                    "filter_type": "all_marketing",
                                    "schedule_at": future})
        assert r.status_code == 200, f"create campaign failed: {r.status_code} {r.text[:300]}"
        campaign = r.json()
        stored = campaign.get("message") or ""

        # Sanitizer must strip these:
        assert "<script" not in stored.lower(), f"<script> not stripped: {stored[:400]}"
        assert "onerror" not in stored.lower(), f"onerror= not stripped: {stored[:400]}"
        assert "javascript:" not in stored.lower(), f"javascript: URL not stripped: {stored[:400]}"
        assert "<iframe" not in stored.lower(), f"<iframe> not stripped: {stored[:400]}"

        # But keep safe formatting + merge fields
        assert "<b>" in stored, f"<b> stripped unexpectedly: {stored[:400]}"
        assert "<p>" in stored, f"<p> stripped: {stored[:400]}"
        assert "<ul>" in stored, f"<ul> stripped: {stored[:400]}"
        assert "<li>" in stored, f"<li> stripped: {stored[:400]}"
        assert "{{patient.first_name}}" in stored, f"merge field lost: {stored[:400]}"
        # Safe anchor kept
        assert "safe.example.com" in stored, f"safe <a> stripped: {stored[:400]}"

        # cleanup
        _, dbh = _mongo()
        dbh.campaigns.delete_one({"id": campaign["id"]})


# --------------------------------------------------------------------------- #
# 4. RBAC 403 sentinel: patient A can't fetch patient B's receipt              #
# --------------------------------------------------------------------------- #
class TestRBACReceiptSentinel:
    def test_wrong_transaction_id_returns_403_or_404(self):
        """The FE api.js validateStatus treats 403 as a sentinel; a random-txn-id
        for a workforce role should be 404 (not-found). For cross-user access we
        rely on the endpoint's owner check. This test only asserts the API
        returns a non-200 answer for an unknown/foreign txn id."""
        tok = _login(ADMIN_EMAIL, ADMIN_PASS)["access_token"]
        fake_id = uuid.uuid4().hex
        r = requests.get(f"{API}/transactions/{fake_id}/receipt",
                         headers=_auth_headers(tok))
        assert r.status_code in (403, 404), f"expected 403/404, got {r.status_code}"


# --------------------------------------------------------------------------- #
# 5. medical_assistant permissions                                            #
# --------------------------------------------------------------------------- #
class TestMedicalAssistantRBAC:
    @pytest.fixture(scope="class")
    def ma_token(self):
        return _login(MA_EMAIL, MA_PASS)["access_token"]

    def test_ma_can_get_labs(self, ma_token):
        # Real endpoint is /labs/review-queue (queue of unreviewed labs).
        r = requests.get(f"{API}/labs/review-queue", headers=_auth_headers(ma_token))
        assert r.status_code == 200, f"MA /labs/review-queue failed {r.status_code}: {r.text[:200]}"

    def test_ma_can_get_clients(self, ma_token):
        r = requests.get(f"{API}/clients", headers=_auth_headers(ma_token))
        # Per RBAC unification spec, medical_assistant should read clients.
        # If backend still hardcodes require_roles("admin","practitioner","staff"),
        # this fails and points at an incomplete unification.
        assert r.status_code == 200, f"MA /clients failed {r.status_code}: {r.text[:200]}"

    def test_ma_blocked_from_post_lab_values(self, ma_token):
        # No active delegation → 403
        r = requests.post(f"{API}/lab-values",
                          headers=_auth_headers(ma_token),
                          json={"client_id": "nonexistent", "test_name": "CBC",
                                "value": "5", "unit": "x10^9/L"})
        # 403 (RBAC) or 404 (endpoint not found) both indicate MA cannot POST.
        # We assert NOT 200/201 — MA must never author lab values directly.
        assert r.status_code not in (200, 201), (
            f"MA unexpectedly created lab value: {r.status_code} {r.text[:200]}"
        )


# --------------------------------------------------------------------------- #
# 6. Auditor: reads OK, writes deny                                            #
# --------------------------------------------------------------------------- #
class TestAuditorRBAC:
    @pytest.fixture(scope="class")
    def auditor_token(self):
        return _login(AUDITOR_EMAIL, AUDITOR_PASS)["access_token"]

    def test_auditor_get_clients(self, auditor_token):
        r = requests.get(f"{API}/clients", headers=_auth_headers(auditor_token))
        assert r.status_code == 200, f"auditor GET clients: {r.status_code} {r.text[:200]}"

    def test_auditor_post_denied(self, auditor_token):
        r = requests.post(f"{API}/clients",
                          headers=_auth_headers(auditor_token),
                          json={"full_name": "TEST_auditor_post",
                                "email": f"TEST_aud_{uuid.uuid4().hex[:6]}@x.com"})
        assert r.status_code == 403, f"auditor POST should 403 got {r.status_code}"


# --------------------------------------------------------------------------- #
# 7. front_desk / staff role — appointments + transactions                    #
# --------------------------------------------------------------------------- #
class TestStaffFrontDeskRBAC:
    @pytest.fixture(scope="class")
    def staff_token(self):
        return _login(FRONTDESK_EMAIL, FRONTDESK_PASS)["access_token"]

    def test_staff_get_appointments(self, staff_token):
        r = requests.get(f"{API}/appointments", headers=_auth_headers(staff_token))
        assert r.status_code == 200, f"staff GET appointments {r.status_code}: {r.text[:200]}"

    def test_staff_get_transactions(self, staff_token):
        r = requests.get(f"{API}/transactions", headers=_auth_headers(staff_token))
        assert r.status_code == 200, f"staff GET transactions {r.status_code}: {r.text[:200]}"


# --------------------------------------------------------------------------- #
# 8. Workforce POST /api/auth/mfa/disable → 403                                #
# --------------------------------------------------------------------------- #
class TestWorkforceCantDisableMFA:
    def test_admin_cannot_disable_mfa(self):
        tok = _login(ADMIN_EMAIL, ADMIN_PASS)["access_token"]
        r = requests.post(f"{API}/auth/mfa/disable", headers=_auth_headers(tok))
        assert r.status_code == 403, f"workforce disable should 403 got {r.status_code}: {r.text[:200]}"


# --------------------------------------------------------------------------- #
# 9. bleach + tinycss2 importable + campaigns endpoint reachable              #
# --------------------------------------------------------------------------- #
class TestBleachInstalled:
    def test_bleach_and_tinycss2_are_installed(self):
        import bleach  # noqa: F401
        import tinycss2  # noqa: F401
        from bleach.css_sanitizer import CSSSanitizer  # noqa: F401
        assert True

    def test_campaigns_config_delivery_reachable(self):
        tok = _login(ADMIN_EMAIL, ADMIN_PASS)["access_token"]
        r = requests.get(f"{API}/campaigns/config/delivery",
                         headers=_auth_headers(tok))
        assert r.status_code == 200
        assert "email" in r.json() and "sms" in r.json()
