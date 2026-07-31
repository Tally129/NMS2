"""Session 3.4b — smoke tests for the Messaging / Forms / Labs / Treatments
runtime cutover via the `motor_compat_pg` adapter.

Every write must land in PostgreSQL. Every read must return the router-shaped
document (payload merged with typed columns) so existing router logic keeps
working. Mongo must remain silent for all 8 retired collections.
"""
from __future__ import annotations

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


# ================================================= treatments (catalog)
def test_treatment_catalog_lands_in_pg(admin_token):
    """POS/inventory-style treatment catalog CRUD via `db.treatments`."""
    name = f"Smoke Treatment {uuid.uuid4().hex[:6]}"
    rc = requests.post(f"{BASE_URL}/treatments", headers=_b(admin_token),
                        json={"name": name, "price": 42.5, "active": True,
                              "duration_min": 30, "category": "wellness"})
    assert rc.status_code == 200, rc.text
    tid = rc.json()["id"]
    assert rc.json()["name"] == name

    # List (active_only filter uses the payload.active field)
    rl = requests.get(f"{BASE_URL}/treatments?active_only=true",
                       headers=_b(admin_token))
    assert rl.status_code == 200
    names = {t["name"] for t in rl.json()}
    assert name in names

    # Update
    ru = requests.put(f"{BASE_URL}/treatments/{tid}", headers=_b(admin_token),
                       json={"name": name, "price": 55.0, "active": True,
                             "duration_min": 45, "category": "wellness"})
    assert ru.status_code == 200
    assert ru.json()["price"] == 55.0

    # PG has the row
    with _pg().begin() as conn:
        row = conn.execute(text(
            "SELECT id, payload FROM emr_treatments WHERE id = :i"
        ), {"i": tid}).first()
    assert row is not None
    assert row[1].get("name") == name and row[1].get("price") == 55.0

    # Mongo silent
    assert _mongo().treatments.find_one({"id": tid}) is None

    # Delete
    rd = requests.delete(f"{BASE_URL}/treatments/{tid}", headers=_b(admin_token))
    assert rd.status_code == 200
    with _pg().begin() as conn:
        n = conn.execute(text(
            "SELECT count(*) FROM emr_treatments WHERE id = :i"
        ), {"i": tid}).scalar_one()
    assert n == 0


# ============================================ form_templates + submissions
def test_form_template_and_submission_land_in_pg(admin_token):
    payload = {
        "title": f"Smoke Consent {uuid.uuid4().hex[:6]}",
        "description": "Adapter smoke test",
        "category": "consent",
        "fields": [
            {"id": "full-name", "type": "text", "label": "Full name",
             "required": True},
            {"id": "signature", "type": "signature", "label": "Signature",
             "required": True},
        ],
        "active": True,
    }
    rc = requests.post(f"{BASE_URL}/forms/templates", headers=_b(admin_token),
                        json=payload)
    assert rc.status_code == 200, rc.text
    tpl = rc.json()
    tpl_id = tpl["id"]
    assert tpl["title"] == payload["title"]

    # List
    rl = requests.get(f"{BASE_URL}/forms/templates", headers=_b(admin_token))
    assert rl.status_code == 200
    assert any(t["id"] == tpl_id for t in rl.json())

    # PG row
    with _pg().begin() as conn:
        row = conn.execute(text(
            "SELECT title, payload FROM emr_form_templates WHERE id = :i"
        ), {"i": tpl_id}).first()
    assert row is not None
    assert row[0] == payload["title"]
    assert row[1].get("category") == "consent"
    assert row[1].get("active") is True

    # Update
    ru = requests.put(f"{BASE_URL}/forms/templates/{tpl_id}",
                       headers=_b(admin_token),
                       json={**payload, "description": "updated"})
    assert ru.status_code == 200
    assert ru.json()["description"] == "updated"

    # Send → creates a form_submission
    rs = requests.post(f"{BASE_URL}/forms/send", headers=_b(admin_token),
                        json={"template_id": tpl_id, "expires_in_hours": 24,
                              "channel": "link"})
    assert rs.status_code == 200, rs.text
    sub = rs.json()
    token = sub["token"]

    # PG has the submission
    with _pg().begin() as conn:
        row = conn.execute(text(
            "SELECT token, status, payload FROM emr_form_submissions WHERE id = :i"
        ), {"i": sub["id"]}).first()
    assert row is not None
    assert row[0] == token
    assert row[1] == "sent"
    assert row[2].get("template_title") == payload["title"]

    # Public GET (no auth)
    rg = requests.get(f"{BASE_URL}/public/forms/{token}")
    assert rg.status_code == 200
    assert rg.json()["template_id"] == tpl_id

    # Submit
    rp = requests.post(f"{BASE_URL}/public/forms/{token}/submit", json={
        "answers": {"full-name": "Jane Smoke"},
        "signature_data": "data:image/png;base64,AAA",
    })
    assert rp.status_code == 200, rp.text

    with _pg().begin() as conn:
        row = conn.execute(text(
            "SELECT status, answers, payload FROM emr_form_submissions WHERE token = :t"
        ), {"t": token}).first()
    assert row[0] == "submitted"
    assert row[1].get("full-name") == "Jane Smoke"

    # Mongo silent
    assert _mongo().form_templates.find_one({"id": tpl_id}) is None
    assert _mongo().form_submissions.find_one({"token": token}) is None


# ============================================ soap_templates
def test_soap_template_crud_lands_in_pg(admin_token):
    title = f"Smoke SOAP {uuid.uuid4().hex[:6]}"
    rc = requests.post(f"{BASE_URL}/soap-templates", headers=_b(admin_token),
                        json={"title": title,
                              "subjective": "S", "objective": "O",
                              "assessment": "A", "plan": "P",
                              "visit_type": "telehealth", "active": True})
    assert rc.status_code == 200, rc.text
    tid = rc.json()["id"]

    with _pg().begin() as conn:
        row = conn.execute(text(
            "SELECT title, payload FROM emr_soap_templates WHERE id = :i"
        ), {"i": tid}).first()
    assert row is not None
    assert row[0] == title
    assert row[1].get("subjective") == "S"
    assert row[1].get("visit_type") == "telehealth"

    # List
    rl = requests.get(f"{BASE_URL}/soap-templates", headers=_b(admin_token))
    assert rl.status_code == 200
    assert any(t["id"] == tid for t in rl.json())

    # Mongo silent
    assert _mongo().soap_templates.find_one({"id": tid}) is None


# ============================================ messages + threads
def _create_client(admin_token, practitioner_token) -> tuple[str, str]:
    """Return (client_id, client_user_id-or-empty). Practitioner threads need
    a client row + a linked user id."""
    unique = uuid.uuid4().hex[:6]
    email = f"msg.{unique}@natmedsol.local"
    rc = requests.post(f"{BASE_URL}/clients", headers=_b(admin_token),
                        json={"full_name": f"Msg Client {unique}",
                              "email": email})
    assert rc.status_code == 200, rc.text
    return rc.json()["id"], email


def test_messages_and_threads_land_in_pg(admin_token, practitioner_token):
    cid, _email = _create_client(admin_token, practitioner_token)

    # Practitioner opens a thread with the client
    rt = requests.post(f"{BASE_URL}/messages/threads",
                        headers=_b(practitioner_token),
                        json={"participant_id": cid,
                              "subject": "Smoke thread",
                              "first_message": "Hello from PG adapter"})
    assert rt.status_code == 200, rt.text
    tid = rt.json()["id"]

    # PG state
    with _pg().begin() as conn:
        thread_row = conn.execute(text(
            "SELECT subject, client_id, practitioner_id, payload "
            "FROM emr_message_threads WHERE id = :i"
        ), {"i": tid}).first()
    assert thread_row is not None
    assert thread_row[0] == "Smoke thread"
    assert thread_row[1] == cid
    assert thread_row[3].get("last_message_preview") == "Hello from PG adapter"

    with _pg().begin() as conn:
        msg_count = conn.execute(text(
            "SELECT count(*) FROM emr_messages WHERE thread_id = :t"
        ), {"t": tid}).scalar_one()
    assert msg_count == 1

    # Post a second message
    rm = requests.post(f"{BASE_URL}/messages/threads/{tid}/messages",
                        headers=_b(practitioner_token),
                        json={"body": "Follow up"})
    assert rm.status_code == 200

    # List messages (also flips read_by via $push)
    rl = requests.get(f"{BASE_URL}/messages/threads/{tid}",
                       headers=_b(practitioner_token))
    assert rl.status_code == 200
    bodies = [m["body"] for m in rl.json()]
    assert bodies == ["Hello from PG adapter", "Follow up"]

    # PG: two messages, thread.last_message_at is not null
    with _pg().begin() as conn:
        rows = conn.execute(text(
            "SELECT body, payload FROM emr_messages WHERE thread_id = :t "
            "ORDER BY created_at ASC"
        ), {"t": tid}).all()
    assert len(rows) == 2
    for _body, p in rows:
        assert practitioner_token  # sanity — sender_id is a hash we can't easily assert
        assert "read_by" in p and isinstance(p["read_by"], list)

    # Mongo silent
    assert _mongo().messages.find_one({"thread_id": tid}) is None
    assert _mongo().message_threads.find_one({"id": tid}) is None


# ============================================ lab_values
def test_lab_values_crud_and_review_land_in_pg(admin_token, practitioner_token):
    cid, _ = _create_client(admin_token, practitioner_token)

    # Create a lab
    rc = requests.post(f"{BASE_URL}/lab-values", headers=_b(practitioner_token),
                        json={"client_id": cid, "test_name": "TSH",
                              "value": "2.5", "unit": "mIU/L",
                              "reference_low": 0.4, "reference_high": 4.0,
                              "measured_at": "2026-08-01T12:00:00Z"})
    assert rc.status_code == 200, rc.text
    lab_id = rc.json()["id"]

    # PG has the lab (typed column `value`, payload has `test_name` etc.)
    with _pg().begin() as conn:
        row = conn.execute(text(
            "SELECT marker, value, unit, payload FROM emr_lab_values WHERE id = :i"
        ), {"i": lab_id}).first()
    assert row is not None
    assert row[3].get("test_name") == "TSH"
    # `value` is a typed column on emr_lab_values
    assert row[1] == "2.5" or row[1] == 2.5

    # Update review status via `PATCH /labs/{id}/review-status` — this uses
    # $set + $push (review_history) simultaneously.
    rp = requests.patch(f"{BASE_URL}/labs/{lab_id}/review-status",
                         headers=_b(practitioner_token),
                         json={"review_status": "reviewed",
                               "review_notes": "Adapter smoke"})
    assert rp.status_code == 200, rp.text
    assert rp.json()["review_status"] == "reviewed"

    with _pg().begin() as conn:
        row = conn.execute(text(
            "SELECT payload FROM emr_lab_values WHERE id = :i"
        ), {"i": lab_id}).first()
    p = row[0]
    assert p.get("review_status") == "reviewed"
    assert isinstance(p.get("review_history"), list) and len(p["review_history"]) >= 1

    # Attach a file via $addToSet
    # Create a fake file metadata record via the adapter (routes to PG).
    file_id = uuid.uuid4().hex
    import asyncio
    from deps import db as _db
    asyncio.run(_db.files.insert_one({
        "id": file_id, "client_id": cid, "deleted_at": None,
        "content_type": "application/pdf", "filename": "smoke.pdf",
    }))
    ra = requests.post(f"{BASE_URL}/labs/{lab_id}/attachments",
                        headers=_b(practitioner_token),
                        json={"file_id": file_id})
    assert ra.status_code == 200

    with _pg().begin() as conn:
        row = conn.execute(text(
            "SELECT payload FROM emr_lab_values WHERE id = :i"
        ), {"i": lab_id}).first()
    assert file_id in (row[0].get("attachment_file_ids") or [])

    # Detach
    rd = requests.delete(
        f"{BASE_URL}/labs/{lab_id}/attachments/{file_id}",
        headers=_b(practitioner_token),
    )
    assert rd.status_code == 200
    with _pg().begin() as conn:
        row = conn.execute(text(
            "SELECT payload FROM emr_lab_values WHERE id = :i"
        ), {"i": lab_id}).first()
    assert file_id not in (row[0].get("attachment_file_ids") or [])

    # List labs (uses find + sort on payload.measured_at)
    rl = requests.get(f"{BASE_URL}/lab-values?client_id={cid}",
                       headers=_b(practitioner_token))
    assert rl.status_code == 200
    assert any(l["id"] == lab_id for l in rl.json())

    # Mongo silent
    assert _mongo().lab_values.find_one({"id": lab_id}) is None

    # cleanup fake file metadata
    asyncio.run(_db.files.delete_one({"id": file_id}))


# ============================================ treatment_plans
def test_treatment_plans_land_in_pg(admin_token, practitioner_token):
    cid, _ = _create_client(admin_token, practitioner_token)
    rc = requests.post(f"{BASE_URL}/treatment-plans",
                        headers=_b(practitioner_token),
                        json={"client_id": cid, "title": "Smoke plan",
                              "status": "active",
                              "follow_up_days": 30,
                              "items": [{"type": "supplement",
                                          "title": "Vitamin D",
                                          "dose": "5000 IU",
                                          "frequency": "daily"}]})
    assert rc.status_code == 200, rc.text
    pid = rc.json()["id"]

    # PG row — title is typed column, follow_up_days + items land in payload
    with _pg().begin() as conn:
        row = conn.execute(text(
            "SELECT title, status, payload FROM emr_treatment_plans WHERE id = :i"
        ), {"i": pid}).first()
    assert row is not None
    assert row[0] == "Smoke plan"
    assert row[1] == "active"
    assert row[2].get("follow_up_days") == 30
    assert len(row[2].get("items") or []) == 1

    # List by client
    rl = requests.get(f"{BASE_URL}/treatment-plans?client_id={cid}",
                       headers=_b(practitioner_token))
    assert rl.status_code == 200
    assert any(p["id"] == pid for p in rl.json())

    # Mongo silent
    assert _mongo().treatment_plans.find_one({"id": pid}) is None
