"""Phase 3.2 pre-flight — scan remaining Mongo collections that reference
`users` or `clients` and verify every referenced id resolves in PostgreSQL.

Produces a JSON report at /tmp/phase3_2_reconciliation.json + prints a
human-readable summary. Orphaned references are logged with counts so
downstream backfill can decide whether to null the FK or fail.

Scheduling-specific collections in scope:
    appointments.client_id, appointments.practitioner_id, appointments.created_by
    reminders.client_id
    appointment_requests (no FKs — free-text patient contact only)
    availability.practitioner_id
    reminder_settings (singleton, no FKs)

Non-scheduling collections are ALSO scanned (broader reference reconciliation
per handoff Step 1) so we know the total health before Phase 3.2 begins.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import defaultdict
from typing import Any, Dict

# Ensure backend importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from motor.motor_asyncio import AsyncIOMotorClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from postgres_db import AsyncSessionLocal  # noqa: E402
from postgres_models import Client, User  # noqa: E402


# `(collection, field, target)` — target ∈ {"user", "client"}
REFERENCE_MAP = [
    ("appointments", "client_id", "client"),
    ("appointments", "practitioner_id", "user"),
    ("appointments", "created_by", "user"),
    ("reminders", "client_id", "client"),
    ("availability", "practitioner_id", "user"),
    # Non-scheduling collections — informational, not repaired here.
    ("visit_notes", "client_id", "client"),
    ("visit_notes", "practitioner_id", "user"),
    ("files", "client_id", "client"),
    ("files", "uploaded_by", "user"),
    ("front_desk_visits", "client_id", "client"),
    ("front_desk_visits", "created_by", "user"),
    ("memberships", "client_id", "client"),
    ("invoices", "client_id", "client"),
    ("treatment_plans", "client_id", "client"),
    ("treatment_plans", "practitioner_id", "user"),
    ("transactions", "client_id", "client"),
    ("message_threads", "client_id", "client"),
    ("message_threads", "practitioner_id", "user"),
    ("messages", "sender_id", "user"),
    ("lab_values", "client_id", "client"),
    ("symptom_logs", "client_id", "client"),
    ("form_submissions", "client_id", "client"),
    ("protocol_enrollments", "client_id", "client"),
    ("protocol_enrollments", "practitioner_id", "user"),
    ("clinical_delegations", "provider_id", "user"),
    ("clinical_delegations", "delegate_id", "user"),
    ("clinical_delegations", "client_id", "client"),
    ("internal_tasks", "assignee_id", "user"),
    ("internal_tasks", "creator_id", "user"),
    ("internal_tasks", "client_id", "client"),
    ("time_entries", "user_id", "user"),
    ("push_subscriptions", "user_id", "user"),
]


async def _pg_ids(session: AsyncSession, model, id_attr) -> set:
    rows = await session.execute(select(id_attr))
    return {r[0] for r in rows}


async def main():
    mongo = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = mongo[os.environ["DB_NAME"]]

    async with AsyncSessionLocal() as pg:
        user_ids = await _pg_ids(pg, User, User.id)
        client_ids = await _pg_ids(pg, Client, Client.id)

    print(f"[pg] users={len(user_ids)}, clients={len(client_ids)}")

    report: Dict[str, Any] = {
        "pg_totals": {"users": len(user_ids), "clients": len(client_ids)},
        "collections": {},
    }
    grand_orphans = 0

    for coll, field, target in REFERENCE_MAP:
        target_set = user_ids if target == "user" else client_ids
        # Distinct values for the field
        try:
            distinct_vals = await db[coll].distinct(field)
        except Exception as e:
            report["collections"][f"{coll}.{field}"] = {"error": str(e)}
            continue
        raw = [v for v in distinct_vals if v]
        orphans = [v for v in raw if v not in target_set]
        # doc-level count for orphans
        doc_count = 0
        if orphans:
            doc_count = await db[coll].count_documents({field: {"$in": orphans}})
        grand_orphans += doc_count
        report["collections"][f"{coll}.{field}"] = {
            "target": target,
            "distinct_values": len(raw),
            "orphan_values": len(orphans),
            "orphan_docs": doc_count,
        }
        print(f"  {coll:.<35}.{field:.<25} → target={target:<7} "
              f"distinct={len(raw):<5} orphans={len(orphans):<4} docs={doc_count}")

    report["orphan_docs_total"] = grand_orphans
    out = "/tmp/phase3_2_reconciliation.json"
    with open(out, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nOK — report written to {out}")
    print(f"TOTAL orphan-referencing documents across scanned collections: {grand_orphans}")
    mongo.close()


if __name__ == "__main__":
    asyncio.run(main())
