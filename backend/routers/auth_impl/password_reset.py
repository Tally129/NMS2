"""password_reset — split from routers/auth.py during Session 1 of the PG migration.
Behaviour is unchanged. All helpers are shared via _common."""
from ._common import *  # noqa: F401,F403

# --------------------------------------------------------------------------- #
# Password reset — Sprint 1                                                    #
# --------------------------------------------------------------------------- #
_RESET_WINDOW_MIN = 15
_RESET_MAX_PER_EMAIL_WINDOW = 3      # per (email_hash, window)
_RESET_MAX_PER_IP_WINDOW = 10        # per IP, window
_RESET_GLOBAL_ABUSE_THRESHOLD = 200  # per window (blocks system-wide brute force)


async def _reset_rate_limit_ok(email_hash: str, ip: Optional[str]) -> bool:
    since = datetime.now(timezone.utc) - timedelta(minutes=_RESET_WINDOW_MIN)
    global_ct = await db.password_reset_attempts.count_documents({"ts": {"$gte": since}})
    if global_ct >= _RESET_GLOBAL_ABUSE_THRESHOLD:
        return False
    email_ct = await db.password_reset_attempts.count_documents({"email_hash": email_hash, "ts": {"$gte": since}})
    if email_ct >= _RESET_MAX_PER_EMAIL_WINDOW:
        return False
    if ip:
        ip_ct = await db.password_reset_attempts.count_documents({"ip": ip, "ts": {"$gte": since}})
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

    # Record every attempt (used for rate limiting). Never store the raw email.
    await db.password_reset_attempts.insert_one({
        "email_hash": email_hash, "ip": ip, "ts": now,
    })

    # Uniform response regardless of what we do below.
    generic = {"ok": True, "message": "If that email is registered, a reset link is on the way."}

    if not email or not email_hash:
        return generic
    if not await _reset_rate_limit_ok(email_hash, ip):
        # Same response body — attackers can't distinguish rate limit from unknown email.
        return generic

    user = await db.users.find_one({"email": email})
    if not user or not user.get("is_active", True):
        return generic

    # Generate a high-entropy token; store only its SHA-256.
    raw_token = secrets.token_urlsafe(48)
    token_hash = _hash_token(raw_token)
    expires_at = now + timedelta(minutes=RESET_TOKEN_TTL_MIN)
    await db.password_reset_tokens.insert_one({
        "id": new_id(),
        "token_hash": token_hash,
        "user_id": user["id"],
        "email_hash": email_hash,
        "created_at": now,
        "expires_at": expires_at,
        "consumed_at": None,
        "ip": ip,
    })

    # Build the reset link — kept in-memory only, never logged.
    frontend_origin = os.environ.get("FRONTEND_ORIGIN") or ""
    reset_url = f"{frontend_origin.rstrip('/')}/reset-password?token={raw_token}" if frontend_origin else f"[configure FRONTEND_ORIGIN]?token={raw_token}"

    from notifiers import send_email as notify_email
    subject = "Reset your NatMedSol password"
    html = (
        "<p>Hi,</p>"
        "<p>Someone (hopefully you) asked to reset the password on your NatMedSol account. "
        f"Follow this link within {RESET_TOKEN_TTL_MIN} minutes to choose a new password:</p>"
        f"<p><a href=\"{reset_url}\">{reset_url}</a></p>"
        "<p>If you didn't request this, you can safely ignore this email.</p>"
        "<p>— NatMedSol Security</p>"
    )
    # redact_recipient=True → integration_log only stores sha256:<prefix>, not the email.
    # No payload_metadata carries the token or URL.
    await notify_email(
        db, email, subject, html,
        action="auth.password_reset_dispatch",
        redact_recipient=True,
    )

    # Redacted audit event — no email, no token, no URL.
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
    now = datetime.now(timezone.utc)

    # ATOMIC consume: only succeeds if the token is unconsumed AND unexpired
    # (we do NOT rely on the TTL index — TTL cleanup is asynchronous).
    row = await db.password_reset_tokens.find_one_and_update(
        {"token_hash": token_hash, "consumed_at": None, "expires_at": {"$gt": now}},
        {"$set": {"consumed_at": now, "consumed_ip": ip}},
    )
    if not row:
        await log_audit(
            db, user_id=None, user_email=None, action="auth.password_reset_denied",
            metadata={"reason": "invalid_or_expired"}, ip=ip,
            user_agent=request.headers.get("user-agent"),
        )
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user = await db.users.find_one({"id": row["user_id"]})
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=400, detail="Account not eligible for reset")

    reason = validate_password_strength(new_pw, email=user["email"], full_name=user.get("full_name") or "")
    if reason:
        # Roll back the token consumption so the user can try again.
        await db.password_reset_tokens.update_one(
            {"id": row["id"]},
            {"$set": {"consumed_at": None, "consumed_ip": None}},
        )
        raise HTTPException(status_code=400, detail=reason)

    await db.users.update_one(
        {"id": user["id"]},
        {
            "$set": {"password_hash": hash_password(new_pw), "password_changed_at": now},
            "$inc": {"session_version": 1},
        },
    )
    revoked_ct = await _revoke_all_sessions(user["id"], reason="password_reset")

    await log_audit(
        db, user["id"], user_email=None, action="auth.password_reset_completed",
        resource_type="user", resource_id=user["id"],
        metadata={"revoked_sessions": revoked_ct}, ip=ip,
        user_agent=request.headers.get("user-agent"),
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
    user = await db.users.find_one({"email": email})
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=404, detail="No such user")
    # Directly issue a fresh reset token — no rate limit, no email dispatch.
    raw = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    await db.password_reset_tokens.insert_one({
        "id": new_id(),
        "token_hash": _hash_token(raw),
        "user_id": user["id"],
        "email_hash": _email_hash(email),
        "created_at": now,
        "expires_at": now + timedelta(minutes=RESET_TOKEN_TTL_MIN),
        "consumed_at": None,
        "ip": None,
    })
    return {"dev_reset_token": raw, "expires_in_min": RESET_TOKEN_TTL_MIN}

