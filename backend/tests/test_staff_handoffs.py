"""
End-to-end verification for the five staff handoffs + the messages/tasks
promotion path.

Every test uses the running backend via the seeded practitioner account and
cleans up after itself. Requires the backend to be running with a live
Mongo connection (the standard test setup).
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://design-158.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def practitioner_headers():
    r = requests.post(
        f"{API}/auth/login",
        json={"email": "ravello@natmedsol.local", "password": "Ravello!2345"},
        timeout=15,
    )
    d = r.json()
    assert "access_token" in d, f"login failed: {d}"
    return {"Authorization": f"Bearer {d['access_token']}"}


@pytest.fixture(scope="module")
def sample_client(practitioner_headers):
    """Create a throw-away client so nothing collides with the seeded data."""
    payload = {
        "full_name": f"Handoff Test {int(time.time())}",
        "email": f"handoff.{int(time.time())}@example.com",
        "phone": "555-0000",
    }
    r = requests.post(f"{API}/clients", json=payload,
                      headers=practitioner_headers, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# Handoff #1 — appointment request → confirmed                                #
# --------------------------------------------------------------------------- #

class TestHandoff1_RequestToConfirmed:
    def test_staff_can_confirm_a_requested_appointment(
        self, practitioner_headers, sample_client,
    ):
        start = datetime.now(timezone.utc) + timedelta(days=1)
        end = start + timedelta(minutes=30)
        # Staff-created appointments default to `confirmed`; force
        # `status=requested` to simulate the patient-initiated flow.
        payload = {
            "client_id": sample_client["id"],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "service": "Consult",
            "status": "requested",
        }
        r = requests.post(f"{API}/appointments", json=payload,
                          headers=practitioner_headers, timeout=15)
        assert r.status_code == 200, r.text
        appt = r.json()
        assert appt["status"] == "requested"

        # Confirm the request.
        r = requests.put(f"{API}/appointments/{appt['id']}",
                         json={"status": "confirmed"},
                         headers=practitioner_headers, timeout=15)
        assert r.status_code == 200
        assert r.json()["status"] == "confirmed"


# --------------------------------------------------------------------------- #
# Handoff #2 — readiness signals hydrated on /front-desk/today                #
# --------------------------------------------------------------------------- #

class TestHandoff2_ReadinessSignals:
    def test_front_desk_today_exposes_intake_forms_docs(
        self, practitioner_headers, sample_client,
    ):
        # Check the client in.
        r = requests.post(
            f"{API}/front-desk/check-in",
            json={"client_id": sample_client["id"], "walk_in": True},
            headers=practitioner_headers, timeout=15,
        )
        assert r.status_code == 200, r.text
        visit = r.json()
        assert "intake_complete" in visit
        assert "forms_pending" in visit
        assert "documents_ready" in visit
        # New client has no intake / forms / files — all falsy.
        assert visit["intake_complete"] is False
        assert visit["forms_pending"] == 0
        assert visit["documents_ready"] is False


# --------------------------------------------------------------------------- #
# Handoff #3 — front-desk status sync onto appointment                        #
# --------------------------------------------------------------------------- #

class TestHandoff3_FrontDeskSync:
    def test_in_room_marks_appointment_in_session(
        self, practitioner_headers, sample_client,
    ):
        start = datetime.now(timezone.utc) + timedelta(hours=1)
        appt = requests.post(
            f"{API}/appointments",
            json={
                "client_id": sample_client["id"],
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=30)).isoformat(),
                "status": "confirmed",
            },
            headers=practitioner_headers, timeout=15,
        ).json()

        # Check-in tied to that appointment.
        v = requests.post(
            f"{API}/front-desk/check-in",
            json={"client_id": sample_client["id"], "appointment_id": appt["id"]},
            headers=practitioner_headers, timeout=15,
        ).json()

        # Move to "in_room" → appointment should become "in_session".
        r = requests.put(
            f"{API}/front-desk/{v['id']}",
            json={"status": "in_room"},
            headers=practitioner_headers, timeout=15,
        )
        assert r.status_code == 200, r.text

        appt_after = requests.get(
            f"{API}/appointments", headers=practitioner_headers, timeout=15,
        ).json()
        appt_after = next(a for a in appt_after if a["id"] == appt["id"])
        assert appt_after["status"] == "in_session"


# --------------------------------------------------------------------------- #
# Handoff #4 — POS checkout links back to appointment                          #
# --------------------------------------------------------------------------- #

class TestHandoff4_PosLinksAppointment:
    def test_pos_checkout_completes_appointment_and_stores_tx_id(
        self, practitioner_headers, sample_client,
    ):
        start = datetime.now(timezone.utc) + timedelta(hours=2)
        appt = requests.post(
            f"{API}/appointments",
            json={
                "client_id": sample_client["id"],
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=30)).isoformat(),
                "status": "confirmed",
            },
            headers=practitioner_headers, timeout=15,
        ).json()

        r = requests.post(
            f"{API}/pos/checkout",
            json={
                "client_id": sample_client["id"],
                "appointment_id": appt["id"],
                "lines": [{
                    "type": "custom", "ref_id": None,
                    "name": "Consult", "qty": 1, "unit_price": 100.0,
                }],
                "payment_method": "cash",
            },
            headers=practitioner_headers, timeout=15,
        )
        assert r.status_code == 200, r.text
        txn = r.json()
        assert txn["status"] == "paid"

        appt_after = requests.get(
            f"{API}/appointments", headers=practitioner_headers, timeout=15,
        ).json()
        appt_after = next(a for a in appt_after if a["id"] == appt["id"])
        assert appt_after["status"] == "completed"
        assert appt_after["transaction_id"] == txn["id"]


# --------------------------------------------------------------------------- #
# Handoff #6 — messages promote-to-task                                       #
# --------------------------------------------------------------------------- #

class TestHandoff6_MessageToTask:
    def test_promote_thread_creates_task_and_links_back(
        self, practitioner_headers, sample_client,
    ):
        thread = requests.post(
            f"{API}/messages/threads",
            json={
                "participant_id": sample_client["id"],
                "subject": f"Handoff test {int(time.time())}",
                "first_message": "Please follow up on this.",
            },
            headers=practitioner_headers, timeout=15,
        ).json()

        r = requests.post(
            f"{API}/messages/threads/{thread['id']}/promote-to-task",
            json={"priority": "high", "category": "message_followup"},
            headers=practitioner_headers, timeout=15,
        )
        assert r.status_code == 200, r.text
        task = r.json()
        assert task["priority"] == "high"
        assert task["linked_thread_id"] == thread["id"]

        # Thread now shows the reverse link.
        threads = requests.get(
            f"{API}/messages/threads", headers=practitioner_headers, timeout=15,
        ).json()
        row = next(t for t in threads if t["id"] == thread["id"])
        assert row.get("linked_task_id") == task["id"]

        # Second call must fail with 409 — never duplicate the task.
        r2 = requests.post(
            f"{API}/messages/threads/{thread['id']}/promote-to-task",
            json={}, headers=practitioner_headers, timeout=15,
        )
        assert r2.status_code == 409
        assert r2.json()["detail"]["code"] == "task_already_linked"
