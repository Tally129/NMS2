"""Common Storage interface.

Every backend implements the same async surface so routers depend on the
abstraction, not the concrete provider (S3, filesystem, MinIO, …).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Optional, Protocol


class StorageError(Exception):
    """Base class for storage-layer errors."""


class NotFound(StorageError):
    """Object does not exist at the given key."""


@dataclass
class ObjectMetadata:
    key: str
    size: int
    content_type: Optional[str] = None
    sha256: Optional[str] = None
    version_id: Optional[str] = None
    etag: Optional[str] = None
    backend: Optional[str] = None
    bucket: Optional[str] = None


class Storage(Protocol):
    """Storage adapter protocol.

    Implementations MUST:
    * Never block the event loop for large I/O (use `asyncio.to_thread`
      or a native async client).
    * Never log object bodies, keys containing PHI, presigned URLs,
      credentials, or access tokens.
    * Raise `NotFound` for missing objects; other failures raise
      `StorageError`.
    """

    backend_name: str
    bucket: Optional[str]

    async def put_bytes(self, key: str, data: bytes, *,
                         content_type: Optional[str] = None,
                         sha256: Optional[str] = None,
                         metadata: Optional[dict] = None) -> ObjectMetadata: ...

    async def get_bytes(self, key: str) -> bytes: ...

    async def stream(self, key: str, *, chunk_size: int = 1024 * 1024
                      ) -> AsyncIterator[bytes]: ...

    async def head(self, key: str) -> ObjectMetadata: ...

    async def exists(self, key: str) -> bool: ...

    async def delete(self, key: str) -> None: ...

    async def generate_presigned_get_url(self, key: str, *,
                                           expires_in: int = 900) -> str: ...
