"""Shared bootstrap helper for Phase 3.1b / 3.2 smoke tests.

After `scripts/reset_test_data.py` wipes the database, these tests still need
a workforce login to exercise the HTTP surface. This helper is TEST
INFRASTRUCTURE (not demo data) — it materialises a single admin + one
practitioner directly in PostgreSQL and enrols the shared MFA fixture
secret so the conftest.py MFA gate works.

Both accounts survive `DEMO_SEED_DISABLE=1` because we insert them ONCE per
test run outside of the server-startup path.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Tuple

import pyotp
import requests
from sqlalchemy import create_engine, text


FIXTURE_TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
ADMIN_EMAIL = "smoketest-admin@natmedsol.local"
ADMIN_PASSWORD = "SmokeAdmin!2345"
PRACTITIONER_EMAIL = "smoketest-prac@natmedsol.local"
PRACTITIONER_PASSWORD = "SmokePrac!2345"


def _sync_dsn() -> str:
    dsn = os.environ["DATABASE_URL"]
    if dsn.startswith("postgresql+asyncpg://"):
        return dsn.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if dsn.startswith("postgresql://"):
        return dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    return dsn


def _engine():
    return create_engine(_sync_dsn(), future=True)


def _upsert_user(email: str, password: str, role: str, full_name: str,
                  mfa_secret_encrypted: str) -> str:
    """Ensure a user row exists with the given credentials + MFA enabled.

    Returns the user id.
    """
    from auth_utils import hash_password  # local import — path only valid in-repo
    import uuid
    uid = None
    with _engine().begin() as conn:
        row = conn.execute(text(
            "SELECT id FROM auth_users WHERE lower(email) = :e"
        ), {"e": email.lower()}).first()
        if row:
            uid = row[0]
            conn.execute(text(
                "UPDATE auth_users SET password_hash = :h, mfa_enabled = TRUE, "
                "mfa_secret = :s, role = :r, is_active = TRUE, "
                "session_version = COALESCE(session_version, 1) "
                "WHERE id = :u"
            ), {"h": hash_password(password), "s": mfa_secret_encrypted,
                "r": role, "u": uid})
            return uid
        uid = uuid.uuid4().hex
        conn.execute(text(
            "INSERT INTO auth_users (id, email, password_hash, full_name, "
            "role, mfa_enabled, mfa_secret, mfa_bypass, must_change_password, "
            "is_active, session_version, created_at) VALUES "
            "(:id, :email, :ph, :fn, :role, TRUE, :s, FALSE, FALSE, "
            " TRUE, 1, :now)"
        ), {"id": uid, "email": email.lower(), "ph": hash_password(password),
            "fn": full_name, "role": role, "s": mfa_secret_encrypted,
            "now": datetime.now(timezone.utc)})
    return uid


def ensure_smoketest_admin_and_practitioner() -> None:
    """Idempotent bootstrap for tests running against a wiped environment."""
    # Import mfa_crypto lazily so this helper is safe to import from tests
    # collected before backend deps are on the path.
    from auth_utils import encrypt_mfa_secret
    enc = encrypt_mfa_secret(FIXTURE_TOTP_SECRET)
    _upsert_user(ADMIN_EMAIL, ADMIN_PASSWORD, "admin", "Smoke Test Admin", enc)
    _upsert_user(PRACTITIONER_EMAIL, PRACTITIONER_PASSWORD,
                  "practitioner", "Smoke Test Practitioner", enc)


def login_smoketest_admin(base_url: str) -> str:
    """Return an access token for the admin, running through the full MFA gate.

    The `/auth/login` endpoint takes an optional `mfa_token` field — on first
    call without one, MFA-enabled accounts respond `mfa_required=True`. We
    retry with the fixture TOTP inline.
    """
    r = requests.post(f"{base_url}/auth/login", json={
        "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD,
    }, timeout=15)
    r.raise_for_status()
    body = r.json()
    if body.get("mfa_required"):
        r2 = requests.post(f"{base_url}/auth/login", json={
            "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD,
            "mfa_token": pyotp.TOTP(FIXTURE_TOTP_SECRET).now(),
        }, timeout=15)
        r2.raise_for_status()
        body = r2.json()
    tok = body.get("access_token")
    if not tok:
        raise RuntimeError(f"smoke test login produced no token: {body}")
    return tok
