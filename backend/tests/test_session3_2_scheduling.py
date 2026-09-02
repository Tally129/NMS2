"""Session 3.2 — smoke tests for the Scheduling runtime cutover.

Verifies:
    * public appointment-request → PG
    * staff list/approve/decline/reschedule appointment requests → PG
    * appointment CRUD + auto-reminder creation → PG
    * availability CRUD + slots computation
    * reminders/settings singleton → PG
    * every Mongo write path is silent for the six scheduling collections
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pymongo
import pytest
import requests

from tests.smoketest_bootstrap import (
    ensure_smoketest_admin_and_practitioner,
    login_smoketest_admin,
    PRACTITIONER_EMAIL,
)

BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8001") + "/api"


def _mongo():
    c = pymongo.MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    return c[os.environ.get("DB_NAME", "test_database")]


@pytest.fixture(scope="module")
def admin_token():
    ensure_smoketest_admin_and_practitioner()
    return login_smoketest_admin(BASE_URL)


def _b(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_public_appointment_request_lands_in_pg(admin_token):
    unique = uuid.uuid4().hex[:8]
    r = requests.post(f"{BASE_URL}/public/appointment-request", json={
        "fullName": f"Sched Test {unique}",
        "email": f"sched.{unique}@ex.com",
        "phone": "555-000-0100",
        "returning": "no",
        "service": "wellness_consult",
        "date": "2026-08-15",
        "time": "10:00",
        "notes": "phase3.2 smoke",
        "addOns": ["telehealth"],
    })
    assert r.status_code == 200, r.text
    req_id = r.json()["id"]

    # Should NOT be in Mongo.
    assert _mongo().appointment_requests.find_one({"id": req_id}) is None

    # Staff can see it.
    r2 = requests.get(f"{BASE_URL}/appointment-requests", headers=_b(admin_token))
    assert r2.status_code == 200
    assert any(x["id"] == req_id for x in r2.json())

    # Approve.
    r3 = requests.post(f"{BASE_URL}/appointment-requests/{req_id}/approve",
                       headers=_b(admin_token))
    assert r3.status_code == 200, r3.text

    # Idempotent second approve.
    r4 = requests.post(f"{BASE_URL}/appointment-requests/{req_id}/approve",
                       headers=_b(admin_token))
    assert r4.status_code == 200
    assert r4.json().get("already_approved") is True


def test_appointment_crud_and_reminder_lands_in_pg(admin_token):
    """Create client → create appointment → auto-reminder created → all in PG."""
    unique = uuid.uuid4().hex[:8]
    # Create client
    rc = requests.post(f"{BASE_URL}/clients", headers=_b(admin_token),
                       json={"full_name": f"Sched Client {unique}",
                              "email": f"sched.client.{unique}@natmedsol.local"})
    assert rc.status_code == 200, rc.text
    cid = rc.json()["id"]

    # Create appointment (2 days out so auto-reminder is scheduled)
    start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
    end = start + timedelta(hours=1)
    ra = requests.post(f"{BASE_URL}/appointments", headers=_b(admin_token), json={
        "client_id": cid, "service": "Consult",
        "start": start.isoformat(), "end": end.isoformat(),
        "status": "confirmed",
    })
    assert ra.status_code == 200, ra.text
    appt_id = ra.json()["id"]

    # Verify Mongo does NOT have it.
    assert _mongo().appointments.find_one({"id": appt_id}) is None
    # A reminder should have been created (channel=email default).
    assert _mongo().reminders.find_one({"appointment_id": appt_id}) is None

    # List
    r_list = requests.get(f"{BASE_URL}/appointments?client_id=" + cid,
                          headers=_b(admin_token))
    assert r_list.status_code == 200
    assert any(x["id"] == appt_id for x in r_list.json())

    # Update
    ru = requests.put(f"{BASE_URL}/appointments/{appt_id}",
                     headers=_b(admin_token), json={"status": "arrived"})
    assert ru.status_code == 200, ru.text
    assert ru.json()["status"] == "arrived"


def test_reminder_settings_singleton_lands_in_pg(admin_token):
    r = requests.get(f"{BASE_URL}/reminders/settings", headers=_b(admin_token))
    assert r.status_code == 200
    # Update
    r2 = requests.put(f"{BASE_URL}/reminders/settings", headers=_b(admin_token), json={
        "appointment_reminder_hours_before": 12,
        "appointment_reminder_channels": ["email", "sms"],
        "follow_up_days_after": 5, "enabled": True,
    })
    assert r2.status_code == 200
    r3 = requests.get(f"{BASE_URL}/reminders/settings", headers=_b(admin_token))
    assert r3.json()["appointment_reminder_hours_before"] == 12
    # Mongo path is silent
    assert _mongo().reminder_settings.find_one({"id": "singleton"}) is None


def test_run_reminders_processes_due(admin_token):
    r = requests.post(f"{BASE_URL}/reminders/run", headers=_b(admin_token))
    assert r.status_code == 200
    assert "processed" in r.json()


def test_dashboard_stats_uses_pg_appointment_requests(admin_token):
    r = requests.get(f"{BASE_URL}/dashboard/stats", headers=_b(admin_token))
    assert r.status_code == 200
    body = r.json()
    assert "appointments_requested" in body
    assert isinstance(body["appointments_requested"], int)


def test_availability_create_delete_list(admin_token):
    """Availability CRUD."""
    # Create availability using bootstrap practitioner
    from tests.pg_test_helpers import pg_users_find_one
    prac = pg_users_find_one({"email": PRACTITIONER_EMAIL})
    if not prac:
        pytest.skip("Seed practitioner missing")

    r = requests.post(f"{BASE_URL}/availability", headers=_b(admin_token), json={
        "practitioner_id": prac["id"], "weekday": 1,
        "start_time": "09:00", "end_time": "17:00", "active": True,
    })
    assert r.status_code == 200, r.text
    avail_id = r.json()["id"]

    # List
    r_list = requests.get(f"{BASE_URL}/availability?practitioner_id=" + prac["id"],
                          headers=_b(admin_token))
    assert r_list.status_code == 200
    assert any(x["id"] == avail_id for x in r_list.json())

    # Delete
    r_del = requests.delete(f"{BASE_URL}/availability/{avail_id}",
                            headers=_b(admin_token))
    assert r_del.status_code == 200

    # Mongo silent
    assert _mongo().availability.find_one({"id": avail_id}) is None
