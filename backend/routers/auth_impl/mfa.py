"""mfa — split from routers/auth.py during Session 1 of the PG migration.
Behaviour is unchanged. All helpers are shared via _common."""
from ._common import *  # noqa: F401,F403

# --------------------------------------------------------------------------- #
# Multi-factor authentication                                                 #
# --------------------------------------------------------------------------- #
@api.post("/auth/mfa/setup")
async def mfa_setup(user=Depends(get_authenticated_user)):
    from auth_utils import encrypt_mfa_secret
    secret = generate_mfa_secret()
    uri = mfa_provisioning_uri(secret, user["email"])
    # Store the AES-256-GCM ciphertext — plaintext leaves memory once the response is sent.
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"mfa_secret": encrypt_mfa_secret(secret), "mfa_enabled": False}},
    )
    return {"secret": secret, "provisioning_uri": uri}


@api.post("/auth/mfa/verify")
async def mfa_verify(payload: MfaVerifyIn, request: Request, user=Depends(get_authenticated_user)):
    secret = user.get("mfa_secret")
    if not secret:
        raise HTTPException(status_code=400, detail="Run /mfa/setup first")
    if not verify_mfa(secret, payload.token):
        raise HTTPException(status_code=401, detail="Invalid code")
    now = datetime.now(timezone.utc)
    await db.users.update_one({"id": user["id"]}, {"$set": {"mfa_enabled": True}})
    # Mark THIS session as MFA-satisfied so PHI routes stop returning 403 immediately.
    sid = (user.get("_session") or {}).get("id")
    if sid:
        await db.user_sessions.update_one({"id": sid}, {"$set": {"mfa_satisfied_at": now}})
    await log_audit(db, user["id"], user["email"], "auth.mfa_enabled",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True, "mfa_enabled": True}


@api.post("/auth/mfa/disable")
async def mfa_disable(request: Request, user=Depends(get_authenticated_user)):
    """Workforce accounts CANNOT disable MFA (Sprint 1 hard cutover)."""
    if user.get("role") in WORKFORCE_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Workforce accounts are not permitted to disable MFA. Contact your security administrator.",
        )
    await db.users.update_one({"id": user["id"]}, {"$set": {"mfa_enabled": False, "mfa_secret": None}})
    await log_audit(db, user["id"], user["email"], "auth.mfa_disabled",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True, "mfa_enabled": False}


