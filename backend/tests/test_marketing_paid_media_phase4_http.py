"""Phase 4 LIVE HTTP tests — Meta / Microsoft read-only paid-media providers.

Covers:
  * GET /api/marketing-os/paid/providers
  * GET /api/marketing-os/paid/{provider}/readiness
  * GET /api/marketing-os/paid/performance
  * GET /api/marketing-os/director/brief  (paid_media block + safety)
  * Authorization (staff role, unauthenticated)
"""
from __future__ import annotations

import os

import pytest
import requests
from dotenv import dotenv_values

_env = dotenv_values("/app/frontend/.env")
BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or _env.get("REACT_APP_BACKEND_URL")
)
if not BASE_URL:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = BASE_URL.rstrip("/")
API = f"{BASE_URL}/api"

PAID = {"google_ads", "meta_ads", "microsoft_ads"}


def _login(email: str, password: str) -> str:
    r = requests.post(
        f"{API}/auth/login", json={"email": email, "password": password},
        timeout=45,
    )
    if r.status_code != 200:
        pytest.fail(f"login failed for {email}: {r.status_code} {r.text[:300]}")
    data = r.json()
    token = (
        data.get("access_token")
        or data.get("token")
        or (data.get("tokens") or {}).get("access_token")
    )
    if not token:
        pytest.fail(f"no token in login response for {email}: {str(data)[:300]}")
    return token


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@natmedsol.local', 'Admin!2345')}"}


@pytest.fixture(scope="module")
def staff_headers():
    return {"Authorization": f"Bearer {_login('frontdesk@natmedsol.local', 'FrontDesk!2345')}"}


# --- /paid/providers ---------------------------------------------------
class TestPaidProviders:
    def test_providers_admin(self, admin_headers):
        r = requests.get(f"{API}/marketing-os/paid/providers",
                         headers=admin_headers, timeout=45)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        assert PAID.issubset(set(d["providers"].keys()))
        assert PAID.issubset(set(d["registered"]))
        assert d["external_writes_enabled"] is False
        assert d["human_approval_required"] is True


# --- /paid/{provider}/readiness ---------------------------------------
class TestReadiness:
    @pytest.mark.parametrize("provider", ["meta_ads", "microsoft_ads"])
    def test_readiness_not_connected(self, admin_headers, provider):
        r = requests.get(f"{API}/marketing-os/paid/{provider}/readiness",
                         headers=admin_headers, timeout=45)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        assert d["provider"] == provider
        assert d["connected"] is False
        assert d["status"] == "not_connected", d
        assert d["read_only"] is True
        assert d["external_write"] is False

    def test_readiness_unknown_provider(self, admin_headers):
        r = requests.get(f"{API}/marketing-os/paid/tiktok_ads/readiness",
                         headers=admin_headers, timeout=45)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        assert d["status"] == "unknown_provider"
        assert d["connected"] is False
        assert d["read_only"] is True


# --- /paid/performance -------------------------------------------------
class TestPaidPerformance:
    def test_performance_shape_and_safety(self, admin_headers):
        r = requests.get(f"{API}/marketing-os/paid/performance",
                         headers=admin_headers, timeout=60)
        assert r.status_code == 200, r.text[:600]
        d = r.json()
        assert d["read_only"] is True
        assert d["external_writes_enabled"] is False
        assert d["automatic_budget_changes_enabled"] is False
        assert d["automatic_campaign_creation_enabled"] is False
        assert d["human_approval_required"] is True

        names = [p["provider"] for p in d["providers"]]
        assert set(names) == PAID, names
        assert len(names) == 3

        for p in d["providers"]:
            assert p["connected"] is False, p
            assert p["has_data"] is False, p
            assert p["metrics"] is None, p
            assert p["readiness"]["read_only"] is True
            assert p["readiness"]["external_write"] is False
            assert p["display_name"]
            assert "not zero" in p["note"].lower()

    def test_performance_requires_auth(self):
        r = requests.get(f"{API}/marketing-os/paid/performance", timeout=45)
        assert r.status_code in (401, 403), f"{r.status_code} {r.text[:300]}"

    def test_performance_forbidden_for_staff(self, staff_headers):
        r = requests.get(f"{API}/marketing-os/paid/performance",
                         headers=staff_headers, timeout=45)
        assert r.status_code in (401, 403), f"{r.status_code} {r.text[:300]}"


# --- /director/brief paid_media integration ---------------------------
class TestDirectorBrief:
    @pytest.fixture(scope="class")
    def brief(self, admin_headers):
        r = requests.get(f"{API}/marketing-os/director/brief",
                         headers=admin_headers, timeout=120)
        assert r.status_code == 200, r.text[:600]
        return r.json()

    def test_brief_has_paid_media_block(self, brief):
        pm = brief.get("paid_media")
        assert pm is not None, "brief missing paid_media block"
        names = [p["provider"] for p in pm["providers"]]
        assert set(names) == PAID, names
        for p in pm["providers"]:
            assert p["connected"] is False
            assert p["has_data"] is False
            assert p["metrics"] is None

    def test_no_paid_channel_recommendations(self, brief):
        offenders = [
            rec for rec in brief.get("recommendations", [])
            if rec.get("channel") in PAID
        ]
        assert not offenders, offenders

    def test_brief_safety_flags(self, brief):
        safety = brief.get("safety") or {}
        assert safety, "brief missing safety block"
        assert safety.get("human_approval_required") is True, safety
        for key, value in safety.items():
            if key == "human_approval_required":
                continue
            if isinstance(value, bool):
                assert value is False, f"{key} should be False: {safety}"
