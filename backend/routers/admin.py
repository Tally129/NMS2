"""
Dashboard stats + Admin audit/user/session routes.

Session 2b: user + user_sessions + audit_logs reads and writes now target
PostgreSQL. Non-auth business collections (clients, notes, files,
appointments, visit_notes) continue to live in MongoDB.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select

from audit import get_client_ip, log_audit, verify_audit_chain
from auth_utils import hash_password
from deps import _resolve_self_client, _strip_id, api, db, get_current_user, require_roles, to_user_out
from models import AuditLogOut, UserCreate, UserOut, new_id
from permissions import P, require_permission
from postgres_db import AsyncSessionLocal
from postgres_models import AuditLog, Client, User
from repositories import audit as audit_repo
from repositories import scheduling as sched_repo
from repositories import user_sessions as sessions_repo
from repositories import users as users_repo
from repositories import clients as clients_repo
from pg_shims import count_clients


async def _pg_visit_note_count(client_id=None, practitioner_id=None):
    from postgres_models.clinical_and_messaging import VisitNote
    from sqlalchemy import select, func as _f
    async with AsyncSessionLocal() as pg:
        stmt = select(_f.count(VisitNote.id))
        if client_id:
            stmt = stmt.where(VisitNote.client_id == client_id)
        if practitioner_id:
            stmt = stmt.where(VisitNote.practitioner_id == practitioner_id)
        return int((await pg.execute(stmt)).scalar_one())
from sessions import list_active_sessions_sanitized, revoke_all_user_sessions, revoke_family


# =================== DASHBOARD ===================
@api.get("/dashboard/stats")
async def dashboard_stats(user=Depends(get_current_user)):
    role = user["role"]
    if role in ("admin", "staff"):
        async with AsyncSessionLocal() as pg:
            users_ct = int((await pg.execute(select(func.count(User.id)))).scalar_one())
            audit_ct = int((await pg.execute(select(func.count(AuditLog.id)))).scalar_one())
            req_ct = await sched_repo.count_appointment_requests(pg)
        return {
            "role": role,
            "clients": await count_clients(),
            "notes": await _pg_visit_note_count(),
            "files": await db.files.count_documents({}),
            "appointments_requested": req_ct,
            "users": users_ct,
            "audit_events": audit_ct,
        }
    if role == "practitioner":
        return {
            "role": role,
            "my_patients": await count_clients(practitioner_id=user["id"]),
            "total_clients": await count_clients(),
            "my_notes": await _pg_visit_note_count(practitioner_id=user['id']),
        }
    self_client = await _resolve_self_client(user)
    if not self_client:
        return {"role": role}
    return {
        "role": role,
        "client_id": self_client["id"],
        "intake_completed": self_client.get("intake_completed", False),
        "notes": await _pg_visit_note_count(client_id=self_client['id']),
        "files": await db.files.count_documents({"client_id": self_client["id"]}),
    }


# =================== ADMIN — AUDIT ===================
@api.get("/admin/audit", response_model=List[AuditLogOut])
async def admin_audit(limit: int = 100, user_id: Optional[str] = None, action: Optional[str] = None,
                      user=Depends(require_roles("admin"))):
    async with AsyncSessionLocal() as pg:
        items = await audit_repo.list_recent(pg, limit=min(limit, 500),
                                              user_id=user_id, action=action)
    return items


# =================== ADMIN — USERS ===================
@api.get("/admin/users", response_model=List[UserOut])
async def admin_users(user=Depends(require_roles("admin"))):
    async with AsyncSessionLocal() as pg:
        rows = await users_repo.list_recent(pg, limit=5000)
    return [to_user_out(r) for r in rows]


@api.post("/admin/users")
async def admin_create_user(payload: UserCreate, request: Request, user=Depends(require_roles("admin"))):
    allowed_roles = {
        "admin",
        "practitioner",
        "staff",
        "front_desk",
        "frontdesk",
        "medical_assistant",
        "auditor",
        "client",
    }
    if payload.role not in allowed_roles:
        raise HTTPException(status_code=400, detail="Invalid role")
    email = (payload.email or "").lower().strip()
    async with AsyncSessionLocal() as pg:
        if await users_repo.get_by_email(pg, email):
            raise HTTPException(status_code=409, detail="Email already registered")
    WORKFORCE = {"admin", "practitioner", "staff", "front_desk", "frontdesk",
                 "medical_assistant", "auditor"}
    is_workforce = payload.role in WORKFORCE

    import secrets

    raw_password = secrets.token_urlsafe(48)
    onboarding_status = "password_change_required"
    must_change_password = True
    temp_exp = None
    now = datetime.now(timezone.utc)
    user_id = new_id()
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            doc = await users_repo.create_user(
                pg,
                user_id=user_id,
                email=email,
                password_hash=hash_password(raw_password),
                full_name=payload.full_name or "",
                phone=payload.phone,
                role=payload.role,
                is_active=True,
                mfa_enabled=False,
                mfa_secret=None,
                session_version=1,
                password_changed_at=now if not is_workforce else None,
                created_at=now,
                must_change_password=must_change_password,
                onboarding_status=onboarding_status,
                temporary_password_expires_at=temp_exp,
            )
    await log_audit(db, user["id"], user["email"], "admin.create_user",
                    resource_type="user", resource_id=user_id,
                    metadata={"role": payload.role, "onboarding": onboarding_status},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    out = to_user_out(doc)

    # Every admin-created account receives a secure setup invitation.
    from routers.portal_ops import _issue_portal_link, RESET_TTL_MIN
    from notifiers import send_account_setup_email

    linked_user = {
        "id": user_id,
        "email": email,
        "full_name": payload.full_name or "",
    }

    _raw_token, setup_url = await _issue_portal_link(
        linked_user,
        request,
        ttl_min=RESET_TTL_MIN * 24,
    )

    delivery = await send_account_setup_email(
        db,
        email,
        first_name=(payload.full_name or "").split(" ")[0] or None,
        setup_url=setup_url,
        expires_in_hours=24,
    )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "admin.account_invitation_sent",
        resource_type="user",
        resource_id=user_id,
        metadata={"role": payload.role, "delivery": delivery},
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return {
        **out,
        "invitation_sent": delivery in ("sent", "sent_stub"),
        "delivery": delivery,
        "onboarding_status": onboarding_status,
    }


async def _ensure_patient_profile_for_user(
    user_record: dict,
) -> dict:
    """Link or create the committed patient chart for a client user."""
    user_id = user_record["id"]
    email = (
        user_record.get("email") or ""
    ).strip().lower()

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            # First, find a chart already linked to this portal user.
            result = await pg.execute(
                select(Client).where(
                    Client.user_id == user_id
                )
            )
            linked_client = result.scalars().first()

            if linked_client:
                return {
                    "id": linked_client.id,
                    "created": False,
                    "linked": True,
                }

            # Otherwise, link an existing patient chart with the same email.
            email_client = None

            if email:
                result = await pg.execute(
                    select(Client).where(
                        func.lower(Client.email) == email
                    )
                )
                email_client = result.scalars().first()

            if email_client:
                await clients_repo.update_fields(
                    pg,
                    email_client.id,
                    {
                        "user_id": user_id,
                        "full_name": (
                            email_client.full_name
                            or user_record.get("full_name")
                            or ""
                        ),
                        "phone": (
                            email_client.phone
                            or user_record.get("phone")
                        ),
                    },
                )

                return {
                    "id": email_client.id,
                    "created": False,
                    "linked": True,
                }

            # No matching chart exists, so create one.
            client_id = new_id()
            mrn = f"NMS-{client_id[:6].upper()}"

            await clients_repo.create(
                pg,
                client_id=client_id,
                user_id=user_id,
                mrn=mrn,
                full_name=(
                    user_record.get("full_name")
                    or ""
                ),
                email=email,
                phone=user_record.get("phone"),
            )

            return {
                "id": client_id,
                "created": True,
                "linked": True,
            }


@api.put("/admin/users/{user_id}/role", response_model=UserOut)
async def admin_update_role(user_id: str, body: dict, request: Request, user=Depends(require_roles("admin"))):
    role = (body or {}).get("role")
    allowed_roles = {
        "admin",
        "practitioner",
        "staff",
        "front_desk",
        "frontdesk",
        "medical_assistant",
        "auditor",
        "client",
    }
    if role not in allowed_roles:
        raise HTTPException(status_code=400, detail="Invalid role")
    async with AsyncSessionLocal() as pg:
        target = await users_repo.get_by_id(pg, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await users_repo.update_fields(
                pg,
                user_id,
                {"role": role},
            )
            await users_repo.bump_session_version(
                pg,
                user_id,
            )

    patient_profile = None

    if role == "client":
        # Use the pre-update user record for name, email and phone.
        patient_profile = await _ensure_patient_profile_for_user(
            target
        )

    revoked = await revoke_all_user_sessions(user_id, "role_change",
                                              also_bump_session_version=False)
    await log_audit(db, user["id"], user["email"], "admin.update_role",
                    resource_type="user",
                    resource_id=user_id,
                    metadata={
                        "role": role,
                        "patient_profile": patient_profile,
                        **revoked,
                    },
                    severity="high", outcome="success",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    async with AsyncSessionLocal() as pg:
        target = await users_repo.get_by_id(pg, user_id)
    return to_user_out(target)


@api.put("/admin/users/{user_id}/active")
async def admin_toggle_active(user_id: str, body: dict, request: Request,
                              user=Depends(require_permission(P.USER_DEACTIVATE))):
    active = bool((body or {}).get("is_active", False))
    async with AsyncSessionLocal() as pg:
        target = await users_repo.get_by_id(pg, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await users_repo.update_fields(pg, user_id, {"is_active": active})
            if not active:
                await users_repo.bump_session_version(pg, user_id)
    revoked = None
    if not active:
        revoked = await revoke_all_user_sessions(user_id, "user_deactivated",
                                                  also_bump_session_version=False)
    await log_audit(
        db, user["id"], user["email"],
        "admin.deactivate_user" if not active else "admin.activate_user",
        resource_type="user", resource_id=user_id,
        severity="high", outcome="success",
        metadata={"is_active": active, **(revoked or {})},
        ip=get_client_ip(request), user_agent=request.headers.get("user-agent"),
    )
    return {"ok": True, "is_active": active}


# =================== SESSION EXPLORER ===================
@api.get("/admin/sessions")
async def admin_list_sessions(user_id: Optional[str] = None, limit: int = 200,
                              user=Depends(require_permission(P.SESSION_LIST_ANY))):
    lim = min(max(1, limit), 500)
    async with AsyncSessionLocal() as pg:
        rows = await sessions_repo.list_active_for_admin(pg, user_id=user_id, limit=lim)
        subject_ids = list({r["user_id"] for r in rows if r.get("user_id")})
        users = {}
        if subject_ids:
            for u in (await pg.execute(select(User).where(User.id.in_(subject_ids)))).scalars():
                users[u.id] = {"email": u.email, "full_name": u.full_name, "role": u.role}
    out = []
    for r in rows:
        u = users.get(r.get("user_id")) or {}
        out.append({
            "id": r["id"],
            "user_id": r.get("user_id"),
            "email": u.get("email"),
            "full_name": u.get("full_name"),
            "role": u.get("role"),
            "created_at": r.get("created_at"),
            "last_used_at": r.get("last_used_at"),
            "absolute_expires_at": r.get("absolute_expires_at"),
            "idle_timeout_minutes": r.get("idle_timeout_minutes"),
            "ip_first": r.get("ip_first"),
            "ip_last": r.get("ip_last"),
            "user_agent": (r.get("user_agent") or "")[:120],
            "mfa_satisfied_at": r.get("mfa_satisfied_at"),
        })
    return out


@api.post("/admin/sessions/{session_id}/revoke")
async def admin_revoke_session(session_id: str, request: Request,
                               user=Depends(require_permission(P.SESSION_REVOKE_ANY))):
    async with AsyncSessionLocal() as pg:
        row = await sessions_repo.get(pg, session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.get("revoked_at"):
        return {"ok": True, "already_revoked": True}
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await sessions_repo.revoke_by_id(pg, session_id, "admin_revoke")
    if row.get("family_id"):
        await revoke_family(row["family_id"], "admin_revoke")
    await log_audit(db, user["id"], user["email"], "admin.session_revoke",
                    resource_type="user_session", resource_id=session_id,
                    severity="high", outcome="success",
                    metadata={"target_user_id": row.get("user_id")},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


@api.post("/admin/users/{target_user_id}/revoke-all-sessions")
async def admin_revoke_all_sessions(target_user_id: str, request: Request,
                                    user=Depends(require_permission(P.SESSION_REVOKE_ANY))):
    async with AsyncSessionLocal() as pg:
        target = await users_repo.get_by_id(pg, target_user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    result = await revoke_all_user_sessions(target_user_id, "admin_revoke_all")
    await log_audit(db, user["id"], user["email"], "admin.session_revoke_all",
                    resource_type="user", resource_id=target_user_id,
                    severity="high", outcome="success",
                    metadata=result,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True, **result}


@api.get("/admin/audit/verify-chain")
async def admin_verify_audit_chain(limit: int = 5000,
                                   user=Depends(require_permission(P.AUDIT_READ))):
    return await verify_audit_chain(db, limit=limit)


@api.post("/admin/users/{target_user_id}/deactivate")
async def admin_deactivate_user(
    target_user_id: str,
    request: Request,
    user=Depends(require_roles("admin")),
):
    if target_user_id == user["id"]:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "cannot_deactivate_self",
                "message": "You cannot deactivate your own account.",
            },
        )

    async with AsyncSessionLocal() as pg:
        target = await users_repo.get_by_id(pg, target_user_id)

    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if not target.get("is_active", True):
        return {
            "ok": True,
            "already_inactive": True,
            "user": to_user_out(target),
        }

    if target.get("role") == "admin":
        async with AsyncSessionLocal() as pg:
            active_admins = int(
                (
                    await pg.execute(
                        select(func.count(User.id)).where(
                            User.role == "admin",
                            User.is_active.is_(True),
                        )
                    )
                ).scalar_one()
            )

        if active_admins <= 1:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "last_active_admin",
                    "message": "The final active administrator cannot be deactivated.",
                },
            )

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await users_repo.update_fields(
                pg,
                target_user_id,
                {"is_active": False},
            )

    revocation = await revoke_all_user_sessions(
        target_user_id,
        reason="admin_deactivated_user",
        also_bump_session_version=True,
    )

    from pg_shims import invalidate_portal_reset_tokens

    invitations_revoked = await invalidate_portal_reset_tokens(target_user_id)

    await log_audit(
        db,
        user["id"],
        user["email"],
        "admin.user_deactivated",
        resource_type="user",
        resource_id=target_user_id,
        metadata={
            "target_role": target.get("role"),
            "sessions_revoked": revocation.get("sessions_revoked", 0),
            "refresh_tokens_revoked": revocation.get("tokens_revoked", 0),
            "invitations_revoked": invitations_revoked,
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    async with AsyncSessionLocal() as pg:
        updated = await users_repo.get_by_id(pg, target_user_id)

    return {
        "ok": True,
        "user": to_user_out(updated),
    }


@api.post("/admin/users/{target_user_id}/reactivate")
async def admin_reactivate_user(
    target_user_id: str,
    request: Request,
    user=Depends(require_roles("admin")),
):
    async with AsyncSessionLocal() as pg:
        target = await users_repo.get_by_id(pg, target_user_id)

    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if target.get("is_active", True):
        return {
            "ok": True,
            "already_active": True,
            "user": to_user_out(target),
        }

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await users_repo.update_fields(
                pg,
                target_user_id,
                {"is_active": True},
            )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "admin.user_reactivated",
        resource_type="user",
        resource_id=target_user_id,
        metadata={
            "target_role": target.get("role"),
            "onboarding_status": target.get("onboarding_status"),
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    async with AsyncSessionLocal() as pg:
        updated = await users_repo.get_by_id(pg, target_user_id)

    return {
        "ok": True,
        "user": to_user_out(updated),
    }


@api.post("/admin/users/{target_user_id}/resend-invitation")
async def admin_resend_user_invitation(
    target_user_id: str,
    request: Request,
    user=Depends(require_roles("admin")),
):
    invitation_roles = {
        "admin",
        "practitioner",
        "staff",
        "front_desk",
        "frontdesk",
        "medical_assistant",
        "auditor",
        "client",
    }

    async with AsyncSessionLocal() as pg:
        target = await users_repo.get_by_id(pg, target_user_id)

    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if target.get("role") not in invitation_roles:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_account_role",
                "message": "Account invitations are not available for this role.",
            },
        )

    if not target.get("is_active", True):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "inactive_account",
                "message": "Reactivate this account before resending an invitation.",
            },
        )

    onboarding_status = target.get("onboarding_status")

    if (
        onboarding_status not in {
            "password_change_required",
            "mfa_enrollment_required",
        }
        and target.get("mfa_enabled")
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "onboarding_complete",
                "message": "This account has already completed setup.",
            },
        )

    from rate_limit import enforce_forgot_rate
    enforce_forgot_rate(request, target.get("email") or target_user_id)

    from pg_shims import invalidate_portal_reset_tokens
    previous_invites_revoked = await invalidate_portal_reset_tokens(
        target_user_id
    )

    from routers.portal_ops import _issue_portal_link, RESET_TTL_MIN
    from notifiers import send_account_setup_email

    _raw_token, setup_url = await _issue_portal_link(
        target,
        request,
        ttl_min=RESET_TTL_MIN * 24,
    )

    delivery = await send_account_setup_email(
        db,
        target["email"],
        first_name=(target.get("full_name") or "").split(" ")[0] or None,
        setup_url=setup_url,
        expires_in_hours=24,
    )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "admin.account_invitation_resent",
        resource_type="user",
        resource_id=target_user_id,
        metadata={
            "target_role": target.get("role"),
            "onboarding_status": onboarding_status,
            "delivery": delivery,
            "previous_invites_revoked": previous_invites_revoked,
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return {
        "ok": True,
        "invitation_sent": delivery in {"sent", "sent_stub"},
        "delivery": delivery,
        "expires_in_hours": 24,
    }
