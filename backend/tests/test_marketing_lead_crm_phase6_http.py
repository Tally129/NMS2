"""Phase 6 LIVE HTTP tests — Lead CRM + Appointment Setter workspace.

Covers:
  * POST /api/marketing-os/leads/sync (idempotent)
  * POST/GET/PATCH /api/marketing-os/leads (+ filters/views, PHI, duplicate)
  * PATCH .../status deterministic transitions (200 valid / 409 invalid)
  * PATCH .../owner (assignment history + timeline activity)
  * GET .../timeline
  * Tasks CRUD + filters
  * GET .../leads/metrics (null-vs-zero) and director brief lead_operations
  * Authorization (staff role, unauthenticated)
"""
from __future__ import annotations

import os
import uuid

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
LEADS = f"{API}/marketing-os/leads"

# Seeded dev TOTP secret (see /app/test_reports/iteration_27.json)
TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"

RUN = uuid.uuid4().hex[:8]
CREATED_SUBJECTS: list[str] = []


def _subject(name: str) -> str:
    s = f"TEST_p6_{RUN}_{name}"
    CREATED_SUBJECTS.append(s)
    return s


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
        detail = r.json().get("detail") or {}
        sessions = detail.get("active_sessions") or []
        if detail.get("continuation_ticket") and sessions:
            r = requests.post(
                f"{API}/auth/login/continue",
                json={
                    "continuation_ticket": detail["continuation_ticket"],
                    "revoke_session_id": sessions[0].get("id")
                    or sessions[0].get("session_id"),
                },
                timeout=60,
            )
    if r.status_code != 200:
        pytest.fail(f"login failed for {email}: {r.status_code} {r.text[:400]}")
    data = r.json()
    token = data.get("access_token") or data.get("token")
    if not token:
        pytest.fail(f"no token for {email}: {str(data)[:300]}")
    return token


@pytest.fixture(scope="session")
def admin_headers():
    tok = _login("admin@natmedsol.local", "Admin!2345")
    return {"Authorization": f"Bearer {tok}"}


def _sub_from_token(token: str) -> str:
    import base64
    import json as _json

    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return _json.loads(base64.urlsafe_b64decode(payload))["sub"]


@pytest.fixture(scope="session")
def admin_user_id():
    return _sub_from_token(_login("admin@natmedsol.local", "Admin!2345"))


@pytest.fixture(scope="session")
def practitioner_user_id():
    return _sub_from_token(
        _login("ravello@natmedsol.local", "Ravello!2345")
    )


@pytest.fixture(scope="session")
def staff_headers():
    tok = _login("frontdesk@natmedsol.local", "FrontDesk!2345")
    return {"Authorization": f"Bearer {tok}"}


def _get(path, headers, **params):
    return requests.get(path, headers=headers, params=params or None,
                        timeout=90)


def _mk_lead(headers, name, **extra):
    body = {
        "marketing_subject_id": _subject(name),
        "source": "google",
        "medium": "cpc",
        "campaign_name": "brand",
        "opportunity_score": 82,
        "service_interest": "wellness",
    }
    body.update(extra)
    r = requests.post(LEADS, headers=headers, json=body, timeout=60)
    assert r.status_code == 201, f"create lead failed: {r.status_code} {r.text[:400]}"
    return r.json()


# --- health / sync ---------------------------------------------------------
class TestSync:
    def test_sync_idempotent(self, admin_headers):
        r1 = requests.post(f"{LEADS}/sync", headers=admin_headers, timeout=180)
        assert r1.status_code == 200, r1.text[:600]
        d1 = r1.json()
        for key in ("created", "updated", "total_opportunities"):
            assert key in d1, d1
        r2 = requests.post(f"{LEADS}/sync", headers=admin_headers, timeout=180)
        assert r2.status_code == 200, r2.text[:600]
        d2 = r2.json()
        assert d2["created"] == 0, f"re-sync duplicated leads: {d2}"
        assert d2["total_opportunities"] == d1["total_opportunities"]


# --- create / validation ---------------------------------------------------
class TestCreateLead:
    def test_create_returns_high_priority_and_new_status(self, admin_headers):
        lead = _mk_lead(admin_headers, "create")
        assert lead["priority"] == "high", lead
        assert lead["lead_status"] == "new"
        assert lead["qualification_status"] == "unqualified"
        assert "_id" not in lead
        # persistence check
        r = _get(f"{LEADS}/{lead['id']}", admin_headers)
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        assert body["lead"]["marketing_subject_id"] == \
            lead["marketing_subject_id"]
        assert isinstance(body["tasks"], list)

    def test_duplicate_subject_returns_409(self, admin_headers):
        subject = f"TEST_p6_{RUN}_dup"
        CREATED_SUBJECTS.append(subject)
        payload = {"marketing_subject_id": subject, "source": "google"}
        r1 = requests.post(LEADS, headers=admin_headers, json=payload,
                           timeout=60)
        assert r1.status_code == 201, r1.text[:400]
        r2 = requests.post(LEADS, headers=admin_headers, json=payload,
                           timeout=60)
        assert r2.status_code == 409, f"{r2.status_code} {r2.text[:300]}"

    @pytest.mark.parametrize("phi", [
        {"email": "x@y.com"},
        {"phone": "555-123-4567"},
        {"patient_name": "John Doe"},
    ])
    def test_phi_payload_rejected_422(self, admin_headers, phi):
        key = list(phi)[0]
        subject = f"TEST_p6_{RUN}_phi_{key}"
        CREATED_SUBJECTS.append(subject)
        payload = {"marketing_subject_id": subject, **phi}
        r = requests.post(LEADS, headers=admin_headers, json=payload,
                          timeout=60)
        assert r.status_code == 422, f"{r.status_code} {r.text[:300]}"

    def test_blank_subject_rejected(self, admin_headers):
        r = requests.post(LEADS, headers=admin_headers,
                          json={"marketing_subject_id": "   "}, timeout=60)
        assert r.status_code == 422, f"{r.status_code} {r.text[:300]}"

    def test_priority_from_low_score(self, admin_headers):
        lead = _mk_lead(admin_headers, "lowscore", opportunity_score=10)
        assert lead["priority"] == "low", lead


# --- list / filters --------------------------------------------------------
class TestListLeads:
    def test_list_and_overdue_count(self, admin_headers):
        _mk_lead(admin_headers, "list")
        r = _get(LEADS, admin_headers)
        assert r.status_code == 200, r.text[:400]
        leads = r.json()["leads"]
        assert isinstance(leads, list) and leads
        assert "overdue_task_count" in leads[0], leads[0].keys()
        assert all("_id" not in lead for lead in leads)

    @pytest.mark.parametrize("params,check", [
        ({"status": "new"}, ("lead_status", "new")),
        ({"priority": "high"}, ("priority", "high")),
        ({"source": "google"}, ("source", "google")),
    ])
    def test_filters(self, admin_headers, params, check):
        r = _get(LEADS, admin_headers, **params)
        assert r.status_code == 200, r.text[:400]
        field, value = check
        for lead in r.json()["leads"]:
            assert lead[field] == value, lead

    @pytest.mark.parametrize("view", [
        "new_leads", "needs_attention", "follow_up_today",
        "appointment_requested", "booked", "no_show", "nurture",
        "won", "lost",
    ])
    def test_views(self, admin_headers, view):
        r = _get(LEADS, admin_headers, view=view)
        assert r.status_code == 200, f"{view}: {r.status_code} {r.text[:300]}"
        assert isinstance(r.json()["leads"], list)

    def test_bogus_lead_id_404(self, admin_headers):
        r = _get(f"{LEADS}/{uuid.uuid4().hex}", admin_headers)
        assert r.status_code == 404, f"{r.status_code} {r.text[:200]}"


# --- transitions -----------------------------------------------------------
class TestTransitions:
    def _status(self, headers, lead_id, target):
        return requests.patch(f"{LEADS}/{lead_id}/status", headers=headers,
                              json={"lead_status": target}, timeout=60)

    def test_valid_new_to_contacted_sets_timestamps(self, admin_headers):
        lead = _mk_lead(admin_headers, "trans_ok")
        r = self._status(admin_headers, lead["id"], "contacted")
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        assert body["lead_status"] == "contacted"
        assert body["first_contact_at"] is not None
        assert isinstance(body["first_response_seconds"], int)
        assert body["first_response_seconds"] >= 0

    def test_appointment_flow_sets_appointment_status(self, admin_headers):
        lead = _mk_lead(admin_headers, "trans_appt")
        lid = lead["id"]
        r = self._status(admin_headers, lid, "appointment_requested")
        assert r.status_code == 200, r.text[:400]
        assert r.json()["appointment_status"] == "requested"
        assert r.json()["appointment_requested_at"] is not None
        r = self._status(admin_headers, lid, "booked")
        assert r.status_code == 200, r.text[:400]
        assert r.json()["appointment_status"] == "booked"
        assert r.json()["booked_at"] is not None
        r = self._status(admin_headers, lid, "showed")
        assert r.status_code == 200, r.text[:400]
        assert r.json()["appointment_status"] == "showed"
        # showed -> booked is NOT allowed
        r = self._status(admin_headers, lid, "booked")
        assert r.status_code == 409, f"{r.status_code} {r.text[:300]}"
        assert r.json().get("detail")
        # showed -> won allowed, then terminal
        r = self._status(admin_headers, lid, "won")
        assert r.status_code == 200, r.text[:400]
        r = self._status(admin_headers, lid, "lost")
        assert r.status_code == 409, f"terminal not enforced: {r.text[:300]}"
        assert "terminal" in str(r.json().get("detail", "")).lower()

    def test_invalid_new_to_won_409(self, admin_headers):
        lead = _mk_lead(admin_headers, "trans_bad")
        r = self._status(admin_headers, lead["id"], "won")
        assert r.status_code == 409, f"{r.status_code} {r.text[:300]}"
        assert "not allowed" in str(r.json().get("detail", "")).lower()

    def test_unknown_stage_409(self, admin_headers):
        lead = _mk_lead(admin_headers, "trans_unknown")
        r = self._status(admin_headers, lead["id"], "banana")
        assert r.status_code == 409, f"{r.status_code} {r.text[:300]}"

    def test_same_stage_409(self, admin_headers):
        lead = _mk_lead(admin_headers, "trans_same")
        r = self._status(admin_headers, lead["id"], "new")
        assert r.status_code == 409, f"{r.status_code} {r.text[:300]}"

    def test_status_on_bogus_lead_404(self, admin_headers):
        r = self._status(admin_headers, uuid.uuid4().hex, "contacted")
        assert r.status_code == 404, f"{r.status_code} {r.text[:200]}"


# --- owner + timeline ------------------------------------------------------
class TestOwnerAndTimeline:
    def test_assign_reassign_unassign_and_timeline(
        self, admin_headers, admin_user_id, practitioner_user_id
    ):
        lead = _mk_lead(admin_headers, "owner")
        lid = lead["id"]
        owner = admin_user_id
        r = requests.patch(f"{LEADS}/{lid}/owner", headers=admin_headers,
                           json={"assigned_owner_id": owner,
                                 "note": "TEST assign"}, timeout=60)
        assert r.status_code == 200, r.text[:400]
        assert r.json()["assigned_owner_id"] == owner
        # reassign
        owner2 = practitioner_user_id
        r = requests.patch(f"{LEADS}/{lid}/owner", headers=admin_headers,
                           json={"assigned_owner_id": owner2}, timeout=60)
        assert r.status_code == 200, r.text[:400]
        assert r.json()["assigned_owner_id"] == owner2
        # unassign
        r = requests.patch(f"{LEADS}/{lid}/owner", headers=admin_headers,
                           json={"assigned_owner_id": None}, timeout=60)
        assert r.status_code == 200, r.text[:400]
        assert r.json()["assigned_owner_id"] is None
        # timeline
        t = _get(f"{LEADS}/{lid}/timeline", admin_headers)
        assert t.status_code == 200, t.text[:400]
        types = [a["activity_type"] for a in t.json()["timeline"]]
        assert types.count("owner_assigned") == 3, types
        assert "lead_created" in types
        blob = str(t.json()).lower()
        for token in ("@", "ssn", "diagnos"):
            assert token not in blob, f"possible PHI in timeline: {token}"

    def test_owner_filter(self, admin_headers, practitioner_user_id):
        lead = _mk_lead(admin_headers, "ownerfilter")
        owner = practitioner_user_id
        r0 = requests.patch(f"{LEADS}/{lead['id']}/owner",
                            headers=admin_headers,
                            json={"assigned_owner_id": owner}, timeout=60)
        assert r0.status_code == 200, r0.text[:300]
        r = _get(LEADS, admin_headers, owner_id=owner)
        assert r.status_code == 200, r.text[:400]
        rows = r.json()["leads"]
        assert any(x["id"] == lead["id"] for x in rows)
        assert all(x["assigned_owner_id"] == owner for x in rows)

    def test_unknown_owner_id_should_not_500(self, admin_headers):
        """A non-existent owner id must fail gracefully (400/404/422)."""
        lead = _mk_lead(admin_headers, "ownerbad")
        r = requests.patch(f"{LEADS}/{lead['id']}/owner",
                           headers=admin_headers,
                           json={"assigned_owner_id": uuid.uuid4().hex},
                           timeout=60)
        assert r.status_code in (400, 404, 422), (
            f"expected validation error, got {r.status_code} {r.text[:200]}"
        )

    def test_timeline_bogus_lead_404(self, admin_headers):
        r = _get(f"{LEADS}/{uuid.uuid4().hex}/timeline", admin_headers)
        assert r.status_code == 404, f"{r.status_code} {r.text[:200]}"


# --- qualification patch ---------------------------------------------------
class TestQualificationPatch:
    def test_patch_qualification_fields(self, admin_headers):
        lead = _mk_lead(admin_headers, "qual")
        r = requests.patch(f"{LEADS}/{lead['id']}", headers=admin_headers,
                           json={"qualification_status": "qualified",
                                 "priority": "high",
                                 "urgency": "high",
                                 "service_interest": "iv_therapy",
                                 "next_action_at":
                                     "2026-07-10T12:00:00+00:00"},
                           timeout=60)
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        assert body["qualification_status"] == "qualified"
        assert body["priority"] == "high"
        assert body["service_interest"] == "iv_therapy"
        assert body["next_action_at"] is not None
        # persistence + activity
        g = _get(f"{LEADS}/{lead['id']}", admin_headers).json()["lead"]
        assert g["qualification_status"] == "qualified"
        types = [a["activity_type"] for a in
                 _get(f"{LEADS}/{lead['id']}/timeline",
                      admin_headers).json()["timeline"]]
        assert "qualification_updated" in types, types

    @pytest.mark.parametrize("body", [
        {"qualification_status": "bogus"},
        {"priority": "urgent"},
    ])
    def test_invalid_values_400(self, admin_headers, body):
        lead = _mk_lead(admin_headers, f"qualbad_{list(body)[0]}")
        r = requests.patch(f"{LEADS}/{lead['id']}", headers=admin_headers,
                           json=body, timeout=60)
        assert r.status_code == 400, f"{r.status_code} {r.text[:300]}"

    def test_empty_body_400(self, admin_headers):
        lead = _mk_lead(admin_headers, "qualempty")
        r = requests.patch(f"{LEADS}/{lead['id']}", headers=admin_headers,
                           json={}, timeout=60)
        assert r.status_code == 400, f"{r.status_code} {r.text[:300]}"

    def test_phi_patch_422(self, admin_headers):
        lead = _mk_lead(admin_headers, "qualphi")
        r = requests.patch(f"{LEADS}/{lead['id']}", headers=admin_headers,
                           json={"urgency": "high", "email": "a@b.com"},
                           timeout=60)
        assert r.status_code == 422, f"{r.status_code} {r.text[:300]}"


# --- tasks -----------------------------------------------------------------
class TestTasks:
    def test_task_lifecycle(self, admin_headers):
        lead = _mk_lead(admin_headers, "task")
        lid = lead["id"]
        r = requests.post(f"{LEADS}/tasks", headers=admin_headers,
                          json={"lead_id": lid, "task_type": "call_lead",
                                "due_at": "2026-01-01T00:00:00+00:00",
                                "notes": "TEST task"}, timeout=60)
        assert r.status_code == 201, r.text[:400]
        task = r.json()
        assert task["status"] == "open"
        assert task["task_type"] == "call_lead"
        tid = task["id"]

        # overdue filter (due_at in the past)
        r = _get(f"{LEADS}/tasks", admin_headers, overdue="true", lead_id=lid)
        assert r.status_code == 200, r.text[:400]
        assert any(t["id"] == tid for t in r.json()["tasks"])

        # overdue_task_count on the lead row
        rows = _get(LEADS, admin_headers).json()["leads"]
        row = next(x for x in rows if x["id"] == lid)
        assert row["overdue_task_count"] >= 1, row

        # follow_up_today view should include it (open task due <= today)
        view = _get(LEADS, admin_headers, view="follow_up_today").json()
        assert any(x["id"] == lid for x in view["leads"])

        # filters
        for params in ({"status": "open"}, {"lead_id": lid}):
            rr = _get(f"{LEADS}/tasks", admin_headers, **params)
            assert rr.status_code == 200, rr.text[:300]

        # complete
        r = requests.patch(f"{LEADS}/tasks/{tid}", headers=admin_headers,
                           json={"status": "completed"}, timeout=60)
        assert r.status_code == 200, r.text[:400]
        assert r.json()["status"] == "completed"
        assert r.json()["completed_at"] is not None

        types = [a["activity_type"] for a in
                 _get(f"{LEADS}/{lid}/timeline",
                      admin_headers).json()["timeline"]]
        assert "task_created" in types and "task_completed" in types, types

        # no longer overdue
        rows = _get(LEADS, admin_headers).json()["leads"]
        row = next(x for x in rows if x["id"] == lid)
        assert row["overdue_task_count"] == 0, row

    def test_invalid_task_type_400(self, admin_headers):
        lead = _mk_lead(admin_headers, "taskbad")
        r = requests.post(f"{LEADS}/tasks", headers=admin_headers,
                          json={"lead_id": lead["id"],
                                "task_type": "hug_lead"}, timeout=60)
        assert r.status_code == 400, f"{r.status_code} {r.text[:300]}"

    def test_unknown_lead_404(self, admin_headers):
        r = requests.post(f"{LEADS}/tasks", headers=admin_headers,
                          json={"lead_id": uuid.uuid4().hex,
                                "task_type": "call_lead"}, timeout=60)
        assert r.status_code == 404, f"{r.status_code} {r.text[:300]}"

    def test_invalid_task_status_400(self, admin_headers):
        lead = _mk_lead(admin_headers, "taskstatus")
        t = requests.post(f"{LEADS}/tasks", headers=admin_headers,
                          json={"lead_id": lead["id"],
                                "task_type": "call_lead"},
                          timeout=60).json()
        r = requests.patch(f"{LEADS}/tasks/{t['id']}", headers=admin_headers,
                           json={"status": "done"}, timeout=60)
        assert r.status_code == 400, f"{r.status_code} {r.text[:300]}"

    def test_patch_unknown_task_404(self, admin_headers):
        r = requests.patch(f"{LEADS}/tasks/{uuid.uuid4().hex}",
                           headers=admin_headers,
                           json={"status": "completed"}, timeout=60)
        assert r.status_code == 404, f"{r.status_code} {r.text[:300]}"


# --- metrics ---------------------------------------------------------------
class TestMetrics:
    def test_metrics_shape_and_safety(self, admin_headers):
        _mk_lead(admin_headers, "metrics")
        r = _get(f"{LEADS}/metrics", admin_headers)
        assert r.status_code == 200, r.text[:400]
        m = r.json()
        for key in ("total_leads", "total_new_leads", "uncontacted_leads",
                    "overdue_leads", "contact_rate", "qualification_rate",
                    "booking_rate", "show_rate", "won_rate", "leads_by_owner",
                    "bookings_by_owner", "speed_to_lead", "safety"):
            assert key in m, f"missing {key}: {list(m)}"
        s = m["safety"]
        assert s == {"external_writes": False, "automatic_outreach": False,
                     "human_approval_required": True, "phi_used": False}, s
        stl = m["speed_to_lead"]
        for key in ("measured_leads", "average_speed_to_lead_seconds",
                    "median_speed_to_lead_seconds",
                    "pct_contacted_within_5_min",
                    "pct_contacted_within_15_min",
                    "pct_contacted_within_1_hour"):
            assert key in stl, stl
        assert m["total_leads"] > 0
        # rates present (non-null) when leads exist
        assert m["contact_rate"] is not None
        # show_rate must be null when no bookings, never fabricated 0
        if m["booking_rate"] == 0:
            assert m["show_rate"] is None, m


class TestMetricsEmptyState:
    """Null-vs-zero contract when the lead table is empty (state dependent)."""

    def test_rates_null_when_no_leads(self, admin_headers):
        m = _get(f"{LEADS}/metrics", admin_headers).json()
        if m["total_leads"] != 0:
            pytest.skip("leads exist; empty-state contract not exercisable")
        for key in ("contact_rate", "qualification_rate", "booking_rate",
                    "show_rate", "won_rate"):
            assert m[key] is None, f"{key} should be null, got {m[key]}"
        assert m["leads_by_owner"] == []
        assert m["bookings_by_owner"] == []
        stl = m["speed_to_lead"]
        assert stl["measured_leads"] == 0
        for key in ("average_speed_to_lead_seconds",
                    "median_speed_to_lead_seconds",
                    "pct_contacted_within_5_min",
                    "pct_contacted_within_15_min",
                    "pct_contacted_within_1_hour"):
            assert stl[key] is None, f"{key} should be null"


# --- director brief --------------------------------------------------------
class TestDirectorBrief:
    def test_brief_lead_operations_and_safety(self, admin_headers):
        r = _get(f"{API}/marketing-os/director/brief", admin_headers)
        assert r.status_code == 200, r.text[:600]
        brief = r.json()
        assert "lead_operations" in brief, list(brief)
        lo = brief["lead_operations"]
        for key in ("total_leads", "uncontacted_leads", "overdue_leads",
                    "speed_to_lead"):
            assert key in lo, list(lo)
        safety = brief.get("safety") or {}
        assert safety.get("human_approval_required") is True, safety
        for key, value in safety.items():
            if key != "human_approval_required" and isinstance(value, bool):
                assert value is False, f"{key} should be False: {safety}"
        for rec in brief.get("recommendations", []):
            assert rec.get("advisory_only") is True, rec
            assert rec.get("requires_human_approval") is True, rec
            assert rec.get("external_write") is False, rec


# --- authorization ---------------------------------------------------------
class TestAuthorization:
    def test_unauthenticated_list_rejected(self):
        r = requests.get(LEADS, timeout=60)
        assert r.status_code in (401, 403), f"{r.status_code} {r.text[:200]}"

    def test_unauthenticated_status_rejected(self):
        r = requests.patch(f"{LEADS}/{uuid.uuid4().hex}/status",
                           json={"lead_status": "contacted"}, timeout=60)
        assert r.status_code in (401, 403), f"{r.status_code} {r.text[:200]}"

    def test_staff_cannot_mutate_status(self, staff_headers, admin_headers):
        lead = _mk_lead(admin_headers, "rbac")
        r = requests.patch(f"{LEADS}/{lead['id']}/status",
                           headers=staff_headers,
                           json={"lead_status": "contacted"}, timeout=60)
        assert r.status_code in (401, 403), f"{r.status_code} {r.text[:300]}"

    def test_staff_cannot_create_lead(self, staff_headers):
        r = requests.post(LEADS, headers=staff_headers,
                          json={"marketing_subject_id":
                                f"TEST_p6_{RUN}_rbac2"}, timeout=60)
        assert r.status_code in (401, 403), f"{r.status_code} {r.text[:300]}"

    def test_staff_list_rejected(self, staff_headers):
        r = _get(LEADS, staff_headers)
        assert r.status_code in (401, 403), f"{r.status_code} {r.text[:300]}"
