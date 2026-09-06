"""Cached SEO-provider intelligence reads.

This module reads previously persisted SEO intelligence from PostgreSQL.

Important boundaries:
- caller supplies the database session
- caller owns session/transaction lifecycle
- SELECT statements only
- no provider adapter
- no DataForSEO/API/network call
- no scheduler
- no refresh side effect
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text


DEFAULT_PROVIDER = "dataforseo"
DEFAULT_LOCATION = "United States"
DEFAULT_LANGUAGE = "English"
DEFAULT_DEVICE = "desktop"

MAX_PAGE_SIZE = 500
DEFAULT_PAGE_SIZE = 100


def _serialize_row(row) -> dict[str, Any]:
    """Serialize one SQLAlchemy row into JSON-safe primitive values."""

    data = dict(row._mapping)

    for key, value in list(data.items()):
        if isinstance(value, Decimal):
            data[key] = float(value)
        elif isinstance(value, (date, datetime)):
            data[key] = value.isoformat()

    return data


def _serialize_rows(rows) -> list[dict[str, Any]]:
    return [_serialize_row(row) for row in rows]


def _validate_page(
    *,
    limit: int,
    offset: int,
) -> tuple[int, int]:
    if not isinstance(limit, int):
        raise ValueError("limit must be an integer")

    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError(
            f"limit must be between 1 and {MAX_PAGE_SIZE}"
        )

    if not isinstance(offset, int):
        raise ValueError("offset must be an integer")

    if offset < 0:
        raise ValueError("offset must be >= 0")

    return limit, offset


async def latest_domain_snapshot(
    pg,
    *,
    site_id: str,
    provider: str = DEFAULT_PROVIDER,
    location: str = DEFAULT_LOCATION,
    language: str = DEFAULT_LANGUAGE,
    device: str = DEFAULT_DEVICE,
) -> dict[str, Any] | None:
    """Return the newest cached domain overview snapshot."""

    result = await pg.execute(
        text(
            """
            SELECT *
            FROM marketing_seo_domain_snapshots
            WHERE site_id = :site_id
              AND provider = :provider
              AND location = :location
              AND language = :language
              AND device = :device
            ORDER BY captured_date DESC, created_at DESC
            LIMIT 1
            """
        ),
        {
            "site_id": site_id,
            "provider": provider,
            "location": location,
            "language": language,
            "device": device,
        },
    )

    row = result.first()

    return _serialize_row(row) if row else None


async def list_organic_keyword_snapshots(
    pg,
    *,
    site_id: str,
    provider: str = DEFAULT_PROVIDER,
    location: str = DEFAULT_LOCATION,
    language: str = DEFAULT_LANGUAGE,
    device: str = DEFAULT_DEVICE,
    captured_date: date | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> dict[str, Any]:
    """Return one cached provider keyword snapshot page.

    If ``captured_date`` is omitted, the newest available snapshot date for
    this exact provider/location/language/device scope is selected.
    """

    limit, offset = _validate_page(
        limit=limit,
        offset=offset,
    )

    params = {
        "site_id": site_id,
        "provider": provider,
        "location": location,
        "language": language,
        "device": device,
        "captured_date": captured_date,
        "limit": limit,
        "offset": offset,
    }

    result = await pg.execute(
        text(
            """
            WITH selected_date AS (
                SELECT COALESCE(
                    :captured_date,
                    MAX(captured_date)
                ) AS captured_date
                FROM marketing_seo_organic_keyword_snapshots
                WHERE site_id = :site_id
                  AND provider = :provider
                  AND location = :location
                  AND language = :language
                  AND device = :device
            )
            SELECT k.*
            FROM marketing_seo_organic_keyword_snapshots k
            CROSS JOIN selected_date d
            WHERE k.site_id = :site_id
              AND k.provider = :provider
              AND k.location = :location
              AND k.language = :language
              AND k.device = :device
              AND k.captured_date = d.captured_date
            ORDER BY
                k.current_rank ASC NULLS LAST,
                k.search_volume DESC NULLS LAST,
                k.keyword ASC
            LIMIT :limit
            OFFSET :offset
            """
        ),
        params,
    )

    rows = _serialize_rows(result)

    count_result = await pg.execute(
        text(
            """
            WITH selected_date AS (
                SELECT COALESCE(
                    :captured_date,
                    MAX(captured_date)
                ) AS captured_date
                FROM marketing_seo_organic_keyword_snapshots
                WHERE site_id = :site_id
                  AND provider = :provider
                  AND location = :location
                  AND language = :language
                  AND device = :device
            )
            SELECT
                d.captured_date,
                COUNT(k.id) AS total
            FROM selected_date d
            LEFT JOIN marketing_seo_organic_keyword_snapshots k
              ON k.site_id = :site_id
             AND k.provider = :provider
             AND k.location = :location
             AND k.language = :language
             AND k.device = :device
             AND k.captured_date = d.captured_date
            GROUP BY d.captured_date
            """
        ),
        params,
    )

    count_row = count_result.first()

    selected_date_value = (
        count_row._mapping.get("captured_date")
        if count_row
        else None
    )

    total = (
        int(count_row._mapping.get("total") or 0)
        if count_row
        else 0
    )

    if isinstance(selected_date_value, date):
        selected_date_value = selected_date_value.isoformat()

    return {
        "captured_date": selected_date_value,
        "items": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(rows) < total,
    }


async def list_competitor_snapshots(
    pg,
    *,
    site_id: str,
    provider: str = DEFAULT_PROVIDER,
    location: str = DEFAULT_LOCATION,
    language: str = DEFAULT_LANGUAGE,
    device: str = DEFAULT_DEVICE,
    captured_date: date | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> dict[str, Any]:
    """Return one cached provider competitor snapshot page."""

    limit, offset = _validate_page(
        limit=limit,
        offset=offset,
    )

    params = {
        "site_id": site_id,
        "provider": provider,
        "location": location,
        "language": language,
        "device": device,
        "captured_date": captured_date,
        "limit": limit,
        "offset": offset,
    }

    result = await pg.execute(
        text(
            """
            WITH selected_date AS (
                SELECT COALESCE(
                    :captured_date,
                    MAX(captured_date)
                ) AS captured_date
                FROM marketing_seo_competitor_snapshots
                WHERE site_id = :site_id
                  AND provider = :provider
                  AND location = :location
                  AND language = :language
                  AND device = :device
            )
            SELECT c.*
            FROM marketing_seo_competitor_snapshots c
            CROSS JOIN selected_date d
            WHERE c.site_id = :site_id
              AND c.provider = :provider
              AND c.location = :location
              AND c.language = :language
              AND c.device = :device
              AND c.captured_date = d.captured_date
            ORDER BY
                c.intersections DESC NULLS LAST,
                c.competitor_estimated_traffic DESC NULLS LAST,
                c.domain ASC
            LIMIT :limit
            OFFSET :offset
            """
        ),
        params,
    )

    rows = _serialize_rows(result)

    count_result = await pg.execute(
        text(
            """
            WITH selected_date AS (
                SELECT COALESCE(
                    :captured_date,
                    MAX(captured_date)
                ) AS captured_date
                FROM marketing_seo_competitor_snapshots
                WHERE site_id = :site_id
                  AND provider = :provider
                  AND location = :location
                  AND language = :language
                  AND device = :device
            )
            SELECT
                d.captured_date,
                COUNT(c.id) AS total
            FROM selected_date d
            LEFT JOIN marketing_seo_competitor_snapshots c
              ON c.site_id = :site_id
             AND c.provider = :provider
             AND c.location = :location
             AND c.language = :language
             AND c.device = :device
             AND c.captured_date = d.captured_date
            GROUP BY d.captured_date
            """
        ),
        params,
    )

    count_row = count_result.first()

    selected_date_value = (
        count_row._mapping.get("captured_date")
        if count_row
        else None
    )

    total = (
        int(count_row._mapping.get("total") or 0)
        if count_row
        else 0
    )

    if isinstance(selected_date_value, date):
        selected_date_value = selected_date_value.isoformat()

    return {
        "captured_date": selected_date_value,
        "items": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(rows) < total,
    }


async def list_provider_runs(
    pg,
    *,
    site_id: str,
    provider: str = DEFAULT_PROVIDER,
    report_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Return cached provider request/cost ledger history."""

    limit, offset = _validate_page(
        limit=limit,
        offset=offset,
    )

    params = {
        "site_id": site_id,
        "provider": provider,
        "report_type": report_type,
        "limit": limit,
        "offset": offset,
    }

    result = await pg.execute(
        text(
            """
            SELECT *
            FROM marketing_seo_provider_runs
            WHERE site_id = :site_id
              AND provider = :provider
              AND (
                    CAST(:report_type AS TEXT) IS NULL
                    OR report_type = CAST(:report_type AS TEXT)
              )
            ORDER BY created_at DESC, id DESC
            LIMIT :limit
            OFFSET :offset
            """
        ),
        params,
    )

    rows = _serialize_rows(result)

    count_result = await pg.execute(
        text(
            """
            SELECT COUNT(*) AS total
            FROM marketing_seo_provider_runs
            WHERE site_id = :site_id
              AND provider = :provider
              AND (
                    CAST(:report_type AS TEXT) IS NULL
                    OR report_type = CAST(:report_type AS TEXT)
              )
            """
        ),
        params,
    )

    count_row = count_result.first()

    total = (
        int(count_row._mapping.get("total") or 0)
        if count_row
        else 0
    )

    return {
        "items": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(rows) < total,
    }
