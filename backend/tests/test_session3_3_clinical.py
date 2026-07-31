"""Session 3.3 — smoke tests for the Clinical runtime cutover.

Verifies:
    * Visit-note CRUD flows through emr_visit_notes (not Mongo).
    * The SHA-256 hash chain is preserved: prev_hash + note_hash populate on
      finalize, prev_hash of the second finalized note equals the note_hash
      of the first for the same practitioner.
    * Push-subscription CRUD lives in PostgreSQL.
"""
from __future__ import annotations

import os
import uuid

import pymongo
import pytest
import requests
from sqlalchemy import create_engine, text

from tests.smoketest_bootstrap import (
    ADMIN_EMAIL, PRACTITIONER_EMAIL,
    ensure_smoketest_admin_and_practitioner, login_smoketest_admin,
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
    # Log in practitioner (MFA enrolled with same fixture secret)
    import pyotp
    from tests.smoketest_bootstrap import FIXTURE_TOTP_SECRET, PRACTITIONER_PASSWORD
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


def test_note_hash_chain_lands_in_pg(admin_token, practitioner_token):
    """Two finalized notes for the same practitioner must chain by note_hash."""
    # Create a client (admin creates)
    unique = uuid.uuid4().hex[:8]
    rc = requests.post(f"{BASE_URL}/clients", headers=_b(admin_token),
                        json={"full_name": f"Chain Client {unique}",
                              "email": f"chain.{unique}@natmedsol.local"})
    assert rc.status_code == 200, rc.text
    cid = rc.json()["id"]

    # Practitioner drafts + finalizes — no delegation needed for their own notes.
    r1 = requests.post(f"{BASE_URL}/notes", headers=_b(practitioner_token), json={
        "client_id": cid,
        "subjective": "S1", "objective": "O1",
        "assessment": "A1", "plan": "P1",
    })
    assert r1.status_code == 200, r1.text
    n1_id = r1.json()["id"]
    r1f = requests.post(f"{BASE_URL}/notes/{n1_id}/finalize",
                        headers=_b(practitioner_token))
    assert r1f.status_code == 200, r1f.text
    # NoteOut may not surface prev_hash / note_hash — read directly from PG.
    with _pg().begin() as conn:
        row = conn.execute(text(
            "SELECT prev_hash, note_hash FROM emr_visit_notes WHERE id = :i"
        ), {"i": n1_id}).first()
    n1_prev, n1_hash = row
    assert n1_hash, "First finalized note should have note_hash"
    # prev_hash is either GENESIS (first ever finalized note for this practitioner)
    # or a chained hash from an earlier run. Either satisfies the invariant.
    assert n1_prev is not None

    # Note 2
    r2 = requests.post(f"{BASE_URL}/notes", headers=_b(practitioner_token), json={
        "client_id": cid,
        "subjective": "S2", "objective": "O2",
        "assessment": "A2", "plan": "P2",
    })
    assert r2.status_code == 200, r2.text
    n2_id = r2.json()["id"]
    r2f = requests.post(f"{BASE_URL}/notes/{n2_id}/finalize",
                        headers=_b(practitioner_token))
    assert r2f.status_code == 200, r2f.text
    with _pg().begin() as conn:
        row = conn.execute(text(
            "SELECT prev_hash, note_hash FROM emr_visit_notes WHERE id = :i"
        ), {"i": n2_id}).first()
    n2_prev, n2_hash = row
    assert n2_hash, "Second note should have note_hash"
    assert n2_prev == n1_hash, (
        f"Second note's prev_hash must equal first note's note_hash "
        f"(got {n2_prev!r} vs {n1_hash!r})"
    )

    # Mongo silent
    assert _mongo().visit_notes.find_one({"id": n1_id}) is None
    assert _mongo().visit_notes.find_one({"id": n2_id}) is None


def test_push_subscribe_unsubscribe_lands_in_pg(admin_token):
    endpoint = f"https://example.test/push/{uuid.uuid4().hex}"
    r = requests.post(f"{BASE_URL}/push/subscribe", headers=_b(admin_token),
                      json={"endpoint": endpoint,
                            "keys": {"p256dh": "abc", "auth": "xyz"}})
    assert r.status_code == 200

    # Confirm in PG
    with _pg().begin() as conn:
        n = conn.execute(text(
            "SELECT count(*) FROM emr_push_subscriptions WHERE endpoint = :ep"
        ), {"ep": endpoint}).scalar_one()
    assert n == 1

    # Unsubscribe
    r2 = requests.post(f"{BASE_URL}/push/unsubscribe", headers=_b(admin_token),
                       json={"endpoint": endpoint})
    assert r2.status_code == 200

    with _pg().begin() as conn:
        n2 = conn.execute(text(
            "SELECT count(*) FROM emr_push_subscriptions WHERE endpoint = :ep"
        ), {"ep": endpoint}).scalar_one()
    assert n2 == 0
    # Mongo silent
    assert _mongo().push_subscriptions.find_one({"endpoint": endpoint}) is None
