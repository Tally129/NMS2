"""Session 3.5 — smoke tests for the CRM & Operations runtime cutover.

Verifies that campaigns, front_desk_visits, internal_tasks, integration_log,
protocol_enrollments, protocol_templates, and file metadata all round-trip
through PostgreSQL via the `motor_compat_pg` adapter.
"""
from __future__ import annotations

import io
import os
import uuid

import pymongo
import pytest
import requests
from sqlalchemy import create_engine, text

from tests.smoketest_bootstrap import (
    ADMIN_EMAIL, PRACTITIONER_EMAIL, PRACTITIONER_PASSWORD,
    FIXTURE_TOTP_SECRET, ensure_smoketest_admin_and_practitioner,
    login_smoketest_admin,
)


BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8001") + "/api"


def _mongo():
    c = pymongo.MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    return c[os.environ.get("DB_NAME", "test_database")]


def _pg():
    dsn = os.environ["DATABASE_URL"]
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    return create_engine(dsn, future=True)


@pytest.fixture(scope="module")
def admin_token():
    ensure_smoketest_admin_and_practitioner()
    return login_smoketest_admin(BASE_URL)


@pytest.fixture(scope="module")
def practitioner_token():
    ensure_smoketest_admin_and_practitioner()
    import pyotp
    r = requests.post(f"{BASE_URL}/auth/login", json={
        "email": PRACTITIONER_EMAIL, "password": PRACTITIONER_PASSWORD,
    }, timeout=15)
    body = r.json()
    if body.get("mfa_required"):
        r2 = requests.post(f"{BASE_URL}/auth/login", json={
            "email": PRACTITIONER_EMAIL, "password": PRACTITIONER_PASSWORD,
            "mfa_token": pyotp.TOTP(FIXTURE_TOTP_SECRET).now(),
        }, timeout=15)
        body = r2.json()
    return body["access_token"]


def _b(tok):
    return {"Authorization": f"Bearer {tok}"}


def _create_client(admin_token) -> str:
    unique = uuid.uuid4().hex[:6]
    rc = requests.post(f"{BASE_URL}/clients", headers=_b(admin_token),
                        json={"full_name": f"Phase35 Client {unique}",
                              "email": f"phase35.{unique}@natmedsol.local"})
    assert rc.status_code == 200, rc.text
    return rc.json()["id"]


# ============================================ campaigns
def test_campaign_lifecycle_lands_in_pg(admin_token):
    rc = requests.post(f"{BASE_URL}/campaigns", headers=_b(admin_token),
                        json={"title": f"Smoke Campaign {uuid.uuid4().hex[:6]}",
                              "channel": "email",
                              "subject": "Hello",
                              "message": "<p>Hi</p>",
                              "filter_type": "all_marketing",
                              "kind": "marketing"})
    assert rc.status_code == 200, rc.text
    cid = rc.json()["id"]

    with _pg().begin() as conn:
        row = conn.execute(text(
            "SELECT id, payload FROM emr_campaigns WHERE id = :i"
        ), {"i": cid}).first()
    assert row is not None
    assert row[1].get("channel") == "email"

    # List
    rl = requests.get(f"{BASE_URL}/campaigns", headers=_b(admin_token))
    assert rl.status_code == 200
    assert any(c["id"] == cid for c in rl.json())

    # Mongo silent
    assert _mongo().campaigns.find_one({"id": cid}) is None


# ============================================ internal_tasks + integration_log
def test_internal_task_dashboard_and_summary(admin_token, practitioner_token):
    client_id = _create_client(admin_token)
    rc = requests.post(f"{BASE_URL}/tasks", headers=_b(admin_token),
                        json={"title": "Smoke task",
                              "client_id": client_id,
                              "priority": "high",
                              "category": "review_labs",
                              "assigned_provider_id": None,
                              "assigned_staff_id": None})
    assert rc.status_code == 200, rc.text
    tid = rc.json()["id"]

    # Landed in PG
    with _pg().begin() as conn:
        row = conn.execute(text(
            "SELECT id, status, payload FROM emr_internal_tasks WHERE id = :i"
        ), {"i": tid}).first()
    assert row is not None
    # status may be typed or in payload depending on router
    assert (row[1] or row[2].get("status")) == "new"

    # List — uses .sort([...]) with multiple keys
    rl = requests.get(f"{BASE_URL}/tasks", headers=_b(admin_token))
    assert rl.status_code == 200
    assert any(t["id"] == tid for t in rl.json())

    # Dashboard summary (uses $or + $in + $lt/$gte/$lte in count_documents)
    rs = requests.get(f"{BASE_URL}/tasks/dashboard/summary",
                       headers=_b(admin_token))
    assert rs.status_code == 200
    body = rs.json()
    for k in ("my_tasks", "overdue", "due_today", "waiting"):
        assert k in body and isinstance(body[k], int)

    # Update status → in_progress
    ru = requests.patch(f"{BASE_URL}/tasks/{tid}", headers=_b(admin_token),
                         json={"status": "in_progress"})
    assert ru.status_code == 200

    # Delete
    rd = requests.delete(f"{BASE_URL}/tasks/{tid}", headers=_b(admin_token))
    assert rd.status_code == 200

    # Mongo silent
    assert _mongo().internal_tasks.find_one({"id": tid}) is None


# ============================================ protocol_templates + enrollments
def test_protocol_template_and_enrollment(admin_token, practitioner_token):
    # Create template
    rt = requests.post(f"{BASE_URL}/protocols/templates",
                        headers=_b(practitioner_token),
                        json={"title": f"Smoke Protocol {uuid.uuid4().hex[:6]}",
                              "description": "Adapter smoke",
                              "weeks": 2, "sessions_per_week": 1,
                              "treatment_label": "IV therapy",
                              "daily_outline": "Hydrate",
                              "foods_recommended": ["water"],
                              "foods_avoid": [],
                              "lifestyle": "rest",
                              "supplements": [],
                              "active": True})
    assert rt.status_code == 200, rt.text
    tpl_id = rt.json()["id"]

    # PG
    with _pg().begin() as conn:
        row = conn.execute(text(
            "SELECT id, payload FROM emr_protocol_templates WHERE id = :i"
        ), {"i": tpl_id}).first()
    assert row is not None
    assert row[1].get("weeks") == 2

    # Enroll a client
    client_id = _create_client(admin_token)
    re = requests.post(f"{BASE_URL}/protocols/enrollments",
                        headers=_b(practitioner_token),
                        json={"template_id": tpl_id, "client_id": client_id,
                              "weeks": 2, "sessions_per_week": 1})
    assert re.status_code == 200, re.text
    enr_id = re.json()["id"]

    with _pg().begin() as conn:
        row = conn.execute(text(
            "SELECT id, client_id, status, payload FROM emr_protocol_enrollments "
            "WHERE id = :i"
        ), {"i": enr_id}).first()
    assert row is not None
    assert row[1] == client_id or row[3].get("client_id") == client_id
    assert (row[2] or row[3].get("status")) == "proposed"

    # List (uses sort on payload->>'proposed_at')
    rl = requests.get(f"{BASE_URL}/protocols/enrollments?client_id={client_id}",
                       headers=_b(practitioner_token))
    assert rl.status_code == 200
    assert any(e["id"] == enr_id for e in rl.json())

    # Mongo silent
    assert _mongo().protocol_templates.find_one({"id": tpl_id}) is None
    assert _mongo().protocol_enrollments.find_one({"id": enr_id}) is None


# ============================================ front_desk_visits
def test_front_desk_visits_land_in_pg(admin_token):
    client_id = _create_client(admin_token)
    rc = requests.post(f"{BASE_URL}/front-desk/check-in", headers=_b(admin_token),
                        json={"client_id": client_id, "walk_in": True,
                              "room": "A1"})
    assert rc.status_code == 200, rc.text
    vid = rc.json()["id"]

    with _pg().begin() as conn:
        row = conn.execute(text(
            "SELECT id, client_id, payload FROM emr_front_desk_visits WHERE id = :i"
        ), {"i": vid}).first()
    assert row is not None
    assert row[1] == client_id or row[2].get("client_id") == client_id

    # Today list (uses range filter on created_at)
    rl = requests.get(f"{BASE_URL}/front-desk/today", headers=_b(admin_token))
    assert rl.status_code == 200
    assert any(v["id"] == vid for v in rl.json())

    # Update
    ru = requests.put(f"{BASE_URL}/front-desk/{vid}", headers=_b(admin_token),
                       json={"status": "checked_out"})
    assert ru.status_code == 200
    assert ru.json()["status"] == "checked_out"

    # Mongo silent
    assert _mongo().front_desk_visits.find_one({"id": vid}) is None


# ============================================ file metadata (not GridFS)
def test_file_metadata_lands_in_pg(admin_token):
    client_id = _create_client(admin_token)
    # Upload a small file — the app inserts metadata into `files` while
    # storing bytes in GridFS.
    body = b"phase 3.5 smoke test\n"
    files = {"file": ("smoke.txt", body, "text/plain")}
    ru = requests.post(f"{BASE_URL}/files/upload", headers=_b(admin_token),
                        data={"client_id": client_id, "category": "other"},
                        files=files)
    assert ru.status_code == 200, ru.text
    file_id = ru.json()["id"]

    # PG metadata
    with _pg().begin() as conn:
        row = conn.execute(text(
            "SELECT id, client_id, deleted_at, payload FROM emr_file_meta "
            "WHERE id = :i"
        ), {"i": file_id}).first()
    assert row is not None
    assert row[1] == client_id
    assert row[2] is None  # not soft-deleted
    assert row[3].get("filename") == "smoke.txt"

    # List for client (uses `deleted_at: None` filter + sort by created_at desc)
    rl = requests.get(f"{BASE_URL}/files?client_id={client_id}",
                       headers=_b(admin_token))
    assert rl.status_code == 200
    assert any(f["id"] == file_id for f in rl.json())

    # Soft-delete
    rd = requests.delete(f"{BASE_URL}/files/{file_id}", headers=_b(admin_token))
    assert rd.status_code == 200

    with _pg().begin() as conn:
        row = conn.execute(text(
            "SELECT deleted_at, payload FROM emr_file_meta WHERE id = :i"
        ), {"i": file_id}).first()
    # `deleted_at` may be typed column or in payload depending on router
    assert row[0] is not None or row[1].get("deleted_at") is not None

    # Mongo silent for file metadata (GridFS chunks stay behind — expected)
    assert _mongo().files.find_one({"id": file_id}) is None


# ============================================ integration_log
def test_integration_log_write_path(admin_token, practitioner_token):
    """Any endpoint that logs an integration attempt (stripe stub, low-stock
    alert, invoice email) writes to emr_integration_log via the adapter.
    Simplest driver: send an email via the campaign estimator + save."""
    # Direct write through the adapter
    from deps import db
    import asyncio

    async def _write():
        await db.integration_log.insert_one({
            "id": uuid.uuid4().hex,
            "service": "smoke", "action": "phase35_test",
            "payload": {"note": "adapter"},
        })

    asyncio.run(_write())

    with _pg().begin() as conn:
        n = conn.execute(text(
            "SELECT count(*) FROM emr_integration_log WHERE payload->>'action' = 'phase35_test'"
        )).scalar_one()
    assert n >= 1

    # Mongo silent
    assert _mongo().integration_log.count_documents({"action": "phase35_test"}) == 0
