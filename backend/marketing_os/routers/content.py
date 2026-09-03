"""Marketing OS — Phase 11 Content + Social Intelligence (draft/planning only).

Absolute guardrails enforced here:
- No autonomous publishing. Drafts/plans/calendar are advisory only.
- No social-provider / blog / email / SMS writes.
- No PHI. No patient/client/clinical FKs.
- Draft generation is deterministic template scaffolds (no LLM in this phase).
- planned_publish_at is planning metadata only — no scheduler/dispatcher.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from deps import api, require_roles
from postgres_db import AsyncSessionLocal
from marketing_os.services.measurement import MarketingDataPolicyError
from marketing_os.services import content_intelligence as ci
from marketing_os.services.content_intelligence import ContentConfigError

MARKETING_ROLES = ("admin", "practitioner")

SAFETY_STATE = {
    "planning_only": True,
    "automatic_publishing": False,
    "social_provider_writes": False,
    "blog_publishing": False,
    "email_sending": False,
    "sms_enabled": False,
    "human_approval_required": True,
    "draft_generation": "deterministic_template",
    "ai_llm_used": False,
    "phi_used": False,
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
    return r


def _cfg(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


async def _one(pg, sql, params):
    return (await pg.execute(text(sql), params)).first()


def _parse_date(v: Optional[str]) -> Optional[date]:
    if v is None or str(v).strip() == "":
        return None
    try:
        return date.fromisoformat(str(v).strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="planned_publish_at must be YYYY-MM-DD") from exc


# --------------------------------------------------------------------------- #
# Deterministic priority scoring
# --------------------------------------------------------------------------- #

def _score_topic(*, metrics: dict, funnel_stage: Optional[str]) -> int:
    seo = ci.seo_opportunity_priority(metrics)
    funnel = ci.funnel_relevance(
        funnel_stage,
        has_offer=bool(metrics.get("has_offer")),
        has_funnel=bool(metrics.get("has_funnel")))
    conversion = ci.conversion_relevance(metrics)
    freshness = ci.freshness_need(metrics.get("days_since_update"))
    return ci.composite_topic_priority(
        seo=seo, funnel=funnel, conversion=conversion, freshness=freshness)


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #

class TopicCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str
    slug: str
    target_keyword: Optional[str] = None
    search_intent: Optional[str] = None
    audience: Optional[str] = None
    funnel_stage: Optional[str] = None
    status: str = "idea"
    source_refs: Optional[dict] = None
    metrics: Optional[dict] = None


class TopicPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Optional[str] = None
    metrics: Optional[dict] = None
    funnel_stage: Optional[str] = None


class BriefCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic_id: Optional[str] = None
    channel: str
    content_type: str
    title: str
    audience: Optional[str] = None
    funnel_stage: Optional[str] = None
    cta: Optional[str] = None
    campaign_theme: Optional[str] = None
    offer_id: Optional[str] = None
    funnel_id: Optional[str] = None
    outline: Optional[dict] = None
    status: str = "planned"


class DraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Draft body is generated deterministically from the brief. Optional
    # overrides let a human tweak the seed inputs (never publishes anything).
    headline_override: Optional[str] = None
    cta_override: Optional[str] = None


class SocialPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: str
    name: str
    campaign_theme: Optional[str] = None
    audience: Optional[str] = None
    cadence: Optional[str] = None
    status: str = "draft"
    config: Optional[dict] = None


class CalendarItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brief_id: Optional[str] = None
    social_plan_id: Optional[str] = None
    channel: str
    title: str
    planned_publish_at: Optional[str] = None
    status: str = "planned"
    metadata: Optional[dict] = None


# --------------------------------------------------------------------------- #
# Topics
# --------------------------------------------------------------------------- #

@api.get("/marketing-os/content/topics")
async def list_topics(status: Optional[str] = Query(None),
                      user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    clauses, params = [], {}
    if status:
        clauses.append("status = :st")
        params["st"] = status
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    async with AsyncSessionLocal() as pg:
        rows = await pg.execute(text(
            f"SELECT * FROM marketing_content_topics {where} "
            "ORDER BY priority DESC, created_at DESC"), params)
        return {"topics": [_ser(r) for r in rows], "safety": SAFETY_STATE}


@api.post("/marketing-os/content/topics", status_code=201)
async def create_topic(payload: TopicCreate,
                       user=Depends(require_roles(*MARKETING_ROLES))):
    try:
        topic = ci.req_str(payload.topic, "topic")
        slug = ci.validate_slug(payload.slug)
        target_keyword = ci.opt_str(payload.target_keyword, "target_keyword")
        audience = ci.opt_str(payload.audience, "audience", max_len=160)
        source_refs = ci.bounded_json(payload.source_refs or {}, "source_refs")
        metrics = ci.bounded_json(payload.metrics or {}, "metrics")
    except (ContentConfigError, MarketingDataPolicyError) as exc:
        raise _cfg(exc) from exc
    if payload.status not in ci.TOPIC_STATUSES:
        raise HTTPException(status_code=422, detail="invalid status")
    intent = payload.search_intent
    if intent is not None and intent not in ci.SEARCH_INTENTS:
        raise HTTPException(status_code=422, detail="invalid search_intent")
    stage = payload.funnel_stage
    if stage is not None and stage not in ci.FUNNEL_STAGES:
        raise HTTPException(status_code=422, detail="invalid funnel_stage")

    priority = _score_topic(metrics=metrics, funnel_stage=stage)
    tid = _new_id()
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            if await _one(pg, "SELECT id FROM marketing_content_topics WHERE "
                              "slug=:s", {"s": slug}):
                raise HTTPException(status_code=409, detail="slug exists")
            row = (await pg.execute(text("""
                INSERT INTO marketing_content_topics
                  (id, topic, slug, target_keyword, search_intent, audience,
                   funnel_stage, priority, status, source_refs, metrics,
                   created_by, created_at, updated_at)
                VALUES (:id, :topic, :slug, :kw, :intent, :aud, :stage, :pri,
                        :status, CAST(:refs AS jsonb), CAST(:metrics AS jsonb),
                        :cb, now(), now())
                RETURNING *
            """), {"id": tid, "topic": topic, "slug": slug,
                   "kw": target_keyword, "intent": intent, "aud": audience,
                   "stage": stage, "pri": priority, "status": payload.status,
                   "refs": json.dumps(source_refs),
                   "metrics": json.dumps(metrics), "cb": _uid(user)})).first()
    return _ser(row)


@api.patch("/marketing-os/content/topics/{topic_id}")
async def patch_topic(topic_id: str, payload: TopicPatch,
                      user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    if payload.status is not None and payload.status not in ci.TOPIC_STATUSES:
        raise HTTPException(status_code=422, detail="invalid status")
    if payload.funnel_stage is not None and \
            payload.funnel_stage not in ci.FUNNEL_STAGES:
        raise HTTPException(status_code=422, detail="invalid funnel_stage")
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            cur = await _one(pg, "SELECT * FROM marketing_content_topics "
                                 "WHERE id=:i", {"i": topic_id})
            if not cur:
                raise HTTPException(status_code=404, detail="topic not found")
            cur = dict(cur._mapping)
            stage = payload.funnel_stage \
                if payload.funnel_stage is not None else cur["funnel_stage"]
            if payload.metrics is not None:
                try:
                    metrics = ci.bounded_json(payload.metrics, "metrics")
                except (ContentConfigError, MarketingDataPolicyError) as exc:
                    raise _cfg(exc) from exc
            else:
                metrics = cur["metrics"] or {}
            priority = _score_topic(metrics=metrics, funnel_stage=stage)
            status = payload.status if payload.status is not None \
                else cur["status"]
            row = (await pg.execute(text("""
                UPDATE marketing_content_topics
                SET status=:status, funnel_stage=:stage,
                    metrics=CAST(:metrics AS jsonb), priority=:pri,
                    updated_at=now()
                WHERE id=:i RETURNING *
            """), {"status": status, "stage": stage,
                   "metrics": json.dumps(metrics), "pri": priority,
                   "i": topic_id})).first()
    return _ser(row)


# --------------------------------------------------------------------------- #
# Briefs
# --------------------------------------------------------------------------- #

@api.get("/marketing-os/content/briefs")
async def list_briefs(channel: Optional[str] = Query(None),
                      topic_id: Optional[str] = Query(None),
                      user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    clauses, params = [], {}
    if channel:
        clauses.append("channel = :ch")
        params["ch"] = channel
    if topic_id:
        clauses.append("topic_id = :tid")
        params["tid"] = topic_id
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    async with AsyncSessionLocal() as pg:
        rows = await pg.execute(text(
            f"SELECT * FROM marketing_content_briefs {where} "
            "ORDER BY created_at DESC"), params)
        return {"briefs": [_ser(r) for r in rows], "safety": SAFETY_STATE}


@api.post("/marketing-os/content/briefs", status_code=201)
async def create_brief(payload: BriefCreate,
                       user=Depends(require_roles(*MARKETING_ROLES))):
    try:
        channel = ci.validate_channel(payload.channel)
        content_type = ci.req_str(payload.content_type, "content_type",
                                  max_len=48)
        title = ci.req_str(payload.title, "title")
        audience = ci.opt_str(payload.audience, "audience", max_len=160)
        cta = ci.opt_str(payload.cta, "cta")
        theme = ci.opt_str(payload.campaign_theme, "campaign_theme", max_len=200)
        outline = ci.bounded_json(payload.outline or {}, "outline")
    except (ContentConfigError, MarketingDataPolicyError) as exc:
        raise _cfg(exc) from exc
    if payload.status not in ci.ITEM_STATUSES:
        raise HTTPException(status_code=422, detail="invalid status")
    stage = payload.funnel_stage
    if stage is not None and stage not in ci.FUNNEL_STAGES:
        raise HTTPException(status_code=422, detail="invalid funnel_stage")

    bid = _new_id()
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            if payload.topic_id and not await _one(
                pg, "SELECT id FROM marketing_content_topics WHERE id=:i",
                {"i": payload.topic_id},
            ):
                raise HTTPException(status_code=422, detail="unknown topic_id")
            if payload.offer_id and not await _one(
                pg, "SELECT id FROM marketing_offers WHERE id=:i",
                {"i": payload.offer_id},
            ):
                raise HTTPException(status_code=422, detail="unknown offer_id")
            if payload.funnel_id and not await _one(
                pg, "SELECT id FROM marketing_funnels WHERE id=:i",
                {"i": payload.funnel_id},
            ):
                raise HTTPException(status_code=422, detail="unknown funnel_id")
            row = (await pg.execute(text("""
                INSERT INTO marketing_content_briefs
                  (id, topic_id, channel, content_type, title, audience,
                   funnel_stage, cta, campaign_theme, offer_id, funnel_id,
                   outline, status, created_by, created_at, updated_at)
                VALUES (:id, :topic, :ch, :ct, :title, :aud, :stage, :cta,
                        :theme, :offer, :funnel, CAST(:outline AS jsonb),
                        :status, :cb, now(), now())
                RETURNING *
            """), {"id": bid, "topic": payload.topic_id, "ch": channel,
                   "ct": content_type, "title": title, "aud": audience,
                   "stage": stage, "cta": cta, "theme": theme,
                   "offer": payload.offer_id, "funnel": payload.funnel_id,
                   "outline": json.dumps(outline), "status": payload.status,
                   "cb": _uid(user)})).first()
    return _ser(row)


# --------------------------------------------------------------------------- #
# Drafts (deterministic scaffolds — never published)
# --------------------------------------------------------------------------- #

@api.get("/marketing-os/content/briefs/{brief_id}/drafts")
async def list_drafts(brief_id: str,
                      user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    async with AsyncSessionLocal() as pg:
        rows = await pg.execute(text(
            "SELECT * FROM marketing_content_drafts WHERE brief_id=:b "
            "ORDER BY created_at DESC"), {"b": brief_id})
        return {"drafts": [_ser(r) for r in rows], "safety": SAFETY_STATE}


@api.post("/marketing-os/content/briefs/{brief_id}/drafts", status_code=201)
async def create_draft(brief_id: str, payload: DraftCreate,
                       user=Depends(require_roles(*MARKETING_ROLES))):
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            brief = await _one(pg, "SELECT * FROM marketing_content_briefs "
                                   "WHERE id=:i", {"i": brief_id})
            if not brief:
                raise HTTPException(status_code=404, detail="brief not found")
            brief = dict(brief._mapping)
            target_keyword = None
            if brief.get("topic_id"):
                trow = await _one(
                    pg, "SELECT target_keyword FROM marketing_content_topics "
                        "WHERE id=:i", {"i": brief["topic_id"]})
                if trow:
                    target_keyword = dict(trow._mapping).get("target_keyword")
            title = payload.headline_override or brief["title"]
            cta = payload.cta_override or brief.get("cta")
            scaffold = ci.generate_draft_scaffold(
                channel=brief["channel"], title=title,
                target_keyword=target_keyword, cta=cta,
                audience=brief.get("audience"))
            did = _new_id()
            row = (await pg.execute(text("""
                INSERT INTO marketing_content_drafts
                  (id, brief_id, channel, headline, body, caption, cta, hook,
                   script, on_screen_text, shot_list, generator, status,
                   created_by, created_at, updated_at)
                VALUES (:id, :b, :ch, :headline, :body, :caption, :cta, :hook,
                        :script, :ost, CAST(:shot AS jsonb), :gen, 'draft',
                        :cb, now(), now())
                RETURNING *
            """), {"id": did, "b": brief_id, "ch": brief["channel"],
                   "headline": scaffold.get("headline"),
                   "body": scaffold.get("body"),
                   "caption": scaffold.get("caption"),
                   "cta": scaffold.get("cta"), "hook": scaffold.get("hook"),
                   "script": scaffold.get("script"),
                   "ost": scaffold.get("on_screen_text"),
                   "shot": json.dumps(scaffold.get("shot_list") or {}),
                   "gen": scaffold.get("generator", "template"),
                   "cb": _uid(user)})).first()
    return _ser(row)


# --------------------------------------------------------------------------- #
# Social plans
# --------------------------------------------------------------------------- #

@api.get("/marketing-os/content/social-plans")
async def list_social_plans(user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    async with AsyncSessionLocal() as pg:
        rows = await pg.execute(text(
            "SELECT * FROM marketing_social_plans ORDER BY created_at DESC"))
        return {"social_plans": [_ser(r) for r in rows], "safety": SAFETY_STATE}


@api.post("/marketing-os/content/social-plans", status_code=201)
async def create_social_plan(payload: SocialPlanCreate,
                             user=Depends(require_roles(*MARKETING_ROLES))):
    try:
        channel = ci.validate_channel(payload.channel)
        name = ci.req_str(payload.name, "name", max_len=200)
        theme = ci.opt_str(payload.campaign_theme, "campaign_theme",
                           max_len=200)
        audience = ci.opt_str(payload.audience, "audience", max_len=160)
        cadence = ci.opt_str(payload.cadence, "cadence", max_len=48)
        config = ci.bounded_json(payload.config or {}, "config")
    except (ContentConfigError, MarketingDataPolicyError) as exc:
        raise _cfg(exc) from exc
    if payload.status not in ci.ITEM_STATUSES:
        raise HTTPException(status_code=422, detail="invalid status")
    sid = _new_id()
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            row = (await pg.execute(text("""
                INSERT INTO marketing_social_plans
                  (id, channel, name, campaign_theme, audience, cadence,
                   status, config, created_by, created_at, updated_at)
                VALUES (:id, :ch, :name, :theme, :aud, :cadence, :status,
                        CAST(:config AS jsonb), :cb, now(), now())
                RETURNING *
            """), {"id": sid, "ch": channel, "name": name, "theme": theme,
                   "aud": audience, "cadence": cadence,
                   "status": payload.status, "config": json.dumps(config),
                   "cb": _uid(user)})).first()
    return _ser(row)


# --------------------------------------------------------------------------- #
# Content calendar (planning metadata only — no scheduler/dispatcher)
# --------------------------------------------------------------------------- #

@api.get("/marketing-os/content/calendar")
async def list_calendar(status: Optional[str] = Query(None),
                        user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    clauses, params = [], {}
    if status:
        clauses.append("status = :st")
        params["st"] = status
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    async with AsyncSessionLocal() as pg:
        rows = await pg.execute(text(
            f"SELECT * FROM marketing_content_calendar_items {where} "
            "ORDER BY planned_publish_at ASC NULLS LAST, created_at DESC"),
            params)
        return {"items": [_ser(r) for r in rows], "safety": SAFETY_STATE}


@api.post("/marketing-os/content/calendar", status_code=201)
async def create_calendar_item(payload: CalendarItemCreate,
                               user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    try:
        channel = ci.validate_channel(payload.channel)
        title = ci.req_str(payload.title, "title")
        meta = ci.bounded_json(payload.metadata or {}, "metadata")
    except (ContentConfigError, MarketingDataPolicyError) as exc:
        raise _cfg(exc) from exc
    if payload.status not in ci.ITEM_STATUSES:
        raise HTTPException(status_code=422, detail="invalid status")
    when = _parse_date(payload.planned_publish_at)
    cid = _new_id()
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            if payload.brief_id and not await _one(
                pg, "SELECT id FROM marketing_content_briefs WHERE id=:i",
                {"i": payload.brief_id},
            ):
                raise HTTPException(status_code=422, detail="unknown brief_id")
            if payload.social_plan_id and not await _one(
                pg, "SELECT id FROM marketing_social_plans WHERE id=:i",
                {"i": payload.social_plan_id},
            ):
                raise HTTPException(status_code=422,
                                    detail="unknown social_plan_id")
            if payload.brief_id and await _one(
                pg, "SELECT id FROM marketing_content_calendar_items WHERE "
                    "brief_id=:b", {"b": payload.brief_id},
            ):
                raise HTTPException(status_code=409,
                                    detail="brief already on calendar")
            row = (await pg.execute(text("""
                INSERT INTO marketing_content_calendar_items
                  (id, brief_id, social_plan_id, channel, title,
                   planned_publish_at, status, metadata, created_at,
                   updated_at)
                VALUES (:id, :b, :sp, :ch, :title, :when, :status,
                        CAST(:meta AS jsonb), now(), now())
                RETURNING *
            """), {"id": cid, "b": payload.brief_id,
                   "sp": payload.social_plan_id, "ch": channel, "title": title,
                   "when": when, "status": payload.status,
                   "meta": json.dumps(meta)})).first()
    return _ser(row)


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #

@api.get("/marketing-os/content/overview")
async def content_overview(user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    async with AsyncSessionLocal() as pg:
        async def _count(table):
            r = await _one(pg, f"SELECT count(*) AS n FROM {table}", {})
            return int(r._mapping["n"]) if r else 0
        counts = {
            "topics": await _count("marketing_content_topics"),
            "briefs": await _count("marketing_content_briefs"),
            "drafts": await _count("marketing_content_drafts"),
            "social_plans": await _count("marketing_social_plans"),
            "calendar_items": await _count("marketing_content_calendar_items"),
        }
        top = await pg.execute(text(
            "SELECT * FROM marketing_content_topics "
            "ORDER BY priority DESC, created_at DESC LIMIT 5"))
        return {"counts": counts, "channels": list(ci.CHANNELS),
                "top_topics": [_ser(r) for r in top], "safety": SAFETY_STATE}
