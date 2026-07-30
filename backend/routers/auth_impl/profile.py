"""profile — split from routers/auth.py during Session 1 of the PG migration.
Behaviour is unchanged. All helpers are shared via _common."""
from ._common import *  # noqa: F401,F403

# Account profile / password change                                            #
# --------------------------------------------------------------------------- #
@api.put("/auth/me", response_model=UserOut)
async def update_me(payload: ProfileUpdate, request: Request, user=Depends(get_authenticated_user)):
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    if updates:
        await db.users.update_one({"id": user["id"]}, {"$set": updates})
        await db.clients.update_many(
            {"user_id": user["id"]},
            {"$set": {k: v for k, v in updates.items() if k in ("full_name", "phone")}},
        )
        await log_audit(db, user["id"], user["email"], "account.update",
                        ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    u = await db.users.find_one({"id": user["id"]})
    return to_user_out(u)


@api.post("/auth/change-password")
async def change_password(payload: PasswordChange, request: Request, user=Depends(get_authenticated_user)):
    if not verify_password(payload.current_password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    reason = validate_password_strength(
        payload.new_password, email=user.get("email", ""), full_name=user.get("full_name") or "",
    )
    if reason:
        raise HTTPException(status_code=400, detail=reason)
    now = datetime.now(timezone.utc)
    await db.users.update_one(
        {"id": user["id"]},
        {
            "$set": {
                "password_hash": hash_password(payload.new_password),
                "password_changed_at": now,
                # Clear the temp-password gate — the user has now chosen their own.
                "must_change_password": False,
            },
            "$inc": {"session_version": 1},
        },
    )
    # Revoke every existing session (including current) — user re-logs in with new password.
    await _revoke_all_sessions(user["id"], reason="password_change")
    await log_audit(db, user["id"], user["email"], "account.password_change",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True, "must_relogin": True}

