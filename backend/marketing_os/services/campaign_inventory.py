"""Provider-neutral Marketing OS campaign inventory.

Campaign inventory is derived only from locally persisted,
aggregate ``marketing_daily_metrics`` rows.

Safety boundaries:
- no provider API calls;
- no credentials;
- no external writes;
- no campaign creation;
- no budget changes;
- no publishing;
- no PHI;
- deterministic provider/campaign identities only.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text


CAMPAIGN_INVENTORY_SQL = """
    SELECT
        provider,
        external_campaign_id,
        nms_campaign_id,
        campaign_name,
        MIN(metric_date) AS first_seen,
        MAX(metric_date) AS last_seen,
        COUNT(*) AS metric_days,
        COALESCE(
            SUM(spend),
            0
        ) AS recorded_spend
    FROM marketing_daily_metrics
    WHERE external_campaign_id IS NOT NULL
      AND BTRIM(external_campaign_id) <> ''
      AND provider IS NOT NULL
      AND BTRIM(provider) <> ''
    GROUP BY
        provider,
        external_campaign_id,
        nms_campaign_id,
        campaign_name
    ORDER BY
        provider,
        campaign_name NULLS LAST,
        external_campaign_id
"""


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, (date, datetime)):
        return value.isoformat()

    return value


def serialize_campaign_inventory_row(
    row: Any,
) -> dict[str, Any]:
    """Normalize one SQL result to the API contract."""

    if hasattr(row, "_mapping"):
        raw = dict(row._mapping)
    else:
        raw = dict(row)

    provider = str(
        raw.get("provider")
        or ""
    ).strip().lower()

    external_campaign_id = str(
        raw.get("external_campaign_id")
        or ""
    ).strip()

    if not provider:
        raise ValueError(
            "campaign inventory provider is required"
        )

    if not external_campaign_id:
        raise ValueError(
            "campaign inventory external_campaign_id "
            "is required"
        )

    nms_campaign_id = raw.get(
        "nms_campaign_id"
    )

    if nms_campaign_id is not None:
        nms_campaign_id = (
            str(nms_campaign_id).strip()
            or None
        )

    campaign_name = raw.get(
        "campaign_name"
    )

    if campaign_name is not None:
        campaign_name = (
            str(campaign_name).strip()
            or None
        )

    return {
        "provider":
            provider,
        "external_campaign_id":
            external_campaign_id,
        "nms_campaign_id":
            nms_campaign_id,
        "campaign_name":
            campaign_name,
        "first_seen":
            _json_value(
                raw.get("first_seen")
            ),
        "last_seen":
            _json_value(
                raw.get("last_seen")
            ),
        "metric_days":
            int(
                raw.get("metric_days")
                or 0
            ),
        "recorded_spend":
            float(
                raw.get("recorded_spend")
                or 0
            ),
    }


async def list_campaign_inventory(
    session,
) -> list[dict[str, Any]]:
    """Return locally observed campaign identities."""

    result = await session.execute(
        text(CAMPAIGN_INVENTORY_SQL)
    )

    return [
        serialize_campaign_inventory_row(
            row
        )
        for row in result
    ]
