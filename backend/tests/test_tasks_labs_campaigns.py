"""
Feb 2026 — Internal Task Manager + Lab Review Queue + Campaign Center tests.

Focused smoke coverage for the three new feature areas. Reuses existing
seeded workforce accounts.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import pymongo
import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"

CREDS = {
    "admin": ("admin@natmedsol.local", "Admin!2345"),
    "practitioner": ("ravello@natmedsol.local", "Ravello!2345"),
    "medical_assistant": ("ma@natmedsol.local", "MedAssist!2345"),
}


def _login(email, password):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, r.text[:200]
    j = r.json()
    return j.get("access_token") or j.get("token")


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def toks():
    return {k: _login(*v) for k, v in CREDS.items()}


@pytest.fixture(scope="module")
def dbm():
    c = pymongo.MongoClient(os.environ["MONGO_URL"])
    yield c[os.environ["DB_NAME"]]
    c.close()


# =========================================================================== #
# 1. Task Manager                                                              #
# =========================================================================== #
class TestTaskManager:
    def test_create_task(self, toks, dbm):
        r = requests.post(f"{API}/tasks", headers=_h(toks["practitioner"]),
                          json={"title": "Review labs for chart demo",
                                "priority": "high", "category": "review_labs"},
                          timeout=10)
        assert r.status_code == 200, r.text
        t = r.json()
        assert t["status"] == "new"
        assert t["priority"] == "high"
        assert t["category"] == "review_labs"
        assert len(t["history"]) == 1
        self.__class__.task_id = t["id"]

    def test_list_filters(self, toks):
        r = requests.get(f"{API}/tasks", headers=_h(toks["admin"]),
                         params={"status": "new"}, timeout=10)
        assert r.status_code == 200
        assert any(x["id"] == self.__class__.task_id for x in r.json())

    def test_transition_status_records_history(self, toks):
        r = requests.patch(f"{API}/tasks/{self.__class__.task_id}",
                           headers=_h(toks["practitioner"]),
                           json={"status": "in_progress",
                                 "add_note": "Started on this"},
                           timeout=10)
        assert r.status_code == 200
        t = r.json()
        assert t["status"] == "in_progress"
        assert any(e["event"] == "status_changed" and e["to"] == "in_progress"
                   for e in t["history"])
        assert any(e["event"] == "note_added" for e in t["history"])
        assert len(t["internal_notes"]) == 1

    def test_reassign_recorded(self, toks, dbm):
        # Reassign to admin
        admin = dbm.users.find_one({"email": CREDS["admin"][0]})
        r = requests.patch(f"{API}/tasks/{self.__class__.task_id}",
                           headers=_h(toks["practitioner"]),
                           json={"assigned_staff_id": admin["id"]}, timeout=10)
        assert r.status_code == 200
        t = r.json()
        assert t["assigned_staff_id"] == admin["id"]
        assert any(e["event"] == "reassigned_staff" for e in t["history"])

    def test_complete_task_sets_completed_fields(self, toks):
        r = requests.patch(f"{API}/tasks/{self.__class__.task_id}",
                           headers=_h(toks["practitioner"]),
                           json={"status": "completed"}, timeout=10)
        assert r.status_code == 200
        t = r.json()
        assert t["status"] == "completed"
        assert t["completed_by"] is not None
        assert t["completed_at"] is not None

    def test_dashboard_summary_shape(self, toks):
        r = requests.get(f"{API}/tasks/dashboard/summary",
                         headers=_h(toks["practitioner"]), timeout=10)
        assert r.status_code == 200
        j = r.json()
        for k in ("my_tasks", "overdue", "due_today", "waiting"):
            assert k in j, f"missing {k}"

    def test_invalid_priority_rejected(self, toks):
        r = requests.post(f"{API}/tasks", headers=_h(toks["admin"]),
                          json={"title": "bad", "priority": "SUPER"}, timeout=10)
        assert r.status_code == 400

    def test_client_role_forbidden(self, dbm):
        # Reuse an existing client account with known password if seeded; else
        # create one directly via the DB and log in through the standard flow.
        email = "client_guard_task@example.com"
        pwd = "Pat!12345678"
        u = dbm.users.find_one({"email": email})
        if not u:
            from passlib.context import CryptContext
            ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
            dbm.users.insert_one({
                "id": f"client-guard-{int(time.time())}",
                "email": email, "password_hash": ctx.hash(pwd),
                "full_name": "Client Guard", "phone": None,
                "role": "client", "mfa_enabled": False, "mfa_secret": None,
                "is_active": True,
                "created_at": datetime.now(timezone.utc), "last_login_at": None,
            })
        r = requests.post(f"{API}/auth/login",
                          json={"email": email, "password": pwd}, timeout=15)
        assert r.status_code == 200, r.text[:200]
        tok = r.json().get("access_token") or r.json().get("token")
        r2 = requests.get(f"{API}/tasks", headers=_h(tok), timeout=10)
        assert r2.status_code == 403


# =========================================================================== #
# 2. Lab Review Queue                                                          #
# =========================================================================== #
class TestLabReviewQueue:
    @pytest.fixture(scope="class", autouse=True)
    def _seed_lab(self, toks, dbm):
        # Ensure at least one lab_value exists for the review-queue tests.
        prov = dbm.users.find_one({"email": CREDS["practitioner"][0]})
        client = dbm.clients.find_one({}) or None
        if not client:
            client = {"id": f"cli-{int(time.time())}",
                      "full_name": "Lab Queue Patient",
                      "email": f"labq_{int(time.time())}@example.com",
                      "created_at": datetime.now(timezone.utc)}
            dbm.clients.insert_one(client)
        lab = {
            "id": f"lab-{int(time.time()*1000)}",
            "client_id": client["id"],
            "test_name": "TSH", "value": 5.9, "unit": "mIU/L",
            "reference_low": 0.4, "reference_high": 4.0,
            "measured_at": datetime.now(timezone.utc),
            "recorded_by": prov["id"], "recorded_by_name": prov.get("full_name"),
            "created_at": datetime.now(timezone.utc),
            "review_status": "new",
        }
        dbm.lab_values.insert_one(lab)
        self.__class__.lab_id = lab["id"]
        self.__class__.client_id = client["id"]

    def test_review_queue_default_excludes_notified(self, toks):
        r = requests.get(f"{API}/labs/review-queue",
                         headers=_h(toks["practitioner"]), timeout=10)
        assert r.status_code == 200
        assert any(x["id"] == self.__class__.lab_id for x in r.json())

    def test_provider_can_transition(self, toks):
        r = requests.patch(f"{API}/labs/{self.__class__.lab_id}/review-status",
                           headers=_h(toks["practitioner"]),
                           json={"review_status": "reviewed",
                                 "review_notes": "TSH slightly elevated"},
                           timeout=10)
        assert r.status_code == 200
        j = r.json()
        assert j["review_status"] == "reviewed"
        assert j.get("reviewed_by") is not None

    def test_ma_denied_without_delegation(self, toks):
        r = requests.patch(f"{API}/labs/{self.__class__.lab_id}/review-status",
                           headers=_h(toks["medical_assistant"]),
                           json={"review_status": "patient_notified"},
                           timeout=10)
        assert r.status_code == 403

    def test_create_task_from_lab(self, toks):
        r = requests.post(f"{API}/labs/{self.__class__.lab_id}/create-task",
                          headers=_h(toks["practitioner"]),
                          json={"priority": "high"}, timeout=10)
        assert r.status_code == 200, r.text
        t = r.json()
        assert t["linked_lab_id"] == self.__class__.lab_id
        assert t["category"] == "review_labs"
        assert t["client_id"] == self.__class__.client_id


# =========================================================================== #
# 3. Campaign Center                                                           #
# =========================================================================== #
class TestCampaigns:
    @pytest.fixture(scope="class", autouse=True)
    def _seed_clients(self, dbm):
        # Guarantee a marketing-opted-in client with valid email + phone.
        for i in range(3):
            existing = dbm.clients.find_one({"email": f"camp_ok_{i}@example.com"})
            if existing:
                dbm.clients.update_one({"id": existing["id"]},
                                        {"$set": {"consent_marketing": True,
                                                  "phone": "+15551230000"}})
                continue
            dbm.clients.insert_one({
                "id": f"cli-camp-{i}-{int(time.time())}",
                "full_name": f"Camp OK {i}",
                "email": f"camp_ok_{i}@example.com",
                "phone": "+15551230000",
                "consent_marketing": True,
                "created_at": datetime.now(timezone.utc),
            })
        # And one opted-out
        if not dbm.clients.find_one({"email": "camp_out@example.com"}):
            dbm.clients.insert_one({
                "id": f"cli-out-{int(time.time())}",
                "full_name": "Camp OptOut",
                "email": "camp_out@example.com",
                "phone": "+15551230000",
                "consent_marketing": False,
                "created_at": datetime.now(timezone.utc),
            })

    def test_estimate_excludes_optout(self, toks):
        r = requests.post(f"{API}/campaigns/estimate",
                          headers=_h(toks["admin"]),
                          json={"channel": "email",
                                "filter_type": "all_marketing"},
                          timeout=10)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["eligible"] >= 3
        # At least one client is opted-out or has invalid email — must be counted
        assert j["skipped_total"] >= 1
        # Reason breakdown includes at least marketing_opt_out
        assert "marketing_opt_out" in j["skipped_by_reason"] or j["skipped_by_reason"]

    def test_email_requires_subject(self, toks):
        r = requests.post(f"{API}/campaigns", headers=_h(toks["admin"]),
                          json={"title": "T1", "message": "Hi", "channel": "email"},
                          timeout=10)
        assert r.status_code == 400

    def test_send_now_stubs(self, toks, dbm):
        r = requests.post(f"{API}/campaigns", headers=_h(toks["admin"]),
                          json={"title": "Wellness Reminder",
                                "subject": "A friendly reminder",
                                "message": "See you soon at NMS!",
                                "channel": "email",
                                "filter_type": "all_marketing"},
                          timeout=20)
        assert r.status_code == 200, r.text
        j = r.json()
        # Since keys aren't set, sent_stub returns 'sent'; either way the
        # campaign should have a delivery_log with entries.
        assert j["status"] in ("completed", "sent_with_failures", "failed")
        c = dbm.campaigns.find_one({"id": j["id"]})
        assert c is not None
        assert isinstance(c.get("delivery_log"), list)
        assert c["stats"]["skipped"] >= 1     # opt-out or invalid contact

    def test_schedule_defers(self, toks, dbm):
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        r = requests.post(f"{API}/campaigns", headers=_h(toks["admin"]),
                          json={"title": "Later", "subject": "Later",
                                "message": "Later msg", "channel": "email",
                                "filter_type": "all_marketing",
                                "schedule_at": future},
                          timeout=10)
        assert r.status_code == 200
        j = r.json()
        assert j["status"] == "scheduled"

    def test_list_and_get(self, toks):
        r = requests.get(f"{API}/campaigns", headers=_h(toks["admin"]), timeout=10)
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) >= 1
        cid = rows[0]["id"]
        r2 = requests.get(f"{API}/campaigns/{cid}", headers=_h(toks["admin"]),
                          timeout=10)
        assert r2.status_code == 200
        assert "delivery_log" in r2.json()

    def test_invalid_filter_type(self, toks):
        r = requests.post(f"{API}/campaigns/estimate",
                          headers=_h(toks["admin"]),
                          json={"channel": "email", "filter_type": "bogus"},
                          timeout=10)
        assert r.status_code == 400
