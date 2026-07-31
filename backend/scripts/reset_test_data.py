"""Development-environment test data reset (2026-07-31).

Wipes ALL application/test rows from PostgreSQL + MongoDB while preserving:

    * PostgreSQL schema (tables, indexes, constraints, `alembic_version`)
    * MongoDB collection existence & indexes
    * The MongoDB system-indexes for GridFS metadata (`emr_files.chunks` and
      `emr_files.files` indexes stay; documents removed)

Nothing else is preserved. The demo-seed startup path is disabled via
`DEMO_SEED_DISABLE=1` so restarting the backend does NOT re-populate.

Usage:
    python -m scripts.reset_test_data           # print before counts + wipe
    python -m scripts.reset_test_data --dry-run # print counts only
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import pymongo  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402


LOG = logging.getLogger("reset_test_data")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")


# All PG tables EXCEPT `alembic_version`. Order matters for FK constraints — we
# use TRUNCATE ... CASCADE so we can list them freely.
PG_TABLES = [
    "auth_login_attempts", "auth_password_reset_attempts", "auth_audit_logs",
    "auth_security_events", "auth_refresh_tokens", "auth_user_sessions",
    "auth_recovery_codes", "emr_legacy_password_reset_tokens",
    "emr_reminders", "emr_reminder_settings", "emr_availability",
    "emr_appointments", "emr_appointment_requests",
    "emr_intake_forms", "emr_client_supplement_assignments",
    "emr_supplement_sheets",
    "emr_clients", "auth_users",
]


def _sync_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL", "")
    if dsn.startswith("postgresql+asyncpg://"):
        return dsn.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if dsn.startswith("postgresql://"):
        return dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    return dsn


def pg_snapshot() -> Dict[str, int]:
    """Return {table: rowcount} for every reset target + alembic_version."""
    counts: Dict[str, int] = {}
    engine = create_engine(_sync_dsn(), future=True)
    with engine.begin() as conn:
        # Alembic version — should never move.
        r = conn.execute(text(
            "SELECT version_num FROM alembic_version LIMIT 1"
        )).first()
        counts["alembic_version"] = r[0] if r else None
        # Also scan every user-owned table so nothing surprises us.
        r2 = conn.execute(text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname='public' ORDER BY tablename"
        ))
        for row in r2:
            tbl = row[0]
            if tbl == "alembic_version":
                continue
            n = conn.execute(text(f'SELECT count(*) FROM "{tbl}"')).scalar_one()
            counts[tbl] = int(n)
    return counts


def pg_reset(dry_run: bool = False) -> int:
    """TRUNCATE every PG table except alembic_version. Returns rows removed."""
    engine = create_engine(_sync_dsn(), future=True)
    with engine.begin() as conn:
        r = conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'"
        ))
        tables = [row[0] for row in r if row[0] != "alembic_version"]
        if not tables:
            return 0
        LOG.info("PG tables to truncate (%d): %s", len(tables), ", ".join(sorted(tables)))
        if dry_run:
            return 0
        joined = ", ".join(f'"{t}"' for t in tables)
        conn.execute(text(f"TRUNCATE {joined} RESTART IDENTITY CASCADE"))
    return len(tables)


# --------------------------------------------------------------- MongoDB #
# Every non-system, non-view collection is wiped. Indexes and the collection
# itself remain intact.
def mongo_snapshot() -> Dict[str, int]:
    client = pymongo.MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    counts: Dict[str, int] = {}
    for name in sorted(db.list_collection_names()):
        # `.system.` collections shouldn't ever be present in the app DB but
        # skip defensively.
        if name.startswith("system."):
            continue
        counts[name] = db[name].count_documents({})
    client.close()
    return counts


def mongo_reset(dry_run: bool = False) -> Tuple[int, int]:
    """Delete every document from every non-system Mongo collection.

    GridFS handling: `emr_files.chunks` + `emr_files.files` are deleted by
    document (not by dropping) so the collections + their indexes survive.
    """
    client = pymongo.MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    total_docs = 0
    total_colls = 0
    for name in sorted(db.list_collection_names()):
        if name.startswith("system."):
            continue
        n = db[name].count_documents({})
        total_docs += n
        total_colls += 1
        LOG.info("  %-40s → deleting %d docs", name, n)
        if not dry_run and n:
            db[name].delete_many({})
    client.close()
    return total_colls, total_docs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Report counts only — no writes.")
    ap.add_argument("--out", default="/tmp/reset_test_data_snapshot.json")
    args = ap.parse_args()

    LOG.info("== BEFORE ==")
    before = {
        "postgres": pg_snapshot(),
        "mongo": mongo_snapshot(),
    }
    print(json.dumps(before, indent=2, default=str))

    LOG.info("== RESET ==")
    pg_reset(dry_run=args.dry_run)
    m_coll, m_docs = mongo_reset(dry_run=args.dry_run)
    LOG.info("Mongo: cleared %d docs across %d collections.", m_docs, m_coll)

    LOG.info("== AFTER ==")
    after = {
        "postgres": pg_snapshot(),
        "mongo": mongo_snapshot(),
    }
    print(json.dumps(after, indent=2, default=str))

    # Sanity assertion — alembic_version must be unchanged.
    assert before["postgres"]["alembic_version"] == after["postgres"]["alembic_version"], (
        "Alembic version drifted during reset — this is a defect."
    )
    with open(args.out, "w") as f:
        json.dump({"before": before, "after": after}, f, indent=2, default=str)
    LOG.info("Snapshot written to %s", args.out)


if __name__ == "__main__":
    main()
