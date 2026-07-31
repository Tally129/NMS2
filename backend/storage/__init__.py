"""Object-storage abstraction (Phase 3.7 GridFS retirement).

Two backends ship in-tree:

* `FilesystemStorage`  – local disk. Default in dev / test / sandbox.
* `S3Storage`          – AWS S3 with SSE-KMS. Production.

Both implement the same async interface (`Storage`). Routers must not
import boto3 directly; call the storage adapter instead.

Selecting the backend:
    STORAGE_BACKEND=filesystem   (default)
    STORAGE_BACKEND=s3
"""
from __future__ import annotations

import os

from .base import Storage, StorageError, ObjectMetadata, NotFound
from .filesystem import FilesystemStorage
from .s3 import S3Storage


_storage_singleton: Storage | None = None


def get_storage() -> Storage:
    """Return the process-wide storage adapter, lazily constructed from
    environment variables."""
    global _storage_singleton
    if _storage_singleton is not None:
        return _storage_singleton
    backend = (os.environ.get("STORAGE_BACKEND") or "filesystem").strip().lower()
    if backend == "s3":
        _storage_singleton = S3Storage.from_env()
    elif backend in ("filesystem", "fs", "local"):
        _storage_singleton = FilesystemStorage.from_env()
    else:
        raise StorageError(f"Unknown STORAGE_BACKEND={backend!r}")
    return _storage_singleton


def reset_storage_for_tests() -> None:
    """Test hook — forces `get_storage()` to re-read env on next call."""
    global _storage_singleton
    _storage_singleton = None


__all__ = [
    "Storage", "StorageError", "NotFound", "ObjectMetadata",
    "FilesystemStorage", "S3Storage",
    "get_storage", "reset_storage_for_tests",
]
