"""Phase 3.2 backfill — Mongo → PostgreSQL for the Scheduling domain.

Idempotent, resumable, dry-run capable. Covers:

    appointments             → emr_appointments
    appointment_requests     → emr_appointment_requests
    availability             → emr_availability
    reminders                → emr_reminders
    reminder_settings        → emr_reminder_settings

Foreign keys to `auth_users` / `emr_clients` are resolved once at start
into memory. Rows referencing missing ids are still inserted — the FK
column is set to NULL and the original id is preserved in the paired
`legacy_*` column for reconciliation.

Usage:
    python -m scripts.phase3_2_backfill --dry-run
    python -m scripts.phase3_2_backfill               # live
    python -m scripts.phase3_2_backfill --only appointments
    python -m scripts.phase3_2_backfill --batch 500
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import pymongo  # noqa: E402
from sqlalchemy import select  # noqa: E402

from postgres_db import AsyncSessionLocal  # noqa: E402
from postgres_models import (  # noqa: E402
    Appointment, AppointmentRequest, Availability, Client, Reminder,
    ReminderSettings, User,
)


LOG = logging.getLogger("phase3_2_backfill")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _json_safe(v):
    """Recursively coerce datetimes / ObjectIds inside JSONB blobs to strings."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): _json_safe(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_json_safe(x) for x in v]
    if isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


COLLECTIONS = ("appointments", "appointment_requests", "availability",
               "reminders", "reminder_settings")


async def _existing_ids(model) -> Set[str]:
    async with AsyncSessionLocal() as s:
        rows = await s.execute(select(model.id))
        return {r[0] for r in rows}


async def _load_fk_ids() -> tuple[Set[str], Set[str]]:
    async with AsyncSessionLocal() as s:
        users = {r[0] for r in (await s.execute(select(User.id))).all()}
        clients = {r[0] for r in (await s.execute(select(Client.id))).all()}
    LOG.info("FK reference sets loaded — users=%d clients=%d",
             len(users), len(clients))
    return users, clients


def _mongo_db():
    client = pymongo.MongoClient(os.environ["MONGO_URL"])
    return client[os.environ["DB_NAME"]], client


# ---------------------------------------------------------- per-collection #
async def backfill_appointments(*, batch: int, dry_run: bool,
                                  user_ids: Set[str], client_ids: Set[str]) -> Dict[str, int]:
    seen = await _existing_ids(Appointment)
    counters = {"total": 0, "inserted": 0, "skipped_dup": 0,
                "orphan_client": 0, "orphan_practitioner": 0, "orphan_created_by": 0}
    db, mc = _mongo_db()
    cur = db.appointments.find({}, no_cursor_timeout=True).batch_size(batch)
    buffer: List[Appointment] = []
    try:
        for doc in cur:
            counters["total"] += 1
            _id = doc.get("id") or str(doc.get("_id"))
            if _id in seen:
                counters["skipped_dup"] += 1
                continue

            legacy_client = doc.get("client_id")
            legacy_prac = doc.get("practitioner_id")
            legacy_cb = doc.get("created_by")

            client_ok = legacy_client in client_ids if legacy_client else False
            prac_ok = legacy_prac in user_ids if legacy_prac else False
            cb_ok = legacy_cb in user_ids if legacy_cb else False
            if legacy_client and not client_ok:
                counters["orphan_client"] += 1
            if legacy_prac and not prac_ok:
                counters["orphan_practitioner"] += 1
            if legacy_cb and not cb_ok:
                counters["orphan_created_by"] += 1

            appt = Appointment(
                id=_id,
                client_id=legacy_client if client_ok else None,
                practitioner_id=legacy_prac if prac_ok else None,
                created_by=legacy_cb if cb_ok else None,
                service=doc.get("service"),
                status=doc.get("status") or "confirmed",
                visit_mode=doc.get("visit_mode") or "in_person",
                consent_telehealth=bool(doc.get("consent_telehealth")),
                start=doc.get("start"),
                end=doc.get("end") or doc.get("start"),
                notes=doc.get("notes"),
                series_id=doc.get("series_id"),
                series_pattern=doc.get("series_pattern"),
                telehealth=_json_safe(doc.get("telehealth")) or None,
                waiting_room=_json_safe(doc.get("waiting_room")) or None,
                recordings=_json_safe(doc.get("recordings")) or None,
                transaction_id=doc.get("transaction_id"),
                reminder_sent_at=doc.get("reminder_sent_at"),
                legacy_mongo_id=doc.get("id"),
                legacy_client_id=legacy_client,
                legacy_practitioner_id=legacy_prac,
                legacy_created_by=legacy_cb,
                created_at=doc.get("created_at") or datetime.now(timezone.utc),
                updated_at=doc.get("updated_at") or datetime.now(timezone.utc),
            )
            buffer.append(appt)
            seen.add(_id)
            if len(buffer) >= batch:
                counters["inserted"] += await _flush(buffer, dry_run)
                buffer.clear()
        if buffer:
            counters["inserted"] += await _flush(buffer, dry_run)
    finally:
        cur.close(); mc.close()
    return counters


async def _flush(rows: List[Any], dry_run: bool) -> int:
    if dry_run:
        return len(rows)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            s.add_all(rows)
    return len(rows)


async def backfill_requests(*, batch: int, dry_run: bool,
                              user_ids: Set[str]) -> Dict[str, int]:
    seen = await _existing_ids(AppointmentRequest)
    counters = {"total": 0, "inserted": 0, "skipped_dup": 0,
                "orphan_reviewed_by": 0}
    db, mc = _mongo_db()
    cur = db.appointment_requests.find({}, no_cursor_timeout=True).batch_size(batch)
    buf: List[AppointmentRequest] = []
    try:
        for doc in cur:
            counters["total"] += 1
            _id = doc.get("id") or str(doc.get("_id"))
            if _id in seen:
                counters["skipped_dup"] += 1
                continue
            reviewed_by = doc.get("reviewed_by")
            rev_ok = reviewed_by in user_ids if reviewed_by else False
            if reviewed_by and not rev_ok:
                counters["orphan_reviewed_by"] += 1
            buf.append(AppointmentRequest(
                id=_id,
                full_name=doc.get("fullName") or doc.get("full_name") or "(unknown)",
                email=doc.get("email"),
                phone=doc.get("phone"),
                returning=doc.get("returning"),
                service=doc.get("service"),
                date=doc.get("date"),
                time=doc.get("time"),
                notes=doc.get("notes"),
                add_ons=doc.get("addOns") or doc.get("add_ons") or [],
                status=doc.get("status") or "new",
                decline_reason=doc.get("decline_reason"),
                suggested_time=doc.get("suggested_time"),
                reviewed_by=reviewed_by if rev_ok else None,
                reviewed_at=doc.get("reviewed_at"),
                ip=doc.get("ip"),
                legacy_mongo_id=doc.get("id"),
                created_at=doc.get("created_at") or datetime.now(timezone.utc),
            ))
            seen.add(_id)
            if len(buf) >= batch:
                counters["inserted"] += await _flush(buf, dry_run)
                buf.clear()
        if buf:
            counters["inserted"] += await _flush(buf, dry_run)
    finally:
        cur.close(); mc.close()
    return counters


async def backfill_availability(*, batch: int, dry_run: bool,
                                  user_ids: Set[str]) -> Dict[str, int]:
    seen = await _existing_ids(Availability)
    counters = {"total": 0, "inserted": 0, "skipped_dup": 0, "orphan_prac": 0}
    db, mc = _mongo_db()
    cur = db.availability.find({}).batch_size(batch)
    buf: List[Availability] = []
    try:
        for doc in cur:
            counters["total"] += 1
            _id = doc.get("id") or str(doc.get("_id"))
            if _id in seen:
                counters["skipped_dup"] += 1
                continue
            prac = doc.get("practitioner_id")
            prac_ok = prac in user_ids if prac else False
            if prac and not prac_ok:
                counters["orphan_prac"] += 1
            buf.append(Availability(
                id=_id, practitioner_id=prac if prac_ok else None,
                weekday=int(doc.get("weekday") or 0),
                start_time=str(doc.get("start_time") or "09:00"),
                end_time=str(doc.get("end_time") or "17:00"),
                active=bool(doc.get("active", True)),
                legacy_mongo_id=doc.get("id"),
                legacy_practitioner_id=prac,
                created_at=doc.get("created_at") or datetime.now(timezone.utc),
            ))
            seen.add(_id)
            if len(buf) >= batch:
                counters["inserted"] += await _flush(buf, dry_run)
                buf.clear()
        if buf:
            counters["inserted"] += await _flush(buf, dry_run)
    finally:
        cur.close(); mc.close()
    return counters


async def backfill_reminders(*, batch: int, dry_run: bool,
                               appt_ids: Set[str],
                               client_ids: Set[str]) -> Dict[str, int]:
    seen = await _existing_ids(Reminder)
    counters = {"total": 0, "inserted": 0, "skipped_dup": 0,
                "orphan_appt": 0, "orphan_client": 0}
    db, mc = _mongo_db()
    cur = db.reminders.find({}).batch_size(batch)
    buf: List[Reminder] = []
    try:
        for doc in cur:
            counters["total"] += 1
            _id = doc.get("id") or str(doc.get("_id"))
            if _id in seen:
                counters["skipped_dup"] += 1
                continue
            appt = doc.get("appointment_id")
            client = doc.get("client_id")
            appt_ok = appt in appt_ids if appt else False
            client_ok = client in client_ids if client else False
            if appt and not appt_ok:
                counters["orphan_appt"] += 1
            if client and not client_ok:
                counters["orphan_client"] += 1
            buf.append(Reminder(
                id=_id,
                appointment_id=appt if appt_ok else None,
                client_id=client if client_ok else None,
                channel=doc.get("channel") or "email",
                scheduled_at=doc.get("scheduled_at") or datetime.now(timezone.utc),
                sent_at=doc.get("sent_at"),
                status=doc.get("status") or "scheduled",
                legacy_mongo_id=doc.get("id"),
                legacy_appointment_id=appt,
                legacy_client_id=client,
                created_at=doc.get("created_at") or datetime.now(timezone.utc),
            ))
            seen.add(_id)
            if len(buf) >= batch:
                counters["inserted"] += await _flush(buf, dry_run)
                buf.clear()
        if buf:
            counters["inserted"] += await _flush(buf, dry_run)
    finally:
        cur.close(); mc.close()
    return counters


async def backfill_reminder_settings(*, dry_run: bool) -> Dict[str, int]:
    """Mongo `reminder_settings` is a single doc keyed by id=singleton."""
    counters = {"total": 0, "inserted": 0, "skipped_dup": 0}
    db, mc = _mongo_db()
    try:
        docs = list(db.reminder_settings.find({}).limit(2))
        counters["total"] = len(docs)
        if not docs:
            return counters
        doc = docs[0]
        async with AsyncSessionLocal() as s:
            existing = (await s.execute(
                select(ReminderSettings)
                .where(ReminderSettings.id == "singleton")
            )).scalar_one_or_none()
            if existing:
                counters["skipped_dup"] = 1
                return counters
            if dry_run:
                counters["inserted"] = 1
                return counters
            async with s.begin():
                s.add(ReminderSettings(
                    id="singleton",
                    appointment_reminder_hours_before=int(
                        doc.get("appointment_reminder_hours_before") or 24),
                    appointment_reminder_channels=doc.get(
                        "appointment_reminder_channels") or ["email"],
                    follow_up_days_after=int(
                        doc.get("follow_up_days_after") or 7),
                    enabled=bool(doc.get("enabled", True)),
                ))
            counters["inserted"] = 1
    finally:
        mc.close()
    return counters


# ------------------------------------------------------------------- main #
async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                    help="Report what would happen — no writes.")
    p.add_argument("--only", choices=COLLECTIONS,
                    help="Backfill only the specified collection.")
    p.add_argument("--batch", type=int, default=500)
    args = p.parse_args()

    LOG.info("Phase 3.2 backfill start (dry_run=%s, only=%s, batch=%d)",
             args.dry_run, args.only, args.batch)
    user_ids, client_ids = await _load_fk_ids()

    to_run = [args.only] if args.only else list(COLLECTIONS)
    results: Dict[str, Dict[str, int]] = {}

    for coll in to_run:
        if coll == "appointments":
            results[coll] = await backfill_appointments(
                batch=args.batch, dry_run=args.dry_run,
                user_ids=user_ids, client_ids=client_ids)
        elif coll == "appointment_requests":
            results[coll] = await backfill_requests(
                batch=args.batch, dry_run=args.dry_run, user_ids=user_ids)
        elif coll == "availability":
            results[coll] = await backfill_availability(
                batch=args.batch, dry_run=args.dry_run, user_ids=user_ids)
        elif coll == "reminders":
            appt_ids = await _existing_ids(Appointment)
            results[coll] = await backfill_reminders(
                batch=args.batch, dry_run=args.dry_run,
                appt_ids=appt_ids, client_ids=client_ids)
        elif coll == "reminder_settings":
            results[coll] = await backfill_reminder_settings(dry_run=args.dry_run)

    for coll, counts in results.items():
        LOG.info("  %-25s → %s", coll, counts)
    LOG.info("Phase 3.2 backfill complete.")


if __name__ == "__main__":
    asyncio.run(main())
