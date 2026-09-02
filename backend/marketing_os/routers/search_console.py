"""Marketing OS — Google Search Console (READ-ONLY) + Rank Tracking API.

All endpoints reuse the existing Marketing OS authorization and namespace.
Google is only ever read; sync persists normalized first-party metrics.
No provider writes, publishing, budget, or campaign actions.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from deps import api, require_roles
from postgres_db import AsyncSessionLocal

from marketing_os.search.gsc import (
    GoogleSearchConsoleAdapter,
    STATE_READ_ERROR,
    aggregate_totals,
    credential_readiness,
)
from marketing_os.search.gsc_recommendations import build_gsc_recommendations
from marketing_os.search.gsc_sync import sync_search_console
from marketing_os.search.rank_tracking import (
    compute_rank_history,
    summarize_movements,
)

MARKETING_ROLES = ("admin", "practitioner")


def _uid(user: dict) -> Optional[str]:
    value = user.get("id")
    return str(value) if value else None


def _f(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


class SyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_id: Optional[str] = Field(default=None, max_length=64)
    start_date: Optional[str] = Field(default=None)
    end_date: Optional[str] = Field(default=None)
    row_limit: int = Field(default=1000, ge=1, le=25000)


async def _resolve_site(pg, site_id: Optional[str]) -> Optional[dict]:
    if site_id:
        res = await pg.execute(
            text("SELECT * FROM marketing_search_sites WHERE id = :id"),
            {"id": site_id},
        )
    else:
        res = await pg.execute(
            text(
                "SELECT * FROM marketing_search_sites WHERE is_active = true "
                "ORDER BY created_at ASC LIMIT 1"
            )
        )
    row = res.first()
    return dict(row._mapping) if row else None


async def _latest_run(pg, site_id: str) -> Optional[dict]:
    res = await pg.execute(
        text(
            "SELECT id, status, error, start_date, end_date, rows_synced, "
            "finished_at FROM marketing_gsc_sync_runs "
            "WHERE site_id = :sid ORDER BY created_at DESC LIMIT 1"
        ),
        {"sid": site_id},
    )
    row = res.first()
    if not row:
        return None
    d = dict(row._mapping)
    for k in ("start_date", "end_date", "finished_at"):
        if isinstance(d.get(k), (date, datetime)):
            d[k] = d[k].isoformat()
    return d


@api.get("/marketing-os/search/search-console/readiness")
async def gsc_readiness(
    site_id: Optional[str] = Query(default=None),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    readiness = credential_readiness()
    last_run = None
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if site:
            last_run = await _latest_run(pg, site["id"])
    # Surface a runtime read error distinctly from configuration state.
    if last_run and last_run.get("status") == "error":
        readiness = {**readiness, "runtime_state": STATE_READ_ERROR}
    return {
        **readiness,
        "site_connected": bool(site) if site_id or True else False,
        "last_sync": last_run,
    }


@api.get("/marketing-os/search/search-console/performance")
async def gsc_performance(
    site_id: Optional[str] = Query(default=None),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    end = date.fromisoformat(end_date) if end_date else date.today()
    start = date.fromisoformat(start_date) if start_date else end - timedelta(
        days=28
    )
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if not site:
            return {"connected": False, "readiness": credential_readiness()}
        res = await pg.execute(
            text(
                "SELECT metric_date, clicks, impressions, ctr, position "
                "FROM marketing_gsc_daily_metrics "
                "WHERE site_id = :sid AND metric_date BETWEEN :s AND :e "
                "ORDER BY metric_date ASC"
            ),
            {"sid": site["id"], "s": start, "e": end},
        )
        series = []
        rows_for_totals = []
        for row in res:
            d = dict(row._mapping)
            series.append({
                "date": d["metric_date"].isoformat(),
                "clicks": int(d["clicks"]),
                "impressions": int(d["impressions"]),
                "ctr": _f(d["ctr"]),
                "position": _f(d["position"]),
            })
            rows_for_totals.append({
                "clicks": int(d["clicks"]),
                "impressions": int(d["impressions"]),
                "position": _f(d["position"]),
            })
    totals = aggregate_totals(rows_for_totals)
    return {
        "connected": bool(series),
        "has_data": bool(series),
        "site": {"id": site["id"], "site_url": site["site_url"]},
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "totals": totals,
        "series": series,
        "position_note": (
            "average_position is a GSC average position, not a dedicated "
            "SERP rank."
        ),
    }


async def _latest_captured(pg, table: str, site_id: str) -> Optional[date]:
    res = await pg.execute(
        text(
            f"SELECT MAX(captured_date) AS c FROM {table} "
            "WHERE site_id = :sid"
        ),
        {"sid": site_id},
    )
    row = res.first()
    return row._mapping["c"] if row else None


@api.get("/marketing-os/search/search-console/queries")
async def gsc_queries(
    site_id: Optional[str] = Query(default=None),
    limit: int = Query(default=25, ge=1, le=500),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if not site:
            return {"connected": False, "queries": []}
        captured = await _latest_captured(
            pg, "marketing_gsc_query_metrics", site["id"]
        )
        if captured is None:
            return {"connected": True, "has_data": False, "queries": []}
        res = await pg.execute(
            text(
                "SELECT query, clicks, impressions, ctr, position "
                "FROM marketing_gsc_query_metrics "
                "WHERE site_id = :sid AND captured_date = :c "
                "ORDER BY clicks DESC, impressions DESC LIMIT :lim"
            ),
            {"sid": site["id"], "c": captured, "lim": limit},
        )
        queries = [
            {
                "query": r._mapping["query"],
                "clicks": int(r._mapping["clicks"]),
                "impressions": int(r._mapping["impressions"]),
                "ctr": _f(r._mapping["ctr"]),
                "position": _f(r._mapping["position"]),
            }
            for r in res
        ]
    return {
        "connected": True,
        "has_data": True,
        "captured_date": captured.isoformat(),
        "queries": queries,
        "source": "google_search_console",
    }


@api.get("/marketing-os/search/search-console/pages")
async def gsc_pages(
    site_id: Optional[str] = Query(default=None),
    limit: int = Query(default=25, ge=1, le=500),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if not site:
            return {"connected": False, "pages": []}
        captured = await _latest_captured(
            pg, "marketing_gsc_page_metrics", site["id"]
        )
        if captured is None:
            return {"connected": True, "has_data": False, "pages": []}
        res = await pg.execute(
            text(
                "SELECT page, clicks, impressions, ctr, position "
                "FROM marketing_gsc_page_metrics "
                "WHERE site_id = :sid AND captured_date = :c "
                "ORDER BY clicks DESC, impressions DESC LIMIT :lim"
            ),
            {"sid": site["id"], "c": captured, "lim": limit},
        )
        pages = [
            {
                "page": r._mapping["page"],
                "clicks": int(r._mapping["clicks"]),
                "impressions": int(r._mapping["impressions"]),
                "ctr": _f(r._mapping["ctr"]),
                "position": _f(r._mapping["position"]),
            }
            for r in res
        ]
    return {
        "connected": True,
        "has_data": True,
        "captured_date": captured.isoformat(),
        "pages": pages,
        "source": "google_search_console",
    }


@api.post("/marketing-os/search/search-console/sync", status_code=201)
async def gsc_sync(
    payload: SyncRequest,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    readiness = credential_readiness()
    if not readiness["connected"]:
        # Honest not-connected / config-incomplete; NO network call.
        return {
            "started": False,
            "reason": readiness["status"],
            "readiness": readiness,
        }

    end = (
        date.fromisoformat(payload.end_date)
        if payload.end_date else date.today()
    )
    start = (
        date.fromisoformat(payload.start_date)
        if payload.start_date else end - timedelta(days=28)
    )

    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, payload.site_id)
        if not site:
            raise HTTPException(
                status_code=400,
                detail="No marketing site configured.",
            )
        adapter = GoogleSearchConsoleAdapter()
        result = await sync_search_console(
            pg,
            site_id=site["id"],
            adapter=adapter,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            created_by=_uid(user),
            row_limit=payload.row_limit,
        )
    result["started"] = True
    return result


@api.get("/marketing-os/search/rank-tracking")
async def rank_tracking(
    site_id: Optional[str] = Query(default=None),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if not site:
            return {"connected": False, "keywords": [], "summary": {}}

        kw_res = await pg.execute(
            text(
                "SELECT id, keyword, normalized_keyword "
                "FROM marketing_search_keywords "
                "WHERE site_id = :sid AND is_tracked = true "
                "ORDER BY keyword ASC"
            ),
            {"sid": site["id"]},
        )
        tracked = [dict(r._mapping) for r in kw_res]

        items = []
        for kw in tracked:
            # GSC average position history (explicitly NOT SERP rank).
            gsc_res = await pg.execute(
                text(
                    "SELECT captured_date, position "
                    "FROM marketing_gsc_query_metrics "
                    "WHERE site_id = :sid AND normalized_query = :q "
                    "ORDER BY captured_date ASC"
                ),
                {"sid": site["id"], "q": kw["normalized_keyword"]},
            )
            gsc_snaps = [
                {"captured_date": r._mapping["captured_date"],
                 "position": _f(r._mapping["position"])}
                for r in gsc_res
            ]
            gsc_hist = compute_rank_history(
                gsc_snaps,
                source="google_search_console",
                metric_type="gsc_average_position",
            )

            # Dedicated SERP rank snapshots (Phase 1 table), if any.
            serp_res = await pg.execute(
                text(
                    "SELECT captured_date, current_rank AS position, source "
                    "FROM marketing_keyword_rank_snapshots "
                    "WHERE keyword_id = :kid ORDER BY captured_date ASC"
                ),
                {"kid": kw["id"]},
            )
            serp_rows = [dict(r._mapping) for r in serp_res]
            serp_source = (
                serp_rows[-1]["source"] if serp_rows else "manual"
            )
            serp_hist = compute_rank_history(
                [{"captured_date": r["captured_date"],
                  "position": r["position"]} for r in serp_rows],
                source=serp_source,
                metric_type="serp_rank",
            )

            items.append({
                "keyword": kw["keyword"],
                "gsc_average_position": {**gsc_hist, "keyword": kw["keyword"]},
                "serp_rank": {**serp_hist, "keyword": kw["keyword"]},
            })

    # Summarize movement using the GSC-position signal.
    summary = summarize_movements(
        [i["gsc_average_position"] for i in items]
    )
    return {
        "connected": True,
        "site": {"id": site["id"], "site_url": site["site_url"]},
        "keywords": items,
        "summary": summary,
        "note": (
            "GSC average position and SERP rank are tracked separately with "
            "explicit source/metric_type; they are not equivalent."
        ),
    }


@api.get("/marketing-os/search/search-console/recommendations")
async def gsc_recommendations(
    site_id: Optional[str] = Query(default=None),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if not site:
            return {
                "connected": False,
                "advisory_only": True,
                "requires_human_approval": True,
                "recommendations": [],
            }
        captured = await _latest_captured(
            pg, "marketing_gsc_query_metrics", site["id"]
        )
        query_rows: list[dict] = []
        if captured is not None:
            res = await pg.execute(
                text(
                    "SELECT query, clicks, impressions, ctr, position "
                    "FROM marketing_gsc_query_metrics "
                    "WHERE site_id = :sid AND captured_date = :c"
                ),
                {"sid": site["id"], "c": captured},
            )
            query_rows = [
                {
                    "query": r._mapping["query"],
                    "clicks": int(r._mapping["clicks"]),
                    "impressions": int(r._mapping["impressions"]),
                    "ctr": _f(r._mapping["ctr"]),
                    "position": _f(r._mapping["position"]),
                }
                for r in res
            ]

    recs = build_gsc_recommendations(query_rows=query_rows)
    return {
        "connected": True,
        "advisory_only": True,
        "requires_human_approval": True,
        "recommendations": recs,
    }
