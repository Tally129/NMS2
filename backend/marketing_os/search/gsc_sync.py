"""READ-ONLY Google Search Console sync into first-party PostgreSQL tables.

The adapter is injected (tests pass a fake). Google is only ever read via
searchanalytics().query(). Persisted metrics are idempotent (ON CONFLICT
upsert), so re-running a sync for the same window does not duplicate rows.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import text

from .gsc import (
    PROVIDER,
    aggregate_totals,
    normalize_query_text,
    normalize_rows,
)


def _new_id() -> str:
    return uuid.uuid4().hex


async def _upsert_daily(pg, site_id: str, rows: list[dict]) -> int:
    count = 0
    for r in rows:
        await pg.execute(
            text(
                """
                INSERT INTO marketing_gsc_daily_metrics
                    (id, site_id, metric_date, clicks, impressions, ctr,
                     position, device, country, source)
                VALUES
                    (:id, :site_id, :metric_date, :clicks, :impressions,
                     :ctr, :position, 'all', 'all', :source)
                ON CONFLICT
                    (site_id, metric_date, device, country, source)
                DO UPDATE SET
                    clicks = EXCLUDED.clicks,
                    impressions = EXCLUDED.impressions,
                    ctr = EXCLUDED.ctr,
                    position = EXCLUDED.position,
                    updated_at = now()
                """
            ),
            {
                "id": _new_id(),
                "site_id": site_id,
                "metric_date": r.get("date"),
                "clicks": r.get("clicks", 0),
                "impressions": r.get("impressions", 0),
                "ctr": r.get("ctr", 0),
                "position": r.get("position"),
                "source": PROVIDER,
            },
        )
        count += 1
    return count


async def _upsert_queries(
    pg, site_id: str, rows: list[dict], captured: date
) -> int:
    count = 0
    for r in rows:
        query = r.get("query") or ""
        if not query:
            continue
        await pg.execute(
            text(
                """
                INSERT INTO marketing_gsc_query_metrics
                    (id, site_id, captured_date, query, normalized_query,
                     clicks, impressions, ctr, position, device, country,
                     source)
                VALUES
                    (:id, :site_id, :captured_date, :query,
                     :normalized_query, :clicks, :impressions, :ctr,
                     :position, 'all', 'all', :source)
                ON CONFLICT
                    (site_id, captured_date, normalized_query, device,
                     country, source)
                DO UPDATE SET
                    query = EXCLUDED.query,
                    clicks = EXCLUDED.clicks,
                    impressions = EXCLUDED.impressions,
                    ctr = EXCLUDED.ctr,
                    position = EXCLUDED.position,
                    updated_at = now()
                """
            ),
            {
                "id": _new_id(),
                "site_id": site_id,
                "captured_date": captured,
                "query": query,
                "normalized_query": normalize_query_text(query),
                "clicks": r.get("clicks", 0),
                "impressions": r.get("impressions", 0),
                "ctr": r.get("ctr", 0),
                "position": r.get("position"),
                "source": PROVIDER,
            },
        )
        count += 1
    return count


async def _upsert_pages(
    pg, site_id: str, rows: list[dict], captured: date
) -> int:
    count = 0
    for r in rows:
        page = r.get("page") or ""
        if not page:
            continue
        await pg.execute(
            text(
                """
                INSERT INTO marketing_gsc_page_metrics
                    (id, site_id, captured_date, page, clicks, impressions,
                     ctr, position, device, country, source)
                VALUES
                    (:id, :site_id, :captured_date, :page, :clicks,
                     :impressions, :ctr, :position, 'all', 'all', :source)
                ON CONFLICT
                    (site_id, captured_date, page, device, country, source)
                DO UPDATE SET
                    clicks = EXCLUDED.clicks,
                    impressions = EXCLUDED.impressions,
                    ctr = EXCLUDED.ctr,
                    position = EXCLUDED.position,
                    updated_at = now()
                """
            ),
            {
                "id": _new_id(),
                "site_id": site_id,
                "captured_date": captured,
                "page": page,
                "clicks": r.get("clicks", 0),
                "impressions": r.get("impressions", 0),
                "ctr": r.get("ctr", 0),
                "position": r.get("position"),
                "source": PROVIDER,
            },
        )
        count += 1
    return count


async def sync_search_console(
    pg,
    *,
    site_id: str,
    adapter,
    start_date: str,
    end_date: str,
    created_by: Optional[str] = None,
    row_limit: int = 1000,
) -> dict[str, Any]:
    """Read GSC (date/query/page) and persist normalized metrics.

    READ-ONLY vs Google. Idempotent persistence. Records a sync run.
    Callers own the transaction boundary is NOT assumed — this opens its
    own transaction on the provided session.
    """
    started = datetime.now(timezone.utc)
    captured = date.fromisoformat(end_date)
    run_id = _new_id()
    status = "completed"
    error: Optional[str] = None
    rows_synced = 0

    try:
        daily = normalize_rows(
            adapter.fetch_search_analytics(
                start_date=start_date, end_date=end_date,
                dimensions=["date"], row_limit=row_limit,
            ),
            ["date"],
        )
        queries = normalize_rows(
            adapter.fetch_search_analytics(
                start_date=start_date, end_date=end_date,
                dimensions=["query"], row_limit=row_limit,
            ),
            ["query"],
        )
        pages = normalize_rows(
            adapter.fetch_search_analytics(
                start_date=start_date, end_date=end_date,
                dimensions=["page"], row_limit=row_limit,
            ),
            ["page"],
        )

        async with pg.begin():
            rows_synced += await _upsert_daily(pg, site_id, daily)
            rows_synced += await _upsert_queries(
                pg, site_id, queries, captured
            )
            rows_synced += await _upsert_pages(pg, site_id, pages, captured)
    except Exception as exc:  # noqa: BLE001 - surface as read_error
        status = "error"
        error = f"{type(exc).__name__}: {str(exc)[:300]}"

    finished = datetime.now(timezone.utc)

    async with pg.begin():
        await pg.execute(
            text(
                """
                INSERT INTO marketing_gsc_sync_runs
                    (id, site_id, status, start_date, end_date,
                     rows_synced, source, error, started_at, finished_at,
                     created_by)
                VALUES
                    (:id, :site_id, :status, :start_date, :end_date,
                     :rows_synced, :source, :error, :started_at,
                     :finished_at, :created_by)
                """
            ),
            {
                "id": run_id,
                "site_id": site_id,
                "status": status,
                "start_date": date.fromisoformat(start_date),
                "end_date": captured,
                "rows_synced": rows_synced,
                "source": PROVIDER,
                "error": error,
                "started_at": started,
                "finished_at": finished,
                "created_by": created_by,
            },
        )

    return {
        "run_id": run_id,
        "site_id": site_id,
        "status": status,
        "error": error,
        "rows_synced": rows_synced,
        "start_date": start_date,
        "end_date": end_date,
        "source": PROVIDER,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
    }
