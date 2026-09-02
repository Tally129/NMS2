"""
AI Content Strategist.

Persistent, draft-only marketing strategy workspace.

This module:
- stores strategy briefs and conversation history;
- generates structured marketing plans through Amazon Bedrock;
- stores reusable content assets;
- stages approved content for controlled publishing;
- supports scheduled publishing through a human-approved queue;
- never reads patient records or recipient lists.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from audit import get_client_ip, log_audit
from deps import _strip_id, api, db, require_roles
from llm_client import (
    PromptTemplate,
    run_template,
    safe_extract_json,
)
from models import new_id


_STRATEGIST_ROLES = (
    "admin",
    "practitioner",
    "staff",
    "medical_assistant",
    "front_desk",
    "frontdesk",
    "auditor",
)

_ALLOWED_CHANNELS = {
    "email",
    "instagram",
    "facebook",
    "tiktok",
    "linkedin",
    "threads",
    "blog",
    "website",
    "short_video",
    "push_notification",
}

_ALLOWED_DURATIONS = {7, 14, 30, 60, 90}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_string_list(
    values: Optional[List[str]],
    *,
    max_items: int = 30,
    max_length: int = 200,
) -> List[str]:
    output: List[str] = []

    for value in values or []:
        cleaned = str(value or "").strip()[:max_length]

        if cleaned and cleaned not in output:
            output.append(cleaned)

        if len(output) >= max_items:
            break

    return output


class StrategyCreateIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=180)
    goal: str = Field(..., min_length=3, max_length=1000)
    services: List[str] = Field(default_factory=list, max_length=30)
    audiences: List[str] = Field(default_factory=list, max_length=30)
    brand_voice: List[str] = Field(default_factory=list, max_length=20)
    channels: List[str] = Field(default_factory=list, max_length=15)
    duration_days: int = Field(default=30)
    posts_per_week: int = Field(default=4, ge=0, le=21)
    emails_per_month: int = Field(default=2, ge=0, le=20)
    objective_notes: Optional[str] = Field(default=None, max_length=2000)
    call_to_action: Optional[str] = Field(default=None, max_length=300)
    offer_details: Optional[str] = Field(default=None, max_length=1500)
    compliance_notes: Optional[str] = Field(default=None, max_length=2000)


class StrategyPatchIn(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=180)
    goal: Optional[str] = Field(default=None, min_length=3, max_length=1000)
    services: Optional[List[str]] = None
    audiences: Optional[List[str]] = None
    brand_voice: Optional[List[str]] = None
    channels: Optional[List[str]] = None
    duration_days: Optional[int] = None
    posts_per_week: Optional[int] = Field(default=None, ge=0, le=21)
    emails_per_month: Optional[int] = Field(default=None, ge=0, le=20)
    objective_notes: Optional[str] = Field(default=None, max_length=2000)
    call_to_action: Optional[str] = Field(default=None, max_length=300)
    offer_details: Optional[str] = Field(default=None, max_length=1500)
    compliance_notes: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[str] = Field(default=None, max_length=32)


class StrategyMessageIn(BaseModel):
    body: str = Field(..., min_length=1, max_length=5000)


class ContentAssetCreateIn(BaseModel):
    strategy_id: Optional[str] = None
    content_type: str = Field(..., min_length=2, max_length=64)
    title: str = Field(..., min_length=2, max_length=200)
    body: str = Field(..., min_length=1, max_length=30000)
    subject: Optional[str] = Field(default=None, max_length=250)
    platform: Optional[str] = Field(default=None, max_length=64)
    status: str = Field(default="draft", max_length=32)
    tags: List[str] = Field(default_factory=list, max_length=30)
    metadata: Dict[str, Any] = Field(default_factory=dict)


STRATEGIST_TEMPLATE = PromptTemplate(
    feature="content_strategist",
    system=(
        "You are the senior content strategist for a wellness and functional "
        "medicine clinic. Create a practical, coordinated marketing strategy. "
        "Draft only; a human must review and approve every recommendation.\n\n"
        "Compliance rules:\n"
        "- Never guarantee results or make cure claims.\n"
        "- Never invent prices, services, credentials, statistics, patient "
        "stories, testimonials, or clinical outcomes.\n"
        "- Do not provide individualized medical advice.\n"
        "- Use educational, wellness-oriented language.\n"
        "- Flag claims, promotions, or disclaimers that require human review.\n"
        "- Do not request or infer patient information or PHI.\n\n"
        "Return STRICT JSON only with this shape:\n"
        "{\n"
        '  "executive_summary": "",\n'
        '  "primary_goal": "",\n'
        '  "audience_insights": [],\n'
        '  "positioning": "",\n'
        '  "campaign_themes": [],\n'
        '  "weekly_plan": [\n'
        "    {\n"
        '      "week": 1,\n'
        '      "objective": "",\n'
        '      "theme": "",\n'
        '      "email_topics": [],\n'
        '      "social_topics": [],\n'
        '      "blog_topics": [],\n'
        '      "video_topics": [],\n'
        '      "calls_to_action": []\n'
        "    }\n"
        "  ],\n"
        '  "content_calendar": [\n'
        "    {\n"
        '      "day_or_date": "",\n'
        '      "channel": "",\n'
        '      "content_type": "",\n'
        '      "topic": "",\n'
        '      "objective": "",\n'
        '      "call_to_action": ""\n'
        "    }\n"
        "  ],\n"
        '  "email_campaign_ideas": [],\n'
        '  "social_series_ideas": [],\n'
        '  "blog_ideas": [],\n'
        '  "short_video_ideas": [],\n'
        '  "recommended_offers": [],\n'
        '  "success_metrics": [],\n'
        '  "compliance_considerations": [],\n'
        '  "next_actions": [],\n'
        '  "human_review_required": true\n'
        "}"
    ),
    max_tokens=4096,
    temperature=0.35,
)


def _build_strategy_prompt(strategy: dict) -> str:
    lines = [
        f"Strategy name: {strategy.get('name') or 'Untitled strategy'}",
        f"Business goal: {strategy.get('goal') or ''}",
        f"Duration: {strategy.get('duration_days') or 30} days",
        f"Posts per week: {strategy.get('posts_per_week') or 0}",
        f"Emails per month: {strategy.get('emails_per_month') or 0}",
    ]

    for label, key in (
        ("Clinic services", "services"),
        ("Generalized audiences", "audiences"),
        ("Brand voice", "brand_voice"),
        ("Channels", "channels"),
    ):
        values = strategy.get(key) or []

        if values:
            lines.append(f"{label}: {', '.join(values)}")

    for label, key in (
        ("Additional objective notes", "objective_notes"),
        ("Preferred call to action", "call_to_action"),
        ("Offer details supplied by clinic", "offer_details"),
        ("Compliance notes supplied by clinic", "compliance_notes"),
    ):
        value = strategy.get(key)

        if value:
            lines.append(f"{label}: {str(value)[:2000]}")

    messages = strategy.get("messages") or []

    if messages:
        lines.append("Recent strategy conversation:")

        for message in messages[-12:]:
            role = message.get("role") or "user"
            body = str(message.get("body") or "")[:1500]
            lines.append(f"- {role}: {body}")

    lines.extend([
        "",
        "Create a coordinated strategy using only the clinic-supplied facts.",
        "Return the strict JSON strategy now.",
    ])

    return "\n".join(lines)


def _validate_plan(data: Optional[dict]) -> dict:
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "invalid_model_response",
                "message": "The strategist response could not be parsed.",
            },
        )

    def text(value: Any, cap: int) -> str:
        return str(value or "")[:cap]

    def string_list(
        value: Any,
        *,
        max_items: int = 40,
        max_length: int = 1000,
    ) -> List[str]:
        if not isinstance(value, list):
            return []

        result: List[str] = []

        for item in value[:max_items]:
            if isinstance(item, (str, int, float)):
                result.append(str(item)[:max_length])

        return result

    weekly_plan = []

    for item in (data.get("weekly_plan") or [])[:14]:
        if not isinstance(item, dict):
            continue

        weekly_plan.append({
            "week": int(item.get("week") or len(weekly_plan) + 1),
            "objective": text(item.get("objective"), 600),
            "theme": text(item.get("theme"), 300),
            "email_topics": string_list(item.get("email_topics")),
            "social_topics": string_list(item.get("social_topics")),
            "blog_topics": string_list(item.get("blog_topics")),
            "video_topics": string_list(item.get("video_topics")),
            "calls_to_action": string_list(item.get("calls_to_action")),
        })

    calendar = []

    for item in (data.get("content_calendar") or [])[:100]:
        if not isinstance(item, dict):
            continue

        calendar.append({
            "day_or_date": text(item.get("day_or_date"), 100),
            "channel": text(item.get("channel"), 64),
            "content_type": text(item.get("content_type"), 64),
            "topic": text(item.get("topic"), 500),
            "objective": text(item.get("objective"), 500),
            "call_to_action": text(item.get("call_to_action"), 300),
        })

    return {
        "executive_summary": text(data.get("executive_summary"), 3000),
        "primary_goal": text(data.get("primary_goal"), 1000),
        "audience_insights": string_list(data.get("audience_insights")),
        "positioning": text(data.get("positioning"), 2000),
        "campaign_themes": string_list(data.get("campaign_themes")),
        "weekly_plan": weekly_plan,
        "content_calendar": calendar,
        "email_campaign_ideas": string_list(data.get("email_campaign_ideas")),
        "social_series_ideas": string_list(data.get("social_series_ideas")),
        "blog_ideas": string_list(data.get("blog_ideas")),
        "short_video_ideas": string_list(data.get("short_video_ideas")),
        "recommended_offers": string_list(data.get("recommended_offers")),
        "success_metrics": string_list(data.get("success_metrics")),
        "compliance_considerations": string_list(
            data.get("compliance_considerations")
        ),
        "next_actions": string_list(data.get("next_actions")),
        "human_review_required": True,
    }


@api.post("/content-strategies")
async def create_content_strategy(
    payload: StrategyCreateIn,
    request: Request,
    user=Depends(require_roles(*_STRATEGIST_ROLES)),
):
    if payload.duration_days not in _ALLOWED_DURATIONS:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_duration",
                "allowed": sorted(_ALLOWED_DURATIONS),
            },
        )

    invalid_channels = [
        channel
        for channel in payload.channels
        if channel not in _ALLOWED_CHANNELS
    ]

    if invalid_channels:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_channels",
                "channels": invalid_channels,
            },
        )

    now = _now()

    doc = {
        "id": new_id(),
        "name": payload.name.strip(),
        "goal": payload.goal.strip(),
        "services": _clean_string_list(payload.services),
        "audiences": _clean_string_list(payload.audiences),
        "brand_voice": _clean_string_list(payload.brand_voice),
        "channels": _clean_string_list(payload.channels),
        "duration_days": payload.duration_days,
        "posts_per_week": payload.posts_per_week,
        "emails_per_month": payload.emails_per_month,
        "objective_notes": payload.objective_notes,
        "call_to_action": payload.call_to_action,
        "offer_details": payload.offer_details,
        "compliance_notes": payload.compliance_notes,
        "status": "draft",
        "messages": [],
        "plan": None,
        "generation_history": [],
        "human_review_required": True,
        "created_by": user["id"],
        "created_by_name": user.get("full_name") or user.get("email"),
        "created_at": now,
        "updated_at": now,
    }

    await db.content_strategies.insert_one(doc)

    await log_audit(
        db,
        user["id"],
        user["email"],
        "content_strategy.create",
        resource_type="content_strategy",
        resource_id=doc["id"],
        metadata={
            "duration_days": payload.duration_days,
            "channel_count": len(doc["channels"]),
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return _strip_id(doc)


@api.get("/content-strategies")
async def list_content_strategies(
    status: Optional[str] = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    user=Depends(require_roles(*_STRATEGIST_ROLES)),
):
    query = {}

    if status:
        query["status"] = status

    rows = (
        await db.content_strategies
        .find(query)
        .sort("updated_at", -1)
        .limit(limit)
        .to_list(limit)
    )

    return [_strip_id(row) for row in rows]


@api.get("/content-strategies/{strategy_id}")
async def get_content_strategy(
    strategy_id: str,
    user=Depends(require_roles(*_STRATEGIST_ROLES)),
):
    strategy = await db.content_strategies.find_one({"id": strategy_id})

    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    return _strip_id(strategy)


@api.patch("/content-strategies/{strategy_id}")
async def update_content_strategy(
    strategy_id: str,
    payload: StrategyPatchIn,
    request: Request,
    user=Depends(require_roles(*_STRATEGIST_ROLES)),
):
    existing = await db.content_strategies.find_one({"id": strategy_id})

    if not existing:
        raise HTTPException(status_code=404, detail="Strategy not found")

    updates = payload.model_dump(exclude_unset=True)

    if "duration_days" in updates:
        if updates["duration_days"] not in _ALLOWED_DURATIONS:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "invalid_duration",
                    "allowed": sorted(_ALLOWED_DURATIONS),
                },
            )

    if "channels" in updates:
        invalid = [
            channel
            for channel in updates["channels"]
            if channel not in _ALLOWED_CHANNELS
        ]

        if invalid:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "invalid_channels",
                    "channels": invalid,
                },
            )

    for key in (
        "services",
        "audiences",
        "brand_voice",
        "channels",
    ):
        if key in updates:
            updates[key] = _clean_string_list(updates[key])

    updates["updated_at"] = _now()
    updates["updated_by"] = user["id"]

    await db.content_strategies.update_one(
        {"id": strategy_id},
        {"$set": updates},
    )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "content_strategy.update",
        resource_type="content_strategy",
        resource_id=strategy_id,
        metadata={"fields": sorted(updates.keys())},
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return _strip_id(
        await db.content_strategies.find_one({"id": strategy_id})
    )


@api.post("/content-strategies/{strategy_id}/messages")
async def add_strategy_message(
    strategy_id: str,
    payload: StrategyMessageIn,
    request: Request,
    user=Depends(require_roles(*_STRATEGIST_ROLES)),
):
    strategy = await db.content_strategies.find_one({"id": strategy_id})

    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    message = {
        "id": new_id(),
        "role": "user",
        "body": payload.body.strip(),
        "created_by": user["id"],
        "created_by_name": user.get("full_name") or user.get("email"),
        "created_at": _now(),
    }

    await db.content_strategies.update_one(
        {"id": strategy_id},
        {
            "$push": {"messages": message},
            "$set": {
                "updated_at": _now(),
                "updated_by": user["id"],
            },
        },
    )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "content_strategy.message_add",
        resource_type="content_strategy",
        resource_id=strategy_id,
        metadata={"message_id": message["id"]},
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return message


@api.post("/content-strategies/{strategy_id}/generate")
async def generate_content_strategy(
    strategy_id: str,
    request: Request,
    user=Depends(require_roles(*_STRATEGIST_ROLES)),
):
    strategy = await db.content_strategies.find_one({"id": strategy_id})

    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    started = _now()

    try:
        raw = await run_template(
            STRATEGIST_TEMPLATE,
            _build_strategy_prompt(strategy),
            session_id=f"content-strategy.{strategy_id}",
        )
    except RuntimeError as exc:
        code = str(exc)
        status = 503 if code in {
            "ai_disabled",
            "bedrock_misconfigured",
            "bedrock_unavailable",
            "model_access_denied",
            "request_timeout",
        } else 502

        raise HTTPException(
            status_code=status,
            detail={"code": code},
        )

    plan = _validate_plan(safe_extract_json(raw))
    generated_at = _now()

    generation = {
        "id": new_id(),
        "generated_at": generated_at,
        "generated_by": user["id"],
        "generated_by_name": user.get("full_name") or user.get("email"),
        "plan": plan,
    }

    assistant_message = {
        "id": new_id(),
        "role": "assistant",
        "body": plan.get("executive_summary") or "Strategy plan generated.",
        "created_at": generated_at,
        "generation_id": generation["id"],
    }

    await db.content_strategies.update_one(
        {"id": strategy_id},
        {
            "$set": {
                "plan": plan,
                "status": "generated",
                "last_generated_at": generated_at,
                "updated_at": generated_at,
                "updated_by": user["id"],
                "human_review_required": True,
            },
            "$push": {
                "generation_history": generation,
                "messages": assistant_message,
            },
        },
    )

    latency_ms = int(
        (generated_at - started).total_seconds() * 1000
    )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "content_strategy.generate",
        resource_type="content_strategy",
        resource_id=strategy_id,
        metadata={
            "generation_id": generation["id"],
            "latency_ms": latency_ms,
            "duration_days": strategy.get("duration_days"),
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return {
        "strategy_id": strategy_id,
        "generation_id": generation["id"],
        "plan": plan,
        "human_review_required": True,
    }


@api.post("/content-assets")
async def create_content_asset(
    payload: ContentAssetCreateIn,
    request: Request,
    user=Depends(require_roles(*_STRATEGIST_ROLES)),
):
    if payload.strategy_id:
        strategy = await db.content_strategies.find_one({
            "id": payload.strategy_id,
        })

        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")

    now = _now()

    doc = {
        "id": new_id(),
        "strategy_id": payload.strategy_id,
        "content_type": payload.content_type.strip(),
        "title": payload.title.strip(),
        "body": payload.body,
        "subject": payload.subject,
        "platform": payload.platform,
        "status": payload.status,
        "tags": _clean_string_list(payload.tags),
        "metadata": payload.metadata,
        "human_review_required": True,
        "created_by": user["id"],
        "created_by_name": user.get("full_name") or user.get("email"),
        "created_at": now,
        "updated_at": now,
    }

    await db.content_assets.insert_one(doc)

    await log_audit(
        db,
        user["id"],
        user["email"],
        "content_asset.create",
        resource_type="content_asset",
        resource_id=doc["id"],
        metadata={
            "content_type": doc["content_type"],
            "strategy_id": doc["strategy_id"],
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return _strip_id(doc)


@api.get("/content-assets")
async def list_content_assets(
    strategy_id: Optional[str] = Query(default=None),
    content_type: Optional[str] = Query(default=None, max_length=64),
    status: Optional[str] = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    user=Depends(require_roles(*_STRATEGIST_ROLES)),
):
    query = {}

    if strategy_id:
        query["strategy_id"] = strategy_id

    if content_type:
        query["content_type"] = content_type

    if status:
        query["status"] = status

    rows = (
        await db.content_assets
        .find(query)
        .sort("updated_at", -1)
        .limit(limit)
        .to_list(limit)
    )

    return [_strip_id(row) for row in rows]


class ContentAssetPatchIn(BaseModel):
    title: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=200,
    )
    body: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=30000,
    )
    subject: Optional[str] = Field(
        default=None,
        max_length=250,
    )
    platform: Optional[str] = Field(
        default=None,
        max_length=64,
    )
    tags: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


@api.patch("/content-assets/{asset_id}")
async def update_content_asset(
    asset_id: str,
    payload: ContentAssetPatchIn,
    request: Request,
    user=Depends(require_roles(*_STRATEGIST_ROLES)),
):
    existing = await db.content_assets.find_one({
        "id": asset_id,
    })

    if not existing:
        raise HTTPException(
            status_code=404,
            detail="Content asset not found",
        )

    # Published/website-delivered content should not be silently
    # mutated through the working-draft editor.
    website_export = existing.get("website_export") or {}

    if website_export.get("status") not in {
        None,
        "",
        "prepared",
    }:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "content_asset_locked",
            },
        )

    update = {}

    if payload.title is not None:
        update["title"] = payload.title.strip()

    if payload.body is not None:
        update["body"] = payload.body

    if payload.subject is not None:
        update["subject"] = (
            payload.subject.strip() or None
        )

    if payload.platform is not None:
        update["platform"] = (
            payload.platform.strip() or None
        )

    if payload.tags is not None:
        update["tags"] = _clean_string_list(
            payload.tags
        )

    if payload.metadata is not None:
        update["metadata"] = payload.metadata

    if not update:
        return _strip_id(existing)

    # Any editorial change requires review again.
    update.update({
        "status": "draft",
        "approved_at": None,
        "approved_by": None,
        "approved_by_name": None,
        "human_review_required": True,
        "updated_at": _now(),
        "updated_by": user["id"],
    })

    await db.content_assets.update_one(
        {"id": asset_id},
        {"$set": update},
    )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "content_asset.update",
        resource_type="content_asset",
        resource_id=asset_id,
        metadata={
            "fields": sorted(update.keys()),
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get(
            "user-agent"
        ),
    )

    row = await db.content_assets.find_one({
        "id": asset_id,
    })

    return _strip_id(row)


class PublishingQueueCreateIn(BaseModel):
    platform: Optional[str] = Field(
        default=None,
        max_length=64,
    )
    scheduled_at: Optional[datetime] = None


class PublishingQueueScheduleIn(BaseModel):
    scheduled_at: datetime


_PUBLISHABLE_CONTENT_TYPES = {
    "social_post",
    "video_prompt",
}

_PUBLISHING_QUEUE_STATUSES = {
    "ready",
    "scheduled",
    "publishing",
    "published",
    "failed",
    "cancelled",
}


class ContentAssetStatusIn(BaseModel):
    status: str = Field(..., min_length=2, max_length=32)


@api.post("/content-assets/{asset_id}/publishing-queue")
async def add_content_asset_to_publishing_queue(
    asset_id: str,
    payload: PublishingQueueCreateIn,
    request: Request,
    user=Depends(require_roles(*_STRATEGIST_ROLES)),
):
    asset = await db.content_assets.find_one({
        "id": asset_id,
    })

    if not asset:
        raise HTTPException(
            status_code=404,
            detail="Content asset not found",
        )

    if str(asset.get("status") or "").lower() != "approved":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "content_asset_not_approved",
                "message": (
                    "Approve this content asset before "
                    "sending it to the Publishing Queue."
                ),
            },
        )

    content_type = str(
        asset.get("content_type") or ""
    ).strip().lower()

    if content_type not in _PUBLISHABLE_CONTENT_TYPES:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "content_asset_not_publishable",
                "allowed": sorted(
                    _PUBLISHABLE_CONTENT_TYPES
                ),
            },
        )

    existing = await db.publishing_queue.find_one({
        "content_asset_id": asset_id,
        "status": {
            "$in": [
                "ready",
                "scheduled",
                "publishing",
            ]
        },
    })

    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "content_asset_already_queued",
                "queue_id": existing.get("id"),
            },
        )

    source = (
        (asset.get("metadata") or {})
        .get("strategy_source")
        or {}
    )

    platform = (
        payload.platform
        or asset.get("platform")
        or source.get("channel")
        or ""
    )
    platform = str(platform).strip().lower()

    now = _now()

    scheduled_at = payload.scheduled_at
    status = (
        "scheduled"
        if scheduled_at is not None
        else "ready"
    )

    doc = {
        "id": new_id(),
        "content_asset_id": asset_id,
        "strategy_id": asset.get("strategy_id"),
        "week_index": (
            asset.get("generated_from_week_index")
            if asset.get(
                "generated_from_week_index"
            ) is not None
            else source.get("week_index")
        ),
        "calendar_index": asset.get(
            "generated_from_calendar_index"
        ),
        "content_type": content_type,
        "title": asset.get("title"),
        "body": asset.get("body"),
        "platform": platform or None,
        "status": status,
        "scheduled_at": scheduled_at,
        "source_topic": source.get("topic"),
        "source_channel": source.get("channel"),
        "human_review_required": True,
        "approved_asset_snapshot": {
            "title": asset.get("title"),
            "body": asset.get("body"),
            "content_type": content_type,
            "platform": asset.get("platform"),
            "approved_at": asset.get("approved_at"),
            "approved_by": asset.get("approved_by"),
        },
        "created_by": user["id"],
        "created_by_name": (
            user.get("full_name")
            or user.get("email")
        ),
        "created_at": now,
        "updated_at": now,
        "published_at": None,
        "external_post_id": None,
        "last_error": None,
    }

    await db.publishing_queue.insert_one(doc)

    await log_audit(
        db,
        user["id"],
        user["email"],
        "content_asset.publishing_queue_add",
        resource_type="publishing_queue",
        resource_id=doc["id"],
        metadata={
            "content_asset_id": asset_id,
            "strategy_id": asset.get("strategy_id"),
            "platform": doc["platform"],
            "status": status,
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get(
            "user-agent"
        ),
    )

    return _strip_id(doc)


@api.get("/publishing-queue")
async def list_publishing_queue(
    strategy_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(
        default=None,
        max_length=32,
    ),
    platform: Optional[str] = Query(
        default=None,
        max_length=64,
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),
    user=Depends(require_roles(*_STRATEGIST_ROLES)),
):
    query = {}

    if strategy_id:
        query["strategy_id"] = strategy_id

    if status:
        normalized_status = status.strip().lower()

        if (
            normalized_status
            not in _PUBLISHING_QUEUE_STATUSES
        ):
            raise HTTPException(
                status_code=400,
                detail={
                    "code":
                        "invalid_publishing_queue_status",
                    "allowed": sorted(
                        _PUBLISHING_QUEUE_STATUSES
                    ),
                },
            )

        query["status"] = normalized_status

    if platform:
        query["platform"] = platform.strip().lower()

    rows = (
        await db.publishing_queue
        .find(query)
        .sort("created_at", -1)
        .limit(limit)
        .to_list(limit)
    )

    return [_strip_id(row) for row in rows]


@api.patch("/publishing-queue/{queue_id}/schedule")
async def schedule_publishing_queue_item(
    queue_id: str,
    payload: PublishingQueueScheduleIn,
    request: Request,
    user=Depends(require_roles(*_STRATEGIST_ROLES)),
):
    existing = await db.publishing_queue.find_one({
        "id": queue_id,
    })

    if not existing:
        raise HTTPException(
            status_code=404,
            detail="Publishing Queue item not found",
        )

    if existing.get("status") not in {
        "ready",
        "scheduled",
    }:
        raise HTTPException(
            status_code=409,
            detail={
                "code":
                    "publishing_queue_item_locked",
                "current_status":
                    existing.get("status"),
            },
        )

    now = _now()

    await db.publishing_queue.update_one(
        {"id": queue_id},
        {
            "$set": {
                "scheduled_at":
                    payload.scheduled_at,
                "status": "scheduled",
                "updated_at": now,
                "updated_by": user["id"],
            }
        },
    )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "publishing_queue.schedule",
        resource_type="publishing_queue",
        resource_id=queue_id,
        metadata={
            "scheduled_at":
                payload.scheduled_at.isoformat(),
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get(
            "user-agent"
        ),
    )

    row = await db.publishing_queue.find_one({
        "id": queue_id,
    })

    return _strip_id(row)


@api.post("/publishing-queue/{queue_id}/retry")
async def retry_failed_publishing_queue_item(
    queue_id: str,
    request: Request,
    user=Depends(require_roles(*_STRATEGIST_ROLES)),
):
    existing = await db.publishing_queue.find_one({
        "id": queue_id,
    })

    if not existing:
        raise HTTPException(
            status_code=404,
            detail="Publishing Queue item not found",
        )

    if existing.get("status") != "failed":
        raise HTTPException(
            status_code=409,
            detail={
                "code":
                    "publishing_queue_item_not_retryable",
                "current_status":
                    existing.get("status"),
            },
        )

    now = _now()

    await db.publishing_queue.update_one(
        {"id": queue_id},
        {
            "$set": {
                "status": "scheduled",
                "scheduled_at": now,
                "next_retry_at": now,
                "attempt_count": 0,
                "worker_id": None,
                "publishing_started_at": None,
                "publishing_failed_at": None,
                "last_error": None,
                "updated_at": now,
                "updated_by": user["id"],
            }
        },
    )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "publishing_queue.retry",
        resource_type="publishing_queue",
        resource_id=queue_id,
        metadata={
            "content_asset_id":
                existing.get("content_asset_id"),
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get(
            "user-agent"
        ),
    )

    row = await db.publishing_queue.find_one({
        "id": queue_id,
    })

    return _strip_id(row)


@api.post("/publishing-queue/{queue_id}/requeue")
async def requeue_publishing_queue_item(
    queue_id: str,
    request: Request,
    user=Depends(require_roles(*_STRATEGIST_ROLES)),
):
    existing = await db.publishing_queue.find_one({
        "id": queue_id,
    })

    if not existing:
        raise HTTPException(
            status_code=404,
            detail="Publishing Queue item not found",
        )

    if existing.get("status") != "cancelled":
        raise HTTPException(
            status_code=409,
            detail={
                "code":
                    "publishing_queue_item_not_requeueable",
                "current_status":
                    existing.get("status"),
            },
        )

    now = _now()

    await db.publishing_queue.update_one(
        {"id": queue_id},
        {
            "$set": {
                "status": "ready",
                "scheduled_at": None,
                "cancelled_at": None,
                "cancelled_by": None,
                "updated_at": now,
                "updated_by": user["id"],
                "last_error": None,
            }
        },
    )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "publishing_queue.requeue",
        resource_type="publishing_queue",
        resource_id=queue_id,
        metadata={
            "content_asset_id":
                existing.get("content_asset_id"),
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get(
            "user-agent"
        ),
    )

    row = await db.publishing_queue.find_one({
        "id": queue_id,
    })

    return _strip_id(row)


@api.post("/publishing-queue/{queue_id}/cancel")
async def cancel_publishing_queue_item(
    queue_id: str,
    request: Request,
    user=Depends(require_roles(*_STRATEGIST_ROLES)),
):
    existing = await db.publishing_queue.find_one({
        "id": queue_id,
    })

    if not existing:
        raise HTTPException(
            status_code=404,
            detail="Publishing Queue item not found",
        )

    if existing.get("status") not in {
        "ready",
        "scheduled",
    }:
        raise HTTPException(
            status_code=409,
            detail={
                "code":
                    "publishing_queue_item_not_cancellable",
                "current_status":
                    existing.get("status"),
            },
        )

    now = _now()

    await db.publishing_queue.update_one(
        {"id": queue_id},
        {
            "$set": {
                "status": "cancelled",
                "cancelled_at": now,
                "cancelled_by": user["id"],
                "updated_at": now,
            }
        },
    )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "publishing_queue.cancel",
        resource_type="publishing_queue",
        resource_id=queue_id,
        metadata={
            "content_asset_id":
                existing.get("content_asset_id"),
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get(
            "user-agent"
        ),
    )

    row = await db.publishing_queue.find_one({
        "id": queue_id,
    })

    return _strip_id(row)



# --------------------------------------------------------------------------- #
# Publishing Queue Worker                                                     #
# --------------------------------------------------------------------------- #

_PUBLISHING_WORKER_BATCH_SIZE = 25
_PUBLISHING_MAX_ATTEMPTS = 3
_PUBLISHING_STALE_MINUTES = 15
_PUBLISHING_RETRY_BACKOFF_MINUTES = (
    5,
    15,
    30,
)


async def _claim_publishing_item(
    queue_id: str,
    worker_id: str,
) -> Optional[dict]:
    """
    Claim one scheduled publishing item.

    The status guard prevents normal duplicate processing. Production
    publishing adapters must additionally be idempotent because a process can
    fail after an external platform accepts a post but before our DB commit.
    """
    now = _now()

    return await db.publishing_queue.find_one_and_update(
        {
            "id": queue_id,
            "status": "scheduled",
        },
        {
            "$set": {
                "status": "publishing",
                "worker_id": worker_id,
                "publishing_started_at": now,
                "last_attempt_at": now,
                "last_error": None,
                "updated_at": now,
            },
            "$inc": {
                "attempt_count": 1,
            },
        },
        return_document=True,
    )


async def _publish_queue_item_dry_run(
    item: dict,
) -> dict:
    """
    Safe Phase-1 publishing adapter.

    No external network request is made. This lets us prove the scheduler,
    state machine, error handling and audit trail before connecting Meta or
    another social platform.
    """
    platform = str(
        item.get("platform") or ""
    ).strip().lower()

    if not platform:
        raise ValueError(
            "Publishing Queue item has no platform."
        )

    return {
        "external_post_id": (
            f"dry-run:{platform}:{item['id']}"
        ),
        "platform": platform,
        "mode": "dry_run",
    }


async def _execute_publishing_item(
    item: dict,
    worker_id: str,
) -> dict:
    queue_id = item["id"]

    try:
        result = await _publish_queue_item_dry_run(
            item
        )

        now = _now()

        await db.publishing_queue.update_one(
            {
                "id": queue_id,
                "status": "publishing",
                "worker_id": worker_id,
            },
            {
                "$set": {
                    "status": "published",
                    "published_at": now,
                    "external_post_id":
                        result.get("external_post_id"),
                    "publishing_result": result,
                    "last_error": None,
                    "updated_at": now,
                }
            },
        )

        return {
            "queue_id": queue_id,
            "status": "published",
            "external_post_id":
                result.get("external_post_id"),
        }

    except Exception as exc:
        now = _now()
        error = str(exc)[:1000]

        attempt_count = int(
            item.get("attempt_count") or 1
        )

        if attempt_count < _PUBLISHING_MAX_ATTEMPTS:
            backoff_index = min(
                max(attempt_count - 1, 0),
                len(
                    _PUBLISHING_RETRY_BACKOFF_MINUTES
                ) - 1,
            )

            retry_minutes = (
                _PUBLISHING_RETRY_BACKOFF_MINUTES[
                    backoff_index
                ]
            )

            next_retry_at = (
                now +
                timedelta(minutes=retry_minutes)
            )

            next_status = "scheduled"
        else:
            next_retry_at = None
            next_status = "failed"

        await db.publishing_queue.update_one(
            {
                "id": queue_id,
                "status": "publishing",
                "worker_id": worker_id,
            },
            {
                "$set": {
                    "status": next_status,
                    "last_error": error,
                    "publishing_failed_at": now,
                    "last_failure_at": now,
                    "next_retry_at":
                        next_retry_at,
                    "scheduled_at":
                        next_retry_at,
                    "updated_at": now,
                }
            },
        )

        return {
            "queue_id": queue_id,
            "status": next_status,
            "error": error,
            "retry_scheduled":
                next_retry_at is not None,
            "next_retry_at":
                next_retry_at,
        }


async def _recover_stale_publishing_items() -> dict:
    """
    Recover items left in `publishing` after a worker/process crash.
    """
    now = _now()
    stale_before = (
        now -
        timedelta(
            minutes=_PUBLISHING_STALE_MINUTES
        )
    )

    rows = (
        await db.publishing_queue
        .find({
            "status": "publishing",
        })
        .sort("created_at", 1)
        .limit(200)
        .to_list(200)
    )

    recovered = 0
    exhausted = 0

    for row in rows:
        raw_started = (
            row.get("publishing_started_at")
            or row.get("last_attempt_at")
        )

        if not raw_started:
            continue

        if isinstance(raw_started, datetime):
            started = raw_started
        else:
            try:
                started = datetime.fromisoformat(
                    str(raw_started)
                    .replace("Z", "+00:00")
                )
            except Exception:
                continue

        if started.tzinfo is None:
            started = started.replace(
                tzinfo=timezone.utc
            )

        if started > stale_before:
            continue

        attempts = int(
            row.get("attempt_count") or 0
        )

        if attempts >= _PUBLISHING_MAX_ATTEMPTS:
            await db.publishing_queue.update_one(
                {
                    "id": row["id"],
                    "status": "publishing",
                },
                {
                    "$set": {
                        "status": "failed",
                        "last_error": (
                            "Publishing worker became "
                            "stale after maximum attempts."
                        ),
                        "publishing_failed_at": now,
                        "updated_at": now,
                    }
                },
            )

            exhausted += 1
            continue

        await db.publishing_queue.update_one(
            {
                "id": row["id"],
                "status": "publishing",
            },
            {
                "$set": {
                    "status": "scheduled",
                    "scheduled_at": now,
                    "next_retry_at": now,
                    "last_error": (
                        "Recovered stale publishing "
                        "worker claim."
                    ),
                    "worker_id": None,
                    "updated_at": now,
                }
            },
        )

        recovered += 1

    return {
        "recovered": recovered,
        "exhausted": exhausted,
    }


async def process_due_publishing_queue(
    *,
    worker_prefix: str = "publishing",
) -> dict:
    """
    Process scheduled Publishing Queue items whose scheduled_at is due.
    """
    import uuid

    now = _now()

    recovery = (
        await _recover_stale_publishing_items()
    )

    candidates = (
        await db.publishing_queue
        .find({
            "status": "scheduled",
            "scheduled_at": {
                "$lte": now,
            },
        })
        .sort("scheduled_at", 1)
        .limit(_PUBLISHING_WORKER_BATCH_SIZE)
        .to_list(_PUBLISHING_WORKER_BATCH_SIZE)
    )

    summary = {
        "due": len(candidates),
        "claimed": 0,
        "published": 0,
        "failed": 0,
        "retry_scheduled": 0,
        "skipped": 0,
        "stale_recovered":
            recovery["recovered"],
        "stale_exhausted":
            recovery["exhausted"],
    }

    for candidate in candidates:
        worker_id = (
            f"{worker_prefix}:{uuid.uuid4()}"
        )

        claimed = await _claim_publishing_item(
            candidate["id"],
            worker_id,
        )

        if not claimed:
            summary["skipped"] += 1
            continue

        summary["claimed"] += 1

        result = await _execute_publishing_item(
            claimed,
            worker_id,
        )

        if result["status"] == "published":
            summary["published"] += 1
        elif result.get("retry_scheduled"):
            summary["retry_scheduled"] += 1
        else:
            summary["failed"] += 1

    return summary


@api.patch("/content-assets/{asset_id}/status")
async def update_content_asset_status(
    asset_id: str,
    payload: ContentAssetStatusIn,
    request: Request,
    user=Depends(require_roles(*_STRATEGIST_ROLES)),
):
    allowed = {
        "draft",
        "approved",
        "rejected",
    }

    status = payload.status.strip().lower()

    if status not in allowed:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_content_asset_status",
                "allowed": sorted(allowed),
            },
        )

    existing = await db.content_assets.find_one({
        "id": asset_id,
    })

    if not existing:
        raise HTTPException(
            status_code=404,
            detail="Content asset not found",
        )

    now = _now()

    update = {
        "status": status,
        "updated_at": now,
    }

    if status == "approved":
        update.update({
            "approved_at": now,
            "approved_by": user["id"],
            "approved_by_name": (
                user.get("full_name")
                or user.get("email")
            ),
        })
    else:
        update.update({
            "approved_at": None,
            "approved_by": None,
            "approved_by_name": None,
        })

    await db.content_assets.update_one(
        {"id": asset_id},
        {"$set": update},
    )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "content_asset.status_update",
        resource_type="content_asset",
        resource_id=asset_id,
        metadata={
            "old_status": existing.get("status"),
            "new_status": status,
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    row = await db.content_assets.find_one({
        "id": asset_id,
    })

    return _strip_id(row)


def _website_content_type(asset: dict) -> str:
    raw = str(
        asset.get("content_type") or ""
    ).strip().lower()

    mapping = {
        "blog": "blog_post",
        "blog_post": "blog_post",
        "article": "blog_post",
        "newsletter": "newsletter_spotlight",
        "newsletter_spotlight": "newsletter_spotlight",
        "email": "newsletter_spotlight",
        "package": "package",
    }

    result = mapping.get(raw)

    if not result:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_website_content_type",
                "content_type": raw,
                "allowed": [
                    "blog_post",
                    "newsletter_spotlight",
                    "package",
                ],
            },
        )

    return result


def _asset_to_website_object(
    asset: dict,
) -> dict:
    metadata = asset.get("metadata") or {}

    if not isinstance(metadata, dict):
        metadata = {}

    content_type = _website_content_type(asset)

    result = {
        "id": str(asset["id"]),
        "type": content_type,
        "title": str(asset.get("title") or ""),
        "slug": str(metadata.get("slug") or ""),
        "summary": str(metadata.get("summary") or ""),
        "body_markdown": str(asset.get("body") or ""),
        "category": str(metadata.get("category") or ""),
        "tags": asset.get("tags") or [],
        "publish_date": metadata.get("publish_date"),
        "seo": metadata.get("seo") or {},
    }

    if content_type == "newsletter_spotlight":
        result["subject"] = str(
            asset.get("subject") or ""
        )

    if content_type == "package":
        result["offer"] = metadata.get("offer") or {}

    return result


@api.post("/content-assets/{asset_id}/website-export")
async def export_content_asset_to_website_s3(
    asset_id: str,
    request: Request,
    user=Depends(require_roles(*_STRATEGIST_ROLES)),
):
    """
    Prepare one approved content asset for website delivery.

    Writes the canonical handoff object and manifest to the dedicated
    marketing S3 bucket. This endpoint does NOT call the website webhook.
    """
    asset = await db.content_assets.find_one({
        "id": asset_id,
    })

    if not asset:
        raise HTTPException(
            status_code=404,
            detail="Content asset not found",
        )

    if str(asset.get("status") or "").lower() != "approved":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "content_asset_not_approved",
                "message": (
                    "Approve this content asset before "
                    "sending it to website drafts."
                ),
            },
        )

    from services.marketing_content_export import (
        build_batch_id,
        write_content_item,
        write_manifest,
    )

    website_object = _asset_to_website_object(
        asset
    )

    batch_id = build_batch_id()

    exported_item = await write_content_item(
        batch_id=batch_id,
        item=website_object,
    )

    manifest_result = await write_manifest(
        batch_id=batch_id,
        items=[exported_item],
    )

    export_record = {
        "batch_id": batch_id,
        "manifest_key": (
            manifest_result["storage"]["key"]
        ),
        "manifest_sha256": (
            manifest_result["storage"]["sha256"]
        ),
        "content_key": (
            f"content/{batch_id}/items/"
            f"{asset_id}.json"
        ),
        "content_sha256": (
            exported_item["content_sha256"]
        ),
        "status": "prepared",
        "prepared_at": _now(),
        "prepared_by": user["id"],
    }

    await db.content_assets.update_one(
        {"id": asset_id},
        {
            "$set": {
                "website_export": export_record,
                "updated_at": _now(),
            }
        },
    )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "content_asset.website_export_prepare",
        resource_type="content_asset",
        resource_id=asset_id,
        metadata={
            "batch_id": batch_id,
            "manifest_key": (
                export_record["manifest_key"]
            ),
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return {
        "status": "prepared",
        "asset_id": asset_id,
        "batch_id": batch_id,
        "manifest_key": export_record["manifest_key"],
        "manifest_sha256": (
            export_record["manifest_sha256"]
        ),
        "content_sha256": (
            export_record["content_sha256"]
        ),
        "website_delivery_started": False,
        "human_review_required": True,
    }


# =================== AI CONTENT ASSET DRAFTER ===================

class ContentAssetGenerateIn(BaseModel):
    calendar_index: int = Field(..., ge=0, le=99)

    asset_type: str = Field(
        ...,
        min_length=2,
        max_length=64,
    )

    additional_instructions: Optional[str] = Field(
        default=None,
        max_length=2000,
    )


CONTENT_ASSET_TEMPLATE = PromptTemplate(
    feature="content_asset_drafter",
    system=(
        "You are a senior marketing copywriter for a wellness and "
        "functional medicine clinic.\n\n"

        "You are converting ONE approved marketing-strategy idea into "
        "finished draft marketing copy.\n\n"

        "IMPORTANT:\n"
        "- This is always a DRAFT requiring human review.\n"
        "- Never publish, schedule, send, or approve anything.\n"
        "- Never request, use, infer, or include patient information or PHI.\n"
        "- Never invent services, pricing, credentials, statistics, "
        "testimonials, patient stories, outcomes, discounts, or guarantees.\n"
        "- Never make cure claims or guarantee results.\n"
        "- Never provide individualized medical advice.\n"
        "- Only use clinic facts explicitly provided in the prompt.\n"
        "- If a necessary factual detail is missing, write around it rather "
        "than inventing it.\n"
        "- Use educational, professional, premium, warm, non-pushy language.\n"
        "- Calls to action must remain appropriate for general marketing.\n\n"

        "Return STRICT JSON only with this shape:\n"
        "{\n"
        '  "content_type": "blog_post|newsletter_spotlight|package",\n'
        '  "title": "",\n'
        '  "body": "",\n'
        '  "subject": null,\n'
        '  "platform": "",\n'
        '  "tags": [],\n'
        '  "metadata": {\n'
        '    "slug": "",\n'
        '    "summary": "",\n'
        '    "category": "",\n'
        '    "publish_date": null,\n'
        '    "seo": {\n'
        '      "title": "",\n'
        '      "description": ""\n'
        '    },\n'
        '    "offer": {}\n'
        "  }\n"
        "}\n\n"

        "For blog_post: body should be polished Markdown suitable for "
        "a useful educational article.\n"
        "For newsletter_spotlight: include an email subject and concise "
        "newsletter-ready body.\n"
        "For package: describe only package details explicitly supplied by "
        "the clinic. Never invent price, inclusions, expiration, or claims."
    ),
    max_tokens=6000,
    temperature=0.3,
)


def _validate_generated_asset(
    data: Optional[dict],
    *,
    requested_type: str,
) -> dict:
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "invalid_asset_model_response",
                "message": (
                    "The generated content draft could not be parsed."
                ),
            },
        )

    allowed_types = {
        "blog_post",
        "newsletter_spotlight",
        "package",
    }

    content_type = str(
        data.get("content_type") or requested_type
    ).strip().lower()

    if content_type not in allowed_types:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "invalid_generated_content_type",
            },
        )

    if content_type != requested_type:
        # The caller selects the publishing target. Do not let the model
        # silently change that routing decision.
        content_type = requested_type

    title = str(data.get("title") or "").strip()[:200]
    body = str(data.get("body") or "").strip()[:30000]

    if len(title) < 2 or not body:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "incomplete_generated_asset",
            },
        )

    subject = data.get("subject")

    if subject is not None:
        subject = str(subject).strip()[:250] or None

    platform = str(
        data.get("platform") or content_type
    ).strip()[:64]

    raw_tags = data.get("tags") or []

    tags = []

    if isinstance(raw_tags, list):
        for tag in raw_tags[:30]:
            value = str(tag or "").strip()[:200]

            if value and value not in tags:
                tags.append(value)

    metadata = data.get("metadata") or {}

    if not isinstance(metadata, dict):
        metadata = {}

    seo = metadata.get("seo") or {}

    if not isinstance(seo, dict):
        seo = {}

    offer = metadata.get("offer") or {}

    if not isinstance(offer, dict):
        offer = {}

    clean_metadata = {
        "slug": str(
            metadata.get("slug") or ""
        ).strip()[:200],
        "summary": str(
            metadata.get("summary") or ""
        ).strip()[:1000],
        "category": str(
            metadata.get("category") or ""
        ).strip()[:200],
        "publish_date": (
            str(metadata.get("publish_date")).strip()[:40]
            if metadata.get("publish_date")
            else None
        ),
        "seo": {
            "title": str(
                seo.get("title") or ""
            ).strip()[:200],
            "description": str(
                seo.get("description") or ""
            ).strip()[:500],
        },
        "offer": offer,
    }

    return {
        "content_type": content_type,
        "title": title,
        "body": body,
        "subject": subject,
        "platform": platform,
        "tags": tags,
        "metadata": clean_metadata,
    }


def _build_content_asset_prompt(
    strategy: dict,
    calendar_item: dict,
    asset_type: str,
    additional_instructions: Optional[str],
) -> str:
    plan = strategy.get("plan") or {}

    lines = [
        f"Strategy name: {strategy.get('name') or 'Untitled'}",
        f"Business goal: {strategy.get('goal') or ''}",
        f"Requested asset type: {asset_type}",
        "",
        "Selected strategy calendar item:",
        f"- Date/day: {calendar_item.get('day_or_date') or ''}",
        f"- Channel: {calendar_item.get('channel') or ''}",
        f"- Strategy content type: "
        f"{calendar_item.get('content_type') or ''}",
        f"- Topic: {calendar_item.get('topic') or ''}",
        f"- Objective: {calendar_item.get('objective') or ''}",
        f"- Call to action: "
        f"{calendar_item.get('call_to_action') or ''}",
        "",
    ]

    for label, key in (
        ("Clinic services", "services"),
        ("Generalized audiences", "audiences"),
        ("Brand voice", "brand_voice"),
    ):
        values = strategy.get(key) or []

        if values:
            lines.append(
                f"{label}: {', '.join(str(x) for x in values)}"
            )

    if strategy.get("call_to_action"):
        lines.append(
            "Clinic-supplied preferred CTA: "
            f"{strategy.get('call_to_action')}"
        )

    if strategy.get("offer_details"):
        lines.append(
            "Clinic-supplied offer details: "
            f"{str(strategy.get('offer_details'))[:1500]}"
        )

    if strategy.get("compliance_notes"):
        lines.append(
            "Clinic-supplied compliance notes: "
            f"{str(strategy.get('compliance_notes'))[:2000]}"
        )

    themes = plan.get("campaign_themes") or []

    if themes:
        lines.append(
            "Campaign themes: "
            + ", ".join(str(x) for x in themes[:10])
        )

    positioning = plan.get("positioning")

    if positioning:
        lines.append(
            "Strategy positioning: "
            f"{str(positioning)[:1500]}"
        )

    if additional_instructions:
        lines.extend([
            "",
            "Additional staff drafting instructions:",
            str(additional_instructions)[:2000],
        ])

    lines.extend([
        "",
        "Generate the finished editable marketing draft now.",
        "Return strict JSON only.",
    ])

    return "\n".join(lines)


@api.post(
    "/content-strategies/{strategy_id}/generate-asset"
)
async def generate_content_asset_from_strategy(
    strategy_id: str,
    payload: ContentAssetGenerateIn,
    request: Request,
    user=Depends(require_roles(*_STRATEGIST_ROLES)),
):
    strategy = await db.content_strategies.find_one({
        "id": strategy_id,
    })

    if not strategy:
        raise HTTPException(
            status_code=404,
            detail="Strategy not found",
        )

    plan = strategy.get("plan") or {}

    if not isinstance(plan, dict):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "strategy_not_generated",
                "message": (
                    "Generate the strategy before creating content drafts."
                ),
            },
        )

    calendar = plan.get("content_calendar") or []

    if not isinstance(calendar, list):
        calendar = []

    if payload.calendar_index >= len(calendar):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_calendar_index",
                "calendar_count": len(calendar),
            },
        )

    calendar_item = calendar[payload.calendar_index]

    if not isinstance(calendar_item, dict):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_calendar_item",
            },
        )

    requested_type = (
        payload.asset_type
        .strip()
        .lower()
    )

    allowed_types = {
        "blog_post",
        "newsletter_spotlight",
        "package",
    }

    if requested_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_asset_type",
                "allowed": sorted(allowed_types),
            },
        )

    started = _now()

    try:
        raw = await run_template(
            CONTENT_ASSET_TEMPLATE,
            _build_content_asset_prompt(
                strategy,
                calendar_item,
                requested_type,
                payload.additional_instructions,
            ),
            session_id=(
                f"content-asset."
                f"{strategy_id}."
                f"{payload.calendar_index}"
            ),
        )

    except RuntimeError as exc:
        code = str(exc)

        status_code = 503 if code in {
            "ai_disabled",
            "bedrock_misconfigured",
            "bedrock_unavailable",
            "model_access_denied",
            "request_timeout",
        } else 502

        raise HTTPException(
            status_code=status_code,
            detail={"code": code},
        )

    generated = _validate_generated_asset(
        safe_extract_json(raw),
        requested_type=requested_type,
    )

    now = _now()
    asset_id = new_id()

    metadata = dict(
        generated.get("metadata") or {}
    )

    # Preserve where this draft came from.
    metadata["strategy_source"] = {
        "strategy_id": strategy_id,
        "calendar_index": payload.calendar_index,
        "day_or_date": (
            calendar_item.get("day_or_date")
        ),
        "channel": calendar_item.get("channel"),
        "topic": calendar_item.get("topic"),
        "objective": calendar_item.get("objective"),
        "call_to_action": (
            calendar_item.get("call_to_action")
        ),
    }

    doc = {
        "id": asset_id,
        "strategy_id": strategy_id,
        "content_type": generated["content_type"],
        "title": generated["title"],
        "body": generated["body"],
        "subject": generated.get("subject"),
        "platform": generated.get("platform"),
        "status": "draft",
        "tags": generated.get("tags") or [],
        "metadata": metadata,
        "human_review_required": True,
        "ai_generated": True,
        "generated_from_calendar_index": (
            payload.calendar_index
        ),
        "created_by": user["id"],
        "created_by_name": (
            user.get("full_name")
            or user.get("email")
        ),
        "created_at": now,
        "updated_at": now,
    }

    await db.content_assets.insert_one(doc)

    latency_ms = int(
        (now - started).total_seconds() * 1000
    )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "content_asset.ai_generate",
        resource_type="content_asset",
        resource_id=asset_id,
        metadata={
            "strategy_id": strategy_id,
            "calendar_index": payload.calendar_index,
            "content_type": generated["content_type"],
            "latency_ms": latency_ms,
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return {
        "asset": _strip_id(doc),
        "strategy_id": strategy_id,
        "calendar_index": payload.calendar_index,
        "human_review_required": True,
    }


# =================== BULK WEEKLY CONTENT DRAFTING ===================

class GenerateWeekIn(BaseModel):
    week_index: int = Field(..., ge=0, le=20)


def _normalized_topic(value: Any) -> str:
    return " ".join(
        str(value or "")
        .strip()
        .lower()
        .split()
    )


WEEKLY_MARKETING_ASSET_TEMPLATE = PromptTemplate(
    feature="content_week_marketing_asset",
    system=(
        "You are a compliance-aware marketing copywriter for a wellness "
        "and functional medicine clinic.\n\n"
        "Create ONE finished marketing draft from the supplied approved "
        "content-calendar item.\n\n"
        "STRICT RULES:\n"
        "- Draft only. Human review is always required.\n"
        "- Never publish, schedule, send, or approve anything.\n"
        "- Never request, infer, or include PHI.\n"
        "- Never invent services, pricing, credentials, statistics, "
        "testimonials, patients, outcomes, discounts, or guarantees.\n"
        "- Never make cure claims or individualized medical recommendations.\n"
        "- Only use clinic facts explicitly provided in the prompt.\n"
        "- Use educational, professional, warm, premium, non-pushy language.\n\n"
        "Return STRICT JSON only with this shape:\n"
        "{\n"
        '  "content_type": "social_post|video_prompt",\n'
        '  "title": "",\n'
        '  "body": "",\n'
        '  "platform": "",\n'
        '  "tags": [],\n'
        '  "metadata": {\n'
        '    "summary": "",\n'
        '    "hashtags": [],\n'
        '    "calls_to_action": [],\n'
        '    "compliance_notes": []\n'
        "  }\n"
        "}\n\n"
        "For social_post: create polished platform-ready copy with useful "
        "educational value and an appropriate CTA.\n"
        "For video_prompt: create a detailed scene-by-scene production prompt "
        "with approximate timing, setting, action, camera direction, lighting, "
        "voiceover, on-screen text, transitions, CTA, and negative prompt."
    ),
    max_tokens=5000,
    temperature=0.3,
)


def _validate_weekly_marketing_asset(
    data: Optional[dict],
    *,
    requested_type: str,
) -> dict:
    if not isinstance(data, dict):
        raise RuntimeError(
            "invalid_weekly_marketing_model_response"
        )

    if requested_type not in {
        "social_post",
        "video_prompt",
    }:
        raise RuntimeError(
            "unsupported_weekly_marketing_asset_type"
        )

    title = str(
        data.get("title") or ""
    ).strip()[:200]

    body = str(
        data.get("body")
        or data.get("draft")
        or ""
    ).strip()[:30000]

    if len(title) < 2 or not body:
        raise RuntimeError(
            "incomplete_weekly_marketing_asset"
        )

    raw_tags = data.get("tags") or []
    tags = []

    if isinstance(raw_tags, list):
        for tag in raw_tags[:30]:
            value = str(tag or "").strip()[:200]

            if value and value not in tags:
                tags.append(value)

    metadata = data.get("metadata") or {}

    if not isinstance(metadata, dict):
        metadata = {}

    return {
        "content_type": requested_type,
        "title": title,
        "body": body,
        "subject": None,
        "platform": str(
            data.get("platform") or ""
        ).strip()[:64],
        "tags": tags,
        "metadata": metadata,
    }


def _build_weekly_marketing_prompt(
    strategy: dict,
    item: dict,
    asset_type: str,
) -> str:
    lines = [
        f"Strategy name: {strategy.get('name') or 'Untitled'}",
        f"Business goal: {strategy.get('goal') or ''}",
        f"Requested asset type: {asset_type}",
        f"Calendar channel: {item.get('channel') or ''}",
        f"Calendar content type: {item.get('content_type') or ''}",
        f"Topic: {item.get('topic') or ''}",
        f"Objective: {item.get('objective') or ''}",
        f"Call to action: {item.get('call_to_action') or ''}",
    ]

    audiences = strategy.get("audiences") or []

    if audiences:
        lines.append(
            "Generalized audiences: "
            + ", ".join(str(x) for x in audiences[:10])
        )

    voices = strategy.get("brand_voice") or []

    if voices:
        lines.append(
            "Brand voice: "
            + ", ".join(str(x) for x in voices[:10])
        )

    services = strategy.get("services") or []

    if services:
        lines.append(
            "Clinic-supplied services: "
            + ", ".join(str(x) for x in services[:20])
        )

    if strategy.get("compliance_notes"):
        lines.append(
            "Clinic compliance notes: "
            + str(strategy.get("compliance_notes"))[:2000]
        )

    lines.extend([
        "",
        "Generate the finished editable marketing draft now.",
        "Return strict JSON only.",
    ])

    return "\n".join(lines)


def _calendar_asset_type(item: dict) -> Optional[str]:
    channel = str(
        item.get("channel") or ""
    ).strip().lower()

    content_type = str(
        item.get("content_type") or ""
    ).strip().lower()

    if (
        channel == "blog"
        or "article" in content_type
        or "blog" in content_type
    ):
        return "blog_post"

    if (
        channel == "email"
        or "newsletter" in content_type
        or content_type == "email"
    ):
        return "newsletter_spotlight"

    if (
        "package" in content_type
        or channel == "package"
    ):
        return "package"

    if (
        "video" in content_type
        or channel in {
            "short_video",
            "video",
        }
    ):
        return "video_prompt"

    if (
        "post" in content_type
        or channel in {
            "instagram",
            "facebook",
            "tiktok",
            "linkedin",
            "threads",
        }
    ):
        return "social_post"

    return None


@api.post(
    "/content-strategies/{strategy_id}/generate-week"
)
async def generate_content_week(
    strategy_id: str,
    payload: GenerateWeekIn,
    request: Request,
    user=Depends(require_roles(*_STRATEGIST_ROLES)),
):
    strategy = await db.content_strategies.find_one({
        "id": strategy_id,
    })

    if not strategy:
        raise HTTPException(
            status_code=404,
            detail="Strategy not found",
        )

    plan = strategy.get("plan") or {}

    if not isinstance(plan, dict):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "strategy_not_generated",
            },
        )

    weeks = plan.get("weekly_plan") or []
    calendar = plan.get("content_calendar") or []

    if not isinstance(weeks, list):
        weeks = []

    if not isinstance(calendar, list):
        calendar = []

    if payload.week_index >= len(weeks):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_week_index",
                "week_count": len(weeks),
            },
        )

    week = weeks[payload.week_index]

    if not isinstance(week, dict):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_week",
            },
        )

    # Build the set of topics explicitly assigned to this week.
    weekly_topics = []

    for key in (
        "email_topics",
        "blog_topics",
        "social_topics",
        "video_topics",
    ):
        values = week.get(key) or []

        if not isinstance(values, list):
            continue

        for value in values:
            normalized = _normalized_topic(value)

            if normalized:
                weekly_topics.append({
                    "topic": str(value),
                    "normalized": normalized,
                    "group": key,
                })

    calendar_matches = []

    for index, item in enumerate(calendar):
        if not isinstance(item, dict):
            continue

        normalized = _normalized_topic(
            item.get("topic")
        )

        matching_week_topic = next(
            (
                topic
                for topic in weekly_topics
                if topic["normalized"] == normalized
            ),
            None,
        )

        if matching_week_topic:
            calendar_matches.append({
                "calendar_index": index,
                "item": item,
                "group": matching_week_topic["group"],
            })

    created = []
    skipped = []
    errors = []

    for match in calendar_matches:
        calendar_index = match["calendar_index"]
        item = match["item"]

        asset_type = _calendar_asset_type(item)

        if not asset_type:
            skipped.append({
                "calendar_index": calendar_index,
                "topic": item.get("topic"),
                "reason": "unsupported_bulk_asset_type",
                "channel": item.get("channel"),
            })
            continue

        # Idempotency: don't generate another canonical draft
        # for the same strategy calendar item.
        existing = await db.content_assets.find_one({
            "strategy_id": strategy_id,
            "$or": [
                {
                    "generated_from_calendar_index":
                        calendar_index,
                },
                {
                    "metadata.strategy_source.calendar_index":
                        calendar_index,
                },
            ],
        })

        if existing:
            skipped.append({
                "calendar_index": calendar_index,
                "topic": item.get("topic"),
                "reason": "draft_already_exists",
                "asset_id": existing.get("id"),
            })
            continue

        try:
            if asset_type in {
                "social_post",
                "video_prompt",
            }:
                raw = await run_template(
                    WEEKLY_MARKETING_ASSET_TEMPLATE,
                    _build_weekly_marketing_prompt(
                        strategy,
                        item,
                        asset_type,
                    ),
                    session_id=(
                        f"content-week-marketing."
                        f"{strategy_id}."
                        f"{payload.week_index}."
                        f"{calendar_index}"
                    ),
                )

                generated = (
                    _validate_weekly_marketing_asset(
                        safe_extract_json(raw),
                        requested_type=asset_type,
                    )
                )
            else:
                raw = await run_template(
                    CONTENT_ASSET_TEMPLATE,
                    _build_content_asset_prompt(
                        strategy,
                        item,
                        asset_type,
                        (
                            "This draft is being generated as "
                            "part of the weekly content batch. "
                            "Keep it implementation-ready but "
                            "require human review."
                        ),
                    ),
                    session_id=(
                        f"content-week."
                        f"{strategy_id}."
                        f"{payload.week_index}."
                        f"{calendar_index}"
                    ),
                )

                generated = _validate_generated_asset(
                    safe_extract_json(raw),
                    requested_type=asset_type,
                )

            now = _now()
            asset_id = new_id()

            metadata = dict(
                generated.get("metadata") or {}
            )

            metadata["strategy_source"] = {
                "strategy_id": strategy_id,
                "week_index": payload.week_index,
                "calendar_index": calendar_index,
                "day_or_date":
                    item.get("day_or_date"),
                "channel": item.get("channel"),
                "topic": item.get("topic"),
                "objective":
                    item.get("objective"),
                "call_to_action":
                    item.get("call_to_action"),
            }

            doc = {
                "id": asset_id,
                "strategy_id": strategy_id,
                "content_type":
                    generated["content_type"],
                "title": generated["title"],
                "body": generated["body"],
                "subject":
                    generated.get("subject"),
                "platform":
                    generated.get("platform"),
                "status": "draft",
                "tags":
                    generated.get("tags") or [],
                "metadata": metadata,
                "human_review_required": True,
                "ai_generated": True,
                "generated_from_calendar_index":
                    calendar_index,
                "generated_from_week_index":
                    payload.week_index,
                "created_by": user["id"],
                "created_by_name": (
                    user.get("full_name")
                    or user.get("email")
                ),
                "created_at": now,
                "updated_at": now,
            }

            await db.content_assets.insert_one(
                doc
            )

            created.append({
                "asset_id": asset_id,
                "calendar_index":
                    calendar_index,
                "content_type":
                    generated["content_type"],
                "title":
                    generated["title"],
            })

        except Exception as exc:
            errors.append({
                "calendar_index":
                    calendar_index,
                "topic": item.get("topic"),
                "error": str(exc)[:500],
            })

    await log_audit(
        db,
        user["id"],
        user["email"],
        "content_asset.generate_week",
        resource_type="content_strategy",
        resource_id=strategy_id,
        metadata={
            "week_index":
                payload.week_index,
            "created_count":
                len(created),
            "skipped_count":
                len(skipped),
            "error_count":
                len(errors),
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get(
            "user-agent"
        ),
    )

    return {
        "strategy_id": strategy_id,
        "week_index": payload.week_index,
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "created_count": len(created),
        "skipped_count": len(skipped),
        "error_count": len(errors),
        "human_review_required": True,
    }
