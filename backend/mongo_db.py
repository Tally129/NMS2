"""MongoDB client + GridFS bucket handle for non-auth routers.

Session 2b of the auth-stack cutover moved every auth persistence path onto
PostgreSQL. This module is what remains of the Mongo dependency — it now
lives OUTSIDE the auth runtime (audit.py, sessions.py, deps.py's auth
functions, routers/auth_impl/*), and is imported only by the non-auth
business routers (clients, notes, files, appointments, POS, …).

`deps.py` re-exports `db` and `fs_bucket` for backward compatibility so no
non-auth router has to change its imports.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket

load_dotenv(Path(__file__).resolve().parent / ".env")

_mongo_url = os.environ["MONGO_URL"]
_client = AsyncIOMotorClient(_mongo_url)

db = _client[os.environ["DB_NAME"]]
fs_bucket = AsyncIOMotorGridFSBucket(db, bucket_name="emr_files")


def close_mongo() -> None:
    _client.close()
