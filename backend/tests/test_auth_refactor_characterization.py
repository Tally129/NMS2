"""Characterization tests for the Session 1 auth refactor.

These tests lock in observable auth-router behaviour so the atomic
PostgreSQL cutover in Session 2 can be verified against the same
guarantees. They rely on `conftest.py`'s session-scoped fixture that
enables MFA on seeded workforce and auto-appends TOTP to any login,
so a single `POST /api/auth/login` returns the final access token.
"""
from __future__ import annotations

import os
import time
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://design-158.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"
PRACTITIONER_EMAIL = "ravello@natmedsol.local"
PRACTITIONER_PW = "Ravello!2345"


# ---------- Structural (imports + route registration) --------------------- #

class TestRouterStructureUnchanged:
    def test_public_module_still_importable(self):
        import routers.auth  # noqa: F401

    def test_every_expected_endpoint_still_registered(self):
        import routers.auth  # noqa: F401
        from deps import api
        paths = {r.path for r in api.routes
                 if hasattr(r, "path") and r.path.startswith("/api/auth")}
        expected = {
            "/api/auth/register", "/api/auth/login", "/api/auth/login/continue",
            "/api/auth/refresh", "/api/auth/logout", "/api/auth/logout-all",
            "/api/auth/sessions", "/api/auth/me",
        }
        assert expected.issubset(paths), f"missing: {expected - paths}"
        # Session 2a removed the four Google OAuth routes; the surface is now
        # ≥16 auth endpoints. Assert a floor so accidental deletions still trip.
        assert len(paths) >= 16, f"expected ≥16 auth routes, got {len(paths)}"
        # And confirm every Google endpoint has been removed.
        google_routes = {p for p in paths if "/google" in p}
        assert google_routes == set(), f"Google routes must be gone: {google_routes}"

    def test_helpers_still_exposed_on_routers_auth(self):
        from routers.auth import (  # noqa: F401
            _create_session, _email_hash, _hash_token,
            _set_refresh_cookie, _clear_refresh_cookie,
            _revoke_all_sessions, _revoke_session,
        )


# ---------- Behavioural (real HTTP through conftest auto-TOTP) ------------ #

class TestLoginFlowStillWorks:
    def _login(self):
        """conftest.py auto-appends TOTP; a single call returns access_token."""
        s = requests.Session()
        r = s.post(f"{API}/auth/login",
                   json={"email": PRACTITIONER_EMAIL,
                         "password": PRACTITIONER_PW}, timeout=15)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        d = r.json()
        assert d.get("access_token"), "missing access_token"
        assert d.get("user", {}).get("id"), "missing user.id"
        assert d.get("user", {}).get("role") == "practitioner"
        # refresh cookie set as HttpOnly on the response (not in JSON body)
        assert s.cookies.get("nms_rt"), "refresh cookie missing"
        return s, d["access_token"]

    def test_login_returns_access_token_and_refresh_cookie(self):
        s, access = self._login()
        assert access and s.cookies.get("nms_rt")

    def test_me_endpoint_works_with_access_token(self):
        _, access = self._login()
        r = requests.get(f"{API}/auth/me",
                         headers={"Authorization": f"Bearer {access}"},
                         timeout=15)
        assert r.status_code == 200, r.text[:200]
        assert r.json().get("email", "").lower() == PRACTITIONER_EMAIL

    def test_invalid_password_returns_401(self):
        # conftest auto-TOTP retries once — a bad password fails both times.
        r = requests.post(f"{API}/auth/login",
                          json={"email": PRACTITIONER_EMAIL,
                                "password": "wrong-password"}, timeout=15)
        assert r.status_code == 401, r.text[:200]

    def test_refresh_rotates_cookie(self):
        s, _ = self._login()
        original_refresh = s.cookies.get("nms_rt")
        time.sleep(0.1)
        r = s.post(f"{API}/auth/refresh", timeout=15)
        assert r.status_code == 200, f"refresh: {r.status_code} {r.text[:200]}"
        assert r.json().get("access_token")
        new_refresh = s.cookies.get("nms_rt")
        assert new_refresh and new_refresh != original_refresh, "cookie must rotate"

    def test_sessions_list_includes_current_session(self):
        _, access = self._login()
        r = requests.get(f"{API}/auth/sessions",
                         headers={"Authorization": f"Bearer {access}"},
                         timeout=15)
        assert r.status_code == 200, r.text[:200]
        rows = r.json()
        assert isinstance(rows, list)
        assert any(s.get("is_current") for s in rows)


class TestPasswordResetContract:
    def test_forgot_password_never_reveals_account_existence(self):
        r = requests.post(f"{API}/auth/forgot-password",
                          json={"email": f"nobody.{int(time.time())}@example.com"},
                          timeout=15)
        # Generic success — never a 4xx that could enumerate accounts.
        assert r.status_code == 200, r.text[:200]


class TestGoogleOAuthRemoved:
    """Session 2a — every Google OAuth surface must return 404."""

    def test_authorize_route_removed(self):
        r = requests.get(f"{API}/auth/google/oauth/authorize", timeout=15)
        assert r.status_code == 404, r.text[:200]

    def test_callback_route_removed(self):
        r = requests.get(f"{API}/auth/google/oauth/callback",
                         params={"code": "x", "state": "y"}, timeout=15)
        assert r.status_code == 404, r.text[:200]

    def test_exchange_route_removed(self):
        r = requests.post(f"{API}/auth/google/oauth/exchange",
                          json={"handoff_id": "x"}, timeout=15)
        assert r.status_code == 404, r.text[:200]

    def test_emergent_session_route_removed(self):
        r = requests.post(f"{API}/auth/google/session", timeout=15)
        assert r.status_code == 404, r.text[:200]
