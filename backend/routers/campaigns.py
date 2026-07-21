"""
Patient Outreach — Campaign Center (lean).

Reuses the existing SendGrid / Twilio notifiers, the existing
`consent_marketing` and `comms_pref` fields on `clients`, and the existing
audit-log infrastructure. Not a CRM, not a drip system, not analytics.

Endpoints
    POST  /api/campaigns/estimate       (dry-run: recipient count + exclusions)
    POST  /api/campaigns                (create + immediately send OR schedule)
    GET   /api/campaigns                (list)
    GET   /api/campaigns/{id}           (details incl. delivery_log)
    POST  /api/campaigns/{id}/run       (execute a scheduled campaign now — admin)
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

from audit import get_client_ip, log_audit
from deps import _strip_id, api, db, require_roles
from models import new_id
from notifiers import send_email, send_sms


CHANNELS = ("email", "sms")
FILTER_TYPES = (
    "all_marketing", "inactive", "upcoming_appointments",
    "due_for_followup", "membership", "treatment_group",
)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?[0-9]{7,15}$")


def _is_valid_email(e: Optional[str]) -> bool:
    return bool(e) and bool(_EMAIL_RE.match(e.strip()))


def _is_valid_phone(p: Optional[str]) -> bool:
    if not p:
        return False
    digits = re.sub(r"[^\d+]", "", p)
    return bool(_PHONE_RE.match(digits))


class CampaignIn(BaseModel):
    title: str = Field(..., min_length=2, max_length=160)
    subject: Optional[str] = Field(default=None, max_length=200)
    message: str = Field(..., min_length=2, max_length=4000)
    channel: str
    filter_type: str = "all_marketing"
    filter_params: dict = {}
    schedule_at: Optional[datetime] = None    # None ⇒ send now


class EstimateIn(BaseModel):
    channel: str
    filter_type: str = "all_marketing"
    filter_params: dict = {}


async def _resolve_recipients(filter_type: str, filter_params: dict) -> List[dict]:
    """Return the raw candidate client documents that match the filter."""
    if filter_type not in FILTER_TYPES:
        raise HTTPException(status_code=400, detail={
            "code": "invalid_filter_type",
            "allowed": list(FILTER_TYPES),
        })
    now = datetime.now(timezone.utc)
    q: dict = {}
    if filter_type == "all_marketing":
        # Everyone (still bound by opt-in exclusion below).
        q = {}
    elif filter_type == "inactive":
        cutoff_days = int(filter_params.get("inactive_days", 90))
        cutoff = now - timedelta(days=cutoff_days)
        active_client_ids = set()
        async for a in db.appointments.find({"start": {"$gte": cutoff}},
                                             {"client_id": 1}):
            if a.get("client_id"):
                active_client_ids.add(a["client_id"])
        if active_client_ids:
            q["id"] = {"$nin": list(active_client_ids)}
    elif filter_type == "upcoming_appointments":
        horizon_days = int(filter_params.get("days_ahead", 14))
        window_end = now + timedelta(days=horizon_days)
        client_ids = set()
        async for a in db.appointments.find(
            {"start": {"$gte": now, "$lte": window_end}}, {"client_id": 1}
        ):
            if a.get("client_id"):
                client_ids.add(a["client_id"])
        if not client_ids:
            return []
        q["id"] = {"$in": list(client_ids)}
    elif filter_type == "due_for_followup":
        # Clients whose last appointment ended before `since_days` and have no
        # future appointment scheduled.
        since_days = int(filter_params.get("since_days", 60))
        cutoff = now - timedelta(days=since_days)
        stale_ids = set()
        future_ids = set()
        async for a in db.appointments.find({}, {"client_id": 1, "start": 1}):
            cid = a.get("client_id")
            if not cid:
                continue
            start = a.get("start")
            if isinstance(start, datetime):
                if start >= now:
                    future_ids.add(cid)
                elif start <= cutoff:
                    stale_ids.add(cid)
        eligible = stale_ids - future_ids
        if not eligible:
            return []
        q["id"] = {"$in": list(eligible)}
    elif filter_type == "membership":
        # Reuse existing "memberships" collection if present, else best-effort
        member_ids = set()
        async for m in db.memberships.find({"status": "active"},
                                            {"client_id": 1}):
            if m.get("client_id"):
                member_ids.add(m["client_id"])
        if not member_ids:
            return []
        q["id"] = {"$in": list(member_ids)}
    elif filter_type == "treatment_group":
        # Filter by an active treatment protocol / plan title supplied in params.
        title = (filter_params.get("group_title") or "").strip()
        if not title:
            return []
        client_ids = set()
        async for p in db.treatment_plans.find(
            {"title": {"$regex": re.escape(title), "$options": "i"}},
            {"client_id": 1},
        ):
            if p.get("client_id"):
                client_ids.add(p["client_id"])
        if not client_ids:
            return []
        q["id"] = {"$in": list(client_ids)}

    return await db.clients.find(q).to_list(5000)


def _classify(client: dict, channel: str) -> tuple[str, str]:
    """Return (status, reason) — status is 'eligible' | 'skipped'."""
    if client.get("consent_marketing") is False:
        return "skipped", "marketing_opt_out"
    if channel == "email":
        if not _is_valid_email(client.get("email")):
            return "skipped", "invalid_email"
    elif channel == "sms":
        if not _is_valid_phone(client.get("phone")):
            return "skipped", "invalid_phone"
    return "eligible", ""


def _partition(clients: List[dict], channel: str):
    eligible, skipped = [], []
    for c in clients:
        status, reason = _classify(c, channel)
        if status == "eligible":
            eligible.append(c)
        else:
            skipped.append({"client_id": c.get("id"), "reason": reason})
    return eligible, skipped


@api.post("/campaigns/estimate")
async def estimate(payload: EstimateIn,
                   user=Depends(require_roles("admin", "practitioner", "staff", "medical_assistant"))):
    if payload.channel not in CHANNELS:
        raise HTTPException(status_code=400, detail={
            "code": "invalid_channel", "allowed": list(CHANNELS),
        })
    candidates = await _resolve_recipients(payload.filter_type, payload.filter_params)
    eligible, skipped = _partition(candidates, payload.channel)
    skipped_counts: dict = {}
    for s in skipped:
        skipped_counts[s["reason"]] = skipped_counts.get(s["reason"], 0) + 1
    return {
        "candidates": len(candidates),
        "eligible": len(eligible),
        "skipped_total": len(skipped),
        "skipped_by_reason": skipped_counts,
    }


async def _run_campaign(campaign: dict) -> dict:
    """Actually dispatch to SendGrid / Twilio, appending delivery_log entries."""
    now = datetime.now(timezone.utc)
    candidates = await _resolve_recipients(campaign["filter_type"], campaign.get("filter_params") or {})
    eligible, skipped = _partition(candidates, campaign["channel"])
    delivery_log = []
    success = 0
    failure = 0

    # Log the skipped set first (do NOT surface PHI in reason strings).
    for s in skipped:
        delivery_log.append({
            "client_id": s["client_id"], "status": "skipped",
            "reason": s["reason"], "ts": now,
        })

    for c in eligible:
        try:
            if campaign["channel"] == "email":
                status = await send_email(
                    db, c["email"],
                    campaign.get("subject") or campaign["title"],
                    _render_html(campaign["message"], c),
                    plain_text=campaign["message"],
                    action="campaign.email",
                    payload_metadata={"campaign_id": campaign["id"]},
                )
            else:
                status = await send_sms(
                    db, c.get("phone", ""),
                    campaign["message"],
                    action="campaign.sms",
                    payload_metadata={"campaign_id": campaign["id"]},
                )
            delivery_log.append({
                "client_id": c.get("id"), "status": status, "ts": now,
                "channel": campaign["channel"],
            })
            if status in ("sent", "sent_stub"):
                success += 1
            else:
                failure += 1
        except Exception as e:  # notifier already writes to integration_log
            delivery_log.append({"client_id": c.get("id"), "status": "failed",
                                  "error": str(e)[:200], "ts": now})
            failure += 1

    final_status = "sent"
    if failure and not success:
        final_status = "failed"
    elif failure:
        final_status = "sent_with_failures"

    await db.campaigns.update_one({"id": campaign["id"]}, {"$set": {
        "status": final_status,
        "sent_at": now,
        "delivery_log": delivery_log,
        "stats": {
            "candidates": len(candidates),
            "eligible": len(eligible),
            "skipped": len(skipped),
            "success": success,
            "failure": failure,
        },
    }})
    return {
        "campaign_id": campaign["id"],
        "status": final_status,
        "success": success,
        "failure": failure,
        "skipped": len(skipped),
    }


def _render_html(message: str, client: dict) -> str:
    safe = (message
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br/>"))
    name = (client.get("full_name") or "").split(" ")[0] or "there"
    return f"<p>Hi {name},</p><p>{safe}</p><p style='color:#999;font-size:12px'>You are receiving this because you opted in to marketing from Natural Medical Solutions. Reply STOP to opt out.</p>"


@api.post("/campaigns")
async def create_campaign(payload: CampaignIn, request: Request,
                          user=Depends(require_roles("admin", "practitioner", "staff"))):
    if payload.channel not in CHANNELS:
        raise HTTPException(status_code=400, detail={
            "code": "invalid_channel", "allowed": list(CHANNELS),
        })
    if payload.channel == "email" and not payload.subject:
        raise HTTPException(status_code=400, detail={
            "code": "subject_required", "message": "Email campaigns need a subject.",
        })
    if payload.filter_type not in FILTER_TYPES:
        raise HTTPException(status_code=400, detail={
            "code": "invalid_filter_type", "allowed": list(FILTER_TYPES),
        })

    now = datetime.now(timezone.utc)
    doc = {
        "id": new_id(),
        "title": payload.title.strip(),
        "subject": (payload.subject or "").strip() or None,
        "message": payload.message,
        "channel": payload.channel,
        "filter_type": payload.filter_type,
        "filter_params": payload.filter_params or {},
        "schedule_at": payload.schedule_at,
        "status": "scheduled" if payload.schedule_at else "sending",
        "created_by": user["id"],
        "created_by_name": user.get("full_name") or user.get("email"),
        "created_at": now,
        "sent_at": None,
        "delivery_log": [],
        "stats": None,
    }
    await db.campaigns.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "campaign.create",
                    resource_type="campaign", resource_id=doc["id"],
                    severity="high", outcome="success",
                    metadata={"channel": payload.channel,
                              "filter_type": payload.filter_type,
                              "scheduled": bool(payload.schedule_at)},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    if payload.schedule_at:
        return _strip_id(doc)
    # Send now.
    await _run_campaign(doc)
    doc = await db.campaigns.find_one({"id": doc["id"]})
    return _strip_id(doc)


@api.get("/campaigns")
async def list_campaigns(user=Depends(require_roles("admin", "practitioner", "staff", "medical_assistant"))):
    rows = await db.campaigns.find({}).sort("created_at", -1).to_list(200)
    out = []
    for r in rows:
        # Trim delivery_log in list view — full log is on the detail endpoint.
        summary = {**_strip_id(r)}
        summary["delivery_log_count"] = len(summary.get("delivery_log") or [])
        summary.pop("delivery_log", None)
        out.append(summary)
    return out


@api.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str,
                       user=Depends(require_roles("admin", "practitioner", "staff", "medical_assistant"))):
    c = await db.campaigns.find_one({"id": campaign_id})
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return _strip_id(c)


@api.post("/campaigns/{campaign_id}/run")
async def run_scheduled(campaign_id: str, request: Request,
                        user=Depends(require_roles("admin"))):
    """Manual trigger for scheduled campaigns (no cron in this build)."""
    c = await db.campaigns.find_one({"id": campaign_id})
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if c.get("status") not in ("scheduled", "sending"):
        raise HTTPException(status_code=409, detail=f"Campaign is {c.get('status')}")
    result = await _run_campaign(c)
    await log_audit(db, user["id"], user["email"], "campaign.dispatch",
                    resource_type="campaign", resource_id=campaign_id,
                    metadata=result,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return result
