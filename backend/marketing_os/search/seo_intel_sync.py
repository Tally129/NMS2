"""Phase 2 provider sync branches — keyword gap, backlinks, SERP rank.

Called ONLY through ``seo_provider_sync.sync_seo_provider_report`` so every
report shares the same provider-run ledger, cost/page bounds and the
critical pagination rule: **offsets advance by provider items consumed
(``items_count``), never by rows that survive normalization**.

No transaction management, no scheduling, no credential handling here.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
from typing import Any

from marketing_os.integrations.dataforseo import (
    REPORT_BACKLINKS, REPORT_BACKLINKS_SUMMARY, REPORT_KEYWORD_GAP, REPORT_SERP_RANK,
    normalize_target,
)

from .seo_intel_store import (
    get_tracked_keyword, persist_backlink_snapshots, persist_backlink_summary_snapshot,
    persist_keyword_gap_snapshots, persist_rank_observation,
)
from .seo_provider_persistence import DEFAULT_PROVIDER, persist_provider_run
from .seo_provider_sync import _page_state, _provider_metadata


def _base(payload: Mapping[str, Any], report: str, target: str) -> dict[str, Any]:
    return {
        "report": report,
        "target": payload.get("target") or target,
        "provider_cost": payload.get("cost"),
        "provider_task_cost": payload.get("task_cost"),
    }


async def sync_extended_report(
    pg, *, site_id: str, target: str, adapter, report: str, location: str, language: str,
    device: str, limit: int, offset: int, captured_date: date | None,
    options: Mapping[str, Any] | None,
) -> dict[str, Any]:
    opts = dict(options or {})
    provider_kw = {"location_name": location, "language_name": language}

    # ---------------------------------------------------------------- gap
    if report == REPORT_KEYWORD_GAP:
        competitor = normalize_target(opts.get("competitor_domain") or "")
        if not competitor:
            raise ValueError("keyword_gap requires options.competitor_domain")
        # mode: shared (both rank) | missing (competitor-only) | untapped (NMS-only)
        mode = str(opts.get("mode") or "shared").lower()
        if mode == "shared":
            intersections, target_first = True, True
        elif mode == "missing":
            intersections, target_first = False, False   # target1=competitor
        elif mode == "untapped":
            intersections, target_first = False, True
        else:
            raise ValueError("keyword_gap options.mode must be shared|missing|untapped")
        payload = await adapter.fetch_domain_intersection(
            target=target, competitor=competitor, limit=limit, offset=offset,
            intersections=intersections, target_is_first=target_first, **provider_kw,
        )
        if not isinstance(payload, Mapping):
            raise ValueError("provider returned invalid domain-intersection payload")
        rows = payload.get("gap_rows") or []
        if not isinstance(rows, list):
            raise ValueError("provider returned invalid gap rows")
        # Force the bucket for non-intersection modes: provider only returns
        # one side's element there, so classification is by construction.
        if mode == "missing":
            for r in rows:
                r["gap_type"] = "missing"; r["target_rank"] = None
        elif mode == "untapped":
            for r in rows:
                r["gap_type"] = "untapped"; r["competitor_rank"] = None
        complete, next_offset = _page_state(payload, row_count=len(rows))
        run = await persist_provider_run(
            pg, site_id=site_id, report_type=report,
            target=f"{normalize_target(target)}|{competitor}|{mode}",
            metadata=_provider_metadata(payload), rows_normalized=len(rows),
            provider=payload.get("provider") or DEFAULT_PROVIDER, location=location,
            language=language, device=device, requested_limit=limit, requested_offset=offset,
            complete=complete, next_offset=next_offset,
        )
        persisted = await persist_keyword_gap_snapshots(
            pg, site_id=site_id, rows=rows, provider_run_id=run["id"],
            provider=payload.get("provider") or DEFAULT_PROVIDER, captured_date=captured_date,
            location=location, language=language, device=device,
        )
        return {**_base(payload, report, target), "provider_run_id": run["id"],
                "competitor_domain": competitor, "mode": mode, "rows_normalized": len(rows),
                "rows_persisted": persisted, "complete": complete, "next_offset": next_offset}

    # ------------------------------------------------------- backlink summary
    if report == REPORT_BACKLINKS_SUMMARY:
        payload = await adapter.fetch_backlinks_summary(target=target)
        if not isinstance(payload, Mapping):
            raise ValueError("provider returned invalid backlink summary payload")
        summary = payload.get("summary") or {}
        run = await persist_provider_run(
            pg, site_id=site_id, report_type=report, target=payload.get("target") or target,
            metadata=_provider_metadata(payload), rows_normalized=1 if summary else 0,
            provider=payload.get("provider") or DEFAULT_PROVIDER, location=location,
            language=language, device=device, complete=True, next_offset=None,
        )
        snapshot = None
        if summary:
            snapshot = await persist_backlink_summary_snapshot(
                pg, site_id=site_id, summary=summary, provider_run_id=run["id"],
                provider=payload.get("provider") or DEFAULT_PROVIDER, captured_date=captured_date,
            )
        return {**_base(payload, report, target), "provider_run_id": run["id"],
                "rows_normalized": 1 if summary else 0, "rows_persisted": 1 if snapshot else 0,
                "complete": True, "next_offset": None}

    # ------------------------------------------------------------- backlinks
    if report == REPORT_BACKLINKS:
        payload = await adapter.fetch_backlinks(
            target=target, limit=limit, offset=offset,
            backlinks_status_type=str(opts.get("status_type") or "live"),
        )
        if not isinstance(payload, Mapping):
            raise ValueError("provider returned invalid backlinks payload")
        rows = payload.get("backlinks") or []
        if not isinstance(rows, list):
            raise ValueError("provider returned invalid backlink rows")
        complete, next_offset = _page_state(payload, row_count=len(rows))
        run = await persist_provider_run(
            pg, site_id=site_id, report_type=report, target=payload.get("target") or target,
            metadata=_provider_metadata(payload), rows_normalized=len(rows),
            provider=payload.get("provider") or DEFAULT_PROVIDER, location=location,
            language=language, device=device, requested_limit=limit, requested_offset=offset,
            complete=complete, next_offset=next_offset,
        )
        persisted = await persist_backlink_snapshots(
            pg, site_id=site_id, rows=rows, provider_run_id=run["id"],
            provider=payload.get("provider") or DEFAULT_PROVIDER, captured_date=captured_date,
        )
        return {**_base(payload, report, target), "provider_run_id": run["id"],
                "rows_normalized": len(rows), "rows_persisted": persisted,
                "complete": complete, "next_offset": next_offset}

    # ------------------------------------------------------------- serp rank
    if report == REPORT_SERP_RANK:
        keyword_id = str(opts.get("tracked_keyword_id") or "")
        tracked = await get_tracked_keyword(pg, site_id=site_id, keyword_id=keyword_id)
        if not tracked:
            raise ValueError("serp_rank requires options.tracked_keyword_id of an existing tracked keyword")
        if not tracked.get("is_active"):
            raise ValueError("tracked keyword is inactive")
        kw_device = tracked.get("device") or device
        payload = await adapter.fetch_serp_rank(
            keyword=tracked["keyword"], target=tracked.get("target_domain") or target,
            location_name=tracked.get("location") or location,
            language_name=tracked.get("language") or language, device=kw_device,
            depth=int(opts.get("depth") or 100),
        )
        if not isinstance(payload, Mapping):
            raise ValueError("provider returned invalid SERP payload")
        observation = payload.get("observation") or {}
        run = await persist_provider_run(
            pg, site_id=site_id, report_type=report,
            target=f"{tracked.get('target_domain')}|{tracked['normalized_keyword']}",
            metadata=_provider_metadata(payload), rows_normalized=1 if observation else 0,
            provider=payload.get("provider") or DEFAULT_PROVIDER,
            location=tracked.get("location") or location,
            language=tracked.get("language") or language, device=kw_device,
            complete=True, next_offset=None,
        )
        stored = None
        if observation:
            stored = await persist_rank_observation(
                pg, site_id=site_id, tracked_keyword_id=tracked["id"], observation=observation,
                provider_run_id=run["id"], provider=payload.get("provider") or DEFAULT_PROVIDER,
                location=tracked.get("location") or location,
                language=tracked.get("language") or language, device=kw_device,
                observed_at=datetime.now(timezone.utc),
            )
        return {**_base(payload, report, target), "provider_run_id": run["id"],
                "tracked_keyword_id": tracked["id"], "keyword": tracked["keyword"],
                "rows_normalized": 1 if observation else 0, "rows_persisted": 1 if stored else 0,
                "observation": stored, "complete": True, "next_offset": None}

    raise ValueError(f"unsupported extended report: {report}")
