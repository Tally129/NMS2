"""Phase 5 LIVE HTTP tests — Lead → Appointment → Revenue attribution.

Covers:
  * GET /api/marketing-os/attribution/overview (+ model switching)
  * GET /api/marketing-os/attribution/funnel   (honest null stages)
  * GET /api/marketing-os/attribution/channels
  * GET /api/marketing-os/attribution/campaigns
  * GET /api/marketing-os/attribution/revenue
  * GET /api/marketing-os/attribution/journeys (PHI-free)
  * GET /api/marketing-os/director/brief (journey_outcomes block)
  * Authorization (staff role, unauthenticated)
"""
from __future__ import annotations

import json
import os
import re

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

ATTR = f"{API}/marketing-os/attribution"
# Seeded dev TOTP secret (see /app/test_reports/iteration_27.json)
TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"

FUNNEL_STAGES = (
    "lead",
    "appointment_intent",
    "appointment_request",
    "appointment_booked",
    "appointment_completed",
    "no_show",
)


def _totp() -> str:
    import pyotp

    return pyotp.TOTP(TOTP_SECRET).now()


def _post_login(email: str, password: str, mfa: str | None = None):
    body = {"email": email, "password": password}
    if mfa:
        body["mfa_token"] = mfa
    return requests.post(f"{API}/auth/login", json=body, timeout=60)


def _login(email: str, password: str) -> str:
    r = _post_login(email, password)
    if r.status_code == 200 and (r.json().get("mfa_required") is True):
        r = _post_login(email, password, _totp())
    if r.status_code == 409:
        # Active session cap — revoke one session and continue.
        detail = r.json().get("detail") or {}
        sessions = detail.get("active_sessions") or []
        if detail.get("continuation_ticket") and sessions:
            cont = requests.post(
                f"{API}/auth/login/continue",
                json={
                    "continuation_ticket": detail["continuation_ticket"],
                    "revoke_session_id": sessions[0].get("id")
                    or sessions[0].get("session_id"),
                },
                timeout=60,
            )
            r = cont
    if r.status_code != 200:
        pytest.fail(f"login failed for {email}: {r.status_code} {r.text[:400]}")
    data = r.json()
    token = data.get("access_token") or data.get("token")
    if not token:
        pytest.fail(f"no token for {email}: {str(data)[:300]}")
    return token


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@natmedsol.local', 'Admin!2345')}"}


@pytest.fixture(scope="module")
def staff_headers():
    return {
        "Authorization": (
            f"Bearer {_login('frontdesk@natmedsol.local', 'FrontDesk!2345')}"
        )
    }


def _get(path: str, headers: dict, **params):
    return requests.get(path, headers=headers, params=params or None, timeout=90)


# --- /attribution/overview -------------------------------------------------
class TestOverview:
    @pytest.fixture(scope="class")
    def overview(self, admin_headers):
        r = _get(f"{ATTR}/overview", admin_headers)
        assert r.status_code == 200, r.text[:600]
        return r.json()

    def test_overview_keys(self, overview):
        for key in (
            "attribution_model", "funnel", "channels", "revenue",
            "booked_attribution", "completed_attribution", "safety",
        ):
            assert key in overview, f"missing {key}: {list(overview)}"

    def test_overview_safety_block(self, overview):
        s = overview["safety"]
        assert s["external_writes"] is False
        assert s["automatic_budget_changes"] is False
        assert s["automatic_campaign_creation"] is False
        assert s["automatic_publishing"] is False
        assert s["human_approval_required"] is True
        assert s["phi_used"] is False
        assert s["attribution_type"] == "deterministic"

    @pytest.mark.parametrize(
        "model,expected",
        [("first_touch", "first_touch"),
         ("last_touch", "last_touch"),
         ("bogus", "last_touch"),
         ("", "last_touch")],
    )
    def test_model_switching_and_fallback(self, admin_headers, model, expected):
        r = _get(f"{ATTR}/overview", admin_headers, model=model)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        assert d["attribution_model"] == expected
        assert d["revenue"]["attribution_model"] == expected
        assert d["booked_attribution"]["attribution_model"] == expected

    def test_overview_default_model(self, overview):
        assert overview["attribution_model"] == "last_touch"

    def test_practitioner_allowed(self):
        token = _login("ravello@natmedsol.local", "Ravello!2345")
        r = _get(f"{ATTR}/overview", {"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text[:400]


# --- /attribution/funnel ---------------------------------------------------
class TestFunnel:
    @pytest.fixture(scope="class")
    def funnel(self, admin_headers):
        r = _get(f"{ATTR}/funnel", admin_headers)
        assert r.status_code == 200, r.text[:600]
        return r.json()

    def test_stage_keys_present(self, funnel):
        stages = funnel["stages"]
        assert set(stages.keys()) == set(FUNNEL_STAGES), stages

    def test_untracked_stages_are_null_not_zero(self, funnel):
        available = set(funnel["available_stages"])
        for stage, value in funnel["stages"].items():
            if stage in available:
                assert isinstance(value, int) and value >= 0, (stage, value)
            else:
                assert value is None, (
                    f"stage {stage} not tracked but reported {value} "
                    "(must be null, never fabricated 0)"
                )

    def test_rates_null_when_denominator_missing(self, funnel):
        stages, rates = funnel["stages"], funnel["rates"]
        pairs = {
            "lead_to_booking_rate": ("appointment_booked", "lead"),
            "booking_to_show_rate": (
                "appointment_completed", "appointment_booked"),
            "lead_to_show_rate": ("appointment_completed", "lead"),
            "request_to_booking_rate": (
                "appointment_booked", "appointment_request"),
            "no_show_rate": ("no_show", "appointment_booked"),
        }
        assert set(rates.keys()) == set(pairs.keys()), rates
        for rate_key, (num, den) in pairs.items():
            if stages[num] is None or not stages[den]:
                assert rates[rate_key] is None, (
                    f"{rate_key} must be null when {num}/{den} unavailable "
                    f"or denominator 0; got {rates[rate_key]}"
                )
            else:
                assert rates[rate_key] == pytest.approx(
                    stages[num] / stages[den], rel=1e-4)


# --- /attribution/channels -------------------------------------------------
class TestChannels:
    @pytest.fixture(scope="class")
    def channels(self, admin_headers):
        r = _get(f"{ATTR}/channels", admin_headers, model="last_touch")
        assert r.status_code == 200, r.text[:600]
        return r.json()

    def test_shape(self, channels):
        assert channels["attribution_model"] == "last_touch"
        assert "revenue_available" in channels
        assert isinstance(channels["channels"], list)

    def test_row_fields_and_null_revenue(self, channels):
        revenue_available = channels["revenue_available"]
        for row in channels["channels"]:
            for key in (
                "channel", "spend", "booked_appointments",
                "completed_appointments", "cost_per_booked_appointment",
                "cost_per_completed_appointment", "attributed_revenue", "roas",
            ):
                assert key in row, f"missing {key} in {row}"
            if not revenue_available:
                assert row["attributed_revenue"] is None, row
                assert row["roas"] is None, row


# --- /attribution/campaigns ------------------------------------------------
class TestCampaigns:
    def test_campaigns_first_touch(self, admin_headers):
        r = _get(f"{ATTR}/campaigns", admin_headers, model="first_touch")
        assert r.status_code == 200, r.text[:600]
        d = r.json()
        assert d["attribution_model"] == "first_touch"
        for key in ("booked", "completed"):
            block = d[key]
            assert block["attribution_model"] == "first_touch"
            assert block["dimension"] == "campaign"
            assert isinstance(block["credited"], list)
        assert "revenue" in d
        assert d["revenue"] is None or isinstance(d["revenue"], list)
        assert d["booked"]["outcome"] == "appointment_booked"
        assert d["completed"]["outcome"] == "appointment_completed"


# --- /attribution/revenue --------------------------------------------------
class TestRevenue:
    @pytest.fixture(scope="class")
    def revenue(self, admin_headers):
        r = _get(f"{ATTR}/revenue", admin_headers)
        assert r.status_code == 200, r.text[:600]
        return r.json()

    def test_revenue_honest_state(self, revenue):
        assert revenue["attribution_source"] == "first_party_purchase_events"
        if revenue["revenue_available"] is False:
            assert revenue["total_attributed_revenue"] is None
            assert revenue["purchase_count"] is None
            assert revenue["by_channel"] is None
            assert revenue["by_source"] is None
            assert revenue["by_campaign"] is None
        else:
            assert isinstance(revenue["total_attributed_revenue"], (int, float))
            assert revenue["purchase_count"] >= 1
            assert isinstance(revenue["by_channel"], list)


# --- /attribution/journeys -------------------------------------------------
_PHI_PATTERNS = (
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),                 # email
    re.compile(r"\b(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b"),  # phone
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),                   # ssn
)
_PHI_KEYS = (
    "first_name", "last_name", "full_name", "name", "email", "phone",
    "dob", "date_of_birth", "patient", "address", "mrn", "ssn",
)


class TestJourneys:
    @pytest.fixture(scope="class")
    def journeys(self, admin_headers):
        r = _get(f"{ATTR}/journeys", admin_headers, limit=50)
        assert r.status_code == 200, r.text[:600]
        return r.json()

    def test_shape(self, journeys):
        assert journeys["phi_used"] is False
        assert isinstance(journeys["count"], int)
        assert isinstance(journeys["journeys"], list)
        assert len(journeys["journeys"]) <= 50
        for j in journeys["journeys"]:
            for key in ("marketing_subject_id", "first_touch", "last_touch",
                        "stages_reached"):
                assert key in j, f"missing {key} in {j}"
            assert isinstance(j["stages_reached"], list)

    def test_no_phi_keys_or_values(self, journeys):
        raw = json.dumps(journeys["journeys"])
        offenders = [k for k in _PHI_KEYS if f'"{k}"' in raw]
        assert not offenders, f"PHI-looking keys in journeys: {offenders}"
        for pattern in _PHI_PATTERNS:
            match = pattern.search(raw)
            assert not match, f"PHI-looking value in journeys: {match.group(0)}"

    def test_limit_validation(self, admin_headers):
        assert _get(f"{ATTR}/journeys", admin_headers,
                    limit=0).status_code == 422
        assert _get(f"{ATTR}/journeys", admin_headers,
                    limit=501).status_code == 422


# --- /director/brief journey_outcomes -------------------------------------
class TestDirectorBrief:
    @pytest.fixture(scope="class")
    def brief(self, admin_headers):
        r = requests.get(f"{API}/marketing-os/director/brief",
                         headers=admin_headers, timeout=180)
        assert r.status_code == 200, r.text[:600]
        return r.json()

    def test_journey_outcomes_block(self, brief):
        jo = brief.get("journey_outcomes")
        assert jo is not None, f"brief missing journey_outcomes: {list(brief)}"
        for key in ("funnel", "channel_economics", "revenue"):
            assert key in jo, f"journey_outcomes missing {key}: {list(jo)}"
        assert set(jo["funnel"]["stages"].keys()) == set(FUNNEL_STAGES)

    def test_brief_safety_flags(self, brief):
        safety = brief.get("safety") or {}
        assert safety, "brief missing safety block"
        assert safety.get("human_approval_required") is True, safety
        for key, value in safety.items():
            if key == "human_approval_required":
                continue
            if isinstance(value, bool):
                assert value is False, f"{key} should be False: {safety}"

    def test_recommendations_advisory_only(self, brief):
        recs = brief.get("recommendations") or []
        for rec in recs:
            assert rec.get("advisory_only") is True, rec
            assert rec.get("requires_human_approval") is True, rec
            assert rec.get("external_write") is False, rec


# --- Authorization ---------------------------------------------------------
ENDPOINTS = ["overview", "funnel", "channels", "campaigns", "revenue",
             "journeys"]


class TestAuthorization:
    @pytest.mark.parametrize("ep", ENDPOINTS)
    def test_unauthenticated_rejected(self, ep):
        r = requests.get(f"{ATTR}/{ep}", timeout=60)
        assert r.status_code in (401, 403), f"{ep}: {r.status_code} {r.text[:200]}"

    @pytest.mark.parametrize("ep", ENDPOINTS)
    def test_staff_rejected(self, staff_headers, ep):
        r = _get(f"{ATTR}/{ep}", staff_headers)
        assert r.status_code in (401, 403), f"{ep}: {r.status_code} {r.text[:200]}"
