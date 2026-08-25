"""Transactional Marketing OS persistence.

This module persists only validated non-PHI marketing data.

Important:
- no transaction is committed here;
- caller owns the transaction boundary;
- IDs are deterministic for idempotency;
- repeated calls with the same idempotency key do not
  create duplicate conversion or attribution records;
- no external marketing API calls occur here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from marketing_os.services.measurement import (
    MarketingDataPolicyError,
    last_touch_attribution,
    normalize_conversion_payload,
)


def _stable_id(
    prefix: str,
    key: str,
) -> str:

    clean = str(key).strip()

    if not clean:
        raise MarketingDataPolicyError(
            "idempotency_key is required"
        )

    digest = hashlib.sha256(
        clean.encode("utf-8")
    ).hexdigest()[:40]

    return f"{prefix}_{digest}"


def conversion_event_id(
    idempotency_key: str,
) -> str:
    return _stable_id(
        "mconv",
        idempotency_key,
    )


def attribution_id(
    *,
    conversion_id: str,
    model: str,
    provider: str | None,
    external_campaign_id: str | None,
    nms_campaign_id: str | None,
) -> str:

    identity = "|".join(
        [
            conversion_id,
            model or "",
            provider or "",
            external_campaign_id or "",
            nms_campaign_id or "",
        ]
    )

    return _stable_id(
        "mattr",
        identity,
    )


def _database_timestamp(
    value: datetime | None,
) -> datetime:

    if value is None:
        value = datetime.now(
            timezone.utc
        )

    if value.tzinfo is not None:
        value = value.astimezone(
            timezone.utc
        ).replace(
            tzinfo=None
        )

    return value


async def persist_conversion_and_attribution(
    session: AsyncSession,
    *,
    payload: Mapping[str, Any],
    idempotency_key: str,
    occurred_at: datetime | None = None,
    provider: str | None = None,
    external_campaign_id: str | None = None,
    nms_campaign_id: str | None = None,
) -> dict[str, Any]:
    """Persist one conversion plus deterministic attribution.

    Caller must create/commit/rollback the transaction.

    This function intentionally does NOT call commit().
    """

    conversion = normalize_conversion_payload(
        payload
    )

    event_id = conversion_event_id(
        idempotency_key
    )

    timestamp = _database_timestamp(
        occurred_at
    )

    event_result = await session.execute(
        text(
            """
            INSERT INTO marketing_conversion_events (
                id,
                event_type,
                occurred_at,
                marketing_subject_id,
                session_id,
                external_click_id,
                source,
                medium,
                campaign,
                content,
                term,
                value,
                currency,
                properties
            )
            VALUES (
                :id,
                :event_type,
                :occurred_at,
                :marketing_subject_id,
                :session_id,
                :external_click_id,
                :source,
                :medium,
                :campaign,
                :content,
                :term,
                :value,
                :currency,
                CAST(:properties AS jsonb)
            )
            ON CONFLICT (id)
            DO NOTHING
            RETURNING id
            """
        ),
        {
            "id": event_id,
            "event_type":
                conversion.event_type,
            "occurred_at":
                timestamp,
            "marketing_subject_id":
                conversion.marketing_subject_id,
            "session_id":
                conversion.session_id,
            "external_click_id":
                conversion.external_click_id,
            "source":
                conversion.source,
            "medium":
                conversion.medium,
            "campaign":
                conversion.campaign,
            "content":
                conversion.content,
            "term":
                conversion.term,
            "value":
                conversion.value,
            "currency":
                conversion.currency,
            "properties":
                json.dumps(
                    conversion.properties
                ),
        },
    )

    event_inserted = (
        event_result.first()
        is not None
    )

    attribution = last_touch_attribution(
        conversion,
        provider=provider,
        external_campaign_id=(
            external_campaign_id
        ),
    )

    attr_id = attribution_id(
        conversion_id=event_id,
        model=attribution.model,
        provider=provider,
        external_campaign_id=(
            external_campaign_id
        ),
        nms_campaign_id=nms_campaign_id,
    )

    attribution_result = await session.execute(
        text(
            """
            INSERT INTO marketing_attributions (
                id,
                conversion_event_id,
                model,
                provider,
                external_campaign_id,
                nms_campaign_id,
                source,
                medium,
                credit,
                attributed_value,
                reason,
                details
            )
            VALUES (
                :id,
                :conversion_event_id,
                :model,
                :provider,
                :external_campaign_id,
                :nms_campaign_id,
                :source,
                :medium,
                :credit,
                :attributed_value,
                :reason,
                CAST(:details AS jsonb)
            )
            ON CONFLICT (id)
            DO NOTHING
            RETURNING id
            """
        ),
        {
            "id":
                attr_id,

            "conversion_event_id":
                event_id,

            "model":
                attribution.model,

            "provider":
                attribution.provider,

            "external_campaign_id":
                attribution.external_campaign_id,

            "nms_campaign_id":
                nms_campaign_id,

            "source":
                attribution.source,

            "medium":
                attribution.medium,

            "credit":
                attribution.credit,

            "attributed_value":
                attribution.attributed_value,

            "reason":
                attribution.reason,

            "details":
                json.dumps(
                    {
                        "idempotency":
                            "deterministic_id",

                        "external_write":
                            False,

                        "phi_required":
                            False,
                    }
                ),
        },
    )

    attribution_inserted = (
        attribution_result.first()
        is not None
    )

    return {
        "conversion_event_id":
            event_id,

        "attribution_id":
            attr_id,

        "conversion_inserted":
            event_inserted,

        "attribution_inserted":
            attribution_inserted,

        "idempotent":
            True,

        "external_write":
            False,

        "phi_required":
            False,
    }
