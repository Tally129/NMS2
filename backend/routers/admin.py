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
from postgres_models import AuditLog, User
from repositories import audit as audit_repo
from repositories import scheduling as sched_repo
from repositories import user_sessions as sessions_repo
from repositories import users as users_repo
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
    if payload.role not in ("admin", "practitioner", "staff", "client"):
        raise HTTPException(status_code=400, detail="Invalid role")
    email = (payload.email or "").lower().strip()
    async with AsyncSessionLocal() as pg:
        if await users_repo.get_by_email(pg, email):
            raise HTTPException(status_code=409, detail="Email already registered")
    # Session 2c — every workforce account is created in the bootstrap flow.
    # Clients keep the pre-existing behaviour: their password is what the
    # admin typed and no forced onboarding is triggered.
    from routers.auth_impl.bootstrap import (
        TEMP_PASSWORD_TTL_HOURS, _generate_temp_password,
    )
    WORKFORCE = {"admin", "practitioner", "staff", "front_desk", "frontdesk",
                 "medical_assistant", "auditor"}
    is_workforce = payload.role in WORKFORCE
    if is_workforce:
        raw_password = _generate_temp_password()
        onboarding_status = "password_change_required"
        must_change_password = True
        temp_exp = datetime.now(timezone.utc) + timedelta(hours=TEMP_PASSWORD_TTL_HOURS)
    else:
        raw_password = payload.password
        onboarding_status = None
        must_change_password = False
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
    if is_workforce:
        await log_audit(db, user_id, email, "temporary_password_issued",
                        resource_type="user", resource_id=user_id,
                        metadata={"ttl_hours": TEMP_PASSWORD_TTL_HOURS,
                                  "issued_by": user["id"]},
                        ip=get_client_ip(request),
                        user_agent=request.headers.get("user-agent"))
    out = to_user_out(doc)
    if is_workforce:
        # Return the plaintext temporary password ONCE. The caller is
        # expected to hand this to the new employee out-of-band.
        out = {**out, "temporary_password": raw_password,
               "temporary_password_expires_at": temp_exp.isoformat(),
               "onboarding_status": onboarding_status}
    return out


@api.put("/admin/users/{user_id}/role", response_model=UserOut)
async def admin_update_role(user_id: str, body: dict, request: Request, user=Depends(require_roles("admin"))):
    role = (body or {}).get("role")
    if role not in ("admin", "practitioner", "staff", "client"):
        raise HTTPException(status_code=400, detail="Invalid role")
    async with AsyncSessionLocal() as pg:
        target = await users_repo.get_by_id(pg, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await users_repo.update_fields(pg, user_id, {"role": role})
            await users_repo.bump_session_version(pg, user_id)
    revoked = await revoke_all_user_sessions(user_id, "role_change",
                                              also_bump_session_version=False)
    await log_audit(db, user["id"], user["email"], "admin.update_role",
                    resource_type="user", resource_id=user_id, metadata={"role": role, **revoked},
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
