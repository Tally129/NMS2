"""
Legal & Policies module.

Public endpoints (no auth required):
  GET  /api/legal/policies                       — list published policies
  GET  /api/legal/policies/{slug}                — current published version
  GET  /api/legal/policies/{slug}/versions       — version history (published only)

Authenticated endpoints:
  POST /api/legal/acceptances                    — record acknowledgment
  GET  /api/legal/acceptances/me                 — my acknowledgments
  GET  /api/legal/pending-reacceptance           — list policies I need to re-accept

Admin endpoints (require role in _ADMIN_ROLES):
  POST /api/legal/policies                       — create a policy
  POST /api/legal/policies/{slug}/versions       — publish a new version
  PATCH /api/legal/policies/{slug}               — edit metadata
  POST /api/legal/policies/{slug}/archive        — archive
  GET  /api/legal/policies/{slug}/acceptance-stats
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

from audit import get_client_ip, log_audit
from deps import api, db, get_authenticated_user, require_roles
from models import new_id
from routers.campaign_extras import sanitize_campaign_html  # reuse safe HTML sanitizer


_ADMIN_ROLES = ("admin",)

# --------------------------------------------------------------------------- #
# Curated default policies (English, plain-language). Rendered on first boot.  #
# Each entry seeds a v1.0 version dated 2026-07-24.                             #
# --------------------------------------------------------------------------- #
DEFAULT_POLICIES = [
    {
        "slug": "terms",
        "title": "Terms of Use",
        "description": "Governs your use of the Natural Medical Solutions website and patient portal.",
        "icon": "scale",
        "kind": "legal",
        "requires_acceptance": True,
        "requires_reacceptance": False,
        "sort_order": 10,
        "content_html": """
<h2>Welcome</h2>
<p>These Terms of Use govern your access to and use of the Natural Medical Solutions website, patient portal, telehealth features, and any related services (collectively, the <b>Services</b>). By using the Services you agree to these Terms. If you do not agree, please do not use the Services.</p>
<h2>Eligibility</h2>
<p>The Services are intended for adults (18+) or minors accessing them through a verified parent or legal guardian account.</p>
<h2>Your account</h2>
<p>You are responsible for maintaining the confidentiality of your credentials and for all activity that occurs under your account. Notify us immediately if you suspect unauthorized access.</p>
<h2>Acceptable use</h2>
<p>You agree not to attempt to bypass security, scrape, reverse-engineer, resell, or misuse the Services. You will not upload malicious content or impersonate any other person.</p>
<h2>Medical information</h2>
<p>Content in the Services is for general informational purposes and does not create a physician–patient relationship except where you have established care with a Natural Medical Solutions provider. Always seek in-person care for medical emergencies.</p>
<h2>Termination</h2>
<p>We may suspend or terminate access at our discretion for policy violations or safety concerns. You may close your account at any time by contacting support.</p>
<h2>Contact</h2>
<p>Questions about these Terms may be directed to <a href="mailto:info@natmedsol.com">info@natmedsol.com</a>.</p>
""",
    },
    {
        "slug": "privacy",
        "title": "Privacy Policy",
        "description": "Explains how we collect, use, protect, and manage your personal information.",
        "icon": "shield",
        "kind": "legal",
        "requires_acceptance": True,
        "requires_reacceptance": False,
        "sort_order": 20,
        "content_html": """
<h2>Overview</h2>
<p>Natural Medical Solutions (\"we\", \"us\") respects your privacy. This Privacy Policy explains what information we collect, how we use it, and the choices you have. Additional protections apply to Protected Health Information (PHI); see our <a href="/legal/hipaa">HIPAA Notice</a>.</p>
<h2>What we collect</h2>
<ul><li>Contact and account information (name, email, phone)</li><li>Demographic and health information you provide</li><li>Appointment, payment, and service history</li><li>Device and log data (IP address, browser, timestamps)</li><li>Cookies and similar technologies (see the <a href="/legal/cookies">Cookie Policy</a>)</li></ul>
<h2>How we use information</h2>
<ul><li>To deliver clinical care and portal features</li><li>To operate our practice (billing, appointments, communications)</li><li>To secure our systems and prevent fraud</li><li>To comply with legal obligations</li></ul>
<h2>Who we share with</h2>
<p>We do <b>not</b> sell personal information. We share information only with vetted service providers under confidentiality agreements, with your treating providers, or where required by law.</p>
<h2>Your choices</h2>
<p>You can update your contact preferences, opt out of marketing at any time, and request access, correction, or deletion of your data by contacting <a href="mailto:info@natmedsol.com">info@natmedsol.com</a>.</p>
<h2>Security</h2>
<p>We use industry-standard safeguards including encryption in transit and at rest, access controls, MFA for workforce accounts, and immutable audit logs.</p>
""",
    },
    {
        "slug": "hipaa",
        "title": "Notice of Privacy Practices (HIPAA)",
        "description": "Describes how your Protected Health Information may be used and disclosed and explains your rights under HIPAA.",
        "icon": "badge-check",
        "kind": "hipaa",
        "requires_acceptance": True,
        "requires_reacceptance": True,
        "sort_order": 30,
        "content_html": """
<p><em>THIS NOTICE DESCRIBES HOW MEDICAL INFORMATION ABOUT YOU MAY BE USED AND DISCLOSED AND HOW YOU CAN GET ACCESS TO THIS INFORMATION. PLEASE REVIEW IT CAREFULLY.</em></p>
<h2>Our commitment</h2>
<p>Natural Medical Solutions is committed to protecting the privacy of your Protected Health Information (PHI) in accordance with the Health Insurance Portability and Accountability Act (HIPAA).</p>
<h2>How we may use and disclose your PHI</h2>
<ul><li><b>Treatment</b> — to provide, coordinate, or manage your care.</li><li><b>Payment</b> — to bill and collect for services delivered.</li><li><b>Healthcare operations</b> — quality assessment, staff training, compliance.</li><li><b>As required by law</b> — including public-health reporting and lawful court orders.</li></ul>
<h2>Uses that require your written authorization</h2>
<p>Marketing communications, sales of PHI, most disclosures of psychotherapy notes, and other uses not described here require your explicit written authorization, which you may revoke at any time.</p>
<h2>Your rights</h2>
<ul><li>Inspect and obtain a copy of your records</li><li>Request amendments</li><li>Receive an accounting of disclosures</li><li>Request restrictions on certain uses and disclosures</li><li>Request confidential communications</li><li>File a complaint without retaliation</li></ul>
<h2>Contact our Privacy Officer</h2>
<p>Privacy Officer, Natural Medical Solutions Wellness Center, 1130 Upper Hembree Rd, Roswell, GA 30076 · (770) 674-6311 · <a href="mailto:privacy@natmedsol.com">privacy@natmedsol.com</a>. You may also file a complaint with the U.S. Department of Health &amp; Human Services Office for Civil Rights.</p>
""",
    },
    {
        "slug": "financial",
        "title": "Financial Policy",
        "description": "Billing, insurance, membership, payment, cancellation, and refund policies.",
        "icon": "receipt",
        "kind": "legal",
        "requires_acceptance": True,
        "requires_reacceptance": False,
        "sort_order": 40,
        "content_html": """
<h2>Payment for services</h2>
<p>Payment is due at the time of service unless prior arrangements are made. We accept major credit cards, cash, HSA/FSA cards, and financing options.</p>
<h2>Insurance</h2>
<p>Wellness and elective services are generally not billed to insurance unless specifically arranged in advance. Where insurance filing is offered, patients remain responsible for balances not covered by their plan.</p>
<h2>Memberships and packages</h2>
<p>Memberships auto-renew monthly on the anniversary of enrollment. You may cancel at any time; cancellations take effect at the end of the current billing period. Prepaid packages are non-refundable once redeemed but transferable between eligible services within one year.</p>
<h2>Cancellations &amp; no-shows</h2>
<p>Please provide at least 24 hours' notice for cancellations. Same-day cancellations or no-shows may incur a fee of up to 50% of the scheduled service.</p>
<h2>Refunds</h2>
<p>Refund requests are evaluated case-by-case and typically apply only to unrendered services within 30 days of purchase.</p>
""",
    },
    {
        "slug": "patient-portal",
        "title": "Patient Portal Terms",
        "description": "Rules and expectations for using the secure patient portal.",
        "icon": "shield",
        "kind": "portal",
        "requires_acceptance": True,
        "requires_reacceptance": False,
        "sort_order": 50,
        "content_html": """
<h2>Purpose</h2>
<p>The patient portal is a secure tool for reviewing your care, messaging your providers, requesting appointments, and managing your account.</p>
<h2>Your responsibilities</h2>
<ul><li>Keep your login credentials confidential</li><li>Do not use the portal for medical emergencies — call 911</li><li>Expect a response to non-urgent messages within two business days</li><li>Report suspected unauthorized access promptly</li></ul>
<h2>Content accuracy</h2>
<p>Please review the information in your portal for accuracy. Notify us of discrepancies so we can correct your record.</p>
<h2>Ending access</h2>
<p>Portal access may be paused or terminated for abuse, safety concerns, or at your request.</p>
""",
    },
    {
        "slug": "telehealth",
        "title": "Telehealth Consent",
        "description": "Information regarding virtual visits, privacy, and patient consent.",
        "icon": "video",
        "kind": "consent",
        "requires_acceptance": True,
        "requires_reacceptance": False,
        "sort_order": 60,
        "content_html": """
<h2>What telehealth is</h2>
<p>Telehealth delivers care through secure video, audio, and messaging technology. It can complement — but does not replace — in-person care where physical examination or procedures are needed.</p>
<h2>Benefits and risks</h2>
<ul><li>Convenient access to care from a private location</li><li>Reduced travel and exposure</li><li>Possible technical issues such as poor connection</li><li>Limits on physical examination</li></ul>
<h2>Privacy</h2>
<p>We use encrypted, HIPAA-aligned platforms. Telehealth sessions are not recorded without your explicit consent.</p>
<h2>Consent</h2>
<p>By scheduling a telehealth visit you consent to receive care by these methods and confirm you are located within a state or jurisdiction where your provider is licensed to practice.</p>
""",
    },
    {
        "slug": "email-sms",
        "title": "Email & SMS Communications",
        "description": "Explains how appointment reminders, email notifications, and text messaging are used.",
        "icon": "mail",
        "kind": "communications",
        "requires_acceptance": False,
        "requires_reacceptance": False,
        "sort_order": 70,
        "content_html": """
<h2>How we communicate</h2>
<p>We send appointment reminders, portal invitations, receipts, and marketing information via email and SMS. Some messages are <b>transactional</b> (appointments, receipts, portal access) and cannot be unsubscribed from — these are required to deliver your care. Marketing messages can be turned off at any time.</p>
<h2>Opting out</h2>
<p>Reply STOP to any marketing text or click the unsubscribe link at the bottom of any marketing email. Email us at <a href="mailto:info@natmedsol.com">info@natmedsol.com</a> to update your preferences directly.</p>
<h2>Message and data rates</h2>
<p>Standard message and data rates from your carrier may apply.</p>
""",
    },
    {
        "slug": "accessibility",
        "title": "Accessibility Statement",
        "description": "Our commitment to providing accessible healthcare technology.",
        "icon": "accessibility",
        "kind": "accessibility",
        "requires_acceptance": False,
        "requires_reacceptance": False,
        "sort_order": 80,
        "content_html": """
<h2>Our commitment</h2>
<p>Natural Medical Solutions is committed to ensuring digital accessibility for people with disabilities. We continually improve the user experience for everyone and apply relevant accessibility standards including WCAG 2.1 AA.</p>
<h2>What we do</h2>
<ul><li>Semantic HTML and ARIA labels for assistive technology</li><li>Keyboard navigation for all interactive elements</li><li>Sufficient color contrast and scalable typography</li><li>Text alternatives for meaningful images</li></ul>
<h2>Feedback</h2>
<p>If you experience any accessibility barriers, please contact <a href="mailto:accessibility@natmedsol.com">accessibility@natmedsol.com</a> or call (770) 674-6311 so we can help and improve.</p>
""",
    },
    {
        "slug": "cookies",
        "title": "Cookie Policy",
        "description": "Information regarding cookies and website technologies.",
        "icon": "file-text",
        "kind": "cookies",
        "requires_acceptance": False,
        "requires_reacceptance": False,
        "sort_order": 90,
        "content_html": """
<h2>What are cookies?</h2>
<p>Cookies are small text files stored on your device that help websites remember you and function properly. We use cookies and related technologies (like local storage) for authentication, security, and to remember your preferences.</p>
<h2>Categories we use</h2>
<ul><li><b>Strictly necessary</b> — session, login, security. These cannot be turned off without breaking the site.</li><li><b>Preference</b> — remembers UI choices such as sidebar state.</li><li><b>Analytics</b> — aggregate, anonymized usage information to improve the portal.</li></ul>
<h2>Your choices</h2>
<p>Most browsers allow you to control cookies through settings. Disabling strictly-necessary cookies may prevent you from logging in.</p>
""",
    },
]


class AcceptanceIn(BaseModel):
    policy_slug: str
    policy_version: str
    method: str = Field(default="click", max_length=40)


class PolicyEditIn(BaseModel):
    title: Optional[str] = Field(default=None, min_length=2, max_length=200)
    description: Optional[str] = Field(default=None, max_length=500)
    icon: Optional[str] = None
    kind: Optional[str] = None
    requires_acceptance: Optional[bool] = None
    requires_reacceptance: Optional[bool] = None
    sort_order: Optional[int] = None


class NewVersionIn(BaseModel):
    version: str = Field(..., min_length=1, max_length=20)  # e.g. "1.1" or "2.0"
    content_html: str
    effective_date: Optional[datetime] = None
    force_reacceptance: bool = False


# --------------------------------------------------------------------------- #
# Seeder                                                                       #
# --------------------------------------------------------------------------- #
async def seed_default_policies() -> None:
    """Idempotent — inserts a v1.0 for each default policy if missing."""
    now = datetime.now(timezone.utc)
    for tpl in DEFAULT_POLICIES:
        existing = await db.legal_policies.find_one({"slug": tpl["slug"]})
        v1 = {
            "version": "1.0",
            "content_html": sanitize_campaign_html(tpl["content_html"]),
            "effective_date": now,
            "created_at": now,
            "created_by": "system",
            "superseded_at": None,
        }
        if not existing:
            await db.legal_policies.insert_one({
                "id": new_id(),
                "slug": tpl["slug"], "title": tpl["title"],
                "description": tpl["description"], "icon": tpl["icon"],
                "kind": tpl["kind"],
                "requires_acceptance": tpl.get("requires_acceptance", True),
                "requires_reacceptance": tpl.get("requires_reacceptance", False),
                "sort_order": tpl.get("sort_order", 999),
                "current_version": "1.0",
                "versions": [v1],
                "archived_at": None,
                "created_at": now,
                "updated_at": now,
            })


def _current_version(policy: dict) -> Optional[dict]:
    cur = policy.get("current_version")
    for v in policy.get("versions") or []:
        if v.get("version") == cur:
            return v
    return None


def _public_view(policy: dict, include_content: bool = False) -> dict:
    v = _current_version(policy) or {}
    row = {
        "slug": policy["slug"],
        "title": policy["title"],
        "description": policy.get("description") or "",
        "icon": policy.get("icon") or "file-text",
        "kind": policy.get("kind") or "legal",
        "requires_acceptance": policy.get("requires_acceptance", True),
        "requires_reacceptance": policy.get("requires_reacceptance", False),
        "sort_order": policy.get("sort_order", 999),
        "current_version": policy.get("current_version"),
        "effective_date": v.get("effective_date"),
        "last_updated": v.get("effective_date") or policy.get("updated_at"),
    }
    if include_content:
        row["content_html"] = v.get("content_html") or ""
    return row


# --------------------------------------------------------------------------- #
# Public endpoints                                                             #
# --------------------------------------------------------------------------- #
@api.get("/legal/policies")
async def list_policies():
    """Public — returns every non-archived policy in sort order."""
    docs = await db.legal_policies.find(
        {"archived_at": None},
    ).sort("sort_order", 1).to_list(200)
    return [_public_view(d) for d in docs]


@api.get("/legal/policies/{slug}")
async def get_policy(slug: str):
    doc = await db.legal_policies.find_one({"slug": slug, "archived_at": None})
    if not doc:
        raise HTTPException(status_code=404, detail="Policy not found")
    return _public_view(doc, include_content=True)


@api.get("/legal/policies/{slug}/versions")
async def get_policy_versions(slug: str):
    doc = await db.legal_policies.find_one({"slug": slug, "archived_at": None})
    if not doc:
        raise HTTPException(status_code=404, detail="Policy not found")
    return [
        {"version": v.get("version"),
         "effective_date": v.get("effective_date"),
         "superseded_at": v.get("superseded_at"),
         "created_at": v.get("created_at")}
        for v in (doc.get("versions") or [])
    ]


# --------------------------------------------------------------------------- #
# Authenticated endpoints                                                      #
# --------------------------------------------------------------------------- #
@api.post("/legal/acceptances")
async def record_acceptance(payload: AcceptanceIn, request: Request,
                             user=Depends(get_authenticated_user)):
    doc = await db.legal_policies.find_one({"slug": payload.policy_slug})
    if not doc:
        raise HTTPException(status_code=404, detail="Policy not found")
    if payload.policy_version not in {v.get("version") for v in doc.get("versions") or []}:
        raise HTTPException(status_code=400, detail="Unknown policy version")
    row = {
        "id": new_id(),
        "user_id": user["id"],
        "policy_slug": payload.policy_slug,
        "policy_version": payload.policy_version,
        "accepted_at": datetime.now(timezone.utc),
        "method": payload.method,
        "ip": get_client_ip(request),
        "user_agent": request.headers.get("user-agent"),
    }
    await db.legal_acceptances.insert_one(row)
    await log_audit(db, user["id"], user["email"], "legal.accept",
                    resource_type="legal_policy", resource_id=payload.policy_slug,
                    metadata={"version": payload.policy_version, "method": payload.method},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    row.pop("_id", None)
    return row


@api.get("/legal/acceptances/me")
async def my_acceptances(user=Depends(get_authenticated_user)):
    rows = await db.legal_acceptances.find(
        {"user_id": user["id"]},
    ).sort("accepted_at", -1).to_list(500)
    for r in rows:
        r.pop("_id", None)
    return rows


@api.get("/legal/pending-reacceptance")
async def pending_reacceptance(user=Depends(get_authenticated_user)):
    """Which policies require the user to re-accept a newer version.
    A policy is pending if:
      - `requires_reacceptance` is True on the policy record
      - the user's most recent acceptance version < the current_version
    """
    docs = await db.legal_policies.find(
        {"archived_at": None, "requires_reacceptance": True},
    ).to_list(200)
    if not docs:
        return []
    accepts = await db.legal_acceptances.find(
        {"user_id": user["id"], "policy_slug": {"$in": [d["slug"] for d in docs]}},
    ).to_list(1000)
    latest_by_slug: dict = {}
    for a in accepts:
        cur = latest_by_slug.get(a["policy_slug"])
        if not cur or a["accepted_at"] > cur["accepted_at"]:
            latest_by_slug[a["policy_slug"]] = a
    pending = []
    for d in docs:
        latest = latest_by_slug.get(d["slug"])
        if not latest or latest.get("policy_version") != d.get("current_version"):
            pending.append(_public_view(d, include_content=True))
    return pending


# --------------------------------------------------------------------------- #
# Admin management                                                             #
# --------------------------------------------------------------------------- #
@api.patch("/legal/policies/{slug}")
async def edit_policy(slug: str, payload: PolicyEditIn, request: Request,
                       user=Depends(require_roles(*_ADMIN_ROLES))):
    doc = await db.legal_policies.find_one({"slug": slug})
    if not doc:
        raise HTTPException(status_code=404, detail="Policy not found")
    updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if updates:
        updates["updated_at"] = datetime.now(timezone.utc)
        await db.legal_policies.update_one({"slug": slug}, {"$set": updates})
        await log_audit(db, user["id"], user["email"], "legal.policy_edit",
                        resource_type="legal_policy", resource_id=slug,
                        metadata={"fields": list(updates.keys())},
                        ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _public_view(await db.legal_policies.find_one({"slug": slug}))


@api.post("/legal/policies/{slug}/versions")
async def publish_version(slug: str, payload: NewVersionIn, request: Request,
                            user=Depends(require_roles(*_ADMIN_ROLES))):
    doc = await db.legal_policies.find_one({"slug": slug})
    if not doc:
        raise HTTPException(status_code=404, detail="Policy not found")
    versions = doc.get("versions") or []
    if any(v.get("version") == payload.version for v in versions):
        raise HTTPException(status_code=409, detail="Version already exists")
    now = datetime.now(timezone.utc)
    new_ver = {
        "version": payload.version,
        "content_html": sanitize_campaign_html(payload.content_html),
        "effective_date": payload.effective_date or now,
        "created_at": now,
        "created_by": user["id"],
        "superseded_at": None,
    }
    # Mark previous current version as superseded.
    for v in versions:
        if v.get("version") == doc.get("current_version"):
            v["superseded_at"] = now
    versions.append(new_ver)
    updates: dict = {
        "versions": versions,
        "current_version": payload.version,
        "updated_at": now,
    }
    if payload.force_reacceptance:
        updates["requires_reacceptance"] = True
    await db.legal_policies.update_one({"slug": slug}, {"$set": updates})
    await log_audit(db, user["id"], user["email"], "legal.policy_publish",
                    resource_type="legal_policy", resource_id=slug,
                    metadata={"version": payload.version,
                               "force_reacceptance": payload.force_reacceptance},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _public_view(await db.legal_policies.find_one({"slug": slug}), include_content=True)


@api.post("/legal/policies/{slug}/archive")
async def archive_policy(slug: str, request: Request,
                          user=Depends(require_roles(*_ADMIN_ROLES))):
    r = await db.legal_policies.update_one(
        {"slug": slug}, {"$set": {"archived_at": datetime.now(timezone.utc)}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Policy not found")
    await log_audit(db, user["id"], user["email"], "legal.policy_archive",
                    resource_type="legal_policy", resource_id=slug,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


@api.get("/legal/policies/{slug}/acceptance-stats")
async def acceptance_stats(slug: str, user=Depends(require_roles(*_ADMIN_ROLES))):
    doc = await db.legal_policies.find_one({"slug": slug})
    if not doc:
        raise HTTPException(status_code=404, detail="Policy not found")
    pipeline = [
        {"$match": {"policy_slug": slug}},
        {"$group": {"_id": "$policy_version", "count": {"$sum": 1}}},
    ]
    rows = await db.legal_acceptances.aggregate(pipeline).to_list(200)
    return {
        "slug": slug,
        "current_version": doc.get("current_version"),
        "by_version": {r["_id"]: r["count"] for r in rows},
        "total": sum(r["count"] for r in rows),
    }
