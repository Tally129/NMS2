"""
Portal usability endpoints: global search + patient portal invitation
management. Reuses the existing password-reset token machinery to send
first-time invitations — never returns or logs a raw password.

Routes
------
GET  /api/search/global?q=…
POST /api/clients/{client_id}/portal-invite
POST /api/clients/{client_id}/portal-reset-password
POST /api/clients/{client_id}/portal-disable
POST /api/clients/{client_id}/portal-enable
GET  /api/clients/{client_id}/portal-status

Test-support (HIPAA_MODE off only):
POST /api/dev/portal-test-patient
    Idempotently seeds a clearly-flagged non-production patient + linked user,
    returns email + one-time reset token so QA can log in through the real
    patient portal without an SMTP configuration.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, EmailStr

from audit import get_client_ip, log_audit
from auth_utils import hash_password, validate_password_strength
from deps import _strip_id, api, db, get_current_user, require_roles
from models import new_id
from notifiers import send_email as notify_email


_PORTAL_ADMIN_ROLES = ("admin", "practitioner", "staff", "front_desk", "frontdesk")


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _hash_email(email: str) -> str:
    return hashlib.sha256(email.lower().strip().encode("utf-8")).hexdigest()


def _frontend_origin(request: Request) -> str:
    origin = os.environ.get("FRONTEND_ORIGIN") or ""
    if origin:
        return origin.rstrip("/")
    # Fall back to the request origin so preview environments work without env.
    return (request.headers.get("origin") or "").rstrip("/")


HIPAA_MODE = os.environ.get("HIPAA_MODE", "false").lower() in {"1", "true", "yes", "on"}
RESET_TTL_MIN = 60  # first-time invites get a longer runway than the 20-min forgot-password token.
TEST_PATIENT_TAG = "portal_test_patient"


async def _issue_portal_link(user: dict, request: Request, ttl_min: int = RESET_TTL_MIN) -> tuple[str, str]:
    """Create a fresh password-reset token for `user`; return (raw_token, url)."""
    raw = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    await db.password_reset_tokens.insert_one({
        "id": new_id(),
        "token_hash": _hash_token(raw),
        "user_id": user["id"],
        "email_hash": _hash_email(user["email"]),
        "created_at": now,
        "expires_at": now + timedelta(minutes=ttl_min),
        "consumed_at": None,
        "ip": get_client_ip(request),
        "purpose": "portal_invite",
    })
    origin = _frontend_origin(request)
    url = f"{origin}/reset-password?token={raw}" if origin else f"[configure FRONTEND_ORIGIN]?token={raw}"
    return raw, url


# --------------------------------------------------------------------------- #
# Global search — read-only, RBAC-aware, single response envelope             #
# --------------------------------------------------------------------------- #
def _re_escape(q: str) -> str:
    return re.escape(q.strip())


@api.get("/search/global")
async def global_search(
    q: str = Query("", max_length=120),
    limit: int = Query(6, ge=1, le=25),
    user=Depends(get_current_user),
):
    """One search box, seven collections. Returns 6 hits per bucket.
    Clients never see workforce data. Practitioners see everything except audit."""
    query = (q or "").strip()
    if not query:
        return {"query": "", "results": {}}
    rx = {"$regex": _re_escape(query), "$options": "i"}
    role = user.get("role", "")
    workforce = role in ("admin", "practitioner", "staff", "medical_assistant", "auditor")

    results: dict[str, list[dict]] = {}

    if workforce:
        # Clients / patients
        clients = await db.clients.find(
            {"$or": [{"full_name": rx}, {"email": rx}, {"phone": rx}, {"mrn": rx}]},
            {"id": 1, "full_name": 1, "email": 1, "mrn": 1, "phone": 1},
        ).limit(limit).to_list(limit)
        results["patients"] = [
            {"id": c["id"], "label": c.get("full_name") or c.get("email") or c["id"],
             "sub": c.get("mrn") or c.get("email") or c.get("phone") or "",
             "url": f"/portal/{'admin' if role == 'admin' else ('provider' if role == 'practitioner' else 'staff')}/patients/{c['id']}"}
            for c in clients
        ]

        # Treatments
        treatments = await db.treatments.find(
            {"$or": [{"name": rx}, {"category": rx}, {"sku": rx}, {"description": rx}]},
            {"id": 1, "name": 1, "category": 1, "price": 1},
        ).limit(limit).to_list(limit)
        results["treatments"] = [
            {"id": t["id"], "label": t.get("name") or "Untitled",
             "sub": f"${(t.get('price') or 0):.2f} · {t.get('category') or 'general'}",
             "url": "/portal/staff/treatments"}
            for t in treatments
        ]

        # Inventory
        inventory = await db.inventory_items.find(
            {"$or": [{"name": rx}, {"sku": rx}, {"category": rx}]},
            {"id": 1, "name": 1, "sku": 1, "stock": 1, "unit_price": 1},
        ).limit(limit).to_list(limit)
        results["inventory"] = [
            {"id": i["id"], "label": i.get("name") or "Untitled",
             "sub": f"stock {i.get('stock', 0)} · {i.get('sku') or ''}".strip(" ·"),
             "url": "/portal/staff/inventory"}
            for i in inventory
        ]

        # Users (staff/providers/admins). Admins see all; providers/staff see their own peer list minus clients.
        user_query: dict = {"$or": [{"full_name": rx}, {"email": rx}]}
        if role != "admin":
            user_query["role"] = {"$in": ["admin", "practitioner", "staff", "medical_assistant"]}
        users = await db.users.find(
            user_query,
            {"id": 1, "full_name": 1, "email": 1, "role": 1},
        ).limit(limit).to_list(limit)
        results["users"] = [
            {"id": u["id"], "label": u.get("full_name") or u.get("email"),
             "sub": f"{u.get('role', '')} · {u.get('email', '')}",
             "url": "/portal/admin/users" if role == "admin" else None}
            for u in users
        ]

        # Appointments
        appt_lookup = await db.appointments.find(
            {"$or": [{"client_name": rx}, {"provider_name": rx}, {"visit_type": rx}, {"reason": rx}]},
            {"id": 1, "client_name": 1, "provider_name": 1, "start_at": 1, "status": 1},
        ).sort("start_at", -1).limit(limit).to_list(limit)
        results["appointments"] = [
            {"id": a["id"],
             "label": f"{a.get('client_name') or 'Patient'} · {a.get('provider_name') or ''}",
             "sub": f"{(a.get('start_at').strftime('%b %d, %I:%M %p') if a.get('start_at') else '')} · {a.get('status', '')}",
             "url": f"/portal/{'admin' if role == 'admin' else ('provider' if role == 'practitioner' else 'staff')}/appointments"}
            for a in appt_lookup
        ]

        # Vendors (from accounting/vendors)
        vendors = await db.vendors.find(
            {"$or": [{"name": rx}, {"email": rx}, {"tax_id": rx}]},
            {"id": 1, "name": 1, "email": 1},
        ).limit(limit).to_list(limit)
        results["vendors"] = [
            {"id": v["id"], "label": v.get("name") or "Untitled",
             "sub": v.get("email") or "",
             "url": "/portal/admin/accounting"}
            for v in vendors
        ]
    else:
        # Client role: search only their own appointments + treatment plans / lab tests names.
        self_client = await db.clients.find_one({"user_id": user["id"]}, {"id": 1})
        if self_client:
            appts = await db.appointments.find(
                {"client_id": self_client["id"], "$or": [{"visit_type": rx}, {"provider_name": rx}, {"reason": rx}]},
                {"id": 1, "provider_name": 1, "start_at": 1, "visit_type": 1},
            ).sort("start_at", -1).limit(limit).to_list(limit)
            results["appointments"] = [
                {"id": a["id"],
                 "label": f"{a.get('provider_name') or 'Provider'} · {a.get('visit_type') or ''}",
                 "sub": a.get("start_at").strftime("%b %d, %I:%M %p") if a.get("start_at") else "",
                 "url": "/portal/patient/appointments"}
                for a in appts
            ]

    # Prune empty buckets so the frontend can render without empty section headers.
    return {"query": query, "results": {k: v for k, v in results.items() if v}}


# --------------------------------------------------------------------------- #
# Patient portal invitation / password management                             #
# --------------------------------------------------------------------------- #
class PortalInviteResponse(BaseModel):
    ok: bool
    email: str
    invite_url: Optional[str] = None
    ttl_minutes: int
    already_has_user: bool
    delivery: Optional[str] = None  # "sent" | "sent_stub" | "skipped"
    message: str


class PortalDisableIn(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=200)


async def _fetch_client(client_id: str) -> dict:
    c = await db.clients.find_one({"id": client_id})
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    return c


async def _get_or_create_portal_user(client: dict, email: str) -> tuple[dict, bool]:
    """Return (user, created). If a user already exists for this email, link
    to the client and return existing. Otherwise create a fresh, active
    client-role user with a random unusable password (which they'll replace
    via the invite link).
    """
    existing = await db.users.find_one({"email": email.lower()})
    if existing:
        # Link the client if not already linked.
        if not client.get("user_id"):
            await db.clients.update_one({"id": client["id"]}, {"$set": {"user_id": existing["id"]}})
        # Ensure activation.
        if not existing.get("is_active", True):
            await db.users.update_one({"id": existing["id"]}, {"$set": {"is_active": True}})
            existing["is_active"] = True
        return existing, False

    now = datetime.now(timezone.utc)
    fresh_password = secrets.token_urlsafe(32)
    doc = {
        "id": new_id(),
        "email": email.lower(),
        "password_hash": hash_password(fresh_password),
        "full_name": client.get("full_name") or "",
        "phone": client.get("phone"),
        "role": "client",
        "mfa_enabled": False,
        "mfa_secret": None,
        "is_active": True,
        "created_at": now,
        "last_login_at": None,
        "must_change_password": True,
    }
    await db.users.insert_one(doc)
    await db.clients.update_one({"id": client["id"]}, {"$set": {"user_id": doc["id"]}})
    return doc, True


@api.get("/clients/{client_id}/portal-status")
async def portal_status(client_id: str, user=Depends(require_roles(*_PORTAL_ADMIN_ROLES, "medical_assistant"))):
    client = await _fetch_client(client_id)
    linked = None
    if client.get("user_id"):
        linked = await db.users.find_one(
            {"id": client["user_id"]},
            {"id": 1, "email": 1, "is_active": 1, "last_login_at": 1, "created_at": 1,
             "must_change_password": 1, "mfa_enabled": 1, "password_changed_at": 1},
        )
    # Newest reset/invite token — used to surface "invitation pending" state.
    latest_token = None
    if linked:
        latest_token = await db.password_reset_tokens.find_one(
            {"user_id": linked["id"], "consumed_at": None},
            sort=[("created_at", -1)],
            projection={"created_at": 1, "expires_at": 1, "purpose": 1, "consumed_at": 1},
        )

    now = datetime.now(timezone.utc)
    exp = latest_token.get("expires_at") if latest_token else None
    if exp is not None and getattr(exp, "tzinfo", None) is None:
        exp = exp.replace(tzinfo=timezone.utc)
    invite_active = bool(exp and exp > now)

    # Human status label. Precedence: disabled > active session > invitation pending > never invited.
    if not linked:
        label = "not_invited"
    elif not linked.get("is_active", True):
        label = "disabled"
    elif linked.get("last_login_at"):
        label = "active"
    elif invite_active:
        label = "invitation_pending"
    else:
        label = "provisioned"

    return {
        "client_id": client_id,
        "has_portal": bool(linked),
        "portal_active": bool(linked and linked.get("is_active", True)),
        "status": label,
        "email": (linked or {}).get("email") or client.get("email"),
        "last_login_at": (linked or {}).get("last_login_at"),
        "created_at": (linked or {}).get("created_at"),
        "must_change_password": (linked or {}).get("must_change_password", False),
        "mfa_enabled": (linked or {}).get("mfa_enabled", False),
        "password_changed_at": (linked or {}).get("password_changed_at"),
        "invitation_sent_at": (latest_token or {}).get("created_at"),
        "invitation_expires_at": (latest_token or {}).get("expires_at"),
        "invitation_active": invite_active,
        "invitation_purpose": (latest_token or {}).get("purpose"),
        "is_test_patient": client.get("tags") and TEST_PATIENT_TAG in (client.get("tags") or []),
    }


class PortalCreateIn(BaseModel):
    email: Optional[EmailStr] = None
    password: str = Field(..., min_length=12, max_length=128)
    password_confirm: str = Field(..., min_length=12, max_length=128)
    require_password_change: bool = True


@api.post("/clients/{client_id}/portal-create-account", response_model=PortalInviteResponse)
async def portal_create_account(client_id: str, payload: PortalCreateIn, request: Request,
                                 user=Depends(require_roles(*_PORTAL_ADMIN_ROLES))):
    """Create a portal login with an admin-set temporary password.
    - Enforces the existing password policy.
    - Uses the existing bcrypt hash — plaintext never stored / logged.
    - Password is displayed to the admin exactly once (in the response) and
      never persisted anywhere in cleartext.
    - Sets `must_change_password` when `require_password_change=True`, which
      the frontend gate uses to force a change before any PHI is loaded.
    """
    from rate_limit import enforce_forgot_rate
    enforce_forgot_rate(request, "portal-create")

    if payload.password != payload.password_confirm:
        raise HTTPException(status_code=400, detail={
            "code": "password_mismatch",
            "message": "Passwords do not match.",
        })
    client = await _fetch_client(client_id)
    email = (payload.email or client.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail={
            "code": "missing_email",
            "message": "Provide a login email (or set one on the client record first).",
        })

    # Password policy — reuse the exact function used everywhere else.
    reason = validate_password_strength(payload.password, email=email,
                                         full_name=client.get("full_name") or "")
    if reason:
        raise HTTPException(status_code=400, detail={"code": "weak_password", "message": reason})

    # Existing account? Refuse — admins must use "Set Temporary Password" for those.
    existing = await db.users.find_one({"email": email})
    if existing and existing.get("role") != "client":
        raise HTTPException(status_code=409, detail={
            "code": "email_in_use_workforce",
            "message": "An admin/staff account already uses this email. Choose a different email.",
        })
    if existing:
        # Existing client user linked to a different patient?
        other = await db.clients.find_one({"user_id": existing["id"], "id": {"$ne": client_id}})
        if other:
            raise HTTPException(status_code=409, detail={
                "code": "email_in_use_client",
                "message": "This email is already linked to a different patient record.",
            })

    now = datetime.now(timezone.utc)
    if existing:
        # Update in place — never create a duplicate patient or account.
        await db.users.update_one(
            {"id": existing["id"]},
            {"$set": {
                "password_hash": hash_password(payload.password),
                "password_changed_at": now,
                "must_change_password": payload.require_password_change,
                "is_active": True,
                "full_name": client.get("full_name") or existing.get("full_name") or "",
                "phone": client.get("phone") or existing.get("phone"),
            }, "$inc": {"session_version": 1}},
        )
        # Ensure the client is linked to this user.
        if not client.get("user_id"):
            await db.clients.update_one({"id": client_id}, {"$set": {"user_id": existing["id"]}})
        # Revoke any active sessions so the fresh password is required next time.
        try:
            from sessions import revoke_all_user_sessions
            await revoke_all_user_sessions(existing["id"], "portal_temp_password_reset")
        except Exception:
            pass
        user_id = existing["id"]
        created = False
    else:
        doc = {
            "id": new_id(),
            "email": email,
            "password_hash": hash_password(payload.password),
            "password_changed_at": now,
            "full_name": client.get("full_name") or "",
            "phone": client.get("phone"),
            "role": "client",
            "mfa_enabled": False, "mfa_secret": None,
            "is_active": True,
            "created_at": now,
            "last_login_at": None,
            "must_change_password": payload.require_password_change,
            "session_version": 1,
        }
        await db.users.insert_one(doc)
        await db.clients.update_one({"id": client_id}, {"$set": {"user_id": doc["id"]}})
        user_id = doc["id"]
        created = True

    # Invalidate any outstanding invitation tokens so an admin-set password
    # supersedes any email link.
    await db.password_reset_tokens.update_many(
        {"user_id": user_id, "consumed_at": None},
        {"$set": {"consumed_at": now, "consumed_reason": "superseded_by_admin_password"}},
    )

    await log_audit(
        db, user["id"], user["email"], "portal.account_created",
        resource_type="client", resource_id=client_id,
        severity="high",
        metadata={
            "created_user": created,
            "email_hash": _hash_email(email),
            "require_password_change": payload.require_password_change,
        },
        ip=get_client_ip(request), user_agent=request.headers.get("user-agent"),
    )

    origin = _frontend_origin(request)
    login_url = f"{origin}/patient-login" if origin else "/patient-login"
    return PortalInviteResponse(
        ok=True,
        email=email,
        invite_url=login_url,  # login URL — the temp password itself is the one-time secret
        ttl_minutes=0,
        already_has_user=not created,
        delivery="admin_shown_once",
        message=(
            "Account created. Share the temporary password with the patient — "
            "it is displayed once and cannot be retrieved again."
            if created else
            "Temporary password set on existing portal account. "
            "Previous sessions and invitation links were revoked."
        ),
    )


@api.post("/clients/{client_id}/portal-invite", response_model=PortalInviteResponse)
async def portal_invite(client_id: str, request: Request,
                        user=Depends(require_roles(*_PORTAL_ADMIN_ROLES))):
    client = await _fetch_client(client_id)
    email = (client.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail={
            "code": "missing_email",
            "message": "Add an email address to the client record before sending an invite.",
        })

    # Rate-limit invitations per admin per IP (piggybacks on forgot-password limiter).
    from rate_limit import enforce_forgot_rate
    enforce_forgot_rate(request, email)

    linked_user, created = await _get_or_create_portal_user(client, email)

    raw, url = await _issue_portal_link(linked_user, request, ttl_min=RESET_TTL_MIN * 24)  # 24h for first-time
    subject = "Welcome to your Natural Medical Solutions patient portal"
    html = (
        f"<p>Hi {client.get('full_name') or 'there'},</p>"
        "<p>Your patient portal at Natural Medical Solutions Wellness Center is ready. "
        "Click the link below within 24 hours to choose a password and sign in:</p>"
        f"<p><a href=\"{url}\">{url}</a></p>"
        "<p>Once signed in you can review your appointments, treatment plan, labs, "
        "messages, and secure documents.</p>"
        "<p>— Natural Medical Solutions</p>"
    )
    delivery_status = await notify_email(
        db, email, subject, html,
        action="portal.invite_dispatch",
        redact_recipient=True,
    )
    await log_audit(db, user["id"], user["email"], "portal.invite",
                    resource_type="client", resource_id=client_id,
                    metadata={"created_user": created, "email_hash": _hash_email(email)},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))

    # In non-HIPAA (dev/QA) mode we return the raw invite URL so the operator can
    # copy it directly without waiting for SMTP. In HIPAA_MODE we redact it.
    return PortalInviteResponse(
        ok=True,
        email=email,
        invite_url=None if HIPAA_MODE else url,
        ttl_minutes=RESET_TTL_MIN * 24,
        already_has_user=not created,
        delivery=delivery_status,
        message=("Invitation email sent." if not HIPAA_MODE else
                 "Invitation email dispatched (link redacted in HIPAA mode)."),
    )


@api.post("/clients/{client_id}/portal-reset-password", response_model=PortalInviteResponse)
async def portal_reset_password(client_id: str, request: Request,
                                 user=Depends(require_roles(*_PORTAL_ADMIN_ROLES))):
    client = await _fetch_client(client_id)
    if not client.get("user_id"):
        raise HTTPException(status_code=400, detail={
            "code": "no_portal_user",
            "message": "This client has no portal account yet — send an invitation first.",
        })
    from rate_limit import enforce_forgot_rate
    enforce_forgot_rate(request, client.get("email") or client_id)
    linked = await db.users.find_one({"id": client["user_id"]})
    if not linked:
        raise HTTPException(status_code=404, detail="Linked user not found")

    raw, url = await _issue_portal_link(linked, request, ttl_min=RESET_TTL_MIN)
    subject = "Reset your Natural Medical Solutions portal password"
    html = (
        f"<p>Hi {linked.get('full_name') or 'there'},</p>"
        "<p>An administrator sent you a fresh password-reset link. "
        f"Use it within {RESET_TTL_MIN} minutes:</p>"
        f"<p><a href=\"{url}\">{url}</a></p>"
        "<p>If you didn't expect this, you can safely ignore it — your current password stays valid.</p>"
    )
    delivery_status = await notify_email(
        db, linked["email"], subject, html,
        action="portal.reset_dispatch",
        redact_recipient=True,
    )
    await log_audit(db, user["id"], user["email"], "portal.reset_password",
                    resource_type="client", resource_id=client_id,
                    metadata={"email_hash": _hash_email(linked["email"])},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return PortalInviteResponse(
        ok=True,
        email=linked["email"],
        invite_url=None if HIPAA_MODE else url,
        ttl_minutes=RESET_TTL_MIN,
        already_has_user=True,
        delivery=delivery_status,
        message="Password reset link sent.",
    )


@api.post("/clients/{client_id}/portal-disable")
async def portal_disable(client_id: str, payload: PortalDisableIn, request: Request,
                          user=Depends(require_roles(*_PORTAL_ADMIN_ROLES))):
    client = await _fetch_client(client_id)
    if not client.get("user_id"):
        raise HTTPException(status_code=400, detail="No portal user to disable")
    result = await db.users.update_one(
        {"id": client["user_id"]}, {"$set": {"is_active": False}},
    )
    # Revoke all active sessions
    from sessions import revoke_all_user_sessions
    revoked = await revoke_all_user_sessions(client["user_id"], "portal_disabled")
    await log_audit(db, user["id"], user["email"], "portal.disable",
                    resource_type="client", resource_id=client_id,
                    severity="high", outcome="success",
                    metadata={"user_id": client["user_id"], "reason": payload.reason, **(revoked or {})},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True, "disabled": bool(result.modified_count)}


@api.post("/clients/{client_id}/portal-enable")
async def portal_enable(client_id: str, request: Request,
                         user=Depends(require_roles(*_PORTAL_ADMIN_ROLES))):
    client = await _fetch_client(client_id)
    if not client.get("user_id"):
        raise HTTPException(status_code=400, detail="No portal user to enable")
    result = await db.users.update_one(
        {"id": client["user_id"]}, {"$set": {"is_active": True}},
    )
    await log_audit(db, user["id"], user["email"], "portal.enable",
                    resource_type="client", resource_id=client_id,
                    metadata={"user_id": client["user_id"]},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True, "enabled": bool(result.modified_count)}


# --------------------------------------------------------------------------- #
# Test-patient seeder (dev/QA only)                                           #
# --------------------------------------------------------------------------- #
class TestPatientSeedIn(BaseModel):
    email: Optional[str] = None


@api.post("/dev/portal-test-patient")
async def dev_portal_test_patient(payload: TestPatientSeedIn, request: Request,
                                   user=Depends(require_roles("admin"))):
    """Idempotently seed a clearly-flagged non-production patient. Returns the
    portal URL so QA can log in as that patient. Refuses to run in HIPAA_MODE."""
    if HIPAA_MODE:
        raise HTTPException(status_code=403, detail={
            "code": "hipaa_mode_active",
            "message": "Test-patient seeding is disabled while HIPAA_MODE is on.",
        })

    email = (payload.email or "portal.test@natmedsol.local").strip().lower()
    now = datetime.now(timezone.utc)

    client = await db.clients.find_one({"email": email})
    if not client:
        client = {
            "id": new_id(),
            "full_name": "Portal Test Patient — NON-PRODUCTION DATA",
            "email": email,
            "phone": "(555) 010-0001",
            "dob": "1985-01-15",
            "sex": "prefer_not_to_say",
            "address": "1 Test Way, Sample City, GA",
            "mrn": "NMS-TEST01",
            "primary_concern": "Manual portal usability testing",
            "consent_marketing": False,
            "consent_photo": False,
            "consent_telehealth": True,
            "intake_completed": False,
            "created_at": now,
            "tags": [TEST_PATIENT_TAG],
            "notes": (
                "This account is a manual QA fixture. Exclude from marketing "
                "campaigns, automated reminders, real lab orders, and billing "
                "collections."
            ),
        }
        await db.clients.insert_one(client)
    else:
        # Ensure tag/notes stay in place.
        await db.clients.update_one(
            {"id": client["id"]},
            {"$set": {"tags": list(set((client.get("tags") or []) + [TEST_PATIENT_TAG])),
                       "consent_marketing": False}},
        )

    linked_user, created = await _get_or_create_portal_user(client, email)
    raw, url = await _issue_portal_link(linked_user, request, ttl_min=RESET_TTL_MIN * 24)

    await log_audit(db, user["id"], user["email"], "portal.test_patient_seed",
                    resource_type="client", resource_id=client["id"],
                    metadata={"created_user": created}, ip=get_client_ip(request),
                    user_agent=request.headers.get("user-agent"))
    return {
        "ok": True,
        "client_id": client["id"],
        "user_id": linked_user["id"],
        "email": email,
        "portal_login_url": f"{_frontend_origin(request)}/login",
        "portal_password_setup_url": url,
        "note": "Use the setup URL to choose a password, then log in at /login as the patient.",
    }


@api.delete("/dev/portal-test-patient/{client_id}")
async def dev_delete_test_patient(client_id: str, request: Request,
                                    user=Depends(require_roles("admin"))):
    if HIPAA_MODE:
        raise HTTPException(status_code=403, detail={"code": "hipaa_mode_active"})
    client = await _fetch_client(client_id)
    if TEST_PATIENT_TAG not in (client.get("tags") or []):
        raise HTTPException(status_code=400, detail="Not a flagged test patient")
    uid = client.get("user_id")
    await db.clients.delete_one({"id": client_id})
    if uid:
        await db.users.delete_one({"id": uid})
    await log_audit(db, user["id"], user["email"], "portal.test_patient_delete",
                    resource_type="client", resource_id=client_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}
