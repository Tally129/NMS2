"""registration — split from routers/auth.py during Session 1 of the PG migration.
Behaviour is unchanged. All helpers are shared via _common."""
from ._common import *  # noqa: F401,F403

# --------------------------------------------------------------------------- #
# Registration / Login / Token refresh                                        #
# --------------------------------------------------------------------------- #
@api.post("/auth/register", response_model=TokenOut)
async def register(payload: UserCreate, request: Request):
    existing = await db.users.find_one({"email": payload.email.lower()})
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    reason = validate_password_strength(payload.password, email=payload.email, full_name=payload.full_name or "")
    if reason:
        raise HTTPException(status_code=400, detail=reason)

    role = "client"
    now = datetime.now(timezone.utc)
    user_doc = {
        "id": new_id(),
        "email": payload.email.lower(),
        "password_hash": hash_password(payload.password),
        "full_name": payload.full_name,
        "phone": payload.phone,
        "role": role,
        "mfa_enabled": False,
        "mfa_secret": None,
        "is_active": True,
        "session_version": 1,
        "password_changed_at": now,
        "created_at": now,
        "last_login_at": None,
    }
    await db.users.insert_one(user_doc)

    await db.clients.insert_one({
        "id": new_id(), "user_id": user_doc["id"],
        "full_name": payload.full_name, "email": payload.email.lower(),
        "phone": payload.phone, "intake_completed": False,
        "created_at": now,
    })

    await log_audit(db, user_doc["id"], user_doc["email"], "auth.register",
                    resource_type="user", resource_id=user_doc["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))

    # Clients don't need MFA; workforce sessions start unsatisfied.
    sid, family_id, raw_refresh = await _create_session(user_doc, request, mfa_satisfied=(role not in WORKFORCE_ROLES))
    access = make_access_token(user_doc["id"], role, sid, session_version=user_doc.get("session_version", 1))
    resp = Response()
    _set_refresh_cookie(resp, raw_refresh)
    resp.body = json_dumps_body({"access_token": access, "refresh_token": "", "user": to_user_out(user_doc), "mfa_required": False})
    resp.media_type = "application/json"
    resp.headers["content-length"] = str(len(resp.body))
    return resp



@api.post("/auth/login")
async def login(payload: LoginIn, request: Request):
    from rate_limit import enforce_login_rate, is_locked, record_login_failure, reset_login_failures
    # 1) IP + email sliding-window rate limit — protects against distributed brute force.
    enforce_login_rate(request, payload.email)
    # 2) Per-email lockout — brute-force controls independent of the rate window.
    locked, retry_after = is_locked(payload.email)
    if locked:
        raise HTTPException(status_code=423, detail={
            "code": "account_locked",
            "retry_after_seconds": retry_after,
        })

    user = await db.users.find_one({"email": payload.email.lower()})
    if not user or not verify_password(payload.password, user.get("password_hash", "")):
        await db.login_history.insert_one({
            "id": new_id(), "user_id": user.get("id") if user else None,
            "email_hash": _email_hash(payload.email),
            "success": False,
            "ip": get_client_ip(request), "user_agent": request.headers.get("user-agent"),
            "ts": datetime.now(timezone.utc),
        })
        record_login_failure(payload.email)
        await log_audit(db, user.get("id") if user else None, payload.email.lower(),
                        "auth.login_fail",
                        severity="warning", outcome="failure",
                        ip=get_client_ip(request),
                        user_agent=request.headers.get("user-agent"))
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account disabled")

    role = user.get("role", "client")
    mfa_satisfied_now = False
    if user.get("mfa_enabled"):
        if not payload.mfa_token:
            return {"access_token": "", "refresh_token": "", "user": to_user_out(user), "mfa_required": True}
        if not verify_mfa(user.get("mfa_secret", ""), payload.mfa_token):
            record_login_failure(payload.email)
            raise HTTPException(status_code=401, detail="Invalid MFA code")
        mfa_satisfied_now = True

    # Success — clear any accumulated failure counter.
    reset_login_failures(payload.email)

    # Active-session limit check BEFORE creating a new session.
    limit_check = await enforce_active_session_limit(user)
    if limit_check["action"] == "reject_workforce":
        # Return a continuation ticket. The user must choose a session to revoke,
        # then call /auth/login/continue with the ticket to actually authenticate.
        ticket_id = new_id()
        await db.login_continuations.insert_one({
            "ticket_id": ticket_id,
            "user_id": user["id"],
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
            "mfa_satisfied_now": mfa_satisfied_now,
            "consumed_at": None,
        })
        sanitized = await list_active_sessions_sanitized(user["id"])
        raise HTTPException(status_code=409, detail={
            "code": "active_session_limit_exceeded",
            "message": "You have too many active sessions. Sign out of one to continue.",
            "continuation_ticket": ticket_id,
            "expires_in_seconds": 300,
            "active_sessions": sanitized,
            "limit": limit_check["limit"],
        })

    await db.users.update_one({"id": user["id"]}, {"$set": {"last_login_at": datetime.now(timezone.utc)}})
    await db.login_history.insert_one({
        "id": new_id(), "user_id": user["id"], "email_hash": _email_hash(user["email"]),
        "success": True,
        "ip": get_client_ip(request), "user_agent": request.headers.get("user-agent"),
        "ts": datetime.now(timezone.utc),
    })
    await log_audit(db, user["id"], user["email"], "auth.login",
                    resource_type="user", resource_id=user["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))

    # `mfa_bypass=true` accounts (e.g. Google-authenticated admins whose
    # Google account already enforces 2FA) skip the internal TOTP gate.
    starts_satisfied = mfa_satisfied_now or (role not in WORKFORCE_ROLES) or bool(user.get("mfa_bypass"))
    sid, family_id, raw_refresh = await _create_session(user, request, mfa_satisfied=starts_satisfied)
    access = make_access_token(user["id"], role, sid, session_version=user.get("session_version", 1))

    body = {"access_token": access, "user": to_user_out(user), "mfa_required": False}
    if limit_check.get("action") == "evicted_oldest":
        body["notice"] = "Another device was signed out to make room for this session."
    resp = Response(content=json_dumps_body(body), media_type="application/json")
    _set_refresh_cookie(resp, raw_refresh)
    return resp


@api.post("/auth/login/continue")
async def login_continue(payload: dict, request: Request):
    """After hitting the workforce active-session cap, the client revokes a
    session (via DELETE /auth/sessions/{id} — but wait, that needs auth; so
    we do it here). Body: {continuation_ticket, revoke_session_id}.
    """
    ticket_id = str(payload.get("continuation_ticket") or "")
    revoke_sid = str(payload.get("revoke_session_id") or "")
    if not ticket_id or not revoke_sid:
        raise HTTPException(status_code=400, detail="Missing ticket or session id")
    row = await db.login_continuations.find_one_and_update(
        {"ticket_id": ticket_id, "consumed_at": None,
         "expires_at": {"$gt": datetime.now(timezone.utc)}},
        {"$set": {"consumed_at": datetime.now(timezone.utc)}},
    )
    if not row:
        raise HTTPException(status_code=400, detail="Invalid or expired continuation ticket")
    # Revoke the chosen session (must belong to this user).
    target = await db.user_sessions.find_one({"id": revoke_sid, "user_id": row["user_id"]})
    if not target:
        raise HTTPException(status_code=404, detail="Session not found")
    await _revoke_session(revoke_sid, "user_chose_revoke")

    user = await db.users.find_one({"id": row["user_id"]})
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account disabled")
    role = user.get("role", "client")

    sid, family_id, raw_refresh = await _create_session(user, request, mfa_satisfied=row.get("mfa_satisfied_now", False))
    access = make_access_token(user["id"], role, sid, session_version=user.get("session_version", 1))
    resp = Response(
        content=json_dumps_body({"access_token": access, "user": to_user_out(user), "mfa_required": False}),
        media_type="application/json",
    )
    _set_refresh_cookie(resp, raw_refresh)
    return resp


