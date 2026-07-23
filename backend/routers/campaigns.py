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

import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo import ReturnDocument

from audit import get_client_ip, log_audit
from deps import _strip_id, api, db, require_roles
from models import new_id
from notifiers import email_status, send_email, send_sms, sms_status


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


# Statuses that mean the campaign is finalised or in-flight and MUST NOT
# be picked up again by the worker or manual retry.
TERMINAL_STATUSES = ("completed", "sent_with_failures", "failed", "cancelled")
IN_FLIGHT_STATUSES = ("processing", "sending")


async def _run_campaign(campaign: dict, *, worker_id: Optional[str] = None) -> dict:
    """Actually dispatch to SendGrid / Twilio, appending delivery_log entries.

    Callers MUST have already claimed the campaign atomically (status set to
    `processing` with a unique worker/lock id). This function is idempotent
    within a claim — it writes final status once and does not re-check
    scheduled_at.
    """
    started_at = datetime.now(timezone.utc)
    try:
        candidates = await _resolve_recipients(campaign["filter_type"], campaign.get("filter_params") or {})
        eligible, skipped = _partition(candidates, campaign["channel"])
    except Exception as e:
        await db.campaigns.update_one({"id": campaign["id"]}, {"$set": {
            "status": "failed",
            "failure_reason": f"recipient_resolution_failed: {str(e)[:200]}",
            "completed_at": datetime.now(timezone.utc),
        }})
        return {"campaign_id": campaign["id"], "status": "failed",
                "failure_reason": str(e)[:200]}

    delivery_log = []
    success = 0
    failure = 0

    for s in skipped:
        delivery_log.append({
            "client_id": s["client_id"], "status": "skipped",
            "reason": s["reason"], "ts": started_at,
        })

    for c in eligible:
        try:
            if campaign["channel"] == "email":
                status = await send_email(
                    db, c["email"],
                    _fill_variables(campaign.get("subject") or campaign["title"], _build_context(c)),
                    _render_html(campaign["message"], c),
                    plain_text=_render_plain(campaign["message"], c),
                    action="campaign.email",
                    payload_metadata={"campaign_id": campaign["id"]},
                )
            else:
                status = await send_sms(
                    db, c.get("phone", ""),
                    _render_plain(campaign["message"], c),
                    action="campaign.sms",
                    payload_metadata={"campaign_id": campaign["id"]},
                )
            delivery_log.append({
                "client_id": c.get("id"), "status": status, "ts": started_at,
                "channel": campaign["channel"],
            })
            if status in ("sent", "sent_stub"):
                success += 1
            else:
                failure += 1
        except Exception as e:  # notifier already writes to integration_log
            delivery_log.append({"client_id": c.get("id"), "status": "failed",
                                  "error": str(e)[:200], "ts": started_at})
            failure += 1

    if failure and not success:
        final_status = "failed"
        failure_reason = f"{failure} of {failure + success} recipients failed to send"
    elif failure:
        final_status = "sent_with_failures"
        failure_reason = f"{failure} of {failure + success} recipients failed"
    else:
        final_status = "completed"
        failure_reason = None

    completed_at = datetime.now(timezone.utc)
    await db.campaigns.update_one({"id": campaign["id"]}, {"$set": {
        "status": final_status,
        "sent_at": started_at,
        "completed_at": completed_at,
        "failure_reason": failure_reason,
        "delivery_log": delivery_log,
        "stats": {
            "candidates": len(candidates),
            "eligible": len(eligible),
            "skipped": len(skipped),
            "success": success,
            "failure": failure,
        },
        # Preserve worker_id if it was set during atomic claim
        **({"worker_id": worker_id} if worker_id else {}),
    }})
    return {
        "campaign_id": campaign["id"],
        "status": final_status,
        "success": success,
        "failure": failure,
        "skipped": len(skipped),
    }


async def _try_claim(campaign_id: str, worker_id: str,
                     allowed_from: tuple = ("scheduled",)) -> Optional[dict]:
    """Atomically transition status → `processing` if the campaign is still
    in an allowed prior state. Returns the claimed doc, or None if another
    worker (or a manual run) has already grabbed it.
    """
    now = datetime.now(timezone.utc)
    result = await db.campaigns.find_one_and_update(
        {
            "id": campaign_id,
            "status": {"$in": list(allowed_from)},
        },
        {"$set": {
            "status": "processing",
            "started_at": now,
            "worker_id": worker_id,
            # Clear stale artefacts from any previous failed run so retries
            # start with a fresh delivery_log.
            "delivery_log": [],
            "stats": None,
            "failure_reason": None,
            "completed_at": None,
        }},
        return_document=ReturnDocument.AFTER,
    )
    return result


_VAR_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def _build_context(client: dict) -> dict:
    """Build the merge-field context for a single recipient."""
    full = (client.get("full_name") or "").strip()
    parts = full.split(" ", 1)
    first = parts[0] if parts else ""
    last = parts[1] if len(parts) > 1 else ""
    return {
        "patient": {
            "first_name": first or "there",
            "last_name": last,
            "full_name": full or "there",
            "email": client.get("email") or "",
            "phone": client.get("phone") or "",
        },
        "clinic": {
            "name": os.environ.get("PRACTICE_NAME", "Natural Medical Solutions"),
            "phone": os.environ.get("PRACTICE_PHONE", "(770) 674-6311"),
            "email": os.environ.get("PRACTICE_EMAIL", "info@natmedsol.com"),
        },
        # Appointment / provider / membership vars fall back to empty strings —
        # campaign senders shouldn't depend on live joins to keep the send loop cheap.
        "appointment": {},
        "provider": {},
        "membership": {},
        "package": {},
    }


def _fill_variables(text: str, ctx: dict) -> str:
    def _sub(match):
        key = match.group(1)
        cur = ctx
        for part in key.split("."):
            if not isinstance(cur, dict):
                return match.group(0)
            cur = cur.get(part)
            if cur is None:
                return ""  # missing var → empty (safer than leaving braces in email)
        return str(cur)
    return _VAR_RE.sub(_sub, text or "")


def _render_html(message: str, client: dict) -> str:
    """Render a campaign message with merge-field substitution.
    If `message` already looks like HTML (starts with a tag), we trust it
    (it came from the TipTap rich-text editor) and only substitute variables.
    Otherwise we escape and wrap it as before."""
    ctx = _build_context(client)
    filled = _fill_variables(message or "", ctx)
    stripped = filled.lstrip()
    footer = ("<p style='color:#999;font-size:12px'>You are receiving this because "
              "you opted in to marketing from Natural Medical Solutions. "
              "Reply STOP to opt out.</p>")
    if stripped.startswith("<"):
        return filled + footer
    safe = (filled
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br/>"))
    name = ctx["patient"]["first_name"]
    return f"<p>Hi {name},</p><p>{safe}</p>{footer}"


def _render_plain(message: str, client: dict) -> str:
    """Plain-text render for SMS. Strips HTML tags and substitutes variables."""
    ctx = _build_context(client)
    filled = _fill_variables(message or "", ctx)
    if "<" in filled:
        # Cheap HTML → text: drop tags, collapse whitespace.
        text = re.sub(r"<br\s*/?>", "\n", filled, flags=re.I)
        text = re.sub(r"</p>", "\n\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", "", text)
        return re.sub(r"[ \t]+", " ", text).strip()
    return filled

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
    # Send now — go through the same atomic-claim → dispatch path used by the
    # worker so the two flows can never diverge.
    worker_id = f"web:{uuid.uuid4()}"
    claimed = await _try_claim(doc["id"], worker_id, allowed_from=("sending",))
    if claimed:
        await _run_campaign(claimed, worker_id=worker_id)
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
    """Manual trigger for scheduled campaigns. Uses the same atomic claim as
    the background worker, so a scheduled campaign can never be dispatched
    twice — even if an admin clicks Run at the exact moment the worker
    processes it."""
    c = await db.campaigns.find_one({"id": campaign_id})
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if c.get("status") in TERMINAL_STATUSES + IN_FLIGHT_STATUSES:
        raise HTTPException(status_code=409, detail={
            "code": "campaign_not_dispatchable",
            "current_status": c.get("status"),
        })
    worker_id = f"manual:{user['id']}:{uuid.uuid4()}"
    claimed = await _try_claim(campaign_id, worker_id, allowed_from=("scheduled",))
    if not claimed:
        raise HTTPException(status_code=409, detail={
            "code": "already_claimed",
            "message": "This campaign is already being processed by another worker.",
        })
    result = await _run_campaign(claimed, worker_id=worker_id)
    await log_audit(db, user["id"], user["email"], "campaign.dispatch",
                    resource_type="campaign", resource_id=campaign_id,
                    metadata={**result, "worker_id": worker_id},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return result


@api.post("/campaigns/{campaign_id}/cancel")
async def cancel_scheduled(campaign_id: str, request: Request,
                           user=Depends(require_roles("admin"))):
    """Cancel a scheduled campaign BEFORE it's picked up. In-flight or
    finished campaigns cannot be cancelled."""
    c = await db.campaigns.find_one({"id": campaign_id})
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if c.get("status") != "scheduled":
        raise HTTPException(status_code=409, detail={
            "code": "not_cancellable",
            "current_status": c.get("status"),
            "message": "Only campaigns in 'scheduled' state can be cancelled.",
        })
    now = datetime.now(timezone.utc)
    result = await db.campaigns.find_one_and_update(
        {"id": campaign_id, "status": "scheduled"},
        {"$set": {
            "status": "cancelled",
            "cancelled_at": now,
            "cancelled_by": user["id"],
            "cancelled_by_name": user.get("full_name") or user.get("email"),
        }},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise HTTPException(status_code=409, detail={
            "code": "race_lost",
            "message": "Campaign transitioned out of 'scheduled' while cancelling.",
        })
    await log_audit(db, user["id"], user["email"], "campaign.cancel",
                    resource_type="campaign", resource_id=campaign_id,
                    metadata={"was_scheduled_at": c.get("schedule_at")},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(result)


@api.post("/campaigns/{campaign_id}/retry")
async def retry_failed(campaign_id: str, request: Request,
                       user=Depends(require_roles("admin"))):
    """Retry a campaign that ended in `failed`. Completed campaigns cannot
    be retried (per spec) — this is intentional to prevent duplicate sends."""
    c = await db.campaigns.find_one({"id": campaign_id})
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if c.get("status") != "failed":
        raise HTTPException(status_code=409, detail={
            "code": "not_retryable",
            "current_status": c.get("status"),
            "message": "Only campaigns in 'failed' state can be retried.",
        })
    worker_id = f"retry:{user['id']}:{uuid.uuid4()}"
    claimed = await _try_claim(campaign_id, worker_id, allowed_from=("failed",))
    if not claimed:
        raise HTTPException(status_code=409, detail={
            "code": "already_claimed",
            "message": "Campaign is currently in-flight.",
        })
    result = await _run_campaign(claimed, worker_id=worker_id)
    await log_audit(db, user["id"], user["email"], "campaign.retry",
                    resource_type="campaign", resource_id=campaign_id,
                    metadata={**result, "worker_id": worker_id},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return result


@api.get("/campaigns/config/delivery")
async def delivery_config(user=Depends(require_roles("admin", "practitioner", "staff", "medical_assistant"))):
    """Boolean report of which delivery credentials are configured. Secret
    values are NEVER returned. Frontend uses this to label simulated sends."""
    return {
        "email": {
            "sendgrid_api_key": bool(os.environ.get("SENDGRID_API_KEY")),
            "sendgrid_from_email": bool(os.environ.get("SENDGRID_FROM_EMAIL")),
            "mode": email_status(),  # "live" | "sent_stub"
        },
        "sms": {
            "twilio_account_sid": bool(os.environ.get("TWILIO_ACCOUNT_SID")),
            "twilio_auth_token": bool(os.environ.get("TWILIO_AUTH_TOKEN")),
            "twilio_from_number": bool(os.environ.get("TWILIO_FROM_NUMBER")),
            "mode": sms_status(),
        },
        "hipaa_mode": bool(os.environ.get("HIPAA_MODE")),
        "simulated": email_status() != "live" or sms_status() != "live",
    }


# --------------------------------------------------------------------------- #
# Scheduler tick — called by the APScheduler job (see server.py).             #
# Also exposed as an authenticated admin endpoint so ops can trigger a sweep  #
# manually or from an external cron/monitor if APScheduler is disabled.       #
# --------------------------------------------------------------------------- #
async def process_due_campaigns(worker_prefix: str = "scheduler") -> dict:
    """Find scheduled campaigns whose `schedule_at` is <= now and dispatch
    them via the atomic-claim path. Returns a summary dict.
    """
    now = datetime.now(timezone.utc)
    processed = 0
    failed = 0
    skipped_races = 0
    due_ids: List[str] = []
    async for row in db.campaigns.find({
        "status": "scheduled",
        "schedule_at": {"$lte": now},
    }, {"id": 1}).limit(50):
        due_ids.append(row["id"])
    for cid in due_ids:
        worker_id = f"{worker_prefix}:{uuid.uuid4()}"
        claimed = await _try_claim(cid, worker_id, allowed_from=("scheduled",))
        if not claimed:
            skipped_races += 1
            continue
        try:
            result = await _run_campaign(claimed, worker_id=worker_id)
            if result.get("status") == "failed":
                failed += 1
            else:
                processed += 1
        except Exception as e:  # pragma: no cover — safety net
            await db.campaigns.update_one({"id": cid}, {"$set": {
                "status": "failed",
                "failure_reason": f"worker_exception: {str(e)[:200]}",
                "completed_at": datetime.now(timezone.utc),
            }})
            failed += 1
    return {"processed": processed, "failed": failed,
            "skipped_races": skipped_races, "candidates": len(due_ids)}


@api.post("/campaigns/scheduler/tick")
async def scheduler_tick(user=Depends(require_roles("admin"))):
    """Admin-only manual sweep of due scheduled campaigns."""
    return await process_due_campaigns(worker_prefix="manual-tick")
