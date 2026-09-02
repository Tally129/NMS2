"""Marketing OS — Search Intelligence API.

Read-only search diagnostics for the Marketing Command Center:
- SEO overview aggregation
- keyword tracking + rank movement
- deterministic technical site audit (READ-ONLY to the target website)
- advisory SEO recommendations for the AI Marketing Director

Uses the existing Marketing OS authorization (require_roles) and the shared
`api` router. No external provider writes, no publishing, no automatic site
changes. Marketing-only data (non-PHI) enforced on write paths.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from deps import api, require_roles
from postgres_db import AsyncSessionLocal

from marketing_os.services.measurement import (
    MarketingDataPolicyError,
    assert_non_phi_marketing_payload,
)
from marketing_os.search.contracts import NormalizedKeyword
from marketing_os.search.keywords import (
    normalize_keyword,
    normalize_keyword_text,
    rank_gainers,
    rank_losers,
    summarize_keywords,
)
from marketing_os.search.overview import build_search_overview
from marketing_os.search.recommendations import build_search_recommendations
from marketing_os.search.site_audit import (
    fetch_site,
    is_public_http_url,
    run_audit,
)

MARKETING_ROLES = ("admin", "practitioner")

_SEVERITY_COLUMN = {
    "critical": "critical_count",
    "warning": "warning_count",
    "opportunity": "opportunity_count",
    "informational": "informational_count",
}


def _new_id() -> str:
    return uuid.uuid4().hex


def _uid(user: dict) -> Optional[str]:
    value = user.get("id")
    return str(value) if value else None


def _serialize(row) -> dict[str, Any]:
    result = dict(row._mapping)
    for key, value in list(result.items()):
        if isinstance(value, Decimal):
            result[key] = float(value)
        elif isinstance(value, (date, datetime)):
            result[key] = value.isoformat()
    return result


def _normalize_site_url(raw: str) -> str:
    parsed = urlparse(raw.strip())
    path = (parsed.path or "").rstrip("/")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------

class SiteRegister(BaseModel):
    # Reject unknown keys (defense-in-depth against PHI leaking in).
    model_config = ConfigDict(extra="forbid")

    site_url: str = Field(..., min_length=4, max_length=512)
    label: Optional[str] = Field(default=None, max_length=200)


class KeywordTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_id: Optional[str] = Field(default=None, max_length=64)
    keyword: str = Field(..., min_length=1, max_length=255)
    intent: Optional[str] = Field(default=None, max_length=32)
    location: Optional[str] = Field(default=None, max_length=128)
    device: Optional[str] = Field(default=None, max_length=32)
    search_volume: Optional[int] = Field(default=None, ge=0)
    keyword_difficulty: Optional[int] = Field(default=None, ge=0, le=100)
    cpc: Optional[float] = Field(default=None, ge=0)
    is_tracked: bool = True
    # Optional first-party rank snapshot seed.
    current_rank: Optional[int] = Field(default=None, ge=1)
    ranking_url: Optional[str] = Field(default=None, max_length=2048)
    serp_features: Optional[list[str]] = None


class AuditRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_id: Optional[str] = Field(default=None, max_length=64)
    site_url: Optional[str] = Field(default=None, max_length=512)
    max_pages: int = Field(default=5, ge=1, le=10)


# --------------------------------------------------------------------------
# Site helpers
# --------------------------------------------------------------------------

async def _resolve_site(pg, site_id: Optional[str]) -> Optional[dict]:
    if site_id:
        result = await pg.execute(
            text(
                "SELECT * FROM marketing_search_sites WHERE id = :id"
            ),
            {"id": site_id},
        )
    else:
        result = await pg.execute(
            text(
                "SELECT * FROM marketing_search_sites "
                "WHERE is_active = true "
                "ORDER BY created_at ASC LIMIT 1"
            )
        )
    row = result.first()
    return _serialize(row) if row else None


async def _load_keywords(
    pg,
    site_id: str,
    *,
    tracked_only: bool,
) -> list[NormalizedKeyword]:
    query = text(
        """
        WITH ranked AS (
            SELECT
                s.keyword_id,
                s.current_rank,
                s.ranking_url,
                s.serp_features,
                s.captured_date,
                s.source,
                ROW_NUMBER() OVER (
                    PARTITION BY s.keyword_id
                    ORDER BY s.captured_date DESC, s.created_at DESC
                ) AS rn
            FROM marketing_keyword_rank_snapshots s
        )
        SELECT
            k.id, k.keyword, k.intent, k.search_volume,
            k.keyword_difficulty, k.cpc, k.location, k.device,
            k.source, k.is_tracked,
            cur.current_rank AS current_rank,
            cur.ranking_url AS ranking_url,
            cur.serp_features AS serp_features,
            cur.captured_date AS captured_date,
            prev.current_rank AS previous_rank
        FROM marketing_search_keywords k
        LEFT JOIN ranked cur ON cur.keyword_id = k.id AND cur.rn = 1
        LEFT JOIN ranked prev ON prev.keyword_id = k.id AND prev.rn = 2
        WHERE k.site_id = :site_id
        ORDER BY k.keyword ASC
        """
    )
    result = await pg.execute(query, {"site_id": site_id})
    keywords: list[NormalizedKeyword] = []
    for row in result:
        data = dict(row._mapping)
        if tracked_only and not data.get("is_tracked"):
            continue
        captured = data.get("captured_date")
        payload = {
            "keyword": data.get("keyword"),
            "intent": data.get("intent"),
            "search_volume": data.get("search_volume"),
            "keyword_difficulty": data.get("keyword_difficulty"),
            "cpc": data.get("cpc"),
            "location": data.get("location"),
            "device": data.get("device"),
            "source": data.get("source"),
            "is_tracked": data.get("is_tracked"),
            "current_rank": data.get("current_rank"),
            "previous_rank": data.get("previous_rank"),
            "ranking_url": data.get("ranking_url"),
            "serp_features": data.get("serp_features") or [],
            "captured_date": (
                captured.isoformat()
                if isinstance(captured, date)
                else captured
            ),
        }
        keywords.append(normalize_keyword(payload))
    return keywords


async def _latest_audit(pg, site_id: str) -> Optional[dict]:
    result = await pg.execute(
        text(
            "SELECT * FROM marketing_site_audit_runs "
            "WHERE site_id = :site_id "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"site_id": site_id},
    )
    row = result.first()
    return _serialize(row) if row else None


# --------------------------------------------------------------------------
# Sites
# --------------------------------------------------------------------------

@api.get("/marketing-os/search/sites")
async def list_search_sites(
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    async with AsyncSessionLocal() as pg:
        result = await pg.execute(
            text(
                "SELECT * FROM marketing_search_sites "
                "ORDER BY created_at ASC"
            )
        )
        return {"sites": [_serialize(row) for row in result]}


@api.post("/marketing-os/search/sites", status_code=201)
async def register_search_site(
    payload: SiteRegister,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    try:
        assert_non_phi_marketing_payload(payload.model_dump())
    except MarketingDataPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not is_public_http_url(payload.site_url):
        raise HTTPException(
            status_code=400,
            detail="site_url must be a public http(s) URL",
        )

    normalized = _normalize_site_url(payload.site_url)
    site_id = _new_id()

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            result = await pg.execute(
                text(
                    """
                    INSERT INTO marketing_search_sites
                        (id, site_url, normalized_url, label,
                         is_active, created_by)
                    VALUES
                        (:id, :site_url, :normalized_url, :label,
                         true, :created_by)
                    ON CONFLICT (normalized_url) DO UPDATE SET
                        label = EXCLUDED.label,
                        is_active = true,
                        updated_at = now()
                    RETURNING *
                    """
                ),
                {
                    "id": site_id,
                    "site_url": payload.site_url.strip(),
                    "normalized_url": normalized,
                    "label": payload.label,
                    "created_by": _uid(user),
                },
            )
            row = result.first()
        return _serialize(row)


# --------------------------------------------------------------------------
# Keywords
# --------------------------------------------------------------------------

@api.get("/marketing-os/search/keywords")
async def list_search_keywords(
    site_id: Optional[str] = Query(default=None),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if site is None:
            return {
                "connected": False,
                "not_connected_reason": "no_marketing_site_configured",
                "keywords": [],
                "summary": summarize_keywords([]),
            }
        keywords = await _load_keywords(
            pg, site["id"], tracked_only=False
        )
    return {
        "connected": True,
        "site": site,
        "keywords": [k.to_dict() for k in keywords],
        "summary": summarize_keywords(keywords),
    }


@api.get("/marketing-os/search/keywords/tracked")
async def list_tracked_keywords(
    site_id: Optional[str] = Query(default=None),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if site is None:
            return {
                "connected": False,
                "not_connected_reason": "no_marketing_site_configured",
                "keywords": [],
                "summary": summarize_keywords([]),
                "gains": [],
                "losses": [],
            }
        keywords = await _load_keywords(
            pg, site["id"], tracked_only=True
        )
    return {
        "connected": True,
        "site": site,
        "keywords": [k.to_dict() for k in keywords],
        "summary": summarize_keywords(keywords),
        "gains": [k.to_dict() for k in rank_gainers(keywords)],
        "losses": [k.to_dict() for k in rank_losers(keywords)],
    }


@api.post("/marketing-os/search/keywords", status_code=201)
async def track_keyword(
    payload: KeywordTrack,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    try:
        normalized = normalize_keyword(
            payload.model_dump(exclude_none=False)
        )
    except MarketingDataPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    keyword_id = _new_id()

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            site = await _resolve_site(pg, payload.site_id)
            if site is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "No marketing site configured. Register a site "
                        "first via POST /marketing-os/search/sites."
                    ),
                )

            result = await pg.execute(
                text(
                    """
                    INSERT INTO marketing_search_keywords
                        (id, site_id, keyword, normalized_keyword, intent,
                         search_volume, keyword_difficulty, cpc, location,
                         device, source, is_tracked, created_by)
                    VALUES
                        (:id, :site_id, :keyword, :normalized_keyword,
                         :intent, :search_volume, :keyword_difficulty,
                         :cpc, :location, :device, :source, :is_tracked,
                         :created_by)
                    ON CONFLICT
                        (site_id, normalized_keyword, location, device)
                    DO UPDATE SET
                        intent = EXCLUDED.intent,
                        search_volume = EXCLUDED.search_volume,
                        keyword_difficulty = EXCLUDED.keyword_difficulty,
                        cpc = EXCLUDED.cpc,
                        is_tracked = EXCLUDED.is_tracked,
                        source = EXCLUDED.source,
                        updated_at = now()
                    RETURNING *
                    """
                ),
                {
                    "id": keyword_id,
                    "site_id": site["id"],
                    "keyword": normalized.keyword,
                    "normalized_keyword": normalized.normalized_keyword,
                    "intent": normalized.intent,
                    "search_volume": normalized.search_volume,
                    "keyword_difficulty": normalized.keyword_difficulty,
                    "cpc": normalized.cpc,
                    "location": normalized.location,
                    "device": normalized.device,
                    "source": normalized.source,
                    "is_tracked": normalized.is_tracked,
                    "created_by": _uid(user),
                },
            )
            row = result.first()
            stored = _serialize(row)

            # Optional first-party rank snapshot.
            if payload.current_rank is not None:
                await pg.execute(
                    text(
                        """
                        INSERT INTO marketing_keyword_rank_snapshots
                            (id, keyword_id, current_rank, ranking_url,
                             serp_features, source, captured_date)
                        VALUES
                            (:id, :keyword_id, :current_rank, :ranking_url,
                             CAST(:serp_features AS JSONB), :source,
                             :captured_date)
                        ON CONFLICT (keyword_id, captured_date, source)
                        DO UPDATE SET
                            current_rank = EXCLUDED.current_rank,
                            ranking_url = EXCLUDED.ranking_url,
                            serp_features = EXCLUDED.serp_features
                        """
                    ),
                    {
                        "id": _new_id(),
                        "keyword_id": stored["id"],
                        "current_rank": payload.current_rank,
                        "ranking_url": payload.ranking_url,
                        "serp_features": _json_dumps(
                            normalized.serp_features
                        ),
                        "source": normalized.source,
                        "captured_date": date.today(),
                    },
                )
        return stored


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value or [])


# --------------------------------------------------------------------------
# Overview
# --------------------------------------------------------------------------

@api.get("/marketing-os/search/overview")
async def search_overview(
    site_id: Optional[str] = Query(default=None),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if site is None:
            return build_search_overview(site=None)
        keywords = await _load_keywords(
            pg, site["id"], tracked_only=True
        )
        latest = await _latest_audit(pg, site["id"])
        gsc_summary = await _gsc_overview_summary(pg, site["id"])
    return build_search_overview(
        site=site,
        keywords=keywords,
        latest_audit=latest,
        gsc_summary=gsc_summary,
    )


async def _gsc_overview_summary(pg, site_id: str) -> dict:
    """Aggregate Search Console totals for the overview (honest empty)."""
    daily = await pg.execute(
        text(
            "SELECT COALESCE(SUM(clicks),0) AS clicks, "
            "COALESCE(SUM(impressions),0) AS impressions, "
            "SUM(position * impressions) AS wpos, "
            "SUM(CASE WHEN position IS NULL THEN 0 ELSE impressions END) "
            "AS pos_impr "
            "FROM marketing_gsc_daily_metrics WHERE site_id = :sid"
        ),
        {"sid": site_id},
    )
    row = daily.first()
    m = dict(row._mapping) if row else {}
    clicks = int(m.get("clicks") or 0)
    impressions = int(m.get("impressions") or 0)
    wpos = float(m.get("wpos") or 0)
    pos_impr = int(m.get("pos_impr") or 0)
    if impressions == 0:
        return {"connected": False}

    captured = await pg.execute(
        text(
            "SELECT MAX(captured_date) AS c FROM marketing_gsc_query_metrics "
            "WHERE site_id = :sid"
        ),
        {"sid": site_id},
    )
    cap = captured.first()._mapping.get("c")
    organic_keywords = None
    if cap is not None:
        cnt = await pg.execute(
            text(
                "SELECT COUNT(DISTINCT normalized_query) AS n "
                "FROM marketing_gsc_query_metrics "
                "WHERE site_id = :sid AND captured_date = :c"
            ),
            {"sid": site_id, "c": cap},
        )
        organic_keywords = int(cnt.first()._mapping.get("n") or 0)

    return {
        "connected": True,
        "clicks": clicks,
        "impressions": impressions,
        "ctr": round(clicks / impressions, 6) if impressions else 0.0,
        "average_position": (
            round(wpos / pos_impr, 2) if pos_impr else None
        ),
        "organic_keywords": organic_keywords,
    }


# --------------------------------------------------------------------------
# Technical site audit (READ-ONLY)
# --------------------------------------------------------------------------

@api.post("/marketing-os/search/site-audit/run", status_code=201)
async def run_site_audit(
    payload: AuditRunRequest,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, payload.site_id)

        if site is None and payload.site_url:
            if not is_public_http_url(payload.site_url):
                raise HTTPException(
                    status_code=400,
                    detail="site_url must be a public http(s) URL",
                )
            normalized = _normalize_site_url(payload.site_url)
            async with pg.begin():
                result = await pg.execute(
                    text(
                        """
                        INSERT INTO marketing_search_sites
                            (id, site_url, normalized_url, is_active,
                             created_by)
                        VALUES
                            (:id, :site_url, :normalized_url, true,
                             :created_by)
                        ON CONFLICT (normalized_url) DO UPDATE SET
                            is_active = true, updated_at = now()
                        RETURNING *
                        """
                    ),
                    {
                        "id": _new_id(),
                        "site_url": payload.site_url.strip(),
                        "normalized_url": normalized,
                        "created_by": _uid(user),
                    },
                )
                site = _serialize(result.first())

        if site is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No marketing site configured. Provide site_url or "
                    "register a site first."
                ),
            )

    started_at = datetime.now(timezone.utc)

    # Live fetch is blocking (httpx sync) + READ-ONLY -> run off the loop.
    fetched = await run_in_threadpool(
        fetch_site,
        site["site_url"],
        max_pages=payload.max_pages,
    )
    audit = run_audit(
        fetched["pages"],
        sitemap_found=fetched.get("sitemap_found"),
        link_status=fetched.get("link_status"),
        site_url=site["site_url"],
    )
    finished_at = datetime.now(timezone.utc)

    run_id = _new_id()
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await pg.execute(
                text(
                    """
                    INSERT INTO marketing_site_audit_runs
                        (id, site_id, status, pages_scanned, issues_total,
                         critical_count, warning_count, opportunity_count,
                         informational_count, summary, started_at,
                         finished_at, created_by)
                    VALUES
                        (:id, :site_id, :status, :pages_scanned,
                         :issues_total, :critical_count, :warning_count,
                         :opportunity_count, :informational_count,
                         CAST(:summary AS JSONB), :started_at, :finished_at,
                         :created_by)
                    """
                ),
                {
                    "id": run_id,
                    "site_id": site["id"],
                    "status": "completed",
                    "pages_scanned": audit["pages_scanned"],
                    "issues_total": audit["issues_total"],
                    "critical_count": audit["critical_count"],
                    "warning_count": audit["warning_count"],
                    "opportunity_count": audit["opportunity_count"],
                    "informational_count": audit["informational_count"],
                    "summary": _json_dumps_dict({
                        "sitemap_found": audit.get("sitemap_found"),
                    }),
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "created_by": _uid(user),
                },
            )
            for issue in audit["issues"]:
                await pg.execute(
                    text(
                        """
                        INSERT INTO marketing_site_audit_issues
                            (id, run_id, severity, category, issue_code,
                             url, description, recommended_action, details)
                        VALUES
                            (:id, :run_id, :severity, :category,
                             :issue_code, :url, :description,
                             :recommended_action, CAST(:details AS JSONB))
                        """
                    ),
                    {
                        "id": _new_id(),
                        "run_id": run_id,
                        "severity": issue["severity"],
                        "category": issue["category"],
                        "issue_code": issue["issue_code"],
                        "url": issue["url"],
                        "description": issue["description"],
                        "recommended_action": issue["recommended_action"],
                        "details": _json_dumps_dict(issue.get("details")),
                    },
                )

    return {
        "run_id": run_id,
        "site_id": site["id"],
        "status": "completed",
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "pages_scanned": audit["pages_scanned"],
        "issues_total": audit["issues_total"],
        "critical_count": audit["critical_count"],
        "warning_count": audit["warning_count"],
        "opportunity_count": audit["opportunity_count"],
        "informational_count": audit["informational_count"],
        "sitemap_found": audit.get("sitemap_found"),
    }


def _json_dumps_dict(value: Any) -> str:
    import json

    return json.dumps(value or {})


@api.get("/marketing-os/search/site-audit")
async def latest_site_audit(
    site_id: Optional[str] = Query(default=None),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if site is None:
            return {
                "connected": False,
                "not_connected_reason": "no_marketing_site_configured",
                "has_run": False,
            }
        latest = await _latest_audit(pg, site["id"])
    if latest is None:
        return {
            "connected": True,
            "site": site,
            "has_run": False,
        }
    latest["connected"] = True
    latest["has_run"] = True
    latest["site"] = site
    return latest


@api.get("/marketing-os/search/site-audit/issues")
async def site_audit_issues(
    run_id: Optional[str] = Query(default=None),
    site_id: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    async with AsyncSessionLocal() as pg:
        resolved_run = run_id
        if resolved_run is None:
            site = await _resolve_site(pg, site_id)
            if site is None:
                return {"connected": False, "issues": []}
            latest = await _latest_audit(pg, site["id"])
            if latest is None:
                return {"connected": True, "has_run": False, "issues": []}
            resolved_run = latest["id"]

        params: dict[str, Any] = {"run_id": resolved_run, "limit": limit}
        severity_clause = ""
        if severity:
            severity_clause = "AND severity = :severity"
            params["severity"] = severity

        result = await pg.execute(
            text(
                f"""
                SELECT * FROM marketing_site_audit_issues
                WHERE run_id = :run_id {severity_clause}
                ORDER BY
                    CASE severity
                        WHEN 'critical' THEN 0
                        WHEN 'warning' THEN 1
                        WHEN 'opportunity' THEN 2
                        ELSE 3
                    END,
                    url, issue_code
                LIMIT :limit
                """
            ),
            params,
        )
        issues = [_serialize(row) for row in result]

    return {
        "connected": True,
        "has_run": True,
        "run_id": resolved_run,
        "issues": issues,
    }


# --------------------------------------------------------------------------
# Advisory recommendations (for the AI Marketing Director)
# --------------------------------------------------------------------------

@api.get("/marketing-os/search/recommendations")
async def search_recommendations(
    site_id: Optional[str] = Query(default=None),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if site is None:
            overview = build_search_overview(site=None)
            recommendations = build_search_recommendations(
                overview=overview,
                audit_issues=[],
                keywords=[],
            )
            return {
                "connected": False,
                "advisory_only": True,
                "requires_human_approval": True,
                "recommendations": recommendations,
            }
        keywords = await _load_keywords(
            pg, site["id"], tracked_only=True
        )
        latest = await _latest_audit(pg, site["id"])
        issues: list[dict] = []
        if latest is not None:
            result = await pg.execute(
                text(
                    "SELECT severity, category, issue_code, url "
                    "FROM marketing_site_audit_issues "
                    "WHERE run_id = :run_id"
                ),
                {"run_id": latest["id"]},
            )
            issues = [dict(row._mapping) for row in result]

    overview = build_search_overview(
        site=site,
        keywords=keywords,
        latest_audit=latest,
    )
    recommendations = build_search_recommendations(
        overview=overview,
        audit_issues=issues,
        keywords=keywords,
    )
    return {
        "connected": True,
        "site": site,
        "advisory_only": True,
        "requires_human_approval": True,
        "recommendations": recommendations,
    }
