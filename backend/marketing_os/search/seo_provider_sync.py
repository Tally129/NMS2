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
    REPORT_BACKLINKS,
    REPORT_BACKLINKS_SUMMARY,
    REPORT_COMPETITORS_DOMAIN,
    REPORT_DOMAIN_RANK_OVERVIEW,
    REPORT_KEYWORD_GAP,
    REPORT_RANKED_KEYWORDS,
    REPORT_SERP_RANK,
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


# Phase 2 reports handled by seo_intel_sync (same bounded paginator).
EXTENDED_REPORTS = frozenset(
    {
        REPORT_KEYWORD_GAP,
        REPORT_BACKLINKS_SUMMARY,
        REPORT_BACKLINKS,
        REPORT_SERP_RANK,
    }
)
SINGLE_REQUEST_REPORTS = frozenset(
    {REPORT_DOMAIN_RANK_OVERVIEW, REPORT_BACKLINKS_SUMMARY, REPORT_SERP_RANK}
)
SUPPORTED_REPORTS = {
    REPORT_RANKED_KEYWORDS,
    REPORT_DOMAIN_RANK_OVERVIEW,
    REPORT_COMPETITORS_DOMAIN,
} | set(EXTENDED_REPORTS)


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
    """Determine whether a paged provider response is complete.

    Pagination must advance by provider items consumed, not by the
    number of normalized rows retained locally. Provider normalization
    may intentionally filter rows, such as removing the target domain
    from competitor results.
    """

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

    provider_items = _coerce_nonnegative_int(
        payload.get("items_count"),
        default=row_count,
    )

    # If the provider consumed no items, there is no safe forward
    # progress. A zero normalized-row count alone is not sufficient to
    # stop because normalization may have filtered provider items.
    if provider_items == 0:
        return True, None

    if total is not None:
        complete = offset + provider_items >= total

        return (
            complete,
            None if complete else offset + provider_items,
        )

    if limit is None:
        return True, None

    complete = provider_items < limit

    return (
        complete,
        None if complete else offset + provider_items,
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
    options: Mapping[str, Any] | None = None,
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

    if normalized_report in EXTENDED_REPORTS:
        from .seo_intel_sync import sync_extended_report

        return await sync_extended_report(
            pg,
            site_id=site_id,
            target=target,
            adapter=adapter,
            report=normalized_report,
            location=location,
            language=language,
            device=device,
            limit=limit,
            offset=offset,
            captured_date=captured_date,
            options=options,
        )

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


# ---------------------------------------------------------------------------
# Bounded multi-page refresh
# ---------------------------------------------------------------------------

MAX_BOUNDED_PROVIDER_PAGES = 100
DEFAULT_REQUEST_COST_RESERVE = 0.05


def _money(value: Any) -> float:
    """Convert provider cost metadata into a safe non-negative float."""

    if value in (None, ""):
        return 0.0

    result = float(value)

    if result < 0:
        raise ValueError("provider cost must be >= 0")

    return result


async def sync_seo_provider_report_bounded(
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
    start_offset: int = 0,
    captured_date: date | None = None,
    max_pages: int = 10,
    max_total_cost: float = 0.50,
    request_cost_reserve: float = DEFAULT_REQUEST_COST_RESERVE,
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a bounded provider refresh.

    Safety controls:

    * ``max_pages`` limits the number of external provider requests.
    * ``max_total_cost`` is the caller's refresh budget.
    * ``request_cost_reserve`` is reserved BEFORE allowing each request.

    Because a provider's final billed amount is only known after a request,
    the reserve is intentionally conservative. A new request is not started
    unless enough budget remains for the configured reserve.

    This function still does NOT:
    * create a database session
    * begin or commit a transaction
    * schedule itself
    * resolve provider credentials
    * perform any advertising write

    The supplied adapter determines whether calls are real or fake.
    """

    normalized_report = str(report or "").strip().lower()

    if normalized_report not in SUPPORTED_REPORTS:
        raise ValueError(
            f"unsupported SEO provider report: {normalized_report}"
        )

    if not isinstance(max_pages, int):
        raise ValueError("max_pages must be an integer")

    if not 1 <= max_pages <= MAX_BOUNDED_PROVIDER_PAGES:
        raise ValueError(
            "max_pages must be between 1 and "
            f"{MAX_BOUNDED_PROVIDER_PAGES}"
        )

    if limit < 1:
        raise ValueError("limit must be >= 1")

    if start_offset < 0:
        raise ValueError("start_offset must be >= 0")

    budget = float(max_total_cost)
    reserve = float(request_cost_reserve)

    if budget <= 0:
        raise ValueError("max_total_cost must be > 0")

    if reserve <= 0:
        raise ValueError("request_cost_reserve must be > 0")

    if reserve > budget:
        raise ValueError(
            "request_cost_reserve cannot exceed max_total_cost"
        )

    # Single-request reports are intentionally one request only.
    effective_max_pages = (
        1
        if normalized_report in SINGLE_REQUEST_REPORTS
        else max_pages
    )

    current_offset = start_offset
    pages = 0
    total_rows_normalized = 0
    total_rows_persisted = 0
    total_provider_cost = 0.0
    total_provider_task_cost = 0.0
    provider_total_count = None
    complete = False
    stop_reason = None
    page_results: list[dict[str, Any]] = []

    while pages < effective_max_pages:
        # Do not start another paid request unless its configured reserve
        # still fits inside the caller's budget.
        if total_provider_cost + reserve > budget:
            stop_reason = "cost_ceiling"
            break

        result = await sync_seo_provider_report(
            pg,
            site_id=site_id,
            target=target,
            adapter=adapter,
            report=normalized_report,
            location=location,
            language=language,
            device=device,
            limit=limit,
            offset=current_offset,
            captured_date=captured_date,
            options=options,
        )

        pages += 1

        page_cost = _money(result.get("provider_cost"))
        page_task_cost = _money(
            result.get("provider_task_cost")
        )

        total_provider_cost += page_cost
        total_provider_task_cost += page_task_cost

        total_rows_normalized += int(
            result.get("rows_normalized") or 0
        )
        total_rows_persisted += int(
            result.get("rows_persisted") or 0
        )

        if result.get("provider_total_count") is not None:
            provider_total_count = result.get(
                "provider_total_count"
            )

        page_results.append(
            {
                "provider_run_id": result.get(
                    "provider_run_id"
                ),
                "rows_normalized": result.get(
                    "rows_normalized"
                ),
                "rows_persisted": result.get(
                    "rows_persisted"
                ),
                "complete": bool(result.get("complete")),
                "next_offset": result.get("next_offset"),
                "provider_cost": page_cost,
                "provider_task_cost": page_task_cost,
            }
        )

        if result.get("complete") is True:
            complete = True
            stop_reason = "complete"
            break

        next_offset = result.get("next_offset")

        if next_offset is None:
            stop_reason = "no_forward_progress"
            break

        next_offset = int(next_offset)

        if next_offset <= current_offset:
            stop_reason = "no_forward_progress"
            break

        current_offset = next_offset

    if stop_reason is None:
        if complete:
            stop_reason = "complete"
        elif pages >= effective_max_pages:
            stop_reason = "page_ceiling"
        else:
            stop_reason = "stopped"

    return {
        "report": normalized_report,
        "target": target,
        "pages": pages,
        "max_pages": effective_max_pages,
        "rows_normalized": total_rows_normalized,
        "rows_persisted": total_rows_persisted,
        "provider_total_count": provider_total_count,
        "provider_cost": round(total_provider_cost, 8),
        "provider_task_cost": round(
            total_provider_task_cost,
            8,
        ),
        "max_total_cost": budget,
        "request_cost_reserve": reserve,
        "complete": complete,
        "next_offset": (
            None if complete else current_offset
        ),
        "stop_reason": stop_reason,
        "page_results": page_results,
    }
