"""Secure first-party Marketing OS event ingestion.

This route is intended for trusted server-to-server use.

The browser must never receive MARKETING_INGEST_KEY.

Safety properties:
- fails closed when the ingest secret is not configured;
- uses constant-time secret comparison;
- requires HTTPS through application middleware;
- limits request body size before JSON parsing;
- validates the entire payload against the non-PHI policy;
- supports deterministic idempotency;
- performs no advertising/provider writes;
- keeps marketing events separate from clinical records.
"""

from __future__ import annotations

import hmac
import json
import os
from datetime import datetime
from typing import Any, Optional

from fastapi import (
    Header,
    HTTPException,
    Request,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
)

from deps import api
from postgres_db import AsyncSessionLocal

from marketing_os.services.measurement import (
    MarketingDataPolicyError,
)
from marketing_os.services.persistence import (
    persist_conversion_and_attribution,
)


MAX_INGEST_BODY_BYTES = 16 * 1024


class MarketingEventPayload(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )

    event_type: str = Field(
        ...,
        min_length=1,
        max_length=64,
    )

    occurred_at: Optional[datetime] = None

    marketing_subject_id: Optional[str] = Field(
        default=None,
        max_length=128,
    )

    session_id: Optional[str] = Field(
        default=None,
        max_length=128,
    )

    external_click_id: Optional[str] = Field(
        default=None,
        max_length=255,
    )

    source: Optional[str] = Field(
        default=None,
        max_length=128,
    )

    medium: Optional[str] = Field(
        default=None,
        max_length=128,
    )

    campaign: Optional[str] = Field(
        default=None,
        max_length=255,
    )

    content: Optional[str] = Field(
        default=None,
        max_length=255,
    )

    term: Optional[str] = Field(
        default=None,
        max_length=255,
    )

    value: Optional[float] = Field(
        default=None,
        ge=0,
    )

    currency: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=3,
    )

    provider: Optional[str] = Field(
        default=None,
        max_length=64,
    )

    external_campaign_id: Optional[str] = Field(
        default=None,
        max_length=255,
    )

    properties: dict[str, Any] = Field(
        default_factory=dict,
    )


def _verify_ingest_secret(
    supplied: Optional[str],
) -> None:

    expected = os.environ.get(
        "MARKETING_INGEST_KEY",
        "",
    ).strip()

    if not expected:
        raise HTTPException(
            status_code=503,
            detail={
                "code":
                    "marketing_ingest_not_configured",

                "message":
                    "Marketing event ingestion is not configured.",
            },
        )

    supplied_value = (
        supplied or ""
    ).strip()

    if (
        not supplied_value
        or not hmac.compare_digest(
            supplied_value,
            expected,
        )
    ):
        raise HTTPException(
            status_code=401,
            detail={
                "code":
                    "invalid_marketing_ingest_key",

                "message":
                    "Marketing ingestion authentication failed.",
            },
        )


async def _read_limited_json(
    request: Request,
) -> dict[str, Any]:

    content_length = request.headers.get(
        "content-length"
    )

    if content_length:

        try:
            declared = int(
                content_length
            )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={
                    "code":
                        "invalid_content_length",
                },
            )

        if declared > MAX_INGEST_BODY_BYTES:
            raise HTTPException(
                status_code=413,
                detail={
                    "code":
                        "marketing_event_too_large",

                    "max_bytes":
                        MAX_INGEST_BODY_BYTES,
                },
            )

    body = bytearray()

    async for chunk in request.stream():

        body.extend(chunk)

        if len(body) > MAX_INGEST_BODY_BYTES:
            raise HTTPException(
                status_code=413,
                detail={
                    "code":
                        "marketing_event_too_large",

                    "max_bytes":
                        MAX_INGEST_BODY_BYTES,
                },
            )

    if not body:
        raise HTTPException(
            status_code=400,
            detail={
                "code":
                    "empty_marketing_event",
            },
        )

    try:
        parsed = json.loads(
            body.decode("utf-8")
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "code":
                    "invalid_marketing_event_json",
            },
        )

    if not isinstance(
        parsed,
        dict,
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "code":
                    "marketing_event_must_be_object",
            },
        )

    return parsed


@api.post(
    "/marketing-os/events",
    status_code=202,
)
async def ingest_marketing_event(
    request: Request,
    x_nms_marketing_ingest_key: Optional[str] = Header(
        default=None,
        alias="X-NMS-Marketing-Ingest-Key",
    ),
    idempotency_key: Optional[str] = Header(
        default=None,
        alias="Idempotency-Key",
    ),
):
    """Accept one trusted first-party non-PHI marketing event."""

    _verify_ingest_secret(
        x_nms_marketing_ingest_key
    )

    key = (
        idempotency_key or ""
    ).strip()

    if not key:
        raise HTTPException(
            status_code=400,
            detail={
                "code":
                    "missing_idempotency_key",
            },
        )

    if len(key) > 128:
        raise HTTPException(
            status_code=400,
            detail={
                "code":
                    "idempotency_key_too_long",
            },
        )

    raw = await _read_limited_json(
        request
    )

    # Policy inspection happens against the entire
    # raw payload inside the normalizer called by
    # persistence. This prevents extra prohibited
    # fields from disappearing during model parsing.

    try:
        parsed = MarketingEventPayload.model_validate(
            raw
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code":
                    "invalid_marketing_event",

                "errors":
                    exc.errors(
                        include_input=False
                    ),
            },
        )

    payload = parsed.model_dump(
        exclude={
            "occurred_at",
            "provider",
            "external_campaign_id",
        },
        exclude_none=True,
    )

    try:

        async with AsyncSessionLocal() as pg:

            async with pg.begin():

                result = await (
                    persist_conversion_and_attribution(
                        pg,
                        payload=payload,
                        idempotency_key=key,
                        occurred_at=(
                            parsed.occurred_at
                        ),
                        provider=(
                            parsed.provider
                        ),
                        external_campaign_id=(
                            parsed.external_campaign_id
                        ),
                    )
                )

    except MarketingDataPolicyError as exc:

        # Do not echo rejected values.
        raise HTTPException(
            status_code=400,
            detail={
                "code":
                    "marketing_data_policy_violation",

                "message":
                    str(exc),
            },
        )

    return {
        "accepted": True,

        "conversion_event_id":
            result[
                "conversion_event_id"
            ],

        "attribution_id":
            result[
                "attribution_id"
            ],

        "conversion_inserted":
            result[
                "conversion_inserted"
            ],

        "attribution_inserted":
            result[
                "attribution_inserted"
            ],

        "idempotent": True,

        "external_write": False,

        "phi_required": False,
    }
