"""Marketing OS — Phase 3 Search Intelligence API (competitors, keyword gap,
content opportunities, backlinks, local SEO). Reuses existing auth/namespace.
Read-only intelligence; competitor records are first-party. Provider-absent
states are honest (never fabricated). No external writes.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from deps import api, require_roles
from postgres_db import AsyncSessionLocal

from marketing_os.services.measurement import (
    MarketingDataPolicyError, assert_non_phi_marketing_payload)
from marketing_os.search.phase3 import (
    backlink_overview, normalize_competitor, summarize_gap)
from marketing_os.search.phase3_recommendations import (
    build_phase3_recommendations)

MARKETING_ROLES = ("admin", "practitioner")


def _new_id() -> str:
    return uuid.uuid4().hex


def _uid(user: dict) -> Optional[str]:
    v = user.get("id")
    return str(v) if v else None


def _ser(row) -> dict[str, Any]:
    d = dict(row._mapping)
    for k, v in list(d.items()):
        if isinstance(v, Decimal):
            d[k] = float(v)
        elif isinstance(v, (date, datetime)):
            d[k] = v.isoformat()
    return d


async def _resolve_site(pg, site_id: Optional[str]) -> Optional[dict]:
    if site_id:
        r = await pg.execute(text(
            "SELECT * FROM marketing_search_sites WHERE id = :id"),
            {"id": site_id})
    else:
        r = await pg.execute(text(
            "SELECT * FROM marketing_search_sites WHERE is_active = true "
            "ORDER BY created_at ASC LIMIT 1"))
    row = r.first()
    return _ser(row) if row else None


class CompetitorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    site_id: Optional[str] = Field(default=None, max_length=64)
    domain: str = Field(..., min_length=3, max_length=255)
    display_name: Optional[str] = Field(default=None, max_length=200)
    is_active: bool = True
    notes: Optional[str] = Field(default=None, max_length=2000)


@api.get("/marketing-os/search/competitors")
async def list_competitors(site_id: Optional[str] = Query(default=None),
                           user=Depends(require_roles(*MARKETING_ROLES))):
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if not site:
            return {"connected": False, "competitors": []}
        r = await pg.execute(text(
            "SELECT * FROM marketing_search_competitors WHERE site_id = :s "
            "ORDER BY created_at ASC"), {"s": site["id"]})
        return {"connected": True, "site": site,
                "competitors": [_ser(x) for x in r]}


@api.post("/marketing-os/search/competitors", status_code=201)
async def add_competitor(payload: CompetitorIn,
                         user=Depends(require_roles(*MARKETING_ROLES))):
    try:
        norm = normalize_competitor(payload.model_dump())
    except MarketingDataPolicyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            site = await _resolve_site(pg, payload.site_id)
            if not site:
                raise HTTPException(status_code=400,
                                    detail="No marketing site configured.")
            r = await pg.execute(text(
                """
                INSERT INTO marketing_search_competitors
                    (id, site_id, domain, normalized_domain, display_name,
                     is_active, notes, created_by)
                VALUES (:id,:site_id,:domain,:nd,:dn,:act,:notes,:cb)
                ON CONFLICT (site_id, normalized_domain) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    is_active = EXCLUDED.is_active,
                    notes = EXCLUDED.notes, updated_at = now()
                RETURNING *
                """), {"id": _new_id(), "site_id": site["id"],
                       "domain": norm["domain"], "nd": norm[
                           "normalized_domain"], "dn": norm["display_name"],
                       "act": norm["is_active"], "notes": norm["notes"],
                       "cb": _uid(user)})
            return _ser(r.first())


@api.get("/marketing-os/search/competitors/{competitor_id}")
async def get_competitor(competitor_id: str,
                         user=Depends(require_roles(*MARKETING_ROLES))):
    async with AsyncSessionLocal() as pg:
        r = await pg.execute(text(
            "SELECT * FROM marketing_search_competitors WHERE id = :id"),
            {"id": competitor_id})
        row = r.first()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        comp = _ser(row)
        # Deterministic comparison summary from available gap data only.
        gap = await pg.execute(text(
            "SELECT opportunity FROM marketing_keyword_gap_snapshots "
            "WHERE competitor_id = :c"), {"c": competitor_id})
        records = [dict(x._mapping) for x in gap]
    comp["comparison"] = (
        {"data_available": False,
         "reason": "no_competitor_data_provider"}
        if not records else
        {"data_available": True, **summarize_gap(records)})
    return comp


async def _gap_records(pg, site_id: str) -> list[dict]:
    r = await pg.execute(text(
        "SELECT * FROM marketing_keyword_gap_snapshots WHERE site_id = :s "
        "ORDER BY captured_date DESC, keyword ASC"), {"s": site_id})
    return [_ser(x) for x in r]


@api.get("/marketing-os/search/keyword-gap")
async def keyword_gap(site_id: Optional[str] = Query(default=None),
                      user=Depends(require_roles(*MARKETING_ROLES))):
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if not site:
            return {"connected": False, "records": [],
                    "summary": summarize_gap([])}
        records = await _gap_records(pg, site["id"])
    if not records:
        return {"connected": False,
                "not_connected_reason": "no_competitor_data_provider",
                "records": [], "summary": summarize_gap([])}
    return {"connected": True, "site": site, "records": records,
            "summary": summarize_gap(records)}


@api.get("/marketing-os/search/content-opportunities")
async def content_opportunities(site_id: Optional[str] = Query(default=None),
                                user=Depends(require_roles(*MARKETING_ROLES))):
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if not site:
            return {"connected": False, "advisory_only": True,
                    "requires_human_approval": True, "opportunities": []}
        records = await _gap_records(pg, site["id"])
    recs = build_phase3_recommendations(gap_records=records)
    return {"connected": bool(records), "advisory_only": True,
            "requires_human_approval": True, "opportunities": recs}


@api.get("/marketing-os/search/backlinks/overview")
async def backlinks_overview(site_id: Optional[str] = Query(default=None),
                             user=Depends(require_roles(*MARKETING_ROLES))):
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if not site:
            return backlink_overview(None, connected=False)
        r = await pg.execute(text(
            "SELECT * FROM marketing_backlink_snapshots WHERE site_id = :s"),
            {"s": site["id"]})
        rows = [_ser(x) for x in r]
    return backlink_overview(rows, connected=bool(rows))


@api.get("/marketing-os/search/backlinks")
async def backlinks_list(site_id: Optional[str] = Query(default=None),
                         limit: int = Query(default=100, ge=1, le=1000),
                         user=Depends(require_roles(*MARKETING_ROLES))):
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if not site:
            return {"connected": False, "backlinks": []}
        r = await pg.execute(text(
            "SELECT * FROM marketing_backlink_snapshots WHERE site_id = :s "
            "ORDER BY last_seen DESC NULLS LAST LIMIT :l"),
            {"s": site["id"], "l": limit})
        rows = [_ser(x) for x in r]
    return {"connected": bool(rows),
            "not_connected_reason":
                None if rows else "no_backlink_provider",
            "backlinks": rows}


@api.get("/marketing-os/search/local")
async def local_seo(site_id: Optional[str] = Query(default=None),
                    user=Depends(require_roles(*MARKETING_ROLES))):
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if not site:
            return {"connected": False, "locations": []}
        r = await pg.execute(text(
            "SELECT * FROM marketing_local_rank_snapshots WHERE site_id = :s "
            "ORDER BY captured_date DESC LIMIT 500"), {"s": site["id"]})
        rows = [_ser(x) for x in r]
    return {"connected": bool(rows),
            "not_connected_reason":
                None if rows else "no_local_data_source",
            "locations": rows}


@api.get("/marketing-os/search/local/opportunities")
async def local_opportunities(site_id: Optional[str] = Query(default=None),
                              user=Depends(require_roles(*MARKETING_ROLES))):
    async with AsyncSessionLocal() as pg:
        site = await _resolve_site(pg, site_id)
        if not site:
            return {"connected": False, "advisory_only": True,
                    "requires_human_approval": True, "opportunities": []}
    # No local provider connected in this phase -> honest empty advisory set.
    recs = build_phase3_recommendations(local_gaps=[])
    return {"connected": False,
            "not_connected_reason": "no_local_data_source",
            "advisory_only": True, "requires_human_approval": True,
            "opportunities": recs}
