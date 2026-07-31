"""
Clinical delegation grant / list / revoke endpoints.

Providers can grant scoped, time-limited edit rights to Admin or Medical
Assistant users. Delegates use the resulting record to unlock draft editing
on SOAP notes, treatment plans, assessments, and forms/protocols.

Route surface
    POST   /api/delegations              (provider)
    GET    /api/delegations              (workforce: mine granted OR received)
    DELETE /api/delegations/{id}         (grantor OR admin)
    GET    /api/delegations/effective    (delegate: is a client_id editable?)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from audit import get_client_ip, log_audit
from delegations import (
    DEFAULT_TTL, ELIGIBLE_DELEGATE_ROLES, MAX_TTL,
    has_active_delegation,
)
from deps import _strip_id, api, db, get_current_user, require_roles
from models import new_id
from pg_shims import find_client, find_user_by_id
from postgres_db import AsyncSessionLocal
from repositories import clinical_and_messaging as cm_repo


class DelegationIn(BaseModel):
    delegate_id: str
    client_id: Optional[str] = None       # None = blanket
    scope: str = "documentation"
    ttl_minutes: int = Field(default=1440, ge=15, le=int(MAX_TTL.total_seconds() // 60))
    note: Optional[str] = None


@api.post("/delegations")
async def create_delegation(payload: DelegationIn, request: Request,
                            user=Depends(require_roles("practitioner"))):
    delegate = await find_user_by_id(payload.delegate_id)
    if not delegate:
        raise HTTPException(status_code=404, detail="Delegate user not found")
    if delegate.get("role") not in ELIGIBLE_DELEGATE_ROLES:
        raise HTTPException(status_code=400, detail={
            "code": "delegate_role_ineligible",
            "message": "Only Admin or Medical Assistant users may be delegates.",
            "eligible_roles": sorted(ELIGIBLE_DELEGATE_ROLES),
        })
    if payload.client_id:
        client = await find_client(client_id=payload.client_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
    if payload.scope != "documentation":
        raise HTTPException(status_code=400, detail="Only 'documentation' scope is supported currently")

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=int(payload.ttl_minutes))
    doc = {
        "id": new_id(),
        "provider_id": user["id"],
        "delegate_id": delegate["id"],
        "client_id": payload.client_id,
        "scope": payload.scope,
        "reason": (payload.note or "").strip()[:400] or None,
        "active": True,
        "created_at": now,
        "expires_at": expires_at,
    }
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            doc = await cm_repo.create_delegation(pg, doc)
    await log_audit(
        db, user["id"], user["email"], "delegation.grant",
        resource_type="delegation", resource_id=doc["id"],
        severity="high", outcome="success",
        metadata={
            "delegate_id": delegate["id"],
            "delegate_role": delegate.get("role"),
            "client_id": payload.client_id,
            "expires_at": expires_at.isoformat(),
        },
        ip=get_client_ip(request), user_agent=request.headers.get("user-agent"),
    )
    return _strip_id(doc)


@api.get("/delegations")
async def list_delegations(role_scope: str = Query("all"),
                           user=Depends(get_current_user)):
    """List delegations relevant to me. `role_scope` = granted | received | all."""
    if user.get("role") == "client":
        raise HTTPException(status_code=403, detail="Forbidden")
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as pg:
        if role_scope == "granted":
            rows = await cm_repo.list_delegations(pg, provider_id=user["id"], limit=200)
        elif role_scope == "received":
            rows = await cm_repo.list_delegations(pg, delegate_id=user["id"], limit=200)
        else:
            granted = await cm_repo.list_delegations(pg, provider_id=user["id"], limit=200)
            received = await cm_repo.list_delegations(pg, delegate_id=user["id"], limit=200)
            # De-dupe by id, most-recent first.
            seen = {}
            for r in granted + received:
                seen[r["id"]] = r
            rows = sorted(seen.values(),
                          key=lambda r: r.get("created_at") or now,
                          reverse=True)[:200]
    out = []
    for r in rows:
        r["is_active"] = (
            r.get("active") is True
            and (r.get("expires_at") is None or r["expires_at"] > now)
        )
        out.append(r)
    return out


@api.delete("/delegations/{delegation_id}")
async def revoke_delegation(delegation_id: str, request: Request,
                            user=Depends(get_current_user)):
    async with AsyncSessionLocal() as pg:
        rows = await cm_repo.list_delegations(pg, limit=200)
    d = next((r for r in rows if r["id"] == delegation_id), None)
    if not d:
        raise HTTPException(status_code=404, detail="Delegation not found")
    if user.get("role") not in ("admin", "practitioner") or (
        user.get("role") == "practitioner" and d.get("provider_id") != user["id"]
    ):
        raise HTTPException(status_code=403, detail="Only the granting provider or an admin can revoke")
    if d.get("active") is False:
        return {"ok": True, "already_revoked": True}
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await cm_repo.revoke_delegation(pg, delegation_id, by_id=user["id"])
    await log_audit(
        db, user["id"], user["email"], "delegation.revoke",
        resource_type="delegation", resource_id=delegation_id,
        severity="high", outcome="success",
        metadata={"delegate_id": d.get("delegate_id"),
                  "client_id": d.get("client_id")},
        ip=get_client_ip(request), user_agent=request.headers.get("user-agent"),
    )
    return {"ok": True}


@api.get("/delegations/effective")
async def effective_delegation(client_id: Optional[str] = None,
                               user=Depends(get_current_user)):
    """Called by clinical UI to decide whether to render editing controls."""
    role = user.get("role")
    if role == "practitioner":
        return {"can_edit_draft": True, "reason": "provider", "delegation": None}
    if role not in ELIGIBLE_DELEGATE_ROLES:
        return {"can_edit_draft": False, "reason": "role_ineligible", "delegation": None}
    d = await has_active_delegation(user, client_id)
    if d:
        return {"can_edit_draft": True, "reason": "delegated",
                "delegation": _strip_id(d)}
    return {"can_edit_draft": False, "reason": "no_delegation", "delegation": None}
