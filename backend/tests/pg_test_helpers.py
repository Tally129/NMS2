"""Test-only helpers for reading/writing PostgreSQL-resident collections.

Phase 3.1b moved `users`, `clients`, `intake_forms`, `supplement_sheets`,
`client_supplement_assignments`, and `password_reset_tokens` out of Mongo.
Test suites that historically used pymongo for these tables should route
through the helpers below.

Usage:
    from tests.pg_test_helpers import pg_users, pg_users_update

    doc = pg_users_find_one({"email": "admin@natmedsol.local"})
    pg_users_update({"email": "..."}, {"password_hash": "..."})
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text


def _sync_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL", "")
    if dsn.startswith("postgresql+psycopg://"):
        # SQLAlchemy 2.x supports psycopg (v3) natively; keep the driver.
        return dsn
    if dsn.startswith("postgresql+asyncpg://"):
        return dsn.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if dsn.startswith("postgresql://"):
        return dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    return dsn


_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_engine(_sync_dsn(), future=True)
    return _ENGINE


_USER_COLS = [
    "id", "email", "password_hash", "full_name", "phone", "role",
    "mfa_enabled", "mfa_secret", "mfa_bypass", "must_change_password",
    "is_active", "onboarding_status", "temporary_password_expires_at",
    "session_version", "auth_provider", "picture_url", "created_at",
    "last_login_at", "password_changed_at",
]


def _row_to_dict(row) -> Dict[str, Any]:
    return dict(zip(_USER_COLS, row))


def pg_users_find_one(filt: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Minimal Mongo-shape find_one over `auth_users`. Supports `email` or `id`."""
    if "email" in filt:
        where = "lower(email) = :val"
        val = filt["email"].lower()
    elif "id" in filt:
        where = "id = :val"
        val = filt["id"]
    else:
        raise ValueError("pg_users_find_one requires 'email' or 'id'")
    q = text(f"SELECT {', '.join(_USER_COLS)} FROM auth_users WHERE {where} LIMIT 1")
    with _engine().begin() as conn:
        row = conn.execute(q, {"val": val}).first()
    return _row_to_dict(row) if row else None


def pg_users_find(filt: Dict[str, Any]) -> List[Dict[str, Any]]:
    if "email_in" in filt:
        emails = [e.lower() for e in filt["email_in"]]
        q = text(
            f"SELECT {', '.join(_USER_COLS)} FROM auth_users "
            "WHERE lower(email) = ANY(:vals)"
        )
        with _engine().begin() as conn:
            return [_row_to_dict(r) for r in conn.execute(q, {"vals": emails}).all()]
    raise ValueError("pg_users_find: unsupported filter")


def pg_users_update_one(filt: Dict[str, Any], updates: Dict[str, Any]) -> int:
    """Mongo-shape update_one. Supports `email` or `id` selector."""
    if "email" in filt:
        where = "lower(email) = :sel"
        sel = filt["email"].lower()
    elif "id" in filt:
        where = "id = :sel"
        sel = filt["id"]
    else:
        raise ValueError("pg_users_update_one requires 'email' or 'id'")
    if not updates:
        return 0
    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    q = text(f"UPDATE auth_users SET {set_clause} WHERE {where}")
    params = dict(updates)
    params["sel"] = sel
    with _engine().begin() as conn:
        r = conn.execute(q, params)
    return r.rowcount or 0


def pg_users_delete(filt: Dict[str, Any]) -> int:
    if "email" in filt:
        where = "lower(email) = :sel"
        sel = filt["email"].lower()
    elif "id" in filt:
        where = "id = :sel"
        sel = filt["id"]
    else:
        raise ValueError("pg_users_delete requires 'email' or 'id'")
    q = text(f"DELETE FROM auth_users WHERE {where}")
    with _engine().begin() as conn:
        r = conn.execute(q, {"sel": sel})
    return r.rowcount or 0


def pg_users_insert(doc: Dict[str, Any]) -> None:
    """Insert a row into auth_users. Extra keys are ignored."""
    doc = {k: v for k, v in doc.items() if k in _USER_COLS}
    # NOT NULL columns with server defaults — set explicitly for driver-agnostic behaviour.
    doc.setdefault("mfa_bypass", False)
    doc.setdefault("must_change_password", False)
    doc.setdefault("session_version", 1)
    doc.setdefault("mfa_enabled", False)
    doc.setdefault("is_active", True)
    cols = list(doc.keys())
    placeholders = ", ".join(f":{c}" for c in cols)
    q = text(
        f"INSERT INTO auth_users ({', '.join(cols)}) VALUES ({placeholders})"
    )
    with _engine().begin() as conn:
        conn.execute(q, doc)


# ------------------------------------------------------------------ clients #
_CLIENT_COLS = [
    "id", "user_id", "full_name", "email", "phone", "dob", "sex",
    "assigned_practitioner_id", "primary_concern",
    "intake_completed",
    "mrn",
    "consent_marketing", "consent_photo", "consent_telehealth",
    "address", "emergency_contact", "allergies",
    "dietary_restrictions", "wellness_goals", "current_supplements",
    "tags", "legacy_mongo_id", "created_at", "updated_at",
]


def pg_clients_find_one(filt: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if "id" in filt:
        where, val = "id = :val", filt["id"]
    elif "user_id" in filt:
        where, val = "user_id = :val", filt["user_id"]
    elif "email" in filt:
        where, val = "lower(email) = :val", filt["email"].lower()
    else:
        raise ValueError("pg_clients_find_one requires id/user_id/email")
    q = text(f"SELECT {', '.join(_CLIENT_COLS)} FROM emr_clients WHERE {where} LIMIT 1")
    with _engine().begin() as conn:
        row = conn.execute(q, {"val": val}).first()
    return dict(zip(_CLIENT_COLS, row)) if row else None


def pg_clients_insert(doc: Dict[str, Any]) -> None:
    doc = {k: v for k, v in doc.items() if k in _CLIENT_COLS}
    doc.setdefault("intake_completed", False)
    cols = list(doc.keys())
    placeholders = ", ".join(f":{c}" for c in cols)
    q = text(
        f"INSERT INTO emr_clients ({', '.join(cols)}) VALUES ({placeholders})"
    )
    with _engine().begin() as conn:
        conn.execute(q, doc)
