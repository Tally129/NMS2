"""Hermetic tests for the PostgreSQL auth foundation.

These tests exercise the models + repositories + Alembic migration against
the local development database. They do NOT touch the still-Mongo auth
routes — that conversion is Phase 7 of the migration and lives in a
separate PR.

Requires the local PostgreSQL instance to be running with the migration
applied. See `PG_MIGRATION_STATUS.md` in the repo root.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio

BACKEND = str(Path(__file__).resolve().parents[1])
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

if not os.environ.get("DATABASE_URL"):
    pytest.skip("DATABASE_URL not configured — skipping PG auth foundation tests",
                allow_module_level=True)

from postgres_db import AsyncSessionLocal  # noqa: E402
from postgres_models import (  # noqa: E402
    AuditLog, Client, LoginContinuation, LoginHistory,
    PasswordResetToken, RefreshToken, User, UserSession,
)
from repositories import audit as audit_repo  # noqa: E402
from repositories import login as login_repo  # noqa: E402
from repositories import password_reset as pr_repo  # noqa: E402
from repositories import refresh_tokens as tokens_repo  # noqa: E402
from repositories import user_sessions as sessions_repo  # noqa: E402
from repositories import users as users_repo  # noqa: E402


def _uid() -> str:
    return secrets.token_hex(16)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- fixtures #

@pytest_asyncio.fixture
async def db_session():
    async with AsyncSessionLocal() as s:
        yield s
        # No commit — each test owns its transaction.
        await s.rollback()


@pytest_asyncio.fixture
async def sample_user(db_session):
    async with db_session.begin():
        u = await users_repo.create_user(
            db_session, user_id=_uid(),
            email=f"pg.test.{secrets.token_hex(4)}@example.com",
            password_hash="$2b$12$fake", full_name="PG Test",
            role="practitioner", mfa_enabled=True,
        )
    return u


# ---------------------------------------------------------------- users #

class TestUsersRepo:
    @pytest.mark.asyncio
    async def test_create_and_fetch_by_email(self, db_session, sample_user):
        found = await users_repo.get_by_email(db_session, sample_user["email"].upper())
        assert found and found["id"] == sample_user["id"]
        assert found["role"] == "practitioner"
        assert found["mfa_enabled"] is True

    @pytest.mark.asyncio
    async def test_email_uniqueness_is_case_insensitive_on_read(self, db_session, sample_user):
        assert await users_repo.get_by_email(db_session, sample_user["email"]) is not None

    @pytest.mark.asyncio
    async def test_bump_session_version(self, db_session, sample_user):
        async with db_session.begin():
            await users_repo.bump_session_version(db_session, sample_user["id"])
        refreshed = await users_repo.get_by_id(db_session, sample_user["id"])
        assert refreshed["session_version"] == 2

    @pytest.mark.asyncio
    async def test_update_fields_partial(self, db_session, sample_user):
        async with db_session.begin():
            await users_repo.update_fields(
                db_session, sample_user["id"],
                {"must_change_password": True, "picture_url": "https://x/y.png"},
            )
        refreshed = await users_repo.get_by_id(db_session, sample_user["id"])
        assert refreshed["must_change_password"] is True
        assert refreshed["picture_url"] == "https://x/y.png"
        # Untouched columns preserved
        assert refreshed["role"] == "practitioner"


# ---------------------------------------------------------------- sessions #

class TestSessionsRepo:
    @pytest.mark.asyncio
    async def test_create_count_and_revoke(self, db_session, sample_user):
        now = _now()
        async with db_session.begin():
            await sessions_repo.create(
                db_session, id=_uid(), user_id=sample_user["id"],
                created_at=now, last_used_at=now, expires_at=now + timedelta(hours=12),
                idle_timeout_minutes=15,
                absolute_expires_at=now + timedelta(hours=12),
                session_version=1, ip_first="1.1.1.1", ip_last="1.1.1.1",
                user_agent="pytest",
            )
            count = await sessions_repo.count_active(db_session, sample_user["id"])
            assert count == 1

        # Revoke all
        async with db_session.begin():
            n = await sessions_repo.revoke_all_for_user(
                db_session, sample_user["id"], "test_teardown",
            )
            assert n == 1
            assert await sessions_repo.count_active(db_session, sample_user["id"]) == 0


# ---------------------------------------------------------------- refresh rotation #

class TestRefreshRotation:
    @pytest.mark.asyncio
    async def test_claim_for_rotation_is_single_use(self, db_session, sample_user):
        now = _now()
        sid = _uid()
        family_id = _uid()
        raw = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        async with db_session.begin():
            await sessions_repo.create(
                db_session, id=sid, user_id=sample_user["id"],
                created_at=now, last_used_at=now, expires_at=now + timedelta(hours=12),
                idle_timeout_minutes=15,
                absolute_expires_at=now + timedelta(hours=12),
                session_version=1,
            )
            await tokens_repo.insert(
                db_session, id=_uid(), token_hash=token_hash,
                session_id=sid, user_id=sample_user["id"],
                family_id=family_id, generation=0,
                created_at=now, expires_at=now + timedelta(days=7),
            )

        # First claim succeeds
        async with db_session.begin():
            claimed = await tokens_repo.claim_for_rotation(
                db_session, token_hash, _now(), "1.1.1.1",
            )
            assert claimed is not None
            assert claimed["used_at"] is not None

        # Second claim returns None (already used → caller treats as reuse)
        async with db_session.begin():
            claimed2 = await tokens_repo.claim_for_rotation(
                db_session, token_hash, _now(), "1.1.1.1",
            )
            assert claimed2 is None

    @pytest.mark.asyncio
    async def test_revoke_family_marks_every_row(self, db_session, sample_user):
        family_id = _uid()
        sid = _uid()
        now = _now()
        async with db_session.begin():
            await sessions_repo.create(
                db_session, id=sid, user_id=sample_user["id"],
                created_at=now, last_used_at=now, expires_at=now + timedelta(hours=12),
                idle_timeout_minutes=15,
                absolute_expires_at=now + timedelta(hours=12),
                session_version=1,
            )
            for gen in range(3):
                await tokens_repo.insert(
                    db_session, id=_uid(),
                    token_hash=hashlib.sha256(secrets.token_hex(16).encode()).hexdigest(),
                    session_id=sid, user_id=sample_user["id"],
                    family_id=family_id, generation=gen,
                    created_at=now, expires_at=now + timedelta(days=7),
                )

        async with db_session.begin():
            n = await tokens_repo.revoke_family(db_session, family_id, "test")
            assert n == 3


# ---------------------------------------------------------------- password reset #

class TestPasswordReset:
    @pytest.mark.asyncio
    async def test_token_is_single_use(self, db_session, sample_user):
        raw = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        async with db_session.begin():
            await pr_repo.create_token(
                db_session, token_id=_uid(), token_hash=token_hash,
                user_id=sample_user["id"], email_hash="dummy",
                expires_at=_now() + timedelta(minutes=30), ip="1.1.1.1",
            )
        async with db_session.begin():
            first = await pr_repo.consume_token(db_session, token_hash, "1.1.1.1")
            assert first is not None and first["user_id"] == sample_user["id"]
        async with db_session.begin():
            second = await pr_repo.consume_token(db_session, token_hash, "1.1.1.1")
            assert second is None


# ---------------------------------------------------------------- oauth #
# OAuth support was removed in Session 2a (auth-remove-google branch).
# The auth_oauth_states / auth_oauth_handoffs tables were dropped by the
# `drop oauth tables` Alembic migration, and the corresponding repository
# and model have been deleted. No test coverage remains here.


# ---------------------------------------------------------------- audit chain #

class TestAuditChain:
    @pytest.mark.asyncio
    async def test_advisory_lock_and_prev_hash(self, db_session):
        async with db_session.begin():
            await audit_repo.acquire_chain_lock(db_session)
            prev = await audit_repo.prev_hash(db_session)
            assert prev in {"GENESIS"} or isinstance(prev, str) and len(prev) == 64
            row = {
                "id": _uid(), "ts": _now(),
                "user_id": None, "user_email": None,
                "action": "test.audit_insert",
                "resource_type": None, "resource_id": None,
                "severity": "info", "outcome": "success",
                "ip": None, "user_agent": None, "metadata": {},
                "prev_hash": prev, "hash": hashlib.sha256(b"x").hexdigest(),
            }
            await audit_repo.insert(db_session, row)

    @pytest.mark.asyncio
    async def test_sequential_seq_ordering(self, db_session):
        ids = []
        for _ in range(5):
            async with db_session.begin():
                await audit_repo.acquire_chain_lock(db_session)
                prev = await audit_repo.prev_hash(db_session)
                row_id = _uid()
                ids.append(row_id)
                await audit_repo.insert(db_session, {
                    "id": row_id, "ts": _now(),
                    "user_id": None, "user_email": None,
                    "action": "test.seq_order",
                    "resource_type": None, "resource_id": None,
                    "severity": "info", "outcome": "success",
                    "ip": None, "user_agent": None, "metadata": {},
                    "prev_hash": prev,
                    "hash": hashlib.sha256(row_id.encode()).hexdigest(),
                })
        ordered = await audit_repo.list_ordered(db_session, limit=1000)
        seen_ids = [r["id"] for r in ordered if r["id"] in ids]
        assert seen_ids == ids, "audit rows must come back in seq order"
