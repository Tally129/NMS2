"""AWS S3-backed Storage.

Enforces:
* Server-side encryption with SSE-KMS (customer-managed key).
* Private bucket — no ACLs are set.
* All blocking boto3 calls run on `asyncio.to_thread` so the event loop
  is never blocked.

Configuration (env):
    S3_BUCKET_NAME              (required)
    AWS_REGION                  (required)
    S3_KMS_KEY_ARN              (required)
    S3_PRESIGN_EXPIRES_SECONDS  (optional, default 900)
    AWS_ACCESS_KEY_ID / SECRET  (dev only; on EC2 use instance profile)
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from typing import AsyncIterator, Optional

from .base import NotFound, ObjectMetadata, Storage, StorageError

_MB = 1024 * 1024


def _lazy_boto3():
    """Import boto3 lazily so the FastAPI process only pays the import
    cost when S3 is actually selected."""
    import boto3  # noqa: WPS433
    from boto3.s3.transfer import TransferConfig  # noqa: WPS433
    from botocore.config import Config as BotoConfig  # noqa: WPS433
    from botocore.exceptions import ClientError  # noqa: WPS433
    return boto3, TransferConfig, BotoConfig, ClientError


class S3Storage:
    backend_name = "s3"

    def __init__(self, bucket: str, region: str, kms_key_arn: str, *,
                  presign_expires_seconds: int = 900,
                  aws_access_key_id: Optional[str] = None,
                  aws_secret_access_key: Optional[str] = None,
                  aws_session_token: Optional[str] = None):
        self.bucket = bucket
        self._region = region
        self._kms_key_arn = kms_key_arn
        self._presign_expires = presign_expires_seconds
        boto3, TransferConfig, BotoConfig, _ClientError = _lazy_boto3()

        self._client_error = _ClientError
        self._transfer_cfg = TransferConfig(
            multipart_threshold=64 * _MB,
            multipart_chunksize=64 * _MB,
            max_concurrency=4, use_threads=True,
        )
        cfg = BotoConfig(
            retries={"max_attempts": 5, "mode": "standard"},
            connect_timeout=5, read_timeout=60,
            signature_version="s3v4",
        )
        kwargs = {"region_name": region, "config": cfg}
        if aws_access_key_id and aws_secret_access_key:
            kwargs.update(
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                aws_session_token=aws_session_token,
            )
        self._client = boto3.client("s3", **kwargs)

    @classmethod
    def from_env(cls) -> "S3Storage":
        bucket = os.environ.get("S3_BUCKET_NAME")
        region = os.environ.get("AWS_REGION")
        kms = os.environ.get("S3_KMS_KEY_ARN")
        if not (bucket and region and kms):
            raise StorageError(
                "STORAGE_BACKEND=s3 requires S3_BUCKET_NAME, AWS_REGION, "
                "S3_KMS_KEY_ARN"
            )
        return cls(
            bucket=bucket, region=region, kms_key_arn=kms,
            presign_expires_seconds=int(os.environ.get(
                "S3_PRESIGN_EXPIRES_SECONDS", "900")),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            aws_session_token=os.environ.get("AWS_SESSION_TOKEN"),
        )

    # -------------------------------------------------- error mapping
    def _map_error(self, exc, key: str):
        code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404", "NotFound"):
            return NotFound(key)
        return StorageError(f"S3 error {code} for key")

    # ---------------------------------------------------------- writes
    async def put_bytes(self, key: str, data: bytes, *,
                          content_type: Optional[str] = None,
                          sha256: Optional[str] = None,
                          metadata: Optional[dict] = None) -> ObjectMetadata:
        checksum = sha256 or hashlib.sha256(data).hexdigest()
        extra = {
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": self._kms_key_arn,
            "ContentType": content_type or "application/octet-stream",
            "Metadata": {
                # These are sent as `x-amz-meta-*` headers. Do NOT put PHI
                # here; only opaque identifiers.
                "sha256": checksum,
                **{k: str(v) for k, v in (metadata or {}).items()},
            },
        }
        import io as _io

        def _put():
            self._client.upload_fileobj(
                _io.BytesIO(data), self.bucket, key,
                ExtraArgs=extra, Config=self._transfer_cfg,
            )
            head = self._client.head_object(Bucket=self.bucket, Key=key)
            return head

        try:
            head = await asyncio.to_thread(_put)
        except self._client_error as e:
            raise self._map_error(e, key)
        return ObjectMetadata(
            key=key, size=len(data), content_type=extra["ContentType"],
            sha256=checksum, version_id=head.get("VersionId"),
            etag=head.get("ETag"), backend=self.backend_name,
            bucket=self.bucket,
        )

    # ------------------------------------------------------------ reads
    async def get_bytes(self, key: str) -> bytes:
        def _get():
            obj = self._client.get_object(Bucket=self.bucket, Key=key)
            return obj["Body"].read()
        try:
            return await asyncio.to_thread(_get)
        except self._client_error as e:
            raise self._map_error(e, key)

    async def stream(self, key: str, *, chunk_size: int = 1024 * 1024
                      ) -> AsyncIterator[bytes]:
        def _open():
            obj = self._client.get_object(Bucket=self.bucket, Key=key)
            return obj["Body"]
        try:
            body = await asyncio.to_thread(_open)
        except self._client_error as e:
            raise self._map_error(e, key)
        try:
            while True:
                chunk = await asyncio.to_thread(body.read, chunk_size)
                if not chunk:
                    return
                yield chunk
        finally:
            await asyncio.to_thread(body.close)

    async def head(self, key: str) -> ObjectMetadata:
        def _head():
            return self._client.head_object(Bucket=self.bucket, Key=key)
        try:
            head = await asyncio.to_thread(_head)
        except self._client_error as e:
            raise self._map_error(e, key)
        md = head.get("Metadata") or {}
        return ObjectMetadata(
            key=key, size=int(head.get("ContentLength", 0)),
            content_type=head.get("ContentType"),
            sha256=md.get("sha256"),
            version_id=head.get("VersionId"),
            etag=head.get("ETag"),
            backend=self.backend_name, bucket=self.bucket,
        )

    async def exists(self, key: str) -> bool:
        try:
            await self.head(key)
            return True
        except NotFound:
            return False

    async def delete(self, key: str) -> None:
        def _del():
            self._client.delete_object(Bucket=self.bucket, Key=key)
        try:
            await asyncio.to_thread(_del)
        except self._client_error as e:
            raise self._map_error(e, key)

    async def generate_presigned_get_url(self, key: str, *,
                                           expires_in: int = 900) -> str:
        def _sign():
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        try:
            return await asyncio.to_thread(_sign)
        except self._client_error as e:
            raise self._map_error(e, key)
