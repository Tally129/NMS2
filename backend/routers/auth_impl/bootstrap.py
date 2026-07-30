"""bootstrap — Session 2c admin onboarding routes.

Endpoints:
  POST /api/auth/bootstrap/first-admin         — one-shot; requires BOOTSTRAP_SECRET
  POST /api/auth/bootstrap/password-change     — bootstrap JWT (stage=password_change)
  POST /api/auth/bootstrap/mfa/setup           — bootstrap JWT (stage=mfa_enrollment)
  POST /api/auth/bootstrap/mfa/verify          — bootstrap JWT (stage=mfa_enrollment)

Bootstrap-stage transitions
  admin_creates_user → password_change_required
  bootstrap password-change → mfa_enrollment_required
  bootstrap mfa/verify (valid TOTP) → onboarding_status=None + issue recovery codes

A separate helper module exposes `attach_bootstrap_state()` used by
`login()` (registration.py) to detect the current stage and swap the
normal token response for a short-lived bootstrap JWT.
"""
from ._common import *  # noqa: F401,F403

import logging as _logging
from auth_utils import BOOTSTRAP_STAGES, encrypt_mfa_secret, make_bootstrap_token
from fastapi import Header
from fastapi.security import HTTPAuthorizationCredentials
from repositories import recovery_codes as recovery_repo

_bootstrap_log = _logging.getLogger("nms.auth.bootstrap")

TEMP_PASSWORD_TTL_HOURS = int(os.environ.get("BOOTSTRAP_TEMP_PASSWORD_TTL_HOURS", "24"))
RECOVERY_CODE_COUNT = 8
RECOVERY_CODE_LENGTH = 10
RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I/O/1/0 (ambiguity)


def _generate_temp_password() -> str:
    """24 chars, printable, cryptographically random. Meets the password
    strength validator so a caller who forgets to hash it still gets a
    strong ephemeral secret."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789!@#$%^&*-_+="
    return "".join(secrets.choice(alphabet) for _ in range(24))


def _generate_recovery_code() -> str:
    return "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_CODE_LENGTH))


def _hash_recovery_code(code: str) -> str:
    return hashlib.sha256((code or "").upper().strip().encode("utf-8")).hexdigest()


async def _mint_recovery_codes(user_id: str) -> list[str]:
    """Generate 8 codes, store their hashes, return the plaintext ONCE."""
    plain = [_generate_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    now = datetime.now(timezone.utc)
    items = [
        {"id": secrets.token_hex(16), "user_id": user_id,
         "code_hash": _hash_recovery_code(p), "used_at": None, "created_at": now}
        for p in plain
    ]
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await recovery_repo.replace_all_for_user(pg, user_id=user_id, items=items)
    return plain


def _decode_bootstrap(request: Request, expected_stage: str) -> dict:
    """Extract + validate a bootstrap-stage JWT from the Authorization header."""
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bootstrap token")
    token = auth.split(" ", 1)[1].strip()
    payload = decode_token(token, expected_type="bootstrap")
    if payload.get("scope") != "bootstrap":
        raise HTTPException(status_code=401, detail="Not a bootstrap token")
    stage = payload.get("bootstrap_stage")
    if stage != expected_stage:
        raise HTTPException(
            status_code=403,
            detail={"code": "wrong_bootstrap_stage",
                    "message": f"This endpoint requires bootstrap_stage='{expected_stage}'.",
                    "current_stage": stage},
        )
    return payload


# --------------------------------------------------------------------------- #
# POST /api/auth/bootstrap/first-admin                                         #
# --------------------------------------------------------------------------- #
@api.post("/auth/bootstrap/first-admin")
async def first_admin_bootstrap(
    payload: dict, request: Request,
    x_bootstrap_secret: Optional[str] = Header(default=None, alias="X-Bootstrap-Secret"),
):
    """One-shot creation of the very first admin account in production.

    * Requires the `BOOTSTRAP_SECRET` env var to match the
      ``X-Bootstrap-Secret`` header exactly (constant-time compare).
    * Refuses to run once any admin exists.
    * Returns the plaintext temporary password ONCE. The caller must copy it
      immediately — subsequent requests will 409/410 forever.
    * Never logs the temporary password, the bootstrap secret, or the new
      admin's password hash.
    """
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")
    expected = os.environ.get("BOOTSTRAP_SECRET") or ""
    if not expected:
        await log_audit(db, None, None, "first_admin_bootstrap_attempt",
                        severity="high", outcome="failure",
                        metadata={"reason": "server_not_configured"},
                        ip=ip, user_agent=ua)
        raise HTTPException(status_code=503, detail="Bootstrap not configured on this server.")
    provided = x_bootstrap_secret or ""
    if not provided or not secrets.compare_digest(expected, provided):
        await log_audit(db, None, None, "first_admin_bootstrap_attempt",
                        severity="high", outcome="failure",
                        metadata={"reason": "wrong_secret"},
                        ip=ip, user_agent=ua)
        raise HTTPException(status_code=401, detail="Invalid bootstrap secret")

    async with AsyncSessionLocal() as pg:
        from postgres_models import User
        from sqlalchemy import select
        existing = (await pg.execute(select(User).where(User.role == "admin").limit(1))).scalar_one_or_none()
    if existing is not None:
        await log_audit(db, None, None, "first_admin_bootstrap_attempt",
                        severity="high", outcome="failure",
                        metadata={"reason": "admin_already_exists"},
                        ip=ip, user_agent=ua)
        raise HTTPException(status_code=409, detail="An admin account already exists.")

    email = (payload.get("email") or "").strip().lower()
    full_name = (payload.get("full_name") or "").strip() or "Bootstrap Admin"
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required.")

    temp_pw = _generate_temp_password()
    now = datetime.now(timezone.utc)
    user_id = new_id()
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await users_repo.create_user(
                pg, user_id=user_id, email=email,
                password_hash=hash_password(temp_pw),
                full_name=full_name, role="admin", is_active=True,
                must_change_password=True,
                onboarding_status="password_change_required",
                temporary_password_expires_at=now + timedelta(hours=TEMP_PASSWORD_TTL_HOURS),
                session_version=1, created_at=now,
                password_changed_at=None,
            )

    await log_audit(
        db, user_id, email, "first_admin_created",
        resource_type="user", resource_id=user_id,
        severity="high", outcome="success",
        metadata={"expires_in_hours": TEMP_PASSWORD_TTL_HOURS},
        ip=ip, user_agent=ua,
    )
    await log_audit(
        db, user_id, email, "temporary_password_issued",
        resource_type="user", resource_id=user_id,
        severity="info", outcome="success",
        metadata={"ttl_hours": TEMP_PASSWORD_TTL_HOURS},
        ip=ip, user_agent=ua,
    )
    return {
        "ok": True,
        "user": {"id": user_id, "email": email, "role": "admin"},
        "temporary_password": temp_pw,
        "expires_at": (now + timedelta(hours=TEMP_PASSWORD_TTL_HOURS)).isoformat(),
        "note": "Store this password securely — it will not be shown again.",
    }


# --------------------------------------------------------------------------- #
# POST /api/auth/bootstrap/password-change                                     #
# --------------------------------------------------------------------------- #
@api.post("/auth/bootstrap/password-change")
async def bootstrap_password_change(payload: dict, request: Request):
    """Complete the forced password change on a bootstrap-stage token."""
    claims = _decode_bootstrap(request, expected_stage="password_change")
    user_id = claims["sub"]
    current = str(payload.get("current_password") or "")
    new_pw = str(payload.get("new_password") or "")
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")

    async with AsyncSessionLocal() as pg:
        user = await users_repo.get_by_id(pg, user_id)
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account not eligible")
    if not user.get("must_change_password"):
        raise HTTPException(
            status_code=400,
            detail={"code": "already_completed", "message": "This account has already changed its password."},
        )
    if not verify_password(current, user.get("password_hash") or ""):
        await log_audit(db, user_id, user["email"], "bootstrap_password_change",
                        severity="warning", outcome="failure",
                        metadata={"reason": "wrong_current"},
                        ip=ip, user_agent=ua)
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    expires_at = user.get("temporary_password_expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc):
        await log_audit(db, user_id, user["email"], "temporary_password_expired",
                        severity="warning", outcome="failure",
                        ip=ip, user_agent=ua)
        raise HTTPException(
            status_code=403,
            detail={"code": "temporary_password_expired",
                    "message": "Your temporary password has expired. Ask an administrator to reissue one."},
        )
    reason = validate_password_strength(new_pw, email=user["email"], full_name=user.get("full_name") or "")
    if reason:
        raise HTTPException(status_code=400, detail=reason)
    if verify_password(new_pw, user.get("password_hash") or ""):
        raise HTTPException(status_code=400, detail="New password must differ from the temporary one.")

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await users_repo.update_fields(pg, user_id, {
                "password_hash": hash_password(new_pw),
                "must_change_password": False,
                "temporary_password_expires_at": None,
                "onboarding_status": "mfa_enrollment_required" if user["role"] in WORKFORCE_ROLES else None,
                "password_changed_at": now,
            })
            await users_repo.bump_session_version(pg, user_id)

    await log_audit(db, user_id, user["email"], "bootstrap_password_changed",
                    resource_type="user", resource_id=user_id,
                    severity="info", outcome="success",
                    ip=ip, user_agent=ua)

    return {
        "ok": True,
        "must_relogin": True,
        "next_step": "mfa_enrollment" if user["role"] in WORKFORCE_ROLES else "login",
    }


# --------------------------------------------------------------------------- #
# POST /api/auth/bootstrap/mfa/setup + /verify                                 #
# --------------------------------------------------------------------------- #
@api.post("/auth/bootstrap/mfa/setup")
async def bootstrap_mfa_setup(request: Request):
    claims = _decode_bootstrap(request, expected_stage="mfa_enrollment")
    user_id = claims["sub"]
    async with AsyncSessionLocal() as pg:
        user = await users_repo.get_by_id(pg, user_id)
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account not eligible")
    secret = generate_mfa_secret()
    uri = mfa_provisioning_uri(secret, user["email"])
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await users_repo.update_fields(pg, user_id, {
                "mfa_secret": encrypt_mfa_secret(secret),
                "mfa_enabled": False,
            })
    await log_audit(db, user_id, user["email"], "mfa_enrollment_started",
                    ip=get_client_ip(request),
                    user_agent=request.headers.get("user-agent"))
    return {"secret": secret, "provisioning_uri": uri}


@api.post("/auth/bootstrap/mfa/verify")
async def bootstrap_mfa_verify(payload: MfaVerifyIn, request: Request):
    claims = _decode_bootstrap(request, expected_stage="mfa_enrollment")
    user_id = claims["sub"]
    async with AsyncSessionLocal() as pg:
        user = await users_repo.get_by_id(pg, user_id)
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account not eligible")
    if user.get("mfa_enabled"):
        raise HTTPException(status_code=400, detail="MFA already enabled on this account.")
    stored = user.get("mfa_secret") or ""
    if not stored:
        raise HTTPException(status_code=400, detail="Run /auth/bootstrap/mfa/setup first")
    if not verify_mfa(stored, payload.token):
        await log_audit(db, user_id, user["email"], "mfa_enrollment_failed",
                        severity="warning", outcome="failure",
                        ip=get_client_ip(request),
                        user_agent=request.headers.get("user-agent"))
        raise HTTPException(status_code=401, detail="Invalid MFA code")

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await users_repo.update_fields(pg, user_id, {
                "mfa_enabled": True,
                "onboarding_status": None,
            })
    codes = await _mint_recovery_codes(user_id)
    await log_audit(db, user_id, user["email"], "mfa_enrollment_completed",
                    severity="info", outcome="success",
                    metadata={"recovery_code_count": len(codes)},
                    ip=get_client_ip(request),
                    user_agent=request.headers.get("user-agent"))
    await log_audit(db, user_id, user["email"], "onboarding_completed",
                    severity="info", outcome="success",
                    resource_type="user", resource_id=user_id,
                    ip=get_client_ip(request),
                    user_agent=request.headers.get("user-agent"))
    return {
        "ok": True,
        "mfa_enabled": True,
        "recovery_codes": codes,
        "recovery_codes_note": (
            "Store these codes securely. Each code works ONCE and is only "
            "displayed here. They are for MFA fallback, not password recovery."
        ),
        "must_relogin": True,
    }
