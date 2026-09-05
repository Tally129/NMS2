"""Controlled SEO-provider read + persistence orchestration.

One invocation performs exactly one provider report request.

The caller supplies:
- the database session
- the read-only provider adapter

The caller owns:
- the transaction boundary
- commit / rollback
- provider selection / registry resolution
- scheduling and refresh policy

This module:
- creates no database engine/session
- begins no transaction
- commits nothing
- creates no provider credentials
- performs no autonomous scheduling
- performs no advertising/external write
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from marketing_os.integrations.dataforseo import (
    REPORT_COMPETITORS_DOMAIN,
    REPORT_DOMAIN_RANK_OVERVIEW,
    REPORT_RANKED_KEYWORDS,
)

from .seo_provider_persistence import (
    DEFAULT_DEVICE,
    DEFAULT_LANGUAGE,
    DEFAULT_LOCATION,
    DEFAULT_PROVIDER,
    persist_competitor_snapshots,
    persist_domain_snapshot,
    persist_organic_keyword_snapshots,
    persist_provider_run,
)


SUPPORTED_REPORTS = {
    REPORT_RANKED_KEYWORDS,
    REPORT_DOMAIN_RANK_OVERVIEW,
    REPORT_COMPETITORS_DOMAIN,
}


def _coerce_nonnegative_int(
    value: Any,
    *,
    default: int = 0,
) -> int:
    if value is None or value == "":
        return default

    result = int(value)

    if result < 0:
        raise ValueError("value must be >= 0")

    return result


def _page_state(
    payload: Mapping[str, Any],
    *,
    row_count: int,
) -> tuple[bool, int | None]:
    """Determine whether a paged provider response is complete."""

    offset = _coerce_nonnegative_int(
        payload.get("offset"),
        default=0,
    )

    limit_value = payload.get("limit")

    limit = (
        int(limit_value)
        if limit_value not in (None, "")
        else None
    )

    total_value = payload.get("total_count")

    total = (
        int(total_value)
        if total_value not in (None, "")
        else None
    )

    # No rows means there is no safe forward progress.
    if row_count == 0:
        return True, None

    if total is not None:
        complete = offset + row_count >= total

        return (
            complete,
            None if complete else offset + row_count,
        )

    if limit is None:
        return True, None

    complete = row_count < limit

    return (
        complete,
        None if complete else offset + row_count,
    )


def _provider_metadata(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Extract only persistence-safe metadata."""

    return {
        "status_code": payload.get("status_code"),
        "task_status_code": payload.get(
            "task_status_code"
        ),
        "cost": payload.get("cost"),
        "task_cost": payload.get("task_cost"),
        "total_count": payload.get("total_count"),
        "items_count": payload.get("items_count"),
    }


async def sync_seo_provider_report(
    pg,
    *,
    site_id: str,
    target: str,
    adapter,
    report: str,
    location: str = DEFAULT_LOCATION,
    language: str = DEFAULT_LANGUAGE,
    device: str = DEFAULT_DEVICE,
    limit: int = 100,
    offset: int = 0,
    captured_date: date | None = None,
) -> dict[str, Any]:
    """Fetch and persist exactly one provider report/page.

    No transaction is opened here.

    For paged reports, the return value includes ``complete`` and
    ``next_offset`` so a higher-level bounded paginator can decide
    whether another paid provider request is appropriate.
    """

    normalized_report = str(report or "").strip().lower()

    if normalized_report not in SUPPORTED_REPORTS:
        raise ValueError(
            f"unsupported SEO provider report: "
            f"{normalized_report}"
        )

    if offset < 0:
        raise ValueError("offset must be >= 0")

    if limit < 1:
        raise ValueError("limit must be >= 1")

    common = {
        "target": target,
        "location_name": location,
        "language_name": language,
    }

    if normalized_report == REPORT_DOMAIN_RANK_OVERVIEW:
        payload = await adapter.fetch_domain_rank_overview(
            **common
        )

        if not isinstance(payload, Mapping):
            raise ValueError(
                "provider returned invalid domain overview payload"
            )

        overview = payload.get("overview") or {}

        if not isinstance(overview, Mapping):
            raise ValueError(
                "provider returned invalid domain overview"
            )

        rows_normalized = 1 if overview else 0
        complete = True
        next_offset = None

        run = await persist_provider_run(
            pg,
            site_id=site_id,
            report_type=normalized_report,
            target=payload.get("target") or target,
            metadata=_provider_metadata(payload),
            rows_normalized=rows_normalized,
            provider=payload.get("provider")
            or DEFAULT_PROVIDER,
            location=payload.get("location")
            or location,
            language=payload.get("language")
            or language,
            device=device,
            complete=True,
            next_offset=None,
        )

        snapshot = None

        if overview:
            snapshot = await persist_domain_snapshot(
                pg,
                site_id=site_id,
                overview=overview,
                provider_run_id=run["id"],
                provider=payload.get("provider")
                or DEFAULT_PROVIDER,
                captured_date=captured_date,
                location=payload.get("location")
                or location,
                language=payload.get("language")
                or language,
                device=device,
            )

        return {
            "provider_run_id": run["id"],
            "report": normalized_report,
            "target": payload.get("target") or target,
            "rows_normalized": rows_normalized,
            "rows_persisted": 1 if snapshot else 0,
            "complete": complete,
            "next_offset": next_offset,
            "provider_cost": payload.get("cost"),
            "provider_task_cost": payload.get(
                "task_cost"
            ),
        }

    if normalized_report == REPORT_RANKED_KEYWORDS:
        payload = await adapter.fetch_ranked_keywords(
            **common,
            limit=limit,
            offset=offset,
        )

        if not isinstance(payload, Mapping):
            raise ValueError(
                "provider returned invalid ranked-keyword payload"
            )

        rows = payload.get("keywords") or []

        if not isinstance(rows, list):
            raise ValueError(
                "provider returned invalid keyword rows"
            )

        complete, next_offset = _page_state(
            payload,
            row_count=len(rows),
        )

        run = await persist_provider_run(
            pg,
            site_id=site_id,
            report_type=normalized_report,
            target=payload.get("target") or target,
            metadata=_provider_metadata(payload),
            rows_normalized=len(rows),
            provider=payload.get("provider")
            or DEFAULT_PROVIDER,
            location=payload.get("location")
            or location,
            language=payload.get("language")
            or language,
            device=device,
            requested_limit=payload.get("limit")
            or limit,
            requested_offset=payload.get("offset")
            if payload.get("offset") is not None
            else offset,
            complete=complete,
            next_offset=next_offset,
        )

        persisted = (
            await persist_organic_keyword_snapshots(
                pg,
                site_id=site_id,
                keywords=rows,
                provider_run_id=run["id"],
                provider=payload.get("provider")
                or DEFAULT_PROVIDER,
                captured_date=captured_date,
                location=payload.get("location")
                or location,
                language=payload.get("language")
                or language,
                device=device,
            )
        )

        return {
            "provider_run_id": run["id"],
            "report": normalized_report,
            "target": payload.get("target") or target,
            "rows_normalized": len(rows),
            "rows_persisted": persisted,
            "complete": complete,
            "next_offset": next_offset,
            "provider_total_count": payload.get(
                "total_count"
            ),
            "provider_cost": payload.get("cost"),
            "provider_task_cost": payload.get(
                "task_cost"
            ),
        }

    payload = await adapter.fetch_competitors_domain(
        **common,
        limit=limit,
        offset=offset,
    )

    if not isinstance(payload, Mapping):
        raise ValueError(
            "provider returned invalid competitor payload"
        )

    rows = payload.get("competitors") or []

    if not isinstance(rows, list):
        raise ValueError(
            "provider returned invalid competitor rows"
        )

    complete, next_offset = _page_state(
        payload,
        row_count=len(rows),
    )

    run = await persist_provider_run(
        pg,
        site_id=site_id,
        report_type=normalized_report,
        target=payload.get("target") or target,
        metadata=_provider_metadata(payload),
        rows_normalized=len(rows),
        provider=payload.get("provider")
        or DEFAULT_PROVIDER,
        location=payload.get("location")
        or location,
        language=payload.get("language")
        or language,
        device=device,
        requested_limit=payload.get("limit")
        or limit,
        requested_offset=payload.get("offset")
        if payload.get("offset") is not None
        else offset,
        complete=complete,
        next_offset=next_offset,
    )

    persisted = await persist_competitor_snapshots(
        pg,
        site_id=site_id,
        competitors=rows,
        target=payload.get("target") or target,
        provider_run_id=run["id"],
        provider=payload.get("provider")
        or DEFAULT_PROVIDER,
        captured_date=captured_date,
        location=payload.get("location")
        or location,
        language=payload.get("language")
        or language,
        device=device,
    )

    return {
        "provider_run_id": run["id"],
        "report": normalized_report,
        "target": payload.get("target") or target,
        "rows_normalized": len(rows),
        "rows_persisted": persisted,
        "complete": complete,
        "next_offset": next_offset,
        "provider_total_count": payload.get(
            "total_count"
        ),
        "provider_cost": payload.get("cost"),
        "provider_task_cost": payload.get(
            "task_cost"
        ),
    }
