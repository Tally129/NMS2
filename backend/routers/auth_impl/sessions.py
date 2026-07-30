"""sessions — split from routers/auth.py during Session 1 of the PG migration.
Behaviour is unchanged. All helpers are shared via _common."""
from ._common import *  # noqa: F401,F403

@api.post("/auth/logout")
async def logout(request: Request, response: Response, user=Depends(get_authenticated_user)):
    sid = (user.get("_session") or {}).get("id")
    if sid:
        await _revoke_session(sid, "user_logout")
    await log_audit(db, user["id"], user["email"], "auth.logout",
                    resource_type="session", resource_id=sid,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    _clear_refresh_cookie(response)
    return {"ok": True}


@api.post("/auth/logout-all")
async def logout_all(request: Request, response: Response, user=Depends(get_authenticated_user)):
    """Revoke every session + refresh family for the authenticated user."""
    r = await revoke_all_user_sessions(user["id"], reason="user_logout_all")
    await log_audit(db, user["id"], user["email"], "auth.sessions_revoked_all",
                    metadata=r, ip=get_client_ip(request),
                    user_agent=request.headers.get("user-agent"))
    _clear_refresh_cookie(response)
    return {"ok": True, **r}


@api.get("/auth/sessions")
async def list_my_sessions(user=Depends(get_authenticated_user)):
    """Return the user's active sessions (sanitized — no raw IPs / full UA)."""
    current_sid = (user.get("_session") or {}).get("id")
    return await list_active_sessions_sanitized(user["id"], current_sid=current_sid)


@api.delete("/auth/sessions/{session_id}")
async def revoke_my_session(session_id: str, request: Request, user=Depends(get_authenticated_user)):
    target = await db.user_sessions.find_one({"id": session_id, "user_id": user["id"]})
    if not target:
        raise HTTPException(status_code=404, detail="Session not found")
    await _revoke_session(session_id, "user_revoked")
    await log_audit(db, user["id"], user["email"], "auth.session_revoked",
                    resource_type="session", resource_id=session_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


@api.get("/auth/me", response_model=UserOut)
async def me(user=Depends(get_authenticated_user)):
    return to_user_out(user)

