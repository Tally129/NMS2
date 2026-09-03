"""Marketing OS — Phase 10 Reputation + Local Growth API (read-only intel).

No automatic listing/review writes, no provider writes, no PHI, no SMS. Staff
ingest sanitized aggregate snapshots; the system derives deterministic scores
and advisory opportunities only.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from deps import api, require_roles
from postgres_db import AsyncSessionLocal
from marketing_os.services.measurement import MarketingDataPolicyError
from marketing_os.services import local_growth as lg
from marketing_os.services.local_growth import LocalConfigError

MARKETING_ROLES = ("admin", "practitioner")

SAFETY_STATE = {
    "read_only_intelligence": True,
    "automatic_review_posting": False,
    "automatic_review_replies": False,
    "automatic_listing_edits": False,
    "external_writes": False,
    "human_approval_required": True,
    "ai_advisory_only": True,
    "phi_used": False,
    "sms_enabled": False,
}


def _new_id() -> str:
    return uuid.uuid4().hex


def _uid(u: dict) -> Optional[str]:
    return str(u.get("id")) if u.get("id") else None


def _ser(row) -> dict[str, Any]:
    r = dict(row._mapping)
    for k, v in list(r.items()):
        if isinstance(v, Decimal):
            r[k] = float(v)
        elif isinstance(v, (date, datetime)):
            r[k] = v.isoformat()
    if "metadata_json" in r and "metadata" not in r:
        r["metadata"] = r.pop("metadata_json")
    return r


def _cfg(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


async def _one(pg, sql, params):
    return (await pg.execute(text(sql), params)).first()


class LocationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    slug: str
    site_id: Optional[str] = None
    address_line: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    phone: Optional[str] = None
    website_url: Optional[str] = None
    primary_category: Optional[str] = None
    hours: Optional[dict] = None
    config: Optional[dict] = None


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    external_ref: Optional[str] = None
    listing_url: Optional[str] = None
    is_active: bool = True
    config: Optional[dict] = None


class ReputationSnapshotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    captured_date: str
    rating: Optional[float] = None
    review_count: Optional[int] = None
    reviews_last_30d: Optional[int] = None
    response_rate: Optional[float] = None
    avg_response_hours: Optional[float] = None
    unanswered_count: Optional[int] = None
    metadata: Optional[dict] = None


class ListingSnapshotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    captured_date: str
    listing_status: str = "unknown"
    name_matches: Optional[bool] = None
    address_matches: Optional[bool] = None
    phone_matches: Optional[bool] = None
    category_matches: Optional[bool] = None
    website_matches: Optional[bool] = None
    hours_present: Optional[bool] = None
    fields_present: Optional[dict] = None
    metadata: Optional[dict] = None


# --------------------------------------------------------------------------- #
# Locations
# --------------------------------------------------------------------------- #

@api.get("/marketing-os/local/locations")
async def list_locations(user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    async with AsyncSessionLocal() as pg:
        rows = await pg.execute(text(
            "SELECT * FROM marketing_locations ORDER BY created_at DESC"))
        return {"locations": [_ser(r) for r in rows], "safety": SAFETY_STATE}


@api.post("/marketing-os/local/locations", status_code=201)
async def create_location(payload: LocationCreate,
                          user=Depends(require_roles(*MARKETING_ROLES))):
    try:
        name = lg._req_str(payload.name, "name", max_len=lg.MAX_NAME_LEN)
        slug = lg.validate_slug(payload.slug)
        hours = lg.bounded_json(payload.hours or {}, "hours")
        config = lg.bounded_json(payload.config or {}, "config")
    except (LocalConfigError, MarketingDataPolicyError) as exc:
        raise _cfg(exc) from exc
    lid = _new_id()
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            if await _one(pg, "SELECT id FROM marketing_locations WHERE "
                              "slug=:s", {"s": slug}):
                raise HTTPException(status_code=409, detail="slug exists")
            if payload.site_id and not await _one(
                pg, "SELECT id FROM marketing_search_sites WHERE id=:i",
                {"i": payload.site_id},
            ):
                raise HTTPException(status_code=422, detail="unknown site_id")
            row = (await pg.execute(text("""
                INSERT INTO marketing_locations
                  (id, site_id, name, slug, status, address_line, city, state,
                   postal_code, country, phone, website_url, primary_category,
                   hours, config, created_by, created_at, updated_at)
                VALUES
                  (:id, :site_id, :name, :slug, 'active', :addr, :city, :state,
                   :zip, :country, :phone, :web, :cat, CAST(:hours AS jsonb),
                   CAST(:config AS jsonb), :cb, now(), now())
                RETURNING *
            """), {"id": lid, "site_id": payload.site_id, "name": name,
                   "slug": slug, "addr": payload.address_line,
                   "city": payload.city, "state": payload.state,
                   "zip": payload.postal_code, "country": payload.country,
                   "phone": payload.phone, "web": payload.website_url,
                   "cat": payload.primary_category, "hours": json.dumps(hours),
                   "config": json.dumps(config), "cb": _uid(user)})).first()
    return _ser(row)


@api.post("/marketing-os/local/locations/{location_id}/sources",
          status_code=201)
async def add_source(location_id: str, payload: SourceCreate,
                     user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    try:
        provider = lg.validate_provider(payload.provider)
        config = lg.bounded_json(payload.config or {}, "config")
    except (LocalConfigError, MarketingDataPolicyError) as exc:
        raise _cfg(exc) from exc
    sid = _new_id()
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            if not await _one(pg, "SELECT id FROM marketing_locations WHERE "
                                  "id=:i", {"i": location_id}):
                raise HTTPException(status_code=404, detail="location not found")
            if await _one(pg, "SELECT id FROM marketing_reputation_sources "
                              "WHERE location_id=:l AND provider=:p",
                          {"l": location_id, "p": provider}):
                raise HTTPException(status_code=409, detail="provider exists")
            row = (await pg.execute(text("""
                INSERT INTO marketing_reputation_sources
                  (id, location_id, provider, external_ref, listing_url,
                   is_active, config, created_at, updated_at)
                VALUES (:id, :l, :p, :ref, :url, :active,
                        CAST(:config AS jsonb), now(), now())
                RETURNING *
            """), {"id": sid, "l": location_id, "p": provider,
                   "ref": payload.external_ref, "url": payload.listing_url,
                   "active": payload.is_active,
                   "config": json.dumps(config)})).first()
    return _ser(row)


def _parse_date(v: str) -> date:
    try:
        return date.fromisoformat(str(v).strip())
    except ValueError as exc:
        raise HTTPException(status_code=422,
                            detail="captured_date must be YYYY-MM-DD") from exc


async def _source_for(pg, location_id, source_id):
    s = await _one(pg, "SELECT id, provider FROM marketing_reputation_sources "
                       "WHERE id=:s AND location_id=:l",
                   {"s": source_id, "l": location_id})
    if not s:
        raise HTTPException(status_code=422,
                            detail="source_id not found for this location")
    return dict(s._mapping)


@api.post("/marketing-os/local/locations/{location_id}/reputation-snapshots",
          status_code=201)
async def add_reputation_snapshot(location_id: str,
                                  payload: ReputationSnapshotCreate,
                                  user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    cap = _parse_date(payload.captured_date)
    try:
        meta = lg.bounded_json(payload.metadata or {}, "metadata")
    except (LocalConfigError, MarketingDataPolicyError) as exc:
        raise _cfg(exc) from exc
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            src = await _source_for(pg, location_id, payload.source_id)
            row = (await pg.execute(text("""
                INSERT INTO marketing_reputation_snapshots
                  (id, location_id, source_id, provider, captured_date, rating,
                   review_count, reviews_last_30d, response_rate,
                   avg_response_hours, unanswered_count, metadata,
                   created_at, updated_at)
                VALUES (:id, :l, :s, :p, :d, :rating, :rc, :r30, :rr, :arh,
                        :un, CAST(:meta AS jsonb), now(), now())
                ON CONFLICT (source_id, captured_date) DO UPDATE SET
                  rating=EXCLUDED.rating, review_count=EXCLUDED.review_count,
                  reviews_last_30d=EXCLUDED.reviews_last_30d,
                  response_rate=EXCLUDED.response_rate,
                  avg_response_hours=EXCLUDED.avg_response_hours,
                  unanswered_count=EXCLUDED.unanswered_count,
                  metadata=EXCLUDED.metadata, updated_at=now()
                RETURNING *
            """), {"id": _new_id(), "l": location_id, "s": src["id"],
                   "p": src["provider"], "d": cap, "rating": payload.rating,
                   "rc": payload.review_count, "r30": payload.reviews_last_30d,
                   "rr": payload.response_rate,
                   "arh": payload.avg_response_hours,
                   "un": payload.unanswered_count,
                   "meta": json.dumps(meta)})).first()
    return _ser(row)


@api.post("/marketing-os/local/locations/{location_id}/listing-snapshots",
          status_code=201)
async def add_listing_snapshot(location_id: str, payload: ListingSnapshotCreate,
                               user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    cap = _parse_date(payload.captured_date)
    if payload.listing_status not in lg.LISTING_STATUSES:
        raise HTTPException(status_code=422, detail="invalid listing_status")
    try:
        fields = lg.validate_fields_present(payload.fields_present or {})
        meta = lg.bounded_json(payload.metadata or {}, "metadata")
    except (LocalConfigError, MarketingDataPolicyError) as exc:
        raise _cfg(exc) from exc
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            src = await _source_for(pg, location_id, payload.source_id)
            row = (await pg.execute(text("""
                INSERT INTO marketing_local_listing_snapshots
                  (id, location_id, source_id, provider, captured_date,
                   listing_status, name_matches, address_matches,
                   phone_matches, category_matches, website_matches,
                   hours_present, fields_present, metadata,
                   created_at, updated_at)
                VALUES (:id, :l, :s, :p, :d, :st, :nm, :am, :pm, :cm, :wm, :hp,
                        CAST(:fp AS jsonb), CAST(:meta AS jsonb), now(), now())
                ON CONFLICT (source_id, captured_date) DO UPDATE SET
                  listing_status=EXCLUDED.listing_status,
                  name_matches=EXCLUDED.name_matches,
                  address_matches=EXCLUDED.address_matches,
                  phone_matches=EXCLUDED.phone_matches,
                  category_matches=EXCLUDED.category_matches,
                  website_matches=EXCLUDED.website_matches,
                  hours_present=EXCLUDED.hours_present,
                  fields_present=EXCLUDED.fields_present,
                  metadata=EXCLUDED.metadata, updated_at=now()
                RETURNING *
            """), {"id": _new_id(), "l": location_id, "s": src["id"],
                   "p": src["provider"], "d": cap,
                   "st": payload.listing_status, "nm": payload.name_matches,
                   "am": payload.address_matches, "pm": payload.phone_matches,
                   "cm": payload.category_matches,
                   "wm": payload.website_matches, "hp": payload.hours_present,
                   "fp": json.dumps(fields), "meta": json.dumps(meta)})).first()
    return _ser(row)


# --------------------------------------------------------------------------- #
# Deterministic health + opportunities
# --------------------------------------------------------------------------- #

async def _latest_by_provider(pg, table, location_id):
    rows = await pg.execute(text(f"""
        SELECT DISTINCT ON (source_id) * FROM {table}
        WHERE location_id = :l ORDER BY source_id, captured_date DESC
    """), {"l": location_id})
    return {r._mapping["provider"]: _ser(r) for r in rows}


async def _compute_health(pg, location: dict):
    lid = location["id"]
    src_rows = await pg.execute(text(
        "SELECT provider FROM marketing_reputation_sources "
        "WHERE location_id=:l AND is_active=true"), {"l": lid})
    active_providers = [r._mapping["provider"] for r in src_rows]
    latest_rep = await _latest_by_provider(
        pg, "marketing_reputation_snapshots", lid)
    latest_listing = await _latest_by_provider(
        pg, "marketing_local_listing_snapshots", lid)

    rank_row = await _one(pg, "SELECT min(local_rank) AS best FROM "
                              "marketing_local_rank_snapshots WHERE "
                              "location_id=:l AND local_rank IS NOT NULL",
                          {"l": lid})
    best_rank = rank_row._mapping["best"] if rank_row else None

    # Aggregate best reputation figures across sources for the headline score.
    ratings = [r.get("rating") for r in latest_rep.values()
               if r.get("rating") is not None]
    best_rating = max(ratings) if ratings else None
    total_reviews = sum(int(r.get("review_count") or 0)
                        for r in latest_rep.values())
    velocity = max((int(r.get("reviews_last_30d") or 0)
                    for r in latest_rep.values()), default=0)
    resp_rates = [r.get("response_rate") for r in latest_rep.values()
                  if r.get("response_rate") is not None]
    best_resp = max(resp_rates) if resp_rates else None

    completeness_vals = [lg.listing_completeness_score(x.get("fields_present")
                         or {}) for x in latest_listing.values()]
    completeness = round(sum(completeness_vals) / len(completeness_vals), 4) \
        if completeness_vals else 0.0
    nap_vals = [lg.nap_consistency_score(x) for x in latest_listing.values()]
    nap = round(sum(nap_vals) / len(nap_vals), 4) if nap_vals else 0.0

    velocity_class = lg.classify_review_velocity(velocity)
    health = lg.location_health_score(
        completeness=completeness, nap=nap, rating=best_rating,
        review_velocity_class=velocity_class, response_rate=best_resp)
    coverage = lg.source_coverage(active_providers)
    opportunities = lg.build_opportunities(
        location=location, active_providers=active_providers,
        latest_reputation=latest_rep, latest_listing=latest_listing,
        best_local_rank=best_rank)
    return {
        "location_id": lid,
        "health_score": health,
        "listing_completeness": completeness,
        "nap_consistency": nap,
        "best_rating": best_rating,
        "total_reviews": total_reviews,
        "review_velocity": velocity,
        "review_velocity_class": velocity_class,
        "best_response_rate": best_resp,
        "best_local_rank": best_rank,
        "source_coverage": coverage,
        "opportunities": opportunities,
    }


@api.get("/marketing-os/local/locations/{location_id}/health")
async def location_health(location_id: str,
                          user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    async with AsyncSessionLocal() as pg:
        loc = await _one(pg, "SELECT * FROM marketing_locations WHERE id=:i",
                         {"i": location_id})
        if not loc:
            raise HTTPException(status_code=404, detail="location not found")
        result = await _compute_health(pg, _ser(loc))
        result["safety"] = SAFETY_STATE
        return result


@api.post("/marketing-os/local/locations/{location_id}/opportunities/recompute")
async def recompute_opportunities(location_id: str,
                                  user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            loc = await _one(pg, "SELECT * FROM marketing_locations WHERE "
                                 "id=:i", {"i": location_id})
            if not loc:
                raise HTTPException(status_code=404,
                                    detail="location not found")
            health = await _compute_health(pg, _ser(loc))
            # Refresh open (non-actioned/dismissed) opportunities deterministly.
            await pg.execute(text(
                "DELETE FROM marketing_local_opportunities WHERE "
                "location_id=:l AND status='open'"), {"l": location_id})
            for o in health["opportunities"]:
                await pg.execute(text("""
                    INSERT INTO marketing_local_opportunities
                      (id, location_id, opportunity_key, opportunity_type,
                       severity, priority, title, detail, status, evidence,
                       created_at, updated_at)
                    VALUES (:id, :l, :k, :t, :sev, :pri, :title, :detail,
                            'open', CAST(:ev AS jsonb), now(), now())
                    ON CONFLICT (location_id, opportunity_key) DO UPDATE SET
                      severity=EXCLUDED.severity, priority=EXCLUDED.priority,
                      title=EXCLUDED.title, detail=EXCLUDED.detail,
                      evidence=EXCLUDED.evidence, status='open',
                      updated_at=now()
                """), {"id": _new_id(), "l": location_id,
                       "k": o["opportunity_key"], "t": o["opportunity_type"],
                       "sev": o["severity"], "pri": o["priority"],
                       "title": o["title"], "detail": o["detail"],
                       "ev": json.dumps(o["evidence"])})
        return {"location_id": location_id,
                "opportunities_written": len(health["opportunities"]),
                "safety": SAFETY_STATE}


@api.get("/marketing-os/local/locations/{location_id}/opportunities")
async def list_opportunities(location_id: str,
                             status: Optional[str] = Query(None),
                             user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    clauses = ["location_id = :l"]
    params = {"l": location_id}
    if status:
        clauses.append("status = :st")
        params["st"] = status
    async with AsyncSessionLocal() as pg:
        rows = await pg.execute(text(
            f"SELECT * FROM marketing_local_opportunities "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY priority DESC, opportunity_key ASC"), params)
        return {"opportunities": [_ser(r) for r in rows]}


@api.get("/marketing-os/local/reputation-overview")
async def reputation_overview(user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    async with AsyncSessionLocal() as pg:
        locs = await pg.execute(text(
            "SELECT * FROM marketing_locations WHERE status='active' "
            "ORDER BY name ASC"))
        locations = [_ser(r) for r in locs]
        summaries = []
        for loc in locations:
            summaries.append(await _compute_health(pg, loc))
        return {"locations": locations, "summaries": summaries,
                "safety": SAFETY_STATE}
