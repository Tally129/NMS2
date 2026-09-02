"""mfa — Session 2b PostgreSQL runtime cutover."""
from ._common import *  # noqa: F401,F403


@api.post("/auth/mfa/setup")
async def mfa_setup(user=Depends(get_authenticated_user)):
    from auth_utils import encrypt_mfa_secret
    secret = generate_mfa_secret()
    uri = mfa_provisioning_uri(secret, user["email"])
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await users_repo.update_fields(pg, user["id"], {
                "mfa_secret": encrypt_mfa_secret(secret),
                "mfa_enabled": False,
            })
    return {"secret": secret, "provisioning_uri": uri}


@api.post("/auth/mfa/verify")
async def mfa_verify(payload: MfaVerifyIn, request: Request, user=Depends(get_authenticated_user)):
    secret = user.get("mfa_secret")
    if not secret:
        raise HTTPException(status_code=400, detail="Run /mfa/setup first")
    if not verify_mfa(secret, payload.token):
        raise HTTPException(status_code=401, detail="Invalid code")
    sid = (user.get("_session") or {}).get("id")
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await users_repo.update_fields(pg, user["id"], {"mfa_enabled": True})
            if sid:
                await sessions_repo.set_mfa_satisfied(pg, sid)
    await log_audit(db, user["id"], user["email"], "auth.mfa_enabled",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    # Post-commit alert; no PHI, no TOTP secret.
    from notifiers import send_mfa_enabled_email
    await send_mfa_enabled_email(
        db, user["email"],
        first_name=(user.get("full_name") or "").split(" ")[0] or None,
    )
    return {"ok": True, "mfa_enabled": True}


@api.post("/auth/mfa/disable")
async def mfa_disable(request: Request, user=Depends(get_authenticated_user)):
    """Workforce accounts CANNOT disable MFA (Sprint 1 hard cutover)."""
    if user.get("role") in WORKFORCE_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Workforce accounts are not permitted to disable MFA. Contact your security administrator.",
        )
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await users_repo.update_fields(pg, user["id"], {
                "mfa_enabled": False, "mfa_secret": None,
            })
    await log_audit(db, user["id"], user["email"], "auth.mfa_disabled",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True, "mfa_enabled": False}
