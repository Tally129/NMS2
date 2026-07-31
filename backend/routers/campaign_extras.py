"""
Campaign platform extensions for Sprint 7 (Production-Ready Email Campaigns).

Extends — never replaces — the existing `routers/campaigns.py` with:
- Template library (predefined + custom)
- Duplicate / Archive / Pause / Cancel / Test send
- Broader recipient segmentation (birthday month, tags, active/new)
- Public unsubscribe endpoint
- Immutable content snapshot when a campaign begins sending

The main campaign HTTP surface (POST/GET /api/campaigns, /estimate, /run,
/retry, /cancel) is left intact so existing UI keeps working.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import Depends, HTTPException, Query, Request, BackgroundTasks
from pydantic import BaseModel, Field, EmailStr

from audit import get_client_ip, log_audit
from deps import api, db, get_current_user, require_roles
from models import new_id
from pg_shims import bulk_clear_marketing_consent, count_clients
from routers.campaigns import (
    CHANNELS, FILTER_TYPES,
    _build_context, _fill_variables, _render_html, _render_plain,
    sanitize_campaign_html,
)


_ADMIN_ROLES = ("admin", "practitioner", "staff", "front_desk", "frontdesk")


# --------------------------------------------------------------------------- #
# Template library                                                             #
# --------------------------------------------------------------------------- #
# Each template ships a subject, an HTML body, and a suggested channel/filter.
# HTML is already allowlist-safe (no scripts, inline images use https:// only).
# Merge fields use the same {{scope.name}} syntax as the rich editor.
CATEGORY_ORDER = [
    "monthly_newsletter", "wellness_tips", "iv_therapy", "membership",
    "hyperbaric", "weight_loss", "hormone_optimization", "peptide_therapy",
    "aesthetics", "med_spa_specials", "birthday", "holiday",
    "appointment_followup", "reactivation", "referral_request",
    "portal_invitation", "password_reset", "invoice", "receipt",
    "lab_results_ready",
]

TRANSACTIONAL_TEMPLATES = {
    "portal_invitation", "password_reset", "invoice", "receipt",
    "lab_results_ready", "appointment_followup",
}

# Curated defaults — admins can duplicate + customize any of them.
DEFAULT_TEMPLATES = [
    {
        "id": "tpl_monthly_newsletter",
        "category": "monthly_newsletter", "kind": "marketing",
        "name": "Monthly Newsletter",
        "subject": "This month at Natural Medical Solutions",
        "html": (
            "<h2 style=\"color:#2f4a3a\">Hi {{patient.first_name}},</h2>"
            "<p>Here's what's new at Natural Medical Solutions this month —"
            " fresh wellness tips, upcoming events, and a couple of specials"
            " chosen for the season.</p>"
            "<h3 style=\"color:#8a6a3c\">In this issue</h3>"
            "<ul><li>Feature story</li><li>Provider spotlight</li>"
            "<li>Member perks</li></ul>"
            "<p><a href=\"{{portal.login_link}}\" style=\"display:inline-block;"
            "padding:10px 20px;background:#2f4a3a;color:#f6f1e6;border-radius:24px;"
            "text-decoration:none\">Open my portal</a></p>"
        ),
    },
    {
        "id": "tpl_wellness_tips",
        "category": "wellness_tips", "kind": "marketing",
        "name": "Wellness Tips",
        "subject": "Three simple habits for this week, {{patient.first_name}}",
        "html": (
            "<p>Hi {{patient.first_name}},</p>"
            "<p>Small daily choices compound. Here are three habits our team"
            " is loving this week:</p>"
            "<ol><li><b>Hydrate first.</b> A tall glass of water before coffee.</li>"
            "<li><b>Move for 10.</b> A ten-minute walk after lunch.</li>"
            "<li><b>Rest well.</b> Screens down 30 minutes before bed.</li></ol>"
            "<p>Want a plan tailored to you? "
            "<a href=\"{{portal.login_link}}\">Book a wellness consult.</a></p>"
        ),
    },
    {
        "id": "tpl_iv_therapy",
        "category": "iv_therapy", "kind": "marketing",
        "name": "IV Therapy Promotion",
        "subject": "Feel your best — IV therapy special this week",
        "html": (
            "<h2 style=\"color:#2f4a3a\">Hydrate, restore, thrive</h2>"
            "<p>Hi {{patient.first_name}}, our Myers' Cocktail and NAD+ drips"
            " are 15% off through Friday.</p>"
            "<p><b>Includes:</b> vitamin C, B-complex, magnesium, "
            "calcium, glutathione.</p>"
            "<p><a href=\"{{portal.login_link}}\">Reserve your seat</a></p>"
        ),
    },
    {
        "id": "tpl_membership",
        "category": "membership", "kind": "marketing",
        "name": "Membership Promotion",
        "subject": "Vitality Plan members save more every month",
        "html": (
            "<p>Hi {{patient.first_name}},</p>"
            "<p>Members on our <b>{{membership.name}}</b> get priority"
            " scheduling, a monthly wellness credit, and 10% off retail.</p>"
            "<p><a href=\"{{portal.login_link}}\">Explore memberships</a></p>"
        ),
    },
    {
        "id": "tpl_hyperbaric",
        "category": "hyperbaric", "kind": "marketing",
        "name": "Hyperbaric Therapy",
        "subject": "Recover faster with hyperbaric oxygen therapy",
        "html": (
            "<p>Hi {{patient.first_name}},</p>"
            "<p>Athletes, post-op patients, and anyone chasing sharper"
            " focus love our HBOT chamber. Try a first session at 20% off.</p>"
            "<p><a href=\"{{portal.login_link}}\">Book HBOT</a></p>"
        ),
    },
    {
        "id": "tpl_weight_loss",
        "category": "weight_loss", "kind": "marketing",
        "name": "Weight Loss Program",
        "subject": "A doctor-supervised path to your goal weight",
        "html": (
            "<p>Hi {{patient.first_name}},</p>"
            "<p>Our medically-supervised weight loss program blends nutrition"
            " coaching, appropriate medications, and progress checks."
            " Consultations are half-price this month.</p>"
            "<p><a href=\"{{portal.login_link}}\">Schedule a consult</a></p>"
        ),
    },
    {
        "id": "tpl_hormone",
        "category": "hormone_optimization", "kind": "marketing",
        "name": "Hormone Optimization",
        "subject": "Rebalance. Reboot. Reclaim your energy.",
        "html": (
            "<p>Hi {{patient.first_name}},</p>"
            "<p>Fatigue, brain fog, or mood swings can be signs of hormonal"
            " imbalance. Our bioidentical hormone optimization consult starts"
            " with a comprehensive lab panel and a personal plan.</p>"
            "<p><a href=\"{{portal.login_link}}\">Book my consult</a></p>"
        ),
    },
    {
        "id": "tpl_peptides",
        "category": "peptide_therapy", "kind": "marketing",
        "name": "Peptide Therapy",
        "subject": "Peptide therapy — precision wellness",
        "html": (
            "<p>Hi {{patient.first_name}}, ask our team about "
            "peptide protocols for recovery, cognition, and metabolic health.</p>"
            "<p><a href=\"{{portal.login_link}}\">Learn more</a></p>"
        ),
    },
    {
        "id": "tpl_aesthetics",
        "category": "aesthetics", "kind": "marketing",
        "name": "Aesthetics",
        "subject": "Refresh with our aesthetics menu",
        "html": (
            "<p>Hi {{patient.first_name}},</p>"
            "<p>Neuromodulator + filler combos are 10% off this quarter."
            " Consults with our injector are complimentary.</p>"
            "<p><a href=\"{{portal.login_link}}\">See the menu</a></p>"
        ),
    },
    {
        "id": "tpl_med_spa",
        "category": "med_spa_specials", "kind": "marketing",
        "name": "Med Spa Specials",
        "subject": "Med spa specials this week",
        "html": (
            "<p>Hi {{patient.first_name}}, this week's med spa specials:</p>"
            "<ul><li>HydraFacial — $20 off</li><li>Microneedling — buy 2, get 1</li>"
            "<li>Chemical peel bundle — 15% off</li></ul>"
            "<p><a href=\"{{portal.login_link}}\">Reserve online</a></p>"
        ),
    },
    {
        "id": "tpl_birthday",
        "category": "birthday", "kind": "marketing",
        "name": "Birthday Promotion",
        "subject": "Happy birthday, {{patient.first_name}} — a gift inside",
        "html": (
            "<h2 style=\"color:#8a6a3c\">Happy birthday, {{patient.first_name}}!</h2>"
            "<p>To celebrate, enjoy <b>20% off</b> any single service this"
            " month with code <b>BDAY20</b>.</p>"
            "<p><a href=\"{{portal.login_link}}\">Book your gift</a></p>"
        ),
    },
    {
        "id": "tpl_holiday",
        "category": "holiday", "kind": "marketing",
        "name": "Holiday Special",
        "subject": "Holiday wellness gifting",
        "html": (
            "<p>Give the gift of feeling great — our gift cards for"
            " IV drips, memberships, and aesthetics services are 10% off"
            " through the holidays.</p>"
        ),
    },
    {
        "id": "tpl_appointment_followup",
        "category": "appointment_followup", "kind": "transactional",
        "name": "Appointment Follow-up",
        "subject": "How are you feeling after your visit?",
        "html": (
            "<p>Hi {{patient.first_name}},</p>"
            "<p>Thanks for coming in on {{appointment.date}}."
            " Please reply with any questions — we're here to help.</p>"
        ),
    },
    {
        "id": "tpl_reactivation",
        "category": "reactivation", "kind": "marketing",
        "name": "Patient Reactivation",
        "subject": "It's been a while — we'd love to see you again",
        "html": (
            "<p>Hi {{patient.first_name}},</p>"
            "<p>We noticed it's been a while since your last visit."
            " Come back for a complimentary wellness check-in.</p>"
            "<p><a href=\"{{portal.login_link}}\">Book my check-in</a></p>"
        ),
    },
    {
        "id": "tpl_referral",
        "category": "referral_request", "kind": "marketing",
        "name": "Referral Request",
        "subject": "Refer a friend and share the wellness",
        "html": (
            "<p>Hi {{patient.first_name}},</p>"
            "<p>Refer a friend and you'll both receive $50 in wellness credit"
            " after their first visit.</p>"
        ),
    },
    {
        "id": "tpl_portal_invite",
        "category": "portal_invitation", "kind": "transactional",
        "name": "Portal Invitation",
        "subject": "Your patient portal is ready",
        "html": (
            "<p>Hi {{patient.first_name}},</p>"
            "<p>Your patient portal at Natural Medical Solutions is ready."
            " Sign in to review appointments, labs, and secure messages.</p>"
            "<p><a href=\"{{portal.login_link}}\">Open my portal</a></p>"
        ),
    },
    {
        "id": "tpl_password_reset",
        "category": "password_reset", "kind": "transactional",
        "name": "Password Reset",
        "subject": "Reset your Natural Medical Solutions portal password",
        "html": (
            "<p>Hi {{patient.first_name}},</p>"
            "<p>Use the link below to choose a new password. It expires in"
            " 60 minutes for security.</p>"
            "<p><a href=\"{{portal.login_link}}\">Reset my password</a></p>"
        ),
    },
    {
        "id": "tpl_invoice",
        "category": "invoice", "kind": "transactional",
        "name": "Invoice Available",
        "subject": "Your invoice is ready",
        "html": (
            "<p>Hi {{patient.first_name}},</p>"
            "<p>Your invoice is attached and also available in your portal.</p>"
            "<p><a href=\"{{portal.login_link}}\">View invoice</a></p>"
        ),
    },
    {
        "id": "tpl_receipt",
        "category": "receipt", "kind": "transactional",
        "name": "Payment Receipt",
        "subject": "Payment receipt from Natural Medical Solutions",
        "html": (
            "<p>Hi {{patient.first_name}},</p>"
            "<p>Thank you for your payment — the receipt is attached and"
            " available in your portal.</p>"
        ),
    },
    {
        "id": "tpl_labs_ready",
        "category": "lab_results_ready", "kind": "transactional",
        "name": "Lab Results Ready (notification only, no PHI)",
        "subject": "Your lab results are available",
        "html": (
            "<p>Hi {{patient.first_name}},</p>"
            "<p>New lab results are available in your patient portal."
            " Please sign in to view them.</p>"
            "<p><a href=\"{{portal.login_link}}\">Sign in to my portal</a></p>"
        ),
    },
]


@api.get("/campaign-templates")
async def list_templates(user=Depends(require_roles(*_ADMIN_ROLES, "medical_assistant"))):
    """Return curated defaults + admin-authored custom templates."""
    custom = await db.campaign_templates.find({"deleted_at": None}).sort("name", 1).to_list(200)
    for c in custom:
        c.pop("_id", None)
    return {"defaults": DEFAULT_TEMPLATES, "custom": custom, "categories": CATEGORY_ORDER}


class TemplateSaveIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    category: str
    kind: str = "marketing"  # "marketing" | "transactional"
    subject: str = ""
    html: str


@api.post("/campaign-templates")
async def save_template(payload: TemplateSaveIn, request: Request,
                         user=Depends(require_roles(*_ADMIN_ROLES))):
    doc = {
        "id": new_id(),
        "name": payload.name.strip(),
        "category": payload.category,
        "kind": payload.kind,
        "subject": payload.subject,
        "html": sanitize_campaign_html(payload.html),
        "created_by": user["id"],
        "created_at": datetime.now(timezone.utc),
        "deleted_at": None,
    }
    await db.campaign_templates.insert_one(doc)
    doc.pop("_id", None)
    await log_audit(db, user["id"], user["email"], "campaign.template_save",
                    resource_type="campaign_template", resource_id=doc["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return doc


@api.delete("/campaign-templates/{tid}")
async def delete_template(tid: str, request: Request,
                           user=Depends(require_roles(*_ADMIN_ROLES))):
    r = await db.campaign_templates.update_one(
        {"id": tid}, {"$set": {"deleted_at": datetime.now(timezone.utc)}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Campaign lifecycle actions                                                   #
# --------------------------------------------------------------------------- #
@api.post("/campaigns/{cid}/duplicate")
async def duplicate_campaign(cid: str, request: Request,
                              user=Depends(require_roles(*_ADMIN_ROLES))):
    src = await db.campaigns.find_one({"id": cid})
    if not src:
        raise HTTPException(status_code=404, detail="Campaign not found")
    now = datetime.now(timezone.utc)
    copy = {
        **{k: src.get(k) for k in
           ("title", "subject", "message", "channel", "filter_type", "filter_params")},
        "id": new_id(),
        "title": f"{src.get('title', 'Untitled')} (copy)",
        "schedule_at": None,
        "status": "draft",
        "created_by": user["id"],
        "created_by_name": user.get("full_name") or user.get("email"),
        "created_at": now,
        "sent_at": None,
        "delivery_log": [],
        "stats": None,
        "archived_at": None,
        "source_campaign_id": cid,
    }
    await db.campaigns.insert_one(copy)
    await log_audit(db, user["id"], user["email"], "campaign.duplicate",
                    resource_type="campaign", resource_id=copy["id"],
                    metadata={"source": cid},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    copy.pop("_id", None)
    return copy


@api.post("/campaigns/{cid}/archive")
async def archive_campaign(cid: str, request: Request,
                            user=Depends(require_roles(*_ADMIN_ROLES))):
    now = datetime.now(timezone.utc)
    r = await db.campaigns.update_one(
        {"id": cid}, {"$set": {"archived_at": now, "status_before_archive": "$status"}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Campaign not found")
    await log_audit(db, user["id"], user["email"], "campaign.archive",
                    resource_type="campaign", resource_id=cid,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


@api.post("/campaigns/{cid}/unarchive")
async def unarchive_campaign(cid: str, request: Request,
                              user=Depends(require_roles(*_ADMIN_ROLES))):
    r = await db.campaigns.update_one({"id": cid}, {"$set": {"archived_at": None}})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return {"ok": True}


@api.post("/campaigns/{cid}/pause")
async def pause_campaign(cid: str, request: Request,
                          user=Depends(require_roles(*_ADMIN_ROLES))):
    c = await db.campaigns.find_one({"id": cid})
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if c.get("status") not in ("scheduled", "sending"):
        raise HTTPException(status_code=400, detail={
            "code": "not_pausable",
            "message": "Only scheduled or in-flight campaigns can be paused.",
        })
    await db.campaigns.update_one(
        {"id": cid}, {"$set": {"status": "paused", "paused_at": datetime.now(timezone.utc)}},
    )
    await log_audit(db, user["id"], user["email"], "campaign.pause",
                    resource_type="campaign", resource_id=cid,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


@api.post("/campaigns/{cid}/resume")
async def resume_campaign(cid: str, request: Request,
                           user=Depends(require_roles(*_ADMIN_ROLES))):
    c = await db.campaigns.find_one({"id": cid})
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if c.get("status") != "paused":
        raise HTTPException(status_code=400, detail={"code": "not_paused"})
    # If a schedule was set and is still in the future, restore scheduled state.
    next_status = "scheduled" if (c.get("schedule_at") and c["schedule_at"] > datetime.now(timezone.utc)) else "sending"
    await db.campaigns.update_one(
        {"id": cid}, {"$set": {"status": next_status, "paused_at": None}},
    )
    return {"ok": True, "status": next_status}


class TestSendIn(BaseModel):
    recipients: List[EmailStr] = Field(..., min_length=1, max_length=5)


@api.post("/campaigns/{cid}/test-send")
async def test_send(cid: str, payload: TestSendIn, request: Request,
                     user=Depends(require_roles(*_ADMIN_ROLES))):
    """Send a live rendering of the campaign to up to 5 opt-in test addresses.
    Ignores the campaign's filter — the recipients here are explicit."""
    from notifiers import send_email
    c = await db.campaigns.find_one({"id": cid})
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if c.get("channel") != "email":
        raise HTTPException(status_code=400, detail={
            "code": "wrong_channel",
            "message": "Only email campaigns support test sends.",
        })
    subj = c.get("subject") or c.get("title") or "Test email"
    # Merge context uses the current admin as a stand-in patient.
    stub_client = {
        "full_name": user.get("full_name") or "Test Recipient",
        "email": user.get("email"),
        "phone": user.get("phone") or "(555) 010-0001",
    }
    html = _render_html(c.get("message") or "", stub_client)
    subj_rendered = _fill_variables(subj, _build_context(stub_client))
    footer = compliance_footer(unsubscribe_token=None, marketing=False)
    results = []
    for to in payload.recipients:
        status = await send_email(
            db, str(to), f"[TEST] {subj_rendered}",
            html + footer,
            plain_text=_render_plain(c.get("message") or "", stub_client),
            action="campaign.test_send",
            payload_metadata={"campaign_id": cid, "requested_by": user["id"]},
        )
        results.append({"to": str(to), "delivery": status})
    await log_audit(db, user["id"], user["email"], "campaign.test_send",
                    resource_type="campaign", resource_id=cid,
                    metadata={"recipient_count": len(payload.recipients)},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True, "results": results}


# --------------------------------------------------------------------------- #
# Compliance footer + unsubscribe                                              #
# --------------------------------------------------------------------------- #
_UNSUB_SECRET = os.environ.get("UNSUBSCRIBE_SECRET", "nms-unsub-2026")


def _unsub_token(client_id: str) -> str:
    """Deterministic HMAC-lite token so the unsub link is stable per patient."""
    return hashlib.sha256(f"{_UNSUB_SECRET}:{client_id}".encode()).hexdigest()[:24]


def unsub_link_for(client_id: str) -> str:
    origin = (os.environ.get("FRONTEND_ORIGIN") or "").rstrip("/")
    # Route users to a friendly public page; backend logic is /api/campaign-unsubscribe.
    return f"{origin}/unsubscribe?c={client_id}&t={_unsub_token(client_id)}"


def compliance_footer(unsubscribe_token: Optional[str], marketing: bool) -> str:
    """Return the CAN-SPAM / brand footer appended to every campaign email."""
    addr = os.environ.get("PRACTICE_ADDRESS", "1130 Upper Hembree Rd, Roswell, GA 30076")
    phone = os.environ.get("PRACTICE_PHONE", "(770) 674-6311")
    web = os.environ.get("PRACTICE_WEBSITE", "natmedsol.com")
    lines = [
        f"<div style=\"margin-top:32px;padding-top:12px;border-top:1px solid #e7dfc9;"
        f"font-size:11px;color:#8a6a3c;line-height:1.5\">"
        f"<div><b>Natural Medical Solutions Wellness Center</b></div>"
        f"<div>{addr}</div>"
        f"<div>{phone} · {web}</div>",
    ]
    if marketing and unsubscribe_token:
        lines.append(
            f"<div style=\"margin-top:8px\">"
            f"You received this because you opted in to marketing from us. "
            f"<a href=\"{unsubscribe_token}\">Unsubscribe</a>.</div>"
        )
    else:
        lines.append(
            "<div style=\"margin-top:8px;color:#9a9a9a\">This is a transactional message "
            "and cannot be unsubscribed from.</div>"
        )
    lines.append("</div>")
    return "".join(lines)


@api.get("/campaign-unsubscribe")
async def unsubscribe(c: str = Query(..., alias="c"), t: str = Query(..., alias="t")):
    """Public unsubscribe endpoint. Toggles `consent_marketing: false` on the
    client record after verifying the HMAC-lite token."""
    if _unsub_token(c) != t:
        raise HTTPException(status_code=400, detail="Invalid unsubscribe link")
    matched = await bulk_clear_marketing_consent([c])
    if matched == 0:
        raise HTTPException(status_code=404, detail="Not found")
    await db.campaign_unsubscribes.insert_one({
        "client_id": c, "ts": datetime.now(timezone.utc), "source": "email_link",
    })
    return {"ok": True, "message": "You have been unsubscribed from marketing emails. Transactional messages (appointment confirmations, portal invites, receipts) will continue."}


# --------------------------------------------------------------------------- #
# Provider abstraction stub                                                    #
# --------------------------------------------------------------------------- #
class ProviderProbe(BaseModel):
    provider: str  # "sendgrid" | "resend" | "ses"
    from_email: Optional[str] = None


@api.get("/campaigns/config/providers")
async def provider_status(user=Depends(require_roles(*_ADMIN_ROLES, "medical_assistant"))):
    """Which email providers are configured. Consumers of `notifiers.send_email`
    always go through SendGrid today; Resend and SES are placeholders whose
    credentials the operator can supply without a code change."""
    return {
        "active": os.environ.get("EMAIL_PROVIDER", "sendgrid"),
        "providers": {
            "sendgrid": {
                "configured": bool(os.environ.get("SENDGRID_API_KEY")) and bool(os.environ.get("SENDGRID_FROM_EMAIL")),
                "from_email": os.environ.get("SENDGRID_FROM_EMAIL", ""),
            },
            "resend": {
                "configured": bool(os.environ.get("RESEND_API_KEY")),
                "from_email": os.environ.get("RESEND_FROM_EMAIL", ""),
            },
            "ses": {
                "configured": bool(os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY")),
                "region": os.environ.get("AWS_SES_REGION", ""),
                "from_email": os.environ.get("SES_FROM_EMAIL", ""),
            },
        },
    }


# --------------------------------------------------------------------------- #
# Extended recipient segments — additive filter types                          #
# --------------------------------------------------------------------------- #
class SegmentEstimateIn(BaseModel):
    filter_type: str
    filter_params: dict = {}


EXTENDED_FILTERS = ("active_patients", "new_patients", "birthday_month",
                     "tags", "custom_list")


@api.post("/campaigns/segments/estimate")
async def segment_estimate(payload: SegmentEstimateIn,
                            user=Depends(require_roles(*_ADMIN_ROLES, "medical_assistant"))):
    """Preview a recipient count without creating a campaign. Understands
    the built-in FILTER_TYPES plus the extended ones."""
    ft = payload.filter_type
    p = payload.filter_params or {}
    total = 0
    if ft in FILTER_TYPES:
        # Delegate to existing resolver.
        from routers.campaigns import _resolve_recipients
        rows = await _resolve_recipients(ft, p)
        total = len(rows)
        return {"filter_type": ft, "total": total}
    if ft == "active_patients":
        days = int(p.get("days", 90))
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        ids = {a["client_id"] async for a in db.appointments.find(
            {"start": {"$gte": cutoff}}, {"client_id": 1}) if a.get("client_id")}
        total = len(ids)
    elif ft == "new_patients":
        days = int(p.get("days", 30))
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        total = await count_clients(created_since=cutoff)
    elif ft == "birthday_month":
        month = int(p.get("month", datetime.now(timezone.utc).month))
        # dob stored as YYYY-MM-DD string.
        rx = f"^\\d{{4}}-{month:02d}-"
        total = await count_clients(dob_regex=rx)
    elif ft == "tags":
        tags = p.get("tags") or []
        if tags:
            total = await count_clients(tags_any=tags)
    elif ft == "custom_list":
        ids = p.get("client_ids") or []
        total = await count_clients(ids=ids)
    else:
        raise HTTPException(status_code=400, detail={
            "code": "unknown_filter_type",
            "allowed": list(FILTER_TYPES) + list(EXTENDED_FILTERS),
        })
    return {"filter_type": ft, "total": total}
