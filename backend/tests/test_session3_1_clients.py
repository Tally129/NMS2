"""Session 3.1b — smoke tests for the Identity/Patients runtime cutover.

Every collection previously read by the routers touched in Phase 3.1b now
lives in PostgreSQL: `users`, `clients`, `intake_forms`,
`client_supplement_assignments`, `supplement_sheets`,
`password_reset_tokens`. These tests exercise the surviving HTTP surface
end-to-end and assert no writes land in the retired Mongo collections.
"""
from __future__ import annotations

import os
import uuid

import pymongo
import pytest
import requests

BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8001") + "/api"
ADMIN = ("admin@natmedsol.local", "Admin!2345")


def _login(email, password):
    r = requests.post(f"{BASE_URL}/auth/login", json={
        "email": email, "password": password,
    })
    r.raise_for_status()
    return r.json()["access_token"]


def _mongo():
    c = pymongo.MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    return c[os.environ.get("DB_NAME", "test_database")]


@pytest.fixture(scope="module")
def admin_token():
    return _login(*ADMIN)


def _bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_practitioners_list_from_pg(admin_token):
    r = requests.get(f"{BASE_URL}/practitioners", headers=_bearer(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    # Non-empty — PG has hundreds of practitioners from prior sessions.
    assert len(body) >= 1


def test_clients_list_from_pg(admin_token):
    r = requests.get(f"{BASE_URL}/clients", headers=_bearer(admin_token))
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_dashboard_stats_uses_pg_client_count(admin_token):
    r = requests.get(f"{BASE_URL}/dashboard/stats", headers=_bearer(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body.get("clients"), int)
    assert body["clients"] >= 0


def test_create_update_client_lands_in_pg(admin_token):
    unique = uuid.uuid4().hex[:8]
    payload = {
        "full_name": f"Session3.1b Test {unique}",
        "email": f"session3.1b.{unique}@natmedsol.local",
        "phone": "555-000-0000",
    }
    r = requests.post(f"{BASE_URL}/clients", json=payload, headers=_bearer(admin_token))
    assert r.status_code == 200, r.text
    created = r.json()
    cid = created["id"]

    # Read back
    r2 = requests.get(f"{BASE_URL}/clients/{cid}", headers=_bearer(admin_token))
    assert r2.status_code == 200, r2.text
    assert r2.json()["full_name"] == payload["full_name"]

    # Update
    payload["full_name"] = payload["full_name"] + " (updated)"
    r3 = requests.put(f"{BASE_URL}/clients/{cid}", json=payload,
                       headers=_bearer(admin_token))
    assert r3.status_code == 200, r3.text
    assert r3.json()["full_name"].endswith("(updated)")

    # Assert Mongo did NOT receive it.
    m = _mongo()
    assert m.clients.find_one({"id": cid}) is None, (
        "Phase 3.1b regression: client write should NOT land in Mongo"
    )


def test_intake_save_lands_in_pg(admin_token):
    unique = uuid.uuid4().hex[:8]
    r = requests.post(f"{BASE_URL}/clients",
                       json={"full_name": f"Intake User {unique}",
                              "email": f"intake.{unique}@natmedsol.local"},
                       headers=_bearer(admin_token))
    assert r.status_code == 200, r.text
    cid = r.json()["id"]

    body = {
        "client_id": cid,
        "demographics": {"first_name": "IntakeFN"},
        "health_history": {},
        "lifestyle": {},
        "symptoms": {},
        "consent": {"signed": True},
        "completed": True,
    }
    r2 = requests.post(f"{BASE_URL}/intake", json=body, headers=_bearer(admin_token))
    assert r2.status_code == 200, r2.text

    r3 = requests.get(f"{BASE_URL}/intake/{cid}", headers=_bearer(admin_token))
    assert r3.status_code == 200, r3.text
    assert r3.json()["client_id"] == cid

    m = _mongo()
    assert m.intake_forms.find_one({"client_id": cid}) is None, (
        "Phase 3.1b regression: intake write should NOT land in Mongo"
    )


def test_admin_users_list_from_pg(admin_token):
    r = requests.get(f"{BASE_URL}/admin/users", headers=_bearer(admin_token))
    assert r.status_code == 200, r.text
    emails = {u["email"] for u in r.json()}
    assert "admin@natmedsol.local" in emails
