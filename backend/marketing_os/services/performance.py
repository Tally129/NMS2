"""Provider-neutral Marketing OS daily performance persistence.

This module is intentionally provider-neutral.

External integrations fetch aggregate advertising performance.
This service normalizes those aggregate metrics and persists them
into ``marketing_daily_metrics``.

Safety boundaries:

- aggregate marketing performance only;
- no patient/contact/clinical data;
- no external writes;
- no campaign creation;
- no budget changes;
- no publishing;
- deterministic metric IDs;
- idempotent campaign/day upserts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from sqlalchemy import text

from marketing_os.services.measurement import (
    assert_non_phi_marketing_payload,
)


_ALLOWED_FIELDS = frozenset(
    {
        "metric_date",
        "channel_account_id",
        "provider",
        "external_campaign_id",
        "nms_campaign_id",
        "campaign_name",
        "impressions",
        "clicks",
        "spend",
        "leads",
        "conversions",
        "conversion_value",
        "raw_metrics",
    }
)


@dataclass(frozen=True)
class NormalizedDailyPerformance:
    metric_date: date
    provider: str
    external_campaign_id: str
    channel_account_id: str | None
    nms_campaign_id: str | None
    campaign_name: str | None
    impressions: int
    clicks: int
    spend: Decimal
    leads: int
    conversions: int
    conversion_value: Decimal
    raw_metrics: dict[str, Any]


def _clean_text(
    value: Any,
    *,
    field: str,
    required: bool = False,
    max_length: int | None = None,
) -> str | None:

    if value is None:
        if required:
            raise ValueError(f"{field} is required")
        return None

    cleaned = str(value).strip()

    if not cleaned:
        if required:
            raise ValueError(f"{field} is required")
        return None

    if max_length is not None and len(cleaned) > max_length:
        raise ValueError(
            f"{field} exceeds maximum length {max_length}"
        )

    return cleaned


def _nonnegative_int(
    value: Any,
    *,
    field: str,
) -> int:

    if value is None:
        return 0

    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")

    try:
        converted = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field} must be an integer"
        ) from exc

    if converted < 0:
        raise ValueError(
            f"{field} must be nonnegative"
        )

    return converted


def _nonnegative_decimal(
    value: Any,
    *,
    field: str,
) -> Decimal:

    if value is None:
        return Decimal("0")

    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")

    try:
        converted = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(
            f"{field} must be numeric"
        ) from exc

    if not converted.is_finite():
        raise ValueError(
            f"{field} must be finite"
        )

    if converted < 0:
        raise ValueError(
            f"{field} must be nonnegative"
        )

    return converted


def _metric_date(value: Any) -> date:

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError(
                "metric_date must be YYYY-MM-DD"
            ) from exc

    raise ValueError(
        "metric_date is required and must be a date"
    )


def normalize_daily_performance(
    payload: Mapping[str, Any],
) -> NormalizedDailyPerformance:
    """Validate and normalize one campaign/day metric record."""

    if not isinstance(payload, Mapping):
        raise ValueError("performance payload must be a mapping")

    unknown = set(payload) - _ALLOWED_FIELDS

    if unknown:
        raise ValueError(
            "Unsupported performance fields: "
            + ", ".join(sorted(unknown))
        )

    # Apply the existing Marketing OS privacy boundary to both the
    # normalized envelope and provider-specific raw metrics.
    assert_non_phi_marketing_payload(dict(payload))

    raw = payload.get("raw_metrics") or {}

    if not isinstance(raw, Mapping):
        raise ValueError("raw_metrics must be a mapping")

    assert_non_phi_marketing_payload(dict(raw))

    provider = _clean_text(
        payload.get("provider"),
        field="provider",
        required=True,
        max_length=64,
    )

    assert provider is not None

    provider = provider.lower()

    external_campaign_id = _clean_text(
        payload.get("external_campaign_id"),
        field="external_campaign_id",
        required=True,
        max_length=255,
    )

    assert external_campaign_id is not None

    return NormalizedDailyPerformance(
        metric_date=_metric_date(
            payload.get("metric_date")
        ),
        provider=provider,
        external_campaign_id=external_campaign_id,
        channel_account_id=_clean_text(
            payload.get("channel_account_id"),
            field="channel_account_id",
            max_length=64,
        ),
        nms_campaign_id=_clean_text(
            payload.get("nms_campaign_id"),
            field="nms_campaign_id",
            max_length=64,
        ),
        campaign_name=_clean_text(
            payload.get("campaign_name"),
            field="campaign_name",
            max_length=255,
        ),
        impressions=_nonnegative_int(
            payload.get("impressions"),
            field="impressions",
        ),
        clicks=_nonnegative_int(
            payload.get("clicks"),
            field="clicks",
        ),
        spend=_nonnegative_decimal(
            payload.get("spend"),
            field="spend",
        ),
        leads=_nonnegative_int(
            payload.get("leads"),
            field="leads",
        ),
        conversions=_nonnegative_int(
            payload.get("conversions"),
            field="conversions",
        ),
        conversion_value=_nonnegative_decimal(
            payload.get("conversion_value"),
            field="conversion_value",
        ),
        raw_metrics=dict(raw),
    )


def daily_metric_id(
    *,
    metric_date: date,
    provider: str,
    external_campaign_id: str,
) -> str:
    """Return deterministic ID for one provider campaign/day."""

    identity = (
        f"{metric_date.isoformat()}|"
        f"{provider.strip().lower()}|"
        f"{external_campaign_id.strip()}"
    )

    return (
        "mdm_"
        + hashlib.sha256(
            identity.encode("utf-8")
        ).hexdigest()[:32]
    )


async def persist_daily_performance(
    session,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Idempotently persist one aggregate campaign/day record.

    Re-fetching the same provider campaign/day updates the existing
    aggregate row rather than creating a duplicate.
    """

    metric = normalize_daily_performance(payload)

    metric_id = daily_metric_id(
        metric_date=metric.metric_date,
        provider=metric.provider,
        external_campaign_id=metric.external_campaign_id,
    )

    result = await session.execute(
        text(
            """
            INSERT INTO marketing_daily_metrics (
                id,
                metric_date,
                channel_account_id,
                provider,
                external_campaign_id,
                nms_campaign_id,
                campaign_name,
                impressions,
                clicks,
                spend,
                leads,
                conversions,
                conversion_value,
                raw_metrics
            )
            VALUES (
                :id,
                :metric_date,
                :channel_account_id,
                :provider,
                :external_campaign_id,
                :nms_campaign_id,
                :campaign_name,
                :impressions,
                :clicks,
                :spend,
                :leads,
                :conversions,
                :conversion_value,
                CAST(:raw_metrics AS JSONB)
            )
            ON CONFLICT (
                metric_date,
                provider,
                external_campaign_id
            )
            DO UPDATE SET
                channel_account_id =
                    EXCLUDED.channel_account_id,
                nms_campaign_id =
                    EXCLUDED.nms_campaign_id,
                campaign_name =
                    EXCLUDED.campaign_name,
                impressions =
                    EXCLUDED.impressions,
                clicks =
                    EXCLUDED.clicks,
                spend =
                    EXCLUDED.spend,
                leads =
                    EXCLUDED.leads,
                conversions =
                    EXCLUDED.conversions,
                conversion_value =
                    EXCLUDED.conversion_value,
                raw_metrics =
                    EXCLUDED.raw_metrics,
                updated_at =
                    now()
            RETURNING id
            """
        ),
        {
            "id": metric_id,
            "metric_date": metric.metric_date,
            "channel_account_id":
                metric.channel_account_id,
            "provider": metric.provider,
            "external_campaign_id":
                metric.external_campaign_id,
            "nms_campaign_id":
                metric.nms_campaign_id,
            "campaign_name":
                metric.campaign_name,
            "impressions": metric.impressions,
            "clicks": metric.clicks,
            "spend": metric.spend,
            "leads": metric.leads,
            "conversions": metric.conversions,
            "conversion_value":
                metric.conversion_value,
            "raw_metrics": json.dumps(
                metric.raw_metrics,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ),
        },
    )

    returned = result.first()

    returned_id = (
        returned[0]
        if returned is not None
        else metric_id
    )

    return {
        "daily_metric_id": returned_id,
        "metric_date":
            metric.metric_date.isoformat(),
        "provider": metric.provider,
        "external_campaign_id":
            metric.external_campaign_id,
        "impressions": metric.impressions,
        "clicks": metric.clicks,
        "spend": str(metric.spend),
        "leads": metric.leads,
        "conversions": metric.conversions,
        "conversion_value":
            str(metric.conversion_value),
    }
