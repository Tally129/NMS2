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
from pg_shims import (
    delete_client as _pg_delete_client, delete_user, find_client,
    find_latest_active_portal_reset, find_user_by_email, find_user_by_id,
    insert_client, insert_portal_reset_token, insert_user,
    invalidate_portal_reset_tokens, list_users_by_roles, search_clients,
    search_users, update_client as _pg_update_client, update_user,
)
from postgres_db import AsyncSessionLocal
from repositories import scheduling as sched_repo


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
    await insert_portal_reset_token(
        token_id=new_id(),
        user_id=user["id"],
        token_hash=_hash_token(raw),
        expires_at=now + timedelta(minutes=ttl_min),
        email_hash=_hash_email(user["email"]),
        ip=get_client_ip(request),
        purpose="portal_invite",
    )
    origin = _frontend_origin(request)
    from urllib.parse import quote as _url_quote
    _encoded = _url_quote(raw, safe="")
    url = (f"{origin}/reset-password?token={_encoded}"
            if origin
            else f"/reset-password?token={_encoded}")
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
        clients = await search_clients(query, limit=limit)
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
        user_roles_filter = None if role == "admin" else [
            "admin", "practitioner", "staff", "medical_assistant",
        ]
        users = await search_users(query, roles=user_roles_filter, limit=limit)
        results["users"] = [
            {"id": u["id"], "label": u.get("full_name") or u.get("email"),
             "sub": f"{u.get('role', '')} · {u.get('email', '')}",
             "url": "/portal/admin/users" if role == "admin" else None}
            for u in users
        ]

        # Appointments — search by service string. Legacy `client_name`,
        # `provider_name`, `visit_type`, `reason` fields do not exist in the
        # PostgreSQL `emr_appointments` schema (Phase 3.2 cutover); recent
        # appointments matching the query's `service` field are surfaced instead.
        q_lower = query.lower()
        async with AsyncSessionLocal() as pg:
            all_appts = await sched_repo.list_appointments(pg, sort_desc=True, limit=200)
        appt_lookup = [a for a in all_appts if q_lower in (a.get("service") or "").lower()][:limit]
        results["appointments"] = [
            {"id": a["id"],
             "label": f"Appointment · {a.get('service') or ''}",
             "sub": f"{(a.get('start').strftime('%b %d, %I:%M %p') if a.get('start') else '')} · {a.get('status', '')}",
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
        self_client = await find_client(user_id=user["id"])
        if self_client:
            q_lower = query.lower()
            async with AsyncSessionLocal() as pg:
                own_appts = await sched_repo.list_appointments(
                    pg, client_id=self_client["id"], sort_desc=True, limit=200,
                )
            appts = [a for a in own_appts
                     if q_lower in (a.get("service") or "").lower()][:limit]
            results["appointments"] = [
                {"id": a["id"],
                 "label": f"Appointment · {a.get('service') or ''}",
                 "sub": a.get("start").strftime("%b %d, %I:%M %p") if a.get("start") else "",
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
    c = await find_client(client_id=client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    return c


async def _get_or_create_portal_user(client: dict, email: str) -> tuple[dict, bool]:
    """Return (user, created). If a user already exists for this email, link
    to the client and return existing. Otherwise create a fresh, active
    client-role user with a random unusable password (which they'll replace
    via the invite link).
    """
    existing = await find_user_by_email(email.lower())
    if existing:
        # Link the client if not already linked.
        if not client.get("user_id"):
            await _pg_update_client(client["id"], {"user_id": existing["id"]})
        # Ensure activation.
        if not existing.get("is_active", True):
            await update_user(existing["id"], {"is_active": True})
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
    await insert_user(doc)
    await _pg_update_client(client["id"], {"user_id": doc["id"]})
    return doc, True


@api.get("/clients/{client_id}/portal-status")
async def portal_status(client_id: str, user=Depends(require_roles(*_PORTAL_ADMIN_ROLES, "medical_assistant"))):
    client = await _fetch_client(client_id)
    linked = None
    if client.get("user_id"):
        linked = await find_user_by_id(client["user_id"])
    # Newest reset/invite token — used to surface "invitation pending" state.
    latest_token = None
    if linked:
        latest_token = await find_latest_active_portal_reset(linked["id"])

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
    existing = await find_user_by_email(email)
    if existing and existing.get("role") != "client":
        raise HTTPException(status_code=409, detail={
            "code": "email_in_use_workforce",
            "message": "An admin/staff account already uses this email. Choose a different email.",
        })
    if existing:
        # Existing client user linked to a different patient?
        from postgres_db import AsyncSessionLocal as _ASL
        from sqlalchemy import select as _select
        from postgres_models import Client as _Client
        async with _ASL() as _pg:
            _row = (await _pg.execute(
                _select(_Client).where(_Client.user_id == existing["id"], _Client.id != client_id)
            )).scalar_one_or_none()
        other = _row is not None
        if other:
            raise HTTPException(status_code=409, detail={
                "code": "email_in_use_client",
                "message": "This email is already linked to a different patient record.",
            })

    now = datetime.now(timezone.utc)
    if existing:
        # Update in place — never create a duplicate patient or account.
        await update_user(
            existing["id"],
            {
                "password_hash": hash_password(payload.password),
                "password_changed_at": now,
                "must_change_password": payload.require_password_change,
                "is_active": True,
                "full_name": client.get("full_name") or existing.get("full_name") or "",
                "phone": client.get("phone") or existing.get("phone"),
            },
            inc={"session_version": 1},
        )
        # Ensure the client is linked to this user.
        if not client.get("user_id"):
            await _pg_update_client(client_id, {"user_id": existing["id"]})
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
        await insert_user(doc)
        await _pg_update_client(client_id, {"user_id": doc["id"]})
        user_id = doc["id"]
        created = True

    # Invalidate any outstanding invitation tokens so an admin-set password
    # supersedes any email link.
    await invalidate_portal_reset_tokens(user_id)

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
    from notifiers import send_account_setup_email
    delivery_status = await send_account_setup_email(
        db, email,
        first_name=(client.get("full_name") or "").split(" ")[0] or None,
        setup_url=url,
        expires_in_hours=int((RESET_TTL_MIN * 24) / 60),
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
    linked = await find_user_by_id(client["user_id"])
    if not linked:
        raise HTTPException(status_code=404, detail="Linked user not found")

    raw, url = await _issue_portal_link(linked, request, ttl_min=RESET_TTL_MIN)
    from notifiers import send_password_reset_email
    delivery_status = await send_password_reset_email(
        db, linked["email"],
        first_name=(linked.get("full_name") or "").split(" ")[0] or None,
        reset_url=url,
        expires_in_minutes=RESET_TTL_MIN,
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
    result = await update_user(client["user_id"], {"is_active": False})
    # Revoke all active sessions
    from sessions import revoke_all_user_sessions
    revoked = await revoke_all_user_sessions(client["user_id"], "portal_disabled")
    await log_audit(db, user["id"], user["email"], "portal.disable",
                    resource_type="client", resource_id=client_id,
                    severity="high", outcome="success",
                    metadata={"user_id": client["user_id"], "reason": payload.reason, **(revoked or {})},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True, "disabled": bool(result)}


@api.post("/clients/{client_id}/portal-enable")
async def portal_enable(client_id: str, request: Request,
                         user=Depends(require_roles(*_PORTAL_ADMIN_ROLES))):
    client = await _fetch_client(client_id)
    if not client.get("user_id"):
        raise HTTPException(status_code=400, detail="No portal user to enable")
    result = await update_user(client["user_id"], {"is_active": True})
    await log_audit(db, user["id"], user["email"], "portal.enable",
                    resource_type="client", resource_id=client_id,
                    metadata={"user_id": client["user_id"]},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True, "enabled": bool(result)}


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

    client = await find_client(email=email)
    if not client:
        client = {
            "id": new_id(),
            "full_name": "Portal Test Patient — NON-PRODUCTION DATA",
            "email": email,
            "phone": "(555) 010-0001",
            "dob": "1985-01-15",
            "sex": "prefer_not_to_say",
            "address": {"raw": "1 Test Way, Sample City, GA"},
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
        await insert_client(client)
    else:
        # Ensure tag/notes stay in place.
        new_tags = list(set((client.get("tags") or []) + [TEST_PATIENT_TAG]))
        await _pg_update_client(client["id"], {
            "tags": new_tags,
            "consent_marketing": False,
        })
        client["tags"] = new_tags

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
    await _pg_delete_client(client_id)
    if uid:
        await delete_user(uid)
    await log_audit(db, user["id"], user["email"], "portal.test_patient_delete",
                    resource_type="client", resource_id=client_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}
