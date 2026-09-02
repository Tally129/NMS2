"""Session 3.7 — smoke tests for GridFS retirement + S3 storage cutover.

Covers:
* file upload / list / download / delete via /api/files/*
* storage-backend metadata columns populated in emr_file_meta
* legacy-GridFS files (no storage_key) return 410
* streaming download works (filesystem backend)
* unauthorized access denied
* soft-delete + double-delete behavior
* MotorCompatDb raises AttributeError on unknown collection (no Mongo fallback)
* backend boots with GridFS collections dropped
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import os
import uuid

import pytest
import requests
from sqlalchemy import create_engine, text

from tests.smoketest_bootstrap import (
    ensure_smoketest_admin_and_practitioner, login_smoketest_admin,
)


BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8001") + "/api"


def _pg():
    dsn = os.environ["DATABASE_URL"]
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    return create_engine(dsn, future=True)


@pytest.fixture(scope="module")
def admin_token():
    ensure_smoketest_admin_and_practitioner()
    return login_smoketest_admin(BASE_URL)


def _b(tok):
    return {"Authorization": f"Bearer {tok}"}


def _create_client(admin_token) -> str:
    unique = uuid.uuid4().hex[:6]
    rc = requests.post(f"{BASE_URL}/clients", headers=_b(admin_token),
                        json={"full_name": f"Storage Client {unique}",
                              "email": f"storage.{unique}@natmedsol.local"})
    assert rc.status_code == 200
    return rc.json()["id"]


# ============================================ upload → download → delete
def test_upload_download_delete_roundtrip(admin_token):
    client_id = _create_client(admin_token)
    payload = b"phase 3.7 smoke: hello object storage\n" * 10
    checksum = hashlib.sha256(payload).hexdigest()

    files = {"file": ("smoke.txt", payload, "text/plain")}
    ru = requests.post(f"{BASE_URL}/files/upload", headers=_b(admin_token),
                        data={"client_id": client_id, "category": "other"},
                        files=files)
    assert ru.status_code == 200, ru.text
    body = ru.json()
    file_id = body["id"]
    assert body["sha256"] == checksum
    # clamd may not be present in the sandbox — accept `clean` or `error`.
    assert body["scan_status"] in ("clean", "error")
    scan_status = body["scan_status"]

    # PG metadata columns populated
    with _pg().begin() as conn:
        row = conn.execute(text(
            "SELECT storage_backend, storage_key, bucket, payload "
            "FROM emr_file_meta WHERE id = :i"
        ), {"i": file_id}).first()
    assert row is not None
    assert row[0] == "filesystem" or row[0] == "s3"
    assert row[1] and row[1].startswith("clients/")
    assert row[3].get("sha256") == checksum

    # Download only when scanner cleared
    if scan_status == "clean":
        rd = requests.get(f"{BASE_URL}/files/{file_id}/download",
                           headers=_b(admin_token))
        assert rd.status_code == 200
        assert rd.content == payload
        assert rd.headers.get("Content-Disposition", "").startswith("attachment;")
    else:
        # Verify the scanner-error gate returns 503, not 500.
        rd = requests.get(f"{BASE_URL}/files/{file_id}/download",
                           headers=_b(admin_token))
        assert rd.status_code == 503

    # Soft-delete
    rdel = requests.delete(f"{BASE_URL}/files/{file_id}", headers=_b(admin_token))
    assert rdel.status_code == 200

    # Second delete is idempotent
    rdel2 = requests.delete(f"{BASE_URL}/files/{file_id}", headers=_b(admin_token))
    assert rdel2.status_code == 200
    assert rdel2.json().get("already_deleted") is True


# ============================================ listing + unauthorized access
def test_files_list_and_unauthorized_access(admin_token):
    client_id = _create_client(admin_token)
    files = {"file": ("list.txt", b"x" * 1000, "text/plain")}
    ru = requests.post(f"{BASE_URL}/files/upload", headers=_b(admin_token),
                        data={"client_id": client_id, "category": "doc"},
                        files=files)
    assert ru.status_code == 200
    file_id = ru.json()["id"]

    rl = requests.get(f"{BASE_URL}/files?client_id={client_id}",
                       headers=_b(admin_token))
    assert rl.status_code == 200
    ids = [f["id"] for f in rl.json()]
    assert file_id in ids

    # No auth → 401
    r_noauth = requests.get(f"{BASE_URL}/files/{file_id}/download")
    assert r_noauth.status_code in (401, 403)


# ============================================ legacy GridFS row returns 410
def test_legacy_gridfs_only_row_returns_410(admin_token):
    """A file row with `gridfs_id` in payload but no `storage_key` column is
    a not-yet-backfilled legacy record and must 410 rather than 500."""
    async def _seed():
        from deps import db
        fid = uuid.uuid4().hex
        await db.files.insert_one({
            "id": fid, "client_id": None, "deleted_at": None,
            "filename": "legacy.pdf", "mime": "application/pdf",
            "size": 100, "sha256": "0" * 64, "category": "other",
            "uploaded_by": "smoketest", "gridfs_id": "abc123",
            "scan_status": "clean",
        })
        return fid

    fid = asyncio.run(_seed())
    r = requests.get(f"{BASE_URL}/files/{fid}/download",
                      headers=_b(admin_token))
    assert r.status_code == 410
    assert r.json()["detail"]["code"] == "storage_not_migrated"


# ============================================ no Mongo fallback
def test_unknown_collection_raises_no_mongo_fallback():
    """Unknown collection access on `db` must raise, not silently hit Mongo."""
    from deps import db
    with pytest.raises((AttributeError, KeyError)):
        _ = db.this_collection_never_existed


def test_motor_compat_no_motor_attribute():
    """The MotorCompatDb wrapper no longer holds a Motor client."""
    from deps import db
    assert not hasattr(db, "_motor"), "MotorCompatDb still binds to Motor"


# ============================================ storage adapter direct
def test_storage_adapter_direct_roundtrip():
    """Bypass the router — exercise the storage adapter directly."""
    async def _work():
        from storage import get_storage, NotFound
        storage = get_storage()
        key = f"smoke/direct/{uuid.uuid4().hex}.bin"
        payload = b"direct adapter payload"
        obj = await storage.put_bytes(key, payload, content_type="application/octet-stream")
        assert obj.size == len(payload)
        assert obj.sha256 == hashlib.sha256(payload).hexdigest()

        got = await storage.get_bytes(key)
        assert got == payload

        head = await storage.head(key)
        assert head.size == len(payload)
        assert await storage.exists(key)

        # Streaming
        chunks = []
        async for chunk in storage.stream(key, chunk_size=8):
            chunks.append(chunk)
        assert b"".join(chunks) == payload

        await storage.delete(key)
        assert not await storage.exists(key)

        try:
            await storage.get_bytes(key)
            raise AssertionError("get_bytes should raise NotFound")
        except NotFound:
            pass

    asyncio.run(_work())


# ============================================ Mongo-availability gate
def test_backend_runs_with_gridfs_unavailable():
    """Sanity: /api/health returns 200 even when GridFS collections are
    dropped (already dropped at this point in the phase)."""
    r = requests.get(f"{BASE_URL}/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
