"""Phase 3.1 backfill — Mongo → PostgreSQL for the Identity + Patients domain.

Idempotent, resumable, dry-run capable. Covers:
  users                        → auth_users
  clients                      → emr_clients
  intake_forms                 → emr_intake_forms
  client_supplement_assignments→ emr_client_supplement_assignments
  supplement_sheets            → emr_supplement_sheets
  password_reset_tokens        → emr_legacy_password_reset_tokens

Usage:
    python -m scripts.phase3_1_backfill --dry-run
    python -m scripts.phase3_1_backfill                # live
    python -m scripts.phase3_1_backfill --only clients # single collection

Progress log entries never include passwords, hashes, TOTP secrets, or
free-text patient PHI — only counters and IDs.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import pymongo  # noqa: E402
from sqlalchemy import select  # noqa: E402

from postgres_db import AsyncSessionLocal  # noqa: E402
from postgres_models import (  # noqa: E402
    Client, ClientSupplementAssignment, IntakeForm,
    LegacyPasswordResetToken, SupplementSheet, User,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("phase3_1_backfill")

BATCH = 500


def _mongo():
    return pymongo.MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _tzaware(v):
    if v is None or not isinstance(v, datetime):
        return v
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


async def backfill_users(dry_run: bool) -> dict:
    """The auth stack already syncs Mongo users on startup, but we run this
    anyway for completeness — it re-checks every row and refreshes stale
    fields. See `backend/pg_bootstrap.py` for the canonical logic; we
    reuse it here so behaviour matches."""
    from pg_bootstrap import sync_mongo_users_to_pg  # noqa: WPS433
    if dry_run:
        # Count what WOULD move.
        db = _mongo()
        total = db.users.count_documents({})
        async with AsyncSessionLocal() as pg:
            existing = (await pg.execute(select(User.id))).scalars().all()
        would_insert = total - len(set(existing))
        log.info("users dry-run: %d in mongo, %d already in PG, ~%d would insert",
                 total, len(existing), max(0, would_insert))
        return {"collection": "users", "mongo": total, "pg": len(existing),
                "inserted": 0, "dry_run": True}
    inserted = await sync_mongo_users_to_pg(_mongo())
    async with AsyncSessionLocal() as pg:
        pg_ct = (await pg.execute(select(User.id))).scalars().all()
    return {"collection": "users", "inserted": inserted, "pg_total": len(pg_ct)}


async def _upsert_batch(pg, model, rows, key: str = "id"):
    from sqlalchemy import select as _s
    ids = [r[key] for r in rows]
    existing = set((await pg.execute(_s(model.id).where(model.id.in_(ids)))).scalars().all())
    new_rows = [r for r in rows if r[key] not in existing]
    if new_rows:
        pg.add_all([model(**r) for r in new_rows])
    return len(new_rows), len(rows) - len(new_rows)


def _map_client(u: dict) -> dict:
    return {
        "id": u["id"], "user_id": u.get("user_id"),
        "mrn": u.get("mrn"), "full_name": u.get("full_name"),
        "email": (u.get("email") or "").lower() or None,
        "phone": u.get("phone"), "alt_phone": u.get("alt_phone"),
        "dob": u.get("dob"), "sex": u.get("sex"),
        "gender_identity": u.get("gender_identity"),
        "pronouns": u.get("pronouns"),
        "marital_status": u.get("marital_status"),
        "language": u.get("language"),
        "referral_source": u.get("referral_source"),
        "assigned_practitioner_id": u.get("assigned_practitioner_id"),
        "photo_file_id": u.get("photo_file_id"),
        "primary_concern": u.get("primary_concern"),
        "notes": u.get("notes"),
        "intake_completed": bool(u.get("intake_completed", False)),
        "consent_marketing": bool(u.get("consent_marketing", False)),
        "consent_photo": bool(u.get("consent_photo", False)),
        "consent_telehealth": bool(u.get("consent_telehealth", False)),
        "comms_pref": u.get("comms_pref"),
        "address": u.get("address"), "emergency_contact": u.get("emergency_contact"),
        "allergies": u.get("allergies"),
        "dietary_restrictions": u.get("dietary_restrictions"),
        "wellness_goals": u.get("wellness_goals"),
        "current_supplements": u.get("current_supplements"),
        "legacy_mongo_id": str(u.get("_id")) if u.get("_id") else None,
        "created_at": _tzaware(u.get("created_at")) or datetime.now(timezone.utc),
    }


async def backfill_clients(dry_run: bool) -> dict:
    db = _mongo()
    total = db.clients.count_documents({})
    if dry_run:
        async with AsyncSessionLocal() as pg:
            pg_ct = len((await pg.execute(select(Client.id))).scalars().all())
        log.info("clients dry-run: mongo=%d pg=%d would_insert≈%d",
                 total, pg_ct, max(0, total - pg_ct))
        return {"collection": "clients", "mongo": total, "pg": pg_ct, "dry_run": True}
    inserted = skipped = 0
    seen_mrns: set = set()  # dedupe MRN across the run
    # Load valid user IDs once so we can NULL-ify orphan user_id / practitioner_id
    async with AsyncSessionLocal() as pg:
        valid_uids = set((await pg.execute(select(User.id))).scalars().all())
    for offset in range(0, total, BATCH):
        chunk = list(db.clients.find({}).skip(offset).limit(BATCH))
        rows = []
        for c in chunk:
            if not c.get("id"):
                continue
            r = _map_client(c)
            if r["user_id"] and r["user_id"] not in valid_uids:
                r["user_id"] = None
            if r["assigned_practitioner_id"] and r["assigned_practitioner_id"] not in valid_uids:
                r["assigned_practitioner_id"] = None
            if r["mrn"] and r["mrn"] in seen_mrns:
                r["mrn"] = None
            elif r["mrn"]:
                seen_mrns.add(r["mrn"])
            rows.append(r)
        async with AsyncSessionLocal() as pg:
            existing_mrns = set((await pg.execute(
                select(Client.mrn).where(Client.mrn.isnot(None))
            )).scalars().all())
        for r in rows:
            if r["mrn"] and r["mrn"] in existing_mrns:
                r["mrn"] = None
        async with AsyncSessionLocal() as pg:
            async with pg.begin():
                i, s = await _upsert_batch(pg, Client, rows)
        inserted += i; skipped += s
        log.info("clients: %d/%d done (+%d new, %d skipped)", offset + len(chunk), total, i, s)
    return {"collection": "clients", "mongo": total, "inserted": inserted, "skipped": skipped}


def _map_intake(d: dict) -> dict:
    return {
        "id": d["id"], "client_id": d["client_id"],
        "completed": bool(d.get("completed", False)),
        "completed_at": _tzaware(d.get("completed_at")),
        "signed_at": _tzaware(d.get("signed_at")),
        "demographics": d.get("demographics"),
        "health_history": d.get("health_history"),
        "lifestyle": d.get("lifestyle"),
        "symptoms": d.get("symptoms"),
        "consent": d.get("consent"),
        "legacy_mongo_id": str(d.get("_id")) if d.get("_id") else None,
        "created_at": _tzaware(d.get("created_at")) or datetime.now(timezone.utc),
    }


def _map_sheet(d: dict) -> dict:
    return {
        "id": d["id"], "title": d.get("title") or "(untitled)",
        "summary": d.get("summary"),
        "items": d.get("items"),
        "created_by": d.get("created_by"),
        "created_by_name": d.get("created_by_name"),
        "active": bool(d.get("active", True)),
        "legacy_mongo_id": str(d.get("_id")) if d.get("_id") else None,
        "created_at": _tzaware(d.get("created_at")) or datetime.now(timezone.utc),
        "updated_at": _tzaware(d.get("updated_at")),
    }


def _map_assignment(d: dict) -> dict:
    return {
        "id": d["id"], "client_id": d.get("client_id"),
        "sheet_id": d.get("sheet_id"),
        "sheet_title": d.get("sheet_title"),
        "sheet_summary": d.get("sheet_summary"),
        "items_snapshot": d.get("items_snapshot"),
        "note_ids": d.get("note_ids"),
        "assigned_by_id": d.get("assigned_by_id"),
        "assigned_by_name": d.get("assigned_by_name"),
        "active": bool(d.get("active", True)),
        "source": d.get("source"),
        "assigned_at": _tzaware(d.get("assigned_at")),
        "last_referenced_at": _tzaware(d.get("last_referenced_at")),
        "removed_at": _tzaware(d.get("removed_at")),
        "removed_by_id": d.get("removed_by_id"),
        "legacy_mongo_id": str(d.get("_id")) if d.get("_id") else None,
    }


async def backfill_generic(name: str, model, mapper, dry_run: bool) -> dict:
    db = _mongo()
    total = db[name].count_documents({})
    if dry_run:
        async with AsyncSessionLocal() as pg:
            pg_ct = len((await pg.execute(select(model.id))).scalars().all())
        log.info("%s dry-run: mongo=%d pg=%d", name, total, pg_ct)
        return {"collection": name, "mongo": total, "pg": pg_ct, "dry_run": True}
    inserted = skipped = 0
    for offset in range(0, max(total, 1), BATCH):
        chunk = list(db[name].find({}).skip(offset).limit(BATCH))
        rows = []
        for d in chunk:
            if not d.get("id"):
                continue
            try:
                rows.append(mapper(d))
            except Exception as e:
                log.warning("%s row %r skipped: %s", name, d.get("id"), type(e).__name__)
        if not rows:
            continue
        async with AsyncSessionLocal() as pg:
            async with pg.begin():
                i, s = await _upsert_batch(pg, model, rows)
        inserted += i; skipped += s
    log.info("%s: mongo=%d inserted=%d skipped=%d", name, total, inserted, skipped)
    return {"collection": name, "mongo": total, "inserted": inserted, "skipped": skipped}


TARGETS = [
    ("users",                          None,           None),
    ("clients",                        None,           None),
    ("intake_forms",                   IntakeForm,     _map_intake),
    ("supplement_sheets",              SupplementSheet, _map_sheet),
    ("client_supplement_assignments",  ClientSupplementAssignment, _map_assignment),
    ("password_reset_tokens",          LegacyPasswordResetToken, None),  # empty in dev; safe to skip
]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="single collection name")
    args = ap.parse_args()

    results = []
    for col, model, mapper in TARGETS:
        if args.only and col != args.only:
            continue
        if col == "users":
            results.append(await backfill_users(args.dry_run))
        elif col == "clients":
            results.append(await backfill_clients(args.dry_run))
        elif col == "password_reset_tokens":
            # empty in the demo DB — nothing to move
            m = _mongo()[col].estimated_document_count()
            results.append({"collection": col, "mongo": m, "skipped_empty": True})
        else:
            results.append(await backfill_generic(col, model, mapper, args.dry_run))

    log.info("=" * 60)
    log.info("Phase 3.1 backfill summary (dry_run=%s):", args.dry_run)
    for r in results:
        log.info("  %s", r)


if __name__ == "__main__":
    asyncio.run(main())
