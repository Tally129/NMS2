"""
Website marketing-content export service.

S3 is the canonical handoff store for content approved for website export.
This module handles marketing content only. PHI must never be supplied here.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import boto3


DEFAULT_BUCKET = (
    "nms-marketing-content-186072212039-us-east-1"
)

BUCKET = os.environ.get(
    "NMS_MARKETING_CONTENT_BUCKET",
    DEFAULT_BUCKET,
)

REGION = os.environ.get(
    "AWS_REGION",
    os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
)

PREFIX = os.environ.get(
    "NMS_MARKETING_CONTENT_PREFIX",
    "content",
).strip("/")

PRESIGN_TTL_SECONDS = int(
    os.environ.get(
        "NMS_MARKETING_PRESIGN_TTL_SECONDS",
        "3600",
    )
)

WEBSITE_INTAKE_URL = os.environ.get(
    "NMS_MARKETING_WEBSITE_INTAKE_URL",
    "",
).strip()

WEBHOOK_SECRET = os.environ.get(
    "NMS_MARKETING_WEBHOOK_SECRET",
    "",
).strip()


def _s3():
    return boto3.client(
        "s3",
        region_name=REGION,
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sign_body(
    body: bytes,
    secret: Optional[str] = None,
) -> str:
    signing_secret = secret or WEBHOOK_SECRET

    if not signing_secret:
        raise RuntimeError(
            "marketing_webhook_secret_missing"
        )

    digest = hmac.new(
        signing_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    return f"sha256={digest}"


def _safe_segment(value: str) -> str:
    cleaned = "".join(
        char
        if char.isalnum() or char in "-_"
        else "-"
        for char in str(value or "")
    )

    cleaned = cleaned.strip("-_")

    return cleaned[:120] or str(uuid.uuid4())


def build_batch_id() -> str:
    now = _utcnow()

    return (
        f"{now:%Y-%m}-"
        f"{uuid.uuid4().hex[:12]}"
    )


def build_content_key(
    batch_id: str,
    item_id: str,
) -> str:
    return (
        f"{PREFIX}/"
        f"{_safe_segment(batch_id)}/"
        f"items/"
        f"{_safe_segment(item_id)}.json"
    )


def build_manifest_key(
    batch_id: str,
) -> str:
    return (
        f"{PREFIX}/"
        f"{_safe_segment(batch_id)}/"
        "manifest.json"
    )


async def put_json(
    key: str,
    value: Dict[str, Any],
) -> Dict[str, Any]:
    body = _json_bytes(value)
    digest = sha256_hex(body)

    def _put():
        return _s3().put_object(
            Bucket=BUCKET,
            Key=key,
            Body=body,
            ContentType="application/json",
            Metadata={
                "sha256": digest,
                "content-class": "marketing",
            },
        )

    response = await asyncio.to_thread(_put)

    return {
        "bucket": BUCKET,
        "key": key,
        "sha256": digest,
        "size": len(body),
        "etag": str(
            response.get("ETag") or ""
        ).strip('"'),
    }


async def presign_get(
    key: str,
    *,
    ttl_seconds: int = PRESIGN_TTL_SECONDS,
) -> str:
    if ttl_seconds < 900:
        raise RuntimeError(
            "marketing_presign_ttl_too_short"
        )

    def _presign():
        return _s3().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": BUCKET,
                "Key": key,
            },
            ExpiresIn=ttl_seconds,
        )

    return await asyncio.to_thread(_presign)


async def write_content_item(
    *,
    batch_id: str,
    item: Dict[str, Any],
) -> Dict[str, Any]:
    item_id = str(
        item.get("id") or uuid.uuid4()
    )

    payload = dict(item)
    payload["id"] = item_id
    payload["batch_id"] = batch_id
    payload["exported_at"] = (
        _utcnow().isoformat()
    )
    payload["human_review_required"] = True

    key = build_content_key(
        batch_id,
        item_id,
    )

    stored = await put_json(
        key,
        payload,
    )

    url = await presign_get(key)

    return {
        "id": item_id,
        "type": str(
            item.get("type")
            or item.get("content_type")
            or ""
        ),
        "title": str(item.get("title") or ""),
        "slug": str(
            item.get("slug")
            or (
                item.get("metadata")
                or {}
            ).get("slug")
            or ""
        ),
        "content_url": url,
        "content_sha256": stored["sha256"],
        "content_type": "application/json",
        "assets": [],
    }


async def write_manifest(
    *,
    batch_id: str,
    items: List[Dict[str, Any]],
    delivery_id: Optional[str] = None,
) -> Dict[str, Any]:
    delivery_id = (
        delivery_id or str(uuid.uuid4())
    )

    manifest = {
        "spec_version": "1.0",
        "delivery_id": delivery_id,
        "sent_at": _utcnow().isoformat(),
        "batch_id": batch_id,
        "items": items,
    }

    key = build_manifest_key(batch_id)

    stored = await put_json(
        key,
        manifest,
    )

    return {
        "manifest": manifest,
        "storage": stored,
    }
