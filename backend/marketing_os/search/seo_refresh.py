"""Governed DataForSEO refresh — the ONLY code path that performs paid
provider calls for the SEO Command Center.

* ``plan_refresh`` — validates + describes a refresh (dry-run, zero calls).
* ``execute_refresh`` — runs the existing bounded paginator inside one
  transaction, writes the provider-run ledger, and audit-logs the request.
* ``run_due_seo_refreshes`` — scheduler tick: conservative, opt-in, kill
  switch via ``SEO_PROVIDER_REFRESH_ENABLED`` (default off), advisory lock
  against overlapping runs, per-schedule retry ceiling.

Credentials are read by the adapter from the server environment only.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text

from marketing_os.integrations.dataforseo import (
    DataForSEOIntegration, REPORT_KEYWORD_GAP, REPORT_SERP_RANK, credential_readiness,
)

from .seo_intel_store import (
    DEFAULT_SCHEDULES, due_refresh_schedules, list_tracked_keywords, record_schedule_run,
)
from .seo_provider_sync import (
    DEFAULT_REQUEST_COST_RESERVE, MAX_BOUNDED_PROVIDER_PAGES, SINGLE_REQUEST_REPORTS,
    SUPPORTED_REPORTS, sync_seo_provider_report_bounded,
)

logger = logging.getLogger("marketing_os.seo_refresh")

REFRESH_ENABLED_ENV = "SEO_PROVIDER_REFRESH_ENABLED"
MAX_MANUAL_COST = 5.0
MAX_MANUAL_PAGES = 20
SCHEDULER_LOCK_KEY = 7_420_026_001  # pg advisory lock id


def _validate_limit(report: str, limit: int) -> int:
    if not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("limit must be 1..1000")
    return limit


def plan_refresh(
    *, report_type: str, site: dict, start_offset: int = 0, limit: int = 1000,
    max_pages: int = 1, max_total_cost: float = 0.25, options: Optional[dict] = None,
) -> dict[str, Any]:
    """Describe exactly what a refresh would do. Performs no provider call."""
    report = str(report_type or "").strip().lower()
    if report not in SUPPORTED_REPORTS:
        raise ValueError(f"unsupported report_type: {report}")
    if not isinstance(max_pages, int) or not 1 <= max_pages <= min(MAX_MANUAL_PAGES, MAX_BOUNDED_PROVIDER_PAGES):
        raise ValueError(f"max_pages must be 1..{MAX_MANUAL_PAGES}")
    if not 0 < float(max_total_cost) <= MAX_MANUAL_COST:
        raise ValueError(f"max_total_cost must be in (0, {MAX_MANUAL_COST}]")
    if start_offset < 0:
        raise ValueError("start_offset must be >= 0")
    limit = _validate_limit(report, limit)
    opts = dict(options or {})
    if report == REPORT_KEYWORD_GAP and not opts.get("competitor_domain"):
        raise ValueError("keyword_gap requires options.competitor_domain")
    if report == REPORT_SERP_RANK and not opts.get("tracked_keyword_id"):
        raise ValueError("serp_rank requires options.tracked_keyword_id")
    effective_pages = 1 if report in SINGLE_REQUEST_REPORTS else max_pages
    readiness = credential_readiness()
    return {
        "report_type": report,
        "site_id": site["id"],
        "target": site.get("normalized_url") or site.get("site_url"),
        "start_offset": start_offset if report not in SINGLE_REQUEST_REPORTS else 0,
        "limit": limit,
        "max_pages": effective_pages,
        "max_requests": effective_pages,
        "max_total_cost": float(max_total_cost),
        "request_cost_reserve": DEFAULT_REQUEST_COST_RESERVE,
        "options": opts,
        "writes_postgresql": True,
        "tables": _tables_for(report),
        "provider_ready": readiness.get("status") == "connected",
        "provider_readiness": readiness.get("status"),
    }


def _tables_for(report: str) -> list[str]:
    base = ["marketing_seo_provider_runs"]
    return base + {
        "ranked_keywords": ["marketing_seo_organic_keyword_snapshots"],
        "domain_rank_overview": ["marketing_seo_domain_snapshots"],
        "competitors_domain": ["marketing_seo_competitor_snapshots"],
        "keyword_gap": ["marketing_seo_keyword_gap_snapshots"],
        "backlinks_summary": ["marketing_seo_backlink_summary_snapshots"],
        "backlinks": ["marketing_seo_backlink_snapshots"],
        "serp_rank": ["marketing_seo_rank_observations"],
    }.get(report, [])


async def execute_refresh(
    pg, *, plan: dict, adapter=None, actor: Optional[dict] = None, trigger: str = "manual",
) -> dict[str, Any]:
    """Run one bounded refresh in a single transaction and audit it."""
    adapter = adapter or DataForSEOIntegration()
    started = datetime.now(timezone.utc)
    result: dict[str, Any]
    status = "completed"
    error: Optional[str] = None
    try:
        result = await sync_seo_provider_report_bounded(
            pg, site_id=plan["site_id"], target=plan["target"], adapter=adapter,
            report=plan["report_type"], limit=plan["limit"],
            start_offset=plan["start_offset"], max_pages=plan["max_pages"],
            max_total_cost=plan["max_total_cost"], options=plan.get("options") or None,
        )
        await pg.commit()
    except Exception as exc:  # provider or validation error — surfaced safely
        try:
            await pg.rollback()
        except Exception:
            logger.exception("rollback after failed SEO refresh")
        status = "error"
        error = f"{type(exc).__name__}: {str(exc)[:300]}"
        result = {"pages": 0, "stop_reason": "error", "complete": False,
                  "next_offset": plan["start_offset"], "provider_cost": 0.0,
                  "rows_normalized": 0, "rows_persisted": 0, "page_results": []}
    finished = datetime.now(timezone.utc)
    try:
        from audit import log_audit
        await log_audit(
            None, (actor or {}).get("id"), (actor or {}).get("email"),
            "marketing_os.seo.provider_refresh", resource_type="seo_provider_refresh",
            resource_id=plan["site_id"], severity="info" if status == "completed" else "warning",
            outcome="success" if status == "completed" else "failure",
            metadata={"trigger": trigger, "report_type": plan["report_type"],
                      "start_offset": plan["start_offset"], "limit": plan["limit"],
                      "max_pages": plan["max_pages"], "max_total_cost": plan["max_total_cost"],
                      "pages": result.get("pages"), "stop_reason": result.get("stop_reason"),
                      "complete": result.get("complete"), "next_offset": result.get("next_offset"),
                      "total_cost": result.get("provider_cost", result.get("total_cost")), "error": error},
        )
    except Exception:  # audit must never mask the provider result
        logger.exception("SEO refresh audit write failed")
    return {
        "status": status,
        "error": error,
        "trigger": trigger,
        "plan": plan,
        "pages": result.get("pages"),
        "requests_made": result.get("pages"),
        "stop_reason": result.get("stop_reason"),
        "complete": result.get("complete"),
        "next_offset": result.get("next_offset"),
        "total_cost": result.get("provider_cost", result.get("total_cost")),
        "provider_task_cost": result.get("provider_task_cost"),
        "provider_total_count": result.get("provider_total_count"),
        "rows_normalized": result.get("rows_normalized"),
        "rows_persisted": result.get("rows_persisted"),
        "provider_run_ids": [p.get("provider_run_id") for p in (result.get("page_results") or []) if p.get("provider_run_id")],
        "page_results": result.get("page_results"),
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
    }


def scheduler_enabled() -> bool:
    return (os.environ.get(REFRESH_ENABLED_ENV) or "false").strip().lower() in {"1", "true", "yes"}


async def run_due_seo_refreshes(session_factory=None, *, adapter=None, now: datetime | None = None) -> dict[str, Any]:
    """Scheduler tick. Safe to call every hour; does nothing unless
    (a) the env kill-switch is on, (b) a schedule row is enabled AND due,
    (c) provider credentials are configured. One schedule per report per
    tick; overlapping ticks are excluded with a PostgreSQL advisory lock."""
    summary: dict[str, Any] = {"enabled": scheduler_enabled(), "ran": [], "skipped": []}
    if not summary["enabled"]:
        summary["reason"] = f"{REFRESH_ENABLED_ENV} is not true"
        return summary
    if credential_readiness().get("status") != "connected":
        summary["reason"] = "provider credentials not configured"
        return summary
    if session_factory is None:
        from postgres_db import AsyncSessionLocal as session_factory  # type: ignore
    async with session_factory() as pg:
        locked = (await pg.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": SCHEDULER_LOCK_KEY})).scalar()
        if not locked:
            summary["reason"] = "another refresh tick holds the lock"
            return summary
        try:
            due = await due_refresh_schedules(pg, now=now)
            for sched in due:
                report = sched["report_type"]
                site = {"id": sched["site_id"], "normalized_url": sched["target"]}
                opts = dict(sched.get("options") or {})
                targets: list[dict] = []
                if report == REPORT_SERP_RANK:
                    tracked = await list_tracked_keywords(pg, site_id=site["id"], limit=int(sched["max_requests"]))
                    targets = [{"tracked_keyword_id": k["id"]} for k in tracked["items"]]
                elif report == REPORT_KEYWORD_GAP:
                    comps = opts.get("competitor_domains") or ([opts["competitor_domain"]] if opts.get("competitor_domain") else [])
                    modes = opts.get("modes") or ["shared", "missing"]
                    targets = [{"competitor_domain": c, "mode": m} for c in comps for m in modes][: int(sched["max_requests"])]
                else:
                    targets = [{}]
                if not targets:
                    await record_schedule_run(pg, schedule_id=sched["id"], status="skipped",
                                              error="no targets configured", provider_run_id=None,
                                              cadence_hours=int(sched["cadence_hours"]), now=now)
                    await pg.commit()
                    summary["skipped"].append({"schedule": sched["id"], "reason": "no targets"})
                    continue
                per_target_cost = float(sched["max_total_cost"]) / max(1, len(targets))
                overall_status, last_error, last_run_id = "completed", None, None
                for t in targets:
                    plan = plan_refresh(
                        report_type=report, site=site, start_offset=0,
                        limit=int(sched["limit_per_page"]), max_pages=int(sched["max_pages"]),
                        max_total_cost=max(0.01, min(per_target_cost, MAX_MANUAL_COST)),
                        options={**{k: v for k, v in opts.items() if k not in {"competitor_domains", "modes"}}, **t},
                    )
                    outcome = await execute_refresh(pg, plan=plan, adapter=adapter, trigger="scheduled")
                    if outcome["status"] != "completed":
                        overall_status, last_error = "error", outcome["error"]
                    if outcome["provider_run_ids"]:
                        last_run_id = outcome["provider_run_ids"][-1]
                await record_schedule_run(pg, schedule_id=sched["id"], status=overall_status, error=last_error,
                                          provider_run_id=last_run_id, cadence_hours=int(sched["cadence_hours"]), now=now)
                await pg.commit()
                summary["ran"].append({"schedule": sched["id"], "report_type": report, "status": overall_status,
                                       "targets": len(targets)})
        finally:
            await pg.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": SCHEDULER_LOCK_KEY})
            await pg.commit()
    return summary


__all__ = ["DEFAULT_SCHEDULES", "REFRESH_ENABLED_ENV", "execute_refresh", "plan_refresh",
           "run_due_seo_refreshes", "scheduler_enabled"]
