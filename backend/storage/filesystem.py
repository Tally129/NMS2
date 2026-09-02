"""Filesystem-backed Storage — dev/test/sandbox default.

Objects live under `STORAGE_FS_ROOT` (default `/app/backend/data/blobs`).
Keys are used verbatim as relative paths; sanitization is applied to
prevent traversal (`../`). Metadata (content-type, sha256, extras) is
sidecar JSON stored next to the blob.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import AsyncIterator, Optional

from .base import NotFound, ObjectMetadata, Storage, StorageError


def _safe_join(root: Path, key: str) -> Path:
    # Never allow keys that resolve outside `root`.
    if not key or key.strip() != key or ".." in key.split("/"):
        raise StorageError(f"Invalid storage key: {key!r}")
    target = (root / key).resolve()
    if root not in target.parents and target != root:
        raise StorageError(f"Storage key {key!r} escapes root")
    return target


class FilesystemStorage:
    backend_name = "filesystem"
    bucket = None

    def __init__(self, root: str):
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "FilesystemStorage":
        return cls(os.environ.get("STORAGE_FS_ROOT", "/app/backend/data/blobs"))

    # ---------------------------------------------------------- writes
    async def put_bytes(self, key: str, data: bytes, *,
                          content_type: Optional[str] = None,
                          sha256: Optional[str] = None,
                          metadata: Optional[dict] = None) -> ObjectMetadata:
        checksum = sha256 or hashlib.sha256(data).hexdigest()
        target = _safe_join(self._root, key)
        sidecar = target.with_suffix(target.suffix + ".meta.json")

        def _write():
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".part")
            tmp.write_bytes(data)
            os.replace(tmp, target)
            sidecar.write_text(json.dumps({
                "content_type": content_type,
                "sha256": checksum,
                "size": len(data),
                "metadata": metadata or {},
            }))
        await asyncio.to_thread(_write)
        return ObjectMetadata(
            key=key, size=len(data), content_type=content_type,
            sha256=checksum, backend=self.backend_name,
        )

    # ------------------------------------------------------------ reads
    async def get_bytes(self, key: str) -> bytes:
        target = _safe_join(self._root, key)
        if not target.exists():
            raise NotFound(key)
        return await asyncio.to_thread(target.read_bytes)

    async def stream(self, key: str, *, chunk_size: int = 1024 * 1024
                      ) -> AsyncIterator[bytes]:
        target = _safe_join(self._root, key)
        if not target.exists():
            raise NotFound(key)

        def _open():
            return target.open("rb")
        fh = await asyncio.to_thread(_open)
        try:
            while True:
                chunk = await asyncio.to_thread(fh.read, chunk_size)
                if not chunk:
                    return
                yield chunk
        finally:
            await asyncio.to_thread(fh.close)

    async def head(self, key: str) -> ObjectMetadata:
        target = _safe_join(self._root, key)
        if not target.exists():
            raise NotFound(key)
        size = await asyncio.to_thread(lambda: target.stat().st_size)
        sidecar = target.with_suffix(target.suffix + ".meta.json")
        ct = None
        checksum = None
        if sidecar.exists():
            try:
                meta = json.loads(sidecar.read_text())
                ct = meta.get("content_type")
                checksum = meta.get("sha256")
            except Exception:
                pass
        return ObjectMetadata(
            key=key, size=size, content_type=ct, sha256=checksum,
            backend=self.backend_name,
        )

    async def exists(self, key: str) -> bool:
        target = _safe_join(self._root, key)
        return await asyncio.to_thread(target.exists)

    async def delete(self, key: str) -> None:
        target = _safe_join(self._root, key)
        sidecar = target.with_suffix(target.suffix + ".meta.json")

        def _rm():
            if target.exists():
                target.unlink()
            if sidecar.exists():
                sidecar.unlink()
        await asyncio.to_thread(_rm)

    async def generate_presigned_get_url(self, key: str, *,
                                           expires_in: int = 900) -> str:
        # No true presign for local FS — return the internal streaming
        # download URL the app already exposes.
        return f"/api/files/local/{key}?expires_in={expires_in}"

    # ------------------------------------------- test / backfill helpers
    def reset_for_tests(self) -> None:  # pragma: no cover
        if self._root.exists():
            shutil.rmtree(self._root)
        self._root.mkdir(parents=True, exist_ok=True)
