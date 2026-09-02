"""refresh — Session 2b PostgreSQL runtime cutover.
Uses PostgreSQL for user + refresh-token rotation. Cookie semantics preserved.
"""
from ._common import *  # noqa: F401,F403


@api.post("/auth/refresh")
async def refresh_endpoint(request: Request):
    """Sprint 2: opaque refresh token, atomic rotation with concurrency grace,
    family reuse detection. Reads the token from the `nms_rt` HttpOnly cookie ONLY.
    """
    allowed = [o.strip() for o in (os.environ.get("ALLOWED_ORIGINS") or "").split(",") if o.strip()]
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    if allowed and origin:
        if not any(origin.startswith(a) for a in allowed):
            raise HTTPException(status_code=403, detail="Origin not allowed")

    raw = request.cookies.get("nms_rt") or ""
    if not raw:
        raise HTTPException(status_code=401, detail="Missing refresh cookie")

    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")
    outcome = await rotate_refresh(raw, ip=ip, user_agent=ua)

    if outcome.kind == "unknown":
        resp = Response(content=b'{"detail":"Invalid refresh"}', status_code=401,
                        media_type="application/json")
        _clear_refresh_cookie(resp)
        return resp

    if outcome.kind == "reuse_detected":
        await log_audit(db, outcome.user_id, None, "auth.refresh_reuse_detected",
                        metadata={"family_id": outcome.family_id, "severity": "high"},
                        ip=ip, user_agent=ua)
        resp = Response(content=b'{"detail":"Invalid refresh"}', status_code=401,
                        media_type="application/json")
        _clear_refresh_cookie(resp)
        return resp

    if outcome.kind == "concurrency_grace":
        await log_audit(db, outcome.user_id, None, "auth.refresh_concurrency_detected",
                        metadata={"family_id": outcome.family_id, "severity": "info"},
                        ip=ip, user_agent=ua)
        return Response(content=b'{"detail":"concurrency_retry"}', status_code=409,
                        media_type="application/json")

    # outcome.kind == "rotated"
    async with AsyncSessionLocal() as pg:
        user = await users_repo.get_by_id(pg, outcome.user_id)
    if not user or not user.get("is_active", True):
        resp = Response(content=b'{"detail":"User disabled"}', status_code=401,
                        media_type="application/json")
        _clear_refresh_cookie(resp)
        return resp
    access = make_access_token(user["id"], user["role"], outcome.session_id,
                                session_version=user.get("session_version", 1))
    await log_audit(db, user["id"], None, "auth.refresh_rotated",
                    metadata={"family_id": outcome.family_id}, ip=ip, user_agent=ua)
    body = {"access_token": access, "user": to_user_out(user)}
    resp = Response(content=json_dumps_body(body), media_type="application/json")
    _set_refresh_cookie(resp, outcome.raw)
    return resp
