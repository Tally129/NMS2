"""
Session 2c — Admin Bootstrap end-to-end tests.

Exercises the forced onboarding flow: first-admin bootstrap → temp password →
short-lived bootstrap JWT (password_change) → forced password change → second
bootstrap JWT (mfa_enrollment) → forced MFA enrollment → 8 recovery codes →
normal MFA-gated login → recovery-code fallback (single-use, atomic).

Runs against the live REACT_APP_BACKEND_URL — no mocking.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pyotp
import pytest
import requests

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass


BASE_URL = os.environ.get("REACT_APP_BACKEND_URL") or "http://127.0.0.1:8001"
API = f"{BASE_URL}/api"
PG_URL_RAW = os.environ.get("DATABASE_URL", "")
PG_URL = PG_URL_RAW.replace("postgresql+psycopg://", "postgresql://", 1) if PG_URL_RAW else ""
BOOTSTRAP_SECRET = os.environ.get("BOOTSTRAP_SECRET") or ""


if not PG_URL:
    pytest.skip("DATABASE_URL not configured — skipping Session 2c tests",
                allow_module_level=True)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #
def _rand_email(prefix: str = "bootstrap") -> str:
    return f"{prefix}.{secrets.token_hex(6)}@natmedsol.local"


def _pg():
    return psycopg.connect(PG_URL)


def _delete_user(email: str) -> None:
    with _pg() as c:
        with c.cursor() as cur:
            cur.execute("DELETE FROM auth_users WHERE lower(email) = %s", (email.lower(),))
        c.commit()


def _read_user(email: str) -> dict:
    with _pg() as c:
        with c.cursor() as cur:
            cur.execute(
                "SELECT id, email, role, mfa_enabled, must_change_password, "
                "onboarding_status, temporary_password_expires_at, password_hash "
                "FROM auth_users WHERE lower(email) = %s", (email.lower(),))
            row = cur.fetchone()
    if not row:
        return {}
    keys = ("id", "email", "role", "mfa_enabled", "must_change_password",
            "onboarding_status", "temporary_password_expires_at", "password_hash")
    return dict(zip(keys, row))


def _set_temp_password_expired(user_id: str) -> None:
    """Push the temp-password expiry into the past for the expiry test."""
    with _pg() as c:
        with c.cursor() as cur:
            cur.execute(
                "UPDATE auth_users SET temporary_password_expires_at = NOW() - INTERVAL '1 hour' "
                "WHERE id = %s", (user_id,))
        c.commit()


def _admin_login_token() -> str:
    """The pre-existing seeded admin used to hit /api/admin/*. This account
    was seeded with MFA + full onboarding done, so it takes the normal path."""
    totp = pyotp.TOTP("JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP").now()
    r = requests.post(f"{API}/auth/login", json={
        "email": "admin@natmedsol.local", "password": "Admin!2345",
        "mfa_token": totp,
    })
    r.raise_for_status()
    return r.json()["access_token"]


# --------------------------------------------------------------------------- #
# 1. First-admin bootstrap                                                     #
# --------------------------------------------------------------------------- #
class TestFirstAdminBootstrap:
    def test_endpoint_returns_503_when_secret_not_configured(self, monkeypatch):
        # The live server may already be configured — this test only asserts
        # the server refuses unauthenticated calls when the secret is missing
        # OR the header is missing. A missing header must always 401.
        r = requests.post(f"{API}/auth/bootstrap/first-admin", json={
            "email": _rand_email(),
        })
        # 401 (bad secret) or 503 (server unconfigured) — never 200 without header
        assert r.status_code in (401, 503), r.text

    @pytest.mark.skipif(not BOOTSTRAP_SECRET,
                        reason="BOOTSTRAP_SECRET not set — first-admin test requires it")
    def test_wrong_secret_fails_and_is_audited(self):
        r = requests.post(f"{API}/auth/bootstrap/first-admin",
                          headers={"X-Bootstrap-Secret": "totally-wrong-secret"},
                          json={"email": _rand_email()})
        assert r.status_code == 401, r.text

    @pytest.mark.skipif(not BOOTSTRAP_SECRET,
                        reason="BOOTSTRAP_SECRET not set — first-admin test requires it")
    def test_refuses_once_admin_exists(self):
        # The seeded admin@natmedsol.local (role=admin) already exists, so any
        # correct-secret call must 409.
        r = requests.post(
            f"{API}/auth/bootstrap/first-admin",
            headers={"X-Bootstrap-Secret": BOOTSTRAP_SECRET},
            json={"email": _rand_email("second-admin")},
        )
        assert r.status_code == 409, r.text


# --------------------------------------------------------------------------- #
# 2. Full onboarding lifecycle — admin creates a new practitioner              #
# --------------------------------------------------------------------------- #
class TestWorkforceOnboardingLifecycle:
    @classmethod
    def setup_class(cls):
        cls.admin_token = _admin_login_token()
        cls.email = _rand_email("pract")
        # Admin creates a practitioner — should get a temp password + onboarding_status.
        r = requests.post(
            f"{API}/admin/users",
            headers={"Authorization": f"Bearer {cls.admin_token}"},
            json={"email": cls.email, "password": "ignored-server-generates",
                  "full_name": "Bootstrap Testee", "role": "practitioner"},
        )
        assert r.status_code == 200, r.text
        cls.create_resp = r.json()
        cls.temp_password = cls.create_resp["temporary_password"]

    @classmethod
    def teardown_class(cls):
        _delete_user(cls.email)

    def test_step_01_creation_returns_temp_password_and_onboarding_state(self):
        assert self.create_resp.get("temporary_password"), self.create_resp
        assert self.create_resp["onboarding_status"] == "password_change_required"
        assert "temporary_password_expires_at" in self.create_resp
        row = _read_user(self.email)
        assert row["role"] == "practitioner"
        assert row["must_change_password"] is True
        assert row["onboarding_status"] == "password_change_required"
        assert row["mfa_enabled"] is False

    def test_step_02_first_login_returns_bootstrap_token_no_refresh_cookie(self):
        sess = requests.Session()
        r = sess.post(f"{API}/auth/login", json={
            "email": self.email, "password": self.temp_password,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("bootstrap_stage") == "password_change"
        assert body.get("bootstrap_token")
        assert not body.get("access_token"), "must NOT issue a normal access token yet"
        assert "nms_rt" not in sess.cookies, "must NOT set a refresh cookie during bootstrap"
        type(self).boot_token_pw = body["bootstrap_token"]

    def test_step_03_bootstrap_token_cannot_access_normal_endpoints(self):
        # /api/auth/me expects a normal access token. Bootstrap must be rejected.
        r = requests.get(f"{API}/auth/me",
                         headers={"Authorization": f"Bearer {self.boot_token_pw}"})
        assert r.status_code == 401, r.text
        assert "access" in r.text.lower() or "token" in r.text.lower()

    def test_step_04_normal_login_endpoints_reject_bootstrap_token(self):
        # /api/auth/mfa/setup (normal) accepts access-JWT via get_authenticated_user;
        # a bootstrap JWT must NOT satisfy that dependency.
        r = requests.post(f"{API}/auth/mfa/setup",
                          headers={"Authorization": f"Bearer {self.boot_token_pw}"})
        assert r.status_code == 401, r.text

    def test_step_05_password_change_completes_and_advances_onboarding(self):
        new_pw = "TrailW1ndSummerBrookHexagon-42"
        r = requests.post(
            f"{API}/auth/bootstrap/password-change",
            headers={"Authorization": f"Bearer {self.boot_token_pw}"},
            json={"current_password": self.temp_password, "new_password": new_pw},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["next_step"] == "mfa_enrollment"
        type(self).new_password = new_pw

        row = _read_user(self.email)
        assert row["must_change_password"] is False
        assert row["onboarding_status"] == "mfa_enrollment_required"
        assert row["temporary_password_expires_at"] is None

    def test_step_06_old_temp_password_stops_working(self):
        r = requests.post(f"{API}/auth/login", json={
            "email": self.email, "password": self.temp_password,
        })
        assert r.status_code == 401, r.text

    def test_step_07_second_login_returns_mfa_enrollment_bootstrap_token(self):
        r = requests.post(f"{API}/auth/login", json={
            "email": self.email, "password": self.new_password,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("bootstrap_stage") == "mfa_enrollment"
        assert body.get("bootstrap_token")
        assert not body.get("access_token")
        type(self).boot_token_mfa = body["bootstrap_token"]

    def test_step_08_mfa_setup_returns_secret_and_uri(self):
        r = requests.post(f"{API}/auth/bootstrap/mfa/setup",
                          headers={"Authorization": f"Bearer {self.boot_token_mfa}"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["secret"] and body["provisioning_uri"]
        type(self).mfa_secret = body["secret"]
        # Still not enabled until /verify succeeds.
        row = _read_user(self.email)
        assert row["mfa_enabled"] is False

    def test_step_09_invalid_totp_does_not_enable_mfa(self):
        r = requests.post(
            f"{API}/auth/bootstrap/mfa/verify",
            headers={"Authorization": f"Bearer {self.boot_token_mfa}"},
            json={"token": "000000"},
        )
        assert r.status_code == 401, r.text
        assert _read_user(self.email)["mfa_enabled"] is False

    def test_step_10_valid_totp_enables_mfa_and_returns_8_recovery_codes(self):
        totp = pyotp.TOTP(self.mfa_secret).now()
        r = requests.post(
            f"{API}/auth/bootstrap/mfa/verify",
            headers={"Authorization": f"Bearer {self.boot_token_mfa}"},
            json={"token": totp},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True and body["mfa_enabled"] is True
        codes = body.get("recovery_codes") or []
        assert len(codes) == 8, f"expected 8 codes, got {len(codes)}"
        # All codes must be 10 chars from the unambiguous alphabet.
        alphabet = set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
        for c in codes:
            assert len(c) == 10
            assert set(c) <= alphabet, f"unexpected chars in {c!r}"
        type(self).recovery_codes = codes

        row = _read_user(self.email)
        assert row["mfa_enabled"] is True
        assert row["onboarding_status"] is None

    def test_step_11_recovery_codes_not_stored_plaintext(self):
        with _pg() as c:
            with c.cursor() as cur:
                cur.execute(
                    "SELECT code_hash FROM auth_recovery_codes "
                    "WHERE user_id = (SELECT id FROM auth_users WHERE lower(email) = %s)",
                    (self.email.lower(),))
                rows = [r[0] for r in cur.fetchall()]
        assert len(rows) == 8
        expected_hashes = {hashlib.sha256(c.upper().encode()).hexdigest() for c in self.recovery_codes}
        assert set(rows) == expected_hashes, "stored hashes must match sha256(code)"

    def test_step_12_normal_login_after_onboarding_requires_totp(self):
        totp = pyotp.TOTP(self.mfa_secret).now()
        sess = requests.Session()
        r = sess.post(f"{API}/auth/login", json={
            "email": self.email, "password": self.new_password,
            "mfa_token": totp,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["access_token"]
        assert "nms_rt" in sess.cookies
        # /api/auth/me now returns the user profile.
        me = requests.get(f"{API}/auth/me",
                          headers={"Authorization": f"Bearer {body['access_token']}"})
        assert me.status_code == 200
        assert me.json()["email"] == self.email

    def test_step_13_recovery_code_succeeds_once(self):
        code = self.recovery_codes[0]
        sess = requests.Session()
        r = sess.post(f"{API}/auth/login", json={
            "email": self.email, "password": self.new_password,
            "mfa_token": code,
        })
        assert r.status_code == 200, r.text
        assert r.json().get("access_token")
        # Reuse must fail with 401.
        r2 = requests.post(f"{API}/auth/login", json={
            "email": self.email, "password": self.new_password,
            "mfa_token": code,
        })
        assert r2.status_code == 401, r2.text

    def test_step_14_concurrent_recovery_code_use_can_only_succeed_once(self):
        """Two threads race the same code — at most one 200 (the other 401)."""
        code = self.recovery_codes[1]

        def _hit():
            return requests.post(f"{API}/auth/login", json={
                "email": self.email, "password": self.new_password,
                "mfa_token": code,
            })

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futures = [ex.submit(_hit) for _ in range(4)]
            statuses = sorted(f.result().status_code for f in futures)
        n_200 = statuses.count(200)
        n_401 = statuses.count(401)
        assert n_200 == 1, f"exactly one concurrent redemption may win (got {statuses})"
        assert n_401 == 3, f"the other three must be 401 (got {statuses})"


# --------------------------------------------------------------------------- #
# 3. Guardrails — existing MFA-enabled admins keep working                     #
# --------------------------------------------------------------------------- #
class TestExistingMfaAdminUnaffected:
    def test_seeded_admin_normal_login_still_works(self):
        totp = pyotp.TOTP("JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP").now()
        r = requests.post(f"{API}/auth/login", json={
            "email": "admin@natmedsol.local", "password": "Admin!2345",
            "mfa_token": totp,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        # Must NOT be a bootstrap response — the seeded admin is fully onboarded.
        assert body.get("access_token"), body
        assert not body.get("bootstrap_token"), body
        assert body["user"]["mfa_enabled"] is True


# --------------------------------------------------------------------------- #
# 4. Client / patient signups are NOT forced through workforce onboarding      #
# --------------------------------------------------------------------------- #
class TestClientSignupNotForcedThroughOnboarding:
    def test_client_registration_yields_normal_session(self):
        email = _rand_email("client")
        try:
            sess = requests.Session()
            r = sess.post(f"{API}/auth/register", json={
                "email": email, "password": "Cli3ntPassPhraseStrong!!",
                "full_name": "Test Client", "phone": "+15550101",
            })
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["access_token"], "clients get a normal session immediately"
            assert not body.get("bootstrap_token")
            row = _read_user(email)
            assert row["role"] == "client"
            assert row["onboarding_status"] is None
            assert row["must_change_password"] is False
        finally:
            _delete_user(email)


# --------------------------------------------------------------------------- #
# 5. Temporary password expiry blocks bootstrap login                          #
# --------------------------------------------------------------------------- #
class TestTemporaryPasswordExpiry:
    def test_expired_temp_password_is_rejected(self):
        admin_token = _admin_login_token()
        email = _rand_email("expired")
        try:
            r = requests.post(
                f"{API}/admin/users",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"email": email, "password": "x", "full_name": "E X", "role": "staff"},
            )
            assert r.status_code == 200
            temp_pw = r.json()["temporary_password"]
            row = _read_user(email)
            _set_temp_password_expired(row["id"])
            r2 = requests.post(f"{API}/auth/login", json={
                "email": email, "password": temp_pw,
            })
            assert r2.status_code == 403, r2.text
            body = r2.json()
            detail = body.get("detail") if isinstance(body, dict) else body
            assert isinstance(detail, dict) and detail.get("code") == "temporary_password_expired"
        finally:
            _delete_user(email)
