"""registration — Session 2b PostgreSQL runtime cutover.

Registration + login + login-continuation now persist users, sessions,
refresh tokens, login history, and continuation tickets in PostgreSQL. The
client business row is still written into MongoDB (that collection has not
been migrated).
"""
from ._common import *  # noqa: F401,F403


@api.post("/auth/register", response_model=TokenOut)
async def register(payload: UserCreate, request: Request):
    now = datetime.now(timezone.utc)
    email = (payload.email or "").lower().strip()
    async with AsyncSessionLocal() as pg:
        existing = await users_repo.get_by_email(pg, email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    reason = validate_password_strength(payload.password, email=email, full_name=payload.full_name or "")
    if reason:
        raise HTTPException(status_code=400, detail=reason)

    user_id = new_id()
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            user_doc = await users_repo.create_user(
                pg,
                user_id=user_id,
                email=email,
                password_hash=hash_password(payload.password),
                full_name=payload.full_name or "",
                phone=payload.phone,
                role="client",
                is_active=True,
                mfa_enabled=False,
                mfa_secret=None,
                session_version=1,
                password_changed_at=now,
                created_at=now,
            )

    # Client business row now lives in PostgreSQL (Phase 3.1b). Old Mongo
    # `clients` collection is scheduled for drop once every non-auth router
    # migrates.
    from repositories import clients as clients_repo
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await clients_repo.create(
                pg, client_id=new_id(), user_id=user_id,
                full_name=payload.full_name, email=email, phone=payload.phone,
            )

    await log_audit(db, user_id, email, "auth.register",
                    resource_type="user", resource_id=user_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))

    # Clients don't need MFA; workforce sessions start unsatisfied.
    sid, family_id, raw_refresh = await _create_session(
        user_doc, request, mfa_satisfied=(user_doc["role"] not in WORKFORCE_ROLES),
    )
    access = make_access_token(user_id, user_doc["role"], sid,
                                session_version=user_doc.get("session_version", 1))
    resp = Response()
    _set_refresh_cookie(resp, raw_refresh)
    resp.body = json_dumps_body({
        "access_token": access, "refresh_token": "",
        "user": to_user_out(user_doc), "mfa_required": False,
    })
    resp.media_type = "application/json"
    resp.headers["content-length"] = str(len(resp.body))
    return resp


@api.post("/auth/login")
async def login(payload: LoginIn, request: Request):
    from rate_limit import enforce_login_rate, is_locked, record_login_failure, reset_login_failures
    enforce_login_rate(request, payload.email)
    locked, retry_after = is_locked(payload.email)
    if locked:
        raise HTTPException(status_code=423, detail={
            "code": "account_locked",
            "retry_after_seconds": retry_after,
        })

    email = (payload.email or "").lower().strip()
    async with AsyncSessionLocal() as pg:
        user = await users_repo.get_by_email(pg, email)

    if not user or not verify_password(payload.password, user.get("password_hash") or ""):
        # Record failed attempt in PostgreSQL.
        try:
            async with AsyncSessionLocal() as pg:
                async with pg.begin():
                    await login_repo.record_attempt(
                        pg,
                        attempt_id=new_id(),
                        user_id=(user.get("id") if user else None),
                        email_hash=_email_hash(email),
                        success=False,
                        ip=get_client_ip(request),
                        user_agent=request.headers.get("user-agent"),
                    )
        except Exception:
            pass
        record_login_failure(payload.email)
        await log_audit(db, user.get("id") if user else None, email,
                        "auth.login_fail",
                        severity="warning", outcome="failure",
                        ip=get_client_ip(request),
                        user_agent=request.headers.get("user-agent"))
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account disabled")

    # Session 2c — enforce bootstrap onboarding BEFORE creating a session or
    # asking for MFA. Bootstrap JWTs are short-lived, refresh-cookie-less
    # tokens that only unlock the /auth/bootstrap/* endpoints.
    onboarding = user.get("onboarding_status")
    temp_exp = user.get("temporary_password_expires_at")
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")
    if onboarding == "password_change_required" or user.get("must_change_password"):
        if temp_exp and temp_exp < datetime.now(timezone.utc):
            await log_audit(db, user["id"], user["email"], "temporary_password_expired",
                            severity="warning", outcome="failure",
                            ip=ip, user_agent=ua)
            raise HTTPException(
                status_code=403,
                detail={"code": "temporary_password_expired",
                        "message": "Your temporary password has expired. Ask an administrator to reissue one."},
            )
        from auth_utils import make_bootstrap_token
        boot = make_bootstrap_token(user["id"], "password_change")
        await log_audit(db, user["id"], user["email"], "bootstrap_login_started",
                        metadata={"stage": "password_change"},
                        ip=ip, user_agent=ua)
        return {
            "bootstrap_token": boot,
            "bootstrap_stage": "password_change",
            "user": to_user_out(user),
            "next_step": "password_change",
        }
    if onboarding == "mfa_enrollment_required" or (user.get("role") in WORKFORCE_ROLES and not user.get("mfa_enabled") and not user.get("mfa_bypass")):
        from auth_utils import make_bootstrap_token
        boot = make_bootstrap_token(user["id"], "mfa_enrollment")
        await log_audit(db, user["id"], user["email"], "bootstrap_login_started",
                        metadata={"stage": "mfa_enrollment"},
                        ip=ip, user_agent=ua)
        return {
            "bootstrap_token": boot,
            "bootstrap_stage": "mfa_enrollment",
            "user": to_user_out(user),
            "next_step": "mfa_enrollment",
        }

    role = user.get("role", "client")
    mfa_satisfied_now = False
    recovery_used_id = None
    if user.get("mfa_enabled"):
        recovery_code = str(payload.mfa_token or "").strip()
        # Recovery codes are longer + include letters; TOTPs are 6 digits.
        if recovery_code and (not recovery_code.isdigit()) and len(recovery_code) >= 8:
            code_hash = hashlib.sha256(recovery_code.upper().encode("utf-8")).hexdigest()
            from repositories import recovery_codes as recovery_repo
            async with AsyncSessionLocal() as pg:
                async with pg.begin():
                    recovery_used_id = await recovery_repo.claim_by_hash(
                        pg, user_id=user["id"], code_hash=code_hash,
                    )
            if not recovery_used_id:
                await log_audit(db, user["id"], user["email"], "recovery_code_failed",
                                severity="high", outcome="failure",
                                ip=ip, user_agent=ua)
                record_login_failure(payload.email)
                raise HTTPException(status_code=401, detail="Invalid recovery code")
            mfa_satisfied_now = True
            await log_audit(db, user["id"], user["email"], "recovery_code_used",
                            severity="high", outcome="success",
                            metadata={"code_id": recovery_used_id},
                            ip=ip, user_agent=ua)
            # Recovery-code security alert. No code value ever ships.
            from notifiers import send_recovery_code_used_email
            await send_recovery_code_used_email(
                db, user["email"],
                first_name=(user.get("full_name") or "").split(" ")[0] or None,
            )
        elif not payload.mfa_token:
            return {"access_token": "", "refresh_token": "", "user": to_user_out(user), "mfa_required": True}
        elif not verify_mfa(user.get("mfa_secret") or "", payload.mfa_token):
            record_login_failure(payload.email)
            raise HTTPException(status_code=401, detail="Invalid MFA code")
        else:
            mfa_satisfied_now = True

    reset_login_failures(payload.email)

    limit_check = await enforce_active_session_limit(user)
    if limit_check["action"] == "reject_workforce":
        ticket_id = new_id()
        async with AsyncSessionLocal() as pg:
            async with pg.begin():
                await login_repo.create_continuation(
                    pg,
                    ticket_id=ticket_id,
                    user_id=user["id"],
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                    mfa_satisfied_now=mfa_satisfied_now,
                )
        sanitized = await list_active_sessions_sanitized(user["id"])
        raise HTTPException(status_code=409, detail={
            "code": "active_session_limit_exceeded",
            "message": "You have too many active sessions. Sign out of one to continue.",
            "continuation_ticket": ticket_id,
            "expires_in_seconds": 300,
            "active_sessions": sanitized,
            "limit": limit_check["limit"],
        })

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await users_repo.touch_last_login(pg, user["id"])
            await login_repo.record_attempt(
                pg,
                attempt_id=new_id(),
                user_id=user["id"],
                email_hash=_email_hash(user["email"]),
                success=True,
                ip=get_client_ip(request),
                user_agent=request.headers.get("user-agent"),
            )
    await log_audit(db, user["id"], user["email"], "auth.login",
                    resource_type="user", resource_id=user["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))

    # `mfa_bypass=true` accounts skip the internal TOTP gate (legacy flag
    # retained on user documents; no runtime path currently sets it).
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
    session via this endpoint. Body: {continuation_ticket, revoke_session_id}."""
    ticket_id = str(payload.get("continuation_ticket") or "")
    revoke_sid = str(payload.get("revoke_session_id") or "")
    if not ticket_id or not revoke_sid:
        raise HTTPException(status_code=400, detail="Missing ticket or session id")

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            row = await login_repo.consume_continuation(pg, ticket_id)
    if not row:
        raise HTTPException(status_code=400, detail="Invalid or expired continuation ticket")

    async with AsyncSessionLocal() as pg:
        target = await sessions_repo.get(pg, revoke_sid)
    if not target or target.get("user_id") != row["user_id"]:
        raise HTTPException(status_code=404, detail="Session not found")
    await _revoke_session(revoke_sid, "user_chose_revoke")

    async with AsyncSessionLocal() as pg:
        user = await users_repo.get_by_id(pg, row["user_id"])
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account disabled")
    role = user.get("role", "client")

    sid, family_id, raw_refresh = await _create_session(
        user, request, mfa_satisfied=row.get("mfa_satisfied_now", False),
    )
    access = make_access_token(user["id"], role, sid, session_version=user.get("session_version", 1))
    resp = Response(
        content=json_dumps_body({"access_token": access, "user": to_user_out(user), "mfa_required": False}),
        media_type="application/json",
    )
    _set_refresh_cookie(resp, raw_refresh)
    return resp
