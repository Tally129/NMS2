"""profile — Session 2b PostgreSQL runtime cutover.

`PUT /auth/me` writes profile updates to PostgreSQL. It ALSO fans out
`full_name` / `phone` into the MongoDB `clients` row so the patient portal
UI (still Mongo-backed) reflects changes immediately.
"""
from ._common import *  # noqa: F401,F403


@api.put("/auth/me", response_model=UserOut)
async def update_me(payload: ProfileUpdate, request: Request, user=Depends(get_authenticated_user)):
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    if updates:
        async with AsyncSessionLocal() as pg:
            async with pg.begin():
                await users_repo.update_fields(pg, user["id"], updates)
        client_fields = {k: v for k, v in updates.items() if k in ("full_name", "phone")}
        if client_fields:
            await db.clients.update_many({"user_id": user["id"]}, {"$set": client_fields})
        await log_audit(db, user["id"], user["email"], "account.update",
                        ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    async with AsyncSessionLocal() as pg:
        u = await users_repo.get_by_id(pg, user["id"])
    return to_user_out(u)


@api.post("/auth/change-password")
async def change_password(payload: PasswordChange, request: Request, user=Depends(get_authenticated_user)):
    if not verify_password(payload.current_password, user.get("password_hash") or ""):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    reason = validate_password_strength(
        payload.new_password, email=user.get("email", ""), full_name=user.get("full_name") or "",
    )
    if reason:
        raise HTTPException(status_code=400, detail=reason)
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await users_repo.update_fields(pg, user["id"], {
                "password_hash": hash_password(payload.new_password),
                "password_changed_at": now,
                # Clear the temp-password gate — the user has now chosen their own.
                "must_change_password": False,
            })
            # revoke_all_user_sessions bumps session_version on its own tx below.
    await _revoke_all_sessions(user["id"], reason="password_change")
    await log_audit(db, user["id"], user["email"], "account.password_change",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True, "must_relogin": True}
