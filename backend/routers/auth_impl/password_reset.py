"""password_reset — Session 2b PostgreSQL runtime cutover.

Reset attempts, tokens, and rate-limit counters now live in PostgreSQL.
Response semantics (uniform "if that email is registered" text) unchanged.
"""
from ._common import *  # noqa: F401,F403


_RESET_WINDOW_MIN = 15
_RESET_MAX_PER_EMAIL_WINDOW = 3      # per (email_hash, window)
_RESET_MAX_PER_IP_WINDOW = 10        # per IP, window
_RESET_GLOBAL_ABUSE_THRESHOLD = 200  # per window (blocks system-wide brute force)


async def _reset_rate_limit_ok(email_hash: str, ip: Optional[str]) -> bool:
    since = datetime.now(timezone.utc) - timedelta(minutes=_RESET_WINDOW_MIN)
    async with AsyncSessionLocal() as pg:
        # Approximate "global abuse" via the sum of per-email + per-ip windows
        # is too fuzzy; instead count all attempts newer than `since`.
        from postgres_models import PasswordResetAttempt
        from sqlalchemy import func, select
        global_ct = int((await pg.execute(
            select(func.count(PasswordResetAttempt.id)).where(PasswordResetAttempt.ts >= since)
        )).scalar_one())
        if global_ct >= _RESET_GLOBAL_ABUSE_THRESHOLD:
            return False
        email_ct = await pr_repo.count_recent_by_email(pg, email_hash, since)
        if email_ct >= _RESET_MAX_PER_EMAIL_WINDOW:
            return False
        if ip:
            ip_ct = await pr_repo.count_recent_by_ip(pg, ip, since)
            if ip_ct >= _RESET_MAX_PER_IP_WINDOW:
                return False
    return True


@api.post("/auth/forgot-password")
async def forgot_password(payload: dict, request: Request):
    """Trigger a password-reset email. Response is IDENTICAL for known + unknown emails."""
    from rate_limit import enforce_forgot_rate
    email = str(payload.get("email") or "").strip().lower()
    enforce_forgot_rate(request, email)
    ip = get_client_ip(request)
    email_hash = _email_hash(email) if email else ""
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await pr_repo.record_attempt(
                pg, attempt_id=new_id(), email_hash=email_hash, ip=ip,
            )

    generic = {"ok": True, "message": "If that email is registered, a reset link is on the way."}

    if not email or not email_hash:
        return generic
    if not await _reset_rate_limit_ok(email_hash, ip):
        return generic

    async with AsyncSessionLocal() as pg:
        user = await users_repo.get_by_email(pg, email)
    if not user or not user.get("is_active", True):
        return generic

    raw_token = secrets.token_urlsafe(48)
    token_hash = _hash_token(raw_token)
    expires_at = now + timedelta(minutes=RESET_TOKEN_TTL_MIN)
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await pr_repo.create_token(
                pg,
                token_id=new_id(),
                token_hash=token_hash,
                user_id=user["id"],
                email_hash=email_hash,
                expires_at=expires_at,
                ip=ip,
            )

    frontend_origin = (os.environ.get("FRONTEND_ORIGIN") or "").rstrip("/")
    # `secrets.token_urlsafe` already produces URL-safe base64 (only
    # `[A-Za-z0-9_-]`), but we still run it through `quote` with an empty
    # safe-set as a defensive measure in case the token generator ever
    # changes.
    from urllib.parse import quote as _url_quote
    _encoded_token = _url_quote(raw_token, safe="")
    reset_url = (
        f"{frontend_origin}/reset-password?token={_encoded_token}"
        if frontend_origin
        else f"/reset-password?token={_encoded_token}"
    )

    from notifiers import send_password_reset_email
    await send_password_reset_email(
        db, email,
        first_name=(user.get("full_name") or "").split(" ")[0] or None,
        reset_url=reset_url,
        expires_in_minutes=RESET_TOKEN_TTL_MIN,
    )

    await log_audit(
        db, user["id"], user_email=None, action="auth.password_reset_requested",
        resource_type="user", resource_id=user["id"],
        metadata={"email_hash": email_hash},
        ip=ip, user_agent=request.headers.get("user-agent"),
    )

    return generic


@api.post("/auth/reset-password")
async def reset_password(payload: dict, request: Request):
    raw_token = str(payload.get("token") or "")
    new_pw = str(payload.get("new_password") or "")
    ip = get_client_ip(request)
    if not raw_token or not new_pw:
        raise HTTPException(status_code=400, detail="Missing token or new_password")

    token_hash = _hash_token(raw_token)

    # Atomic single-use consume in PostgreSQL.
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            row = await pr_repo.consume_token(pg, token_hash, ip)
    if not row:
        await log_audit(
            db, user_id=None, user_email=None, action="auth.password_reset_denied",
            metadata={"reason": "invalid_or_expired"}, ip=ip,
            user_agent=request.headers.get("user-agent"),
        )
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    async with AsyncSessionLocal() as pg:
        user = await users_repo.get_by_id(pg, row["user_id"])
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=400, detail="Account not eligible for reset")

    reason = validate_password_strength(new_pw, email=user["email"], full_name=user.get("full_name") or "")
    if reason:
        # Roll back the token consumption so the user can try again.
        async with AsyncSessionLocal() as pg:
            async with pg.begin():
                from sqlalchemy import update
                from postgres_models import PasswordResetToken
                await pg.execute(
                    update(PasswordResetToken)
                    .where(PasswordResetToken.id == row["id"])
                    .values(consumed_at=None, consumed_ip=None)
                )
        raise HTTPException(status_code=400, detail=reason)

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await users_repo.update_fields(pg, user["id"], {
                "password_hash": hash_password(new_pw),
                "password_changed_at": now,
            })
    revoked_ct = await _revoke_all_sessions(user["id"], reason="password_reset")

    await log_audit(
        db, user["id"], user_email=None, action="auth.password_reset_completed",
        resource_type="user", resource_id=user["id"],
        metadata={"revoked_sessions": revoked_ct}, ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    # Password-changed alert. Fire AFTER the DB commit so a mail-provider
    # failure never rolls back the password change.
    from notifiers import send_password_changed_email
    await send_password_changed_email(
        db, user["email"],
        first_name=(user.get("full_name") or "").split(" ")[0] or None,
    )
    return {"ok": True, "must_relogin": True}


# --------------------------------------------------------------------------- #
# DEV-ONLY helper — issue a raw reset token for automated tests directly.     #
# Bypasses the rate limiter so multiple tests can hit it from the same IP.    #
# Explicitly disabled in HIPAA_MODE.                                          #
# --------------------------------------------------------------------------- #
@api.post("/auth/dev/reset-token")
async def dev_reset_token(payload: dict):
    if _hipaa_mode() or os.environ.get("DEV_EXPOSE_RESET_TOKEN", "").lower() not in {"1", "true", "yes"}:
        raise HTTPException(status_code=404, detail="Not available")
    email = str(payload.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Missing email")
    async with AsyncSessionLocal() as pg:
        user = await users_repo.get_by_email(pg, email)
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=404, detail="No such user")
    raw = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await pr_repo.create_token(
                pg,
                token_id=new_id(),
                token_hash=_hash_token(raw),
                user_id=user["id"],
                email_hash=_email_hash(email),
                expires_at=now + timedelta(minutes=RESET_TOKEN_TTL_MIN),
                ip=None,
            )
    return {"dev_reset_token": raw, "expires_in_min": RESET_TOKEN_TTL_MIN}
