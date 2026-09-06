"""Marketing OS — SEO intelligence phase 2 routes.

Cached reads (PostgreSQL only): keyword gap, backlinks, rank tracking,
refresh schedules, GSC sync-run completeness.
Governed writes: tracked keywords, schedules (admin), and the ONLY route
that may trigger paid DataForSEO calls — ``POST /seo/refresh`` (admin,
bounded, audited, dry-run by default).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from deps import api, require_roles
from postgres_db import AsyncSessionLocal

from marketing_os.integrations.dataforseo import credential_readiness
from marketing_os.routers.search import MARKETING_ROLES, _resolve_site
from marketing_os.search.seo_intel_store import (
    DEFAULT_SCHEDULES, GAP_TYPES, create_tracked_keyword, latest_backlink_summary,
    list_backlinks, list_keyword_gap, list_keyword_gap_competitors, list_rank_observations,
    list_refresh_schedules, list_tracked_keywords, rank_tracking_summary,
    set_tracked_keyword_active, upsert_refresh_schedule,
)
from marketing_os.search.seo_refresh import (
    MAX_MANUAL_COST, MAX_MANUAL_PAGES, execute_refresh, plan_refresh, scheduler_enabled,
)
from marketing_os.search.seo_intel_store import _sers as _serialize_rows

ADMIN_ROLES = ("admin",)


async def _site_or_404(pg, site_id: Optional[str]) -> dict:
    site = await _resolve_site(pg, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="No marketing site configured")
    return site


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


# ------------------------------------------------------------------ keyword gap


@api.get("/marketing-os/search/seo/keyword-gap/competitors")
async def seo_keyword_gap_competitors(site_id: Optional[str] = Query(default=None),
                                      user=Depends(require_roles(*MARKETING_ROLES))):
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if site is None:
            return {"connected": False, "items": []}
        items = await list_keyword_gap_competitors(pg, site_id=site["id"])
        # Also offer DataForSEO competitor snapshots (not yet gapped) as candidates.
        rows = (await pg.execute(text("""
            SELECT DISTINCT ON (normalized_domain) normalized_domain AS competitor_domain,
                   intersections, competitor_estimated_traffic, captured_date
            FROM marketing_seo_competitor_snapshots WHERE site_id = :site_id
            ORDER BY normalized_domain, captured_date DESC
        """), {"site_id": site["id"]})).mappings().all()
    gapped = {i["competitor_domain"] for i in items}
    candidates = [r for r in _serialize_rows(rows) if r["competitor_domain"] not in gapped]
    candidates.sort(key=lambda r: -(r.get("intersections") or 0))
    return {"connected": True, "items": items, "candidates": candidates[:50]}


@api.get("/marketing-os/search/seo/keyword-gap")
async def seo_keyword_gap(
    competitor_domain: str = Query(..., min_length=3),
    site_id: Optional[str] = Query(default=None),
    gap_type: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None, max_length=200),
    sort: str = Query(default="search_volume"), direction: str = Query(default="desc"),
    limit: int = Query(default=50, ge=1, le=500), offset: int = Query(default=0, ge=0),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    if gap_type and gap_type not in GAP_TYPES:
        raise HTTPException(status_code=422, detail=f"gap_type must be one of {list(GAP_TYPES)}")
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if site is None:
            return {"connected": False, "has_snapshot": False, "items": [], "total": 0}
        return await list_keyword_gap(pg, site_id=site["id"], competitor_domain=competitor_domain,
                                      gap_type=gap_type, search=search, sort=sort,
                                      direction=direction, limit=limit, offset=offset)


# -------------------------------------------------------------------- backlinks


@api.get("/marketing-os/search/seo/backlinks/summary")
async def seo_backlinks_summary(site_id: Optional[str] = Query(default=None),
                                user=Depends(require_roles(*MARKETING_ROLES))):
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if site is None:
            return {"connected": False, "has_snapshot": False, "summary": None}
        summary = await latest_backlink_summary(pg, site_id=site["id"])
    return {"connected": True, "has_snapshot": summary is not None, "summary": summary}


@api.get("/marketing-os/search/seo/backlinks")
async def seo_backlinks(
    site_id: Optional[str] = Query(default=None), search: Optional[str] = Query(default=None, max_length=200),
    dofollow: Optional[bool] = Query(default=None), status: Optional[str] = Query(default=None),
    sort: str = Query(default="domain_from_rank"), direction: str = Query(default="desc"),
    limit: int = Query(default=50, ge=1, le=500), offset: int = Query(default=0, ge=0),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    if status and status not in {"new", "lost", "broken"}:
        raise HTTPException(status_code=422, detail="status must be new|lost|broken")
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if site is None:
            return {"connected": False, "has_snapshot": False, "items": [], "total": 0}
        return await list_backlinks(pg, site_id=site["id"], search=search, dofollow=dofollow,
                                    status=status, sort=sort, direction=direction, limit=limit, offset=offset)


# --------------------------------------------------------------- rank tracking


class TrackedKeywordIn(BaseModel):
    keyword: str = Field(min_length=1, max_length=512)
    target_url: Optional[str] = Field(default=None, max_length=2048)
    location: str = Field(default="United States", max_length=128)
    language: str = Field(default="English", max_length=64)
    device: str = Field(default="desktop", pattern="^(desktop|mobile)$")
    tags: Optional[list[str]] = None


@api.get("/marketing-os/search/seo/tracked-keywords")
async def seo_tracked_keywords(site_id: Optional[str] = Query(default=None),
                               include_inactive: bool = Query(default=False),
                               limit: int = Query(default=200, ge=1, le=500), offset: int = Query(default=0, ge=0),
                               user=Depends(require_roles(*MARKETING_ROLES))):
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if site is None:
            return {"connected": False, "items": [], "total": 0, "summary": {}}
        page = await list_tracked_keywords(pg, site_id=site["id"], include_inactive=include_inactive,
                                           limit=limit, offset=offset)
        summary = await rank_tracking_summary(pg, site_id=site["id"])
    return {"connected": True, **page, "summary": summary}


@api.post("/marketing-os/search/seo/tracked-keywords", status_code=201)
async def seo_tracked_keyword_create(body: TrackedKeywordIn, site_id: Optional[str] = Query(default=None),
                                     user=Depends(require_roles(*MARKETING_ROLES))):
    async with AsyncSessionLocal() as pg:
        site = await _site_or_404(pg, site_id)
        try:
            row = await create_tracked_keyword(
                pg, site_id=site["id"], keyword=body.keyword, target_domain=site["normalized_url"],
                target_url=body.target_url, location=body.location, language=body.language,
                device=body.device, tags=body.tags, created_by=(user or {}).get("id"))
            await pg.commit()
        except ValueError as exc:
            await pg.rollback()
            raise _bad(exc)
    return row


@api.delete("/marketing-os/search/seo/tracked-keywords/{keyword_id}")
async def seo_tracked_keyword_deactivate(keyword_id: str, site_id: Optional[str] = Query(default=None),
                                         user=Depends(require_roles(*MARKETING_ROLES))):
    async with AsyncSessionLocal() as pg:
        site = await _site_or_404(pg, site_id)
        row = await set_tracked_keyword_active(pg, site_id=site["id"], keyword_id=keyword_id, is_active=False)
        await pg.commit()
    if row is None:
        raise HTTPException(status_code=404, detail="tracked keyword not found")
    return row


@api.get("/marketing-os/search/seo/tracked-keywords/{keyword_id}/history")
async def seo_tracked_keyword_history(keyword_id: str, site_id: Optional[str] = Query(default=None),
                                      limit: int = Query(default=90, ge=1, le=500),
                                      user=Depends(require_roles(*MARKETING_ROLES))):
    async with AsyncSessionLocal() as pg:
        site = await _site_or_404(pg, site_id)
        items = await list_rank_observations(pg, site_id=site["id"], keyword_id=keyword_id, limit=limit)
    return {"items": items, "total": len(items)}


# ------------------------------------------------------- GSC completeness runs


@api.get("/marketing-os/search/search-console/runs")
async def gsc_sync_runs(site_id: Optional[str] = Query(default=None), limit: int = Query(default=20, ge=1, le=200),
                        user=Depends(require_roles(*MARKETING_ROLES))):
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if site is None:
            return {"connected": False, "items": []}
        rows = (await pg.execute(text("""
            SELECT id, status, start_date, end_date, rows_synced, source, error, started_at, finished_at,
                   complete, pagination, pages_consumed, safety_ceiling_reached
            FROM marketing_gsc_sync_runs WHERE site_id = :site_id
            ORDER BY started_at DESC LIMIT :limit"""), {"site_id": site["id"], "limit": limit})).mappings().all()
    items = _serialize_rows(rows)
    for it in items:
        it["completeness"] = ("complete" if it.get("complete") is True else
                              "incomplete" if it.get("complete") is False else "unknown")
    return {"connected": True, "items": items}


# ---------------------------------------------------- governed provider refresh


class RefreshRequest(BaseModel):
    report_type: str = Field(min_length=3, max_length=64)
    site_id: Optional[str] = None
    start_offset: int = Field(default=0, ge=0)
    limit: int = Field(default=1000, ge=1, le=1000)
    max_pages: int = Field(default=1, ge=1, le=MAX_MANUAL_PAGES)
    max_total_cost: float = Field(default=0.25, gt=0, le=MAX_MANUAL_COST)
    options: Optional[dict[str, Any]] = None
    dry_run: bool = True
    confirm: bool = False


@api.get("/marketing-os/search/seo/refresh/readiness")
async def seo_refresh_readiness(user=Depends(require_roles(*MARKETING_ROLES))):
    readiness = credential_readiness()
    return {"provider": "dataforseo", "status": readiness.get("status"),
            "scheduler_enabled": scheduler_enabled(), "supported_reports": sorted(DEFAULT_SCHEDULES),
            "max_manual_pages": MAX_MANUAL_PAGES, "max_manual_cost": MAX_MANUAL_COST}


@api.post("/marketing-os/search/seo/refresh")
async def seo_refresh(body: RefreshRequest, request: Request, user=Depends(require_roles(*ADMIN_ROLES))):
    """Admin-only, bounded, audited DataForSEO refresh.

    Defaults to ``dry_run=true`` (returns the plan, zero provider calls).
    A live run requires ``dry_run=false`` AND ``confirm=true``.
    """
    async with AsyncSessionLocal() as pg:
        site = await _site_or_404(pg, body.site_id)
        try:
            plan = plan_refresh(report_type=body.report_type, site=site, start_offset=body.start_offset,
                                limit=body.limit, max_pages=body.max_pages,
                                max_total_cost=body.max_total_cost, options=body.options)
        except ValueError as exc:
            raise _bad(exc)
        if body.dry_run or not body.confirm:
            return {"status": "dry_run", "live": False, "plan": plan,
                    "note": "No provider call made. Send dry_run=false and confirm=true to execute."}
        if not plan["provider_ready"]:
            raise HTTPException(status_code=409, detail=f"DataForSEO not ready: {plan['provider_readiness']}")
        result = await execute_refresh(pg, plan=plan, actor={"id": (user or {}).get("id"),
                                                             "email": (user or {}).get("email")},
                                       trigger="manual")
    return {**result, "live": True}


# ------------------------------------------------------------------ schedules


class ScheduleIn(BaseModel):
    enabled: bool = False
    cadence_hours: int = Field(default=168, ge=24, le=24 * 90)
    max_pages: int = Field(default=1, ge=1, le=20)
    max_requests: int = Field(default=1, ge=1, le=100)
    max_total_cost: float = Field(default=0.25, gt=0, le=25)
    retry_ceiling: int = Field(default=2, ge=0, le=5)
    limit_per_page: int = Field(default=1000, ge=1, le=1000)
    options: Optional[dict[str, Any]] = None


@api.get("/marketing-os/search/seo/schedules")
async def seo_schedules(site_id: Optional[str] = Query(default=None), user=Depends(require_roles(*MARKETING_ROLES))):
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if site is None:
            return {"connected": False, "scheduler_enabled": scheduler_enabled(), "items": []}
        items = await list_refresh_schedules(pg, site_id=site["id"])
    return {"connected": True, "scheduler_enabled": scheduler_enabled(),
            "provider_ready": credential_readiness().get("status") == "connected", "items": items}


@api.put("/marketing-os/search/seo/schedules/{report_type}")
async def seo_schedule_upsert(report_type: str, body: ScheduleIn, site_id: Optional[str] = Query(default=None),
                              user=Depends(require_roles(*ADMIN_ROLES))):
    async with AsyncSessionLocal() as pg:
        site = await _site_or_404(pg, site_id)
        try:
            row = await upsert_refresh_schedule(
                pg, site_id=site["id"], report_type=report_type, enabled=body.enabled,
                cadence_hours=body.cadence_hours, max_pages=body.max_pages, max_requests=body.max_requests,
                max_total_cost=body.max_total_cost, retry_ceiling=body.retry_ceiling,
                limit_per_page=body.limit_per_page, options=body.options, updated_by=(user or {}).get("id"))
            await pg.commit()
        except ValueError as exc:
            await pg.rollback()
            raise _bad(exc)
    return row
