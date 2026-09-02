"""GridFS → object-storage backfill (Phase 3.7).

Idempotent + resumable. Reads every blob from Mongo GridFS
(`emr_files.files` + `emr_files.chunks`) and re-uploads it to the
configured storage backend (S3 or filesystem). PostgreSQL `emr_file_meta`
rows are updated with:

  * `storage_backend`
  * `storage_key`
  * `bucket`
  * `version_id`
  * `legacy_gridfs_id`

If a row's `storage_key` is already set and the object exists in the
target backend, the row is skipped (checkpoint-safe).

Usage:
    python -m scripts.backfill_gridfs_to_storage --dry-run
    python -m scripts.backfill_gridfs_to_storage
    python -m scripts.backfill_gridfs_to_storage --limit 100 --resume

The GridFS source is NEVER deleted by this script. Drop the source
collections manually after the smoke tests are green.

No PHI is written to logs — only opaque IDs, counts, and byte sizes.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Make imports work when invoked either as a module (``python -m``) or
# directly from `/app/backend/scripts/`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket
from sqlalchemy import select, update

from postgres_db import AsyncSessionLocal
from postgres_models.crm_and_ops import FileMeta
from storage import get_storage

log = logging.getLogger("gridfs-backfill")


async def _iter_gridfs(client):
    """Yield (gridfs_doc, bytes) for every blob, streamed."""
    db = client[os.environ["DB_NAME"]]
    fs = AsyncIOMotorGridFSBucket(db, bucket_name="emr_files")
    cursor = db["emr_files.files"].find({}, no_cursor_timeout=True)
    async for doc in cursor:
        try:
            stream = await fs.open_download_stream(doc["_id"])
            data = await stream.read()
        except Exception as exc:  # noqa: BLE001
            log.warning("Skipping unreadable GridFS %s: %s", doc["_id"], exc)
            continue
        yield doc, data


async def _find_pg_row(pg, legacy_id: str):
    """Match a GridFS legacy id back to its emr_file_meta row.

    Search order:
      1. `legacy_gridfs_id == legacy_id` (already-linked row)
      2. `payload->>'gridfs_id' == legacy_id`  (pre-Phase 3.7 upload)
    """
    stmt = select(FileMeta).where(FileMeta.legacy_gridfs_id == legacy_id)
    row = (await pg.execute(stmt)).scalar_one_or_none()
    if row:
        return row
    stmt = select(FileMeta).where(
        FileMeta.payload["gridfs_id"].astext == legacy_id
    )
    return (await pg.execute(stmt)).scalar_one_or_none()


async def backfill(*, dry_run: bool, limit: Optional[int], resume: bool):
    mongo_url = os.environ.get("MONGO_URL")
    if not mongo_url:
        log.error("MONGO_URL not set — nothing to backfill from")
        return {"ok": False, "reason": "no-mongo"}

    client = AsyncIOMotorClient(mongo_url)
    try:
        source_count = await client[os.environ["DB_NAME"]]["emr_files.files"].count_documents({})
    except Exception as e:  # noqa: BLE001
        log.error("Unable to reach GridFS: %s", e)
        return {"ok": False, "reason": "mongo-unreachable"}
    log.info("GridFS source count: %d", source_count)

    storage = get_storage()
    log.info("Target backend: %s bucket=%s", storage.backend_name, storage.bucket)

    stats = {
        "source_count": source_count,
        "processed": 0, "skipped": 0, "uploaded": 0,
        "size_uploaded_bytes": 0, "orphans_no_pg_row": 0,
        "checksum_mismatch": 0, "unreadable": 0,
    }

    async for gdoc, data in _iter_gridfs(client):
        stats["processed"] += 1
        if limit and stats["processed"] > limit:
            break
        legacy_id = str(gdoc["_id"])
        checksum = (gdoc.get("metadata") or {}).get("sha256")
        if not checksum:
            checksum = hashlib.sha256(data).hexdigest()

        async with AsyncSessionLocal() as pg:
            row = await _find_pg_row(pg, legacy_id)
            if row is None:
                stats["orphans_no_pg_row"] += 1
                log.warning("orphan GridFS blob %s (no PG row)", legacy_id)
                continue

            if resume and row.storage_key:
                # Verify remote presence before skipping.
                if await storage.exists(row.storage_key):
                    stats["skipped"] += 1
                    continue

            key = f"gridfs-backfill/{legacy_id[:2]}/{legacy_id}"
            if dry_run:
                log.info("[dry-run] would upload %s -> %s (%d bytes)",
                          legacy_id, key, len(data))
                stats["uploaded"] += 1
                stats["size_uploaded_bytes"] += len(data)
                continue

            obj = await storage.put_bytes(
                key, data,
                content_type=(gdoc.get("metadata") or {}).get("mime")
                              or "application/octet-stream",
                sha256=checksum,
                metadata={"legacy_gridfs_id": legacy_id},
            )
            # Verify the round-trip checksum.
            head = await storage.head(key)
            if head.sha256 and head.sha256 != checksum:
                stats["checksum_mismatch"] += 1
                log.error("checksum mismatch for %s", legacy_id)
                # Roll back this row's assignment so a retry re-runs it.
                continue

            await pg.execute(update(FileMeta).where(FileMeta.id == row.id).values(
                storage_backend=obj.backend,
                storage_key=key,
                bucket=obj.bucket,
                version_id=obj.version_id,
                legacy_gridfs_id=legacy_id,
            ))
            await pg.commit()
            stats["uploaded"] += 1
            stats["size_uploaded_bytes"] += len(data)

    client.close()
    log.info("Backfill complete: %s", stats)
    return {"ok": True, **stats}


def _parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--resume", action="store_true",
                    help="Skip rows whose storage_key already resolves.")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def main():
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    result = asyncio.run(backfill(
        dry_run=args.dry_run, limit=args.limit, resume=args.resume,
    ))
    if not result.get("ok"):
        sys.exit(2)


if __name__ == "__main__":
    main()
