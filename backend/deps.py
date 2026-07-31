"""
Shared FastAPI singletons + auth dependencies.

Session 2b (PostgreSQL runtime cutover): user + session persistence for
authentication now lives in PostgreSQL. The auth surface of this module
does NOT import Motor. The MongoDB `db` handle used by non-auth business
routers has moved to `mongo_db.py`; we re-export it here so existing
`from deps import db` callers keep working during the transition.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from audit import get_client_ip, log_audit  # noqa: F401 (re-exported for routers)
from auth_utils import (
    assert_valid_secret, decode_token, get_jwt_audience, get_jwt_issuer,
)
from mongo_db import close_mongo, db, fs_bucket  # noqa: F401 (re-exported)
from postgres_db import AsyncSessionLocal
from repositories import user_sessions as sessions_repo
from repositories import users as users_repo

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")


# --------------------------------------------------------------------------- #
# Startup configuration assertion                                              #
# --------------------------------------------------------------------------- #
_HIPAA_MODE = os.environ.get("HIPAA_MODE", "false").lower() in {"1", "true", "yes", "on"}

assert_valid_secret()
get_jwt_issuer()
get_jwt_audience()

WORKFORCE_ROLES = {"admin", "practitioner", "staff", "front_desk", "frontdesk", "medical_assistant", "auditor"}


# --------------------------------------------------------------------------- #
# FastAPI plumbing                                                             #
# --------------------------------------------------------------------------- #
api = APIRouter(prefix="/api")
bearer = HTTPBearer(auto_error=False)

logger = logging.getLogger("nms.emr")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


# --------------------------------------------------------------------------- #
# Utility helpers                                                              #
# --------------------------------------------------------------------------- #
def _strip_id(doc):
    if doc is None:
        return None
    d = dict(doc)
    d.pop("_id", None)
    return d


def to_user_out(user) -> dict:
    if user is None:
        return None
    return {
        "id": user["id"],
        "email": user["email"],
        "full_name": user.get("full_name", ""),
        "phone": user.get("phone"),
        "role": user.get("role", "client"),
        "mfa_enabled": user.get("mfa_enabled", False),
        "is_active": user.get("is_active", True),
        "must_change_password": user.get("must_change_password", False),
        "created_at": user.get("created_at"),
        "last_login_at": user.get("last_login_at"),
    }


async def _resolve_self_client(user) -> Optional[dict]:
    """Client business data reads from PostgreSQL (Phase 3.1a landed the
    data + Phase 3.1b partial adds the repository). Non-auth routers that
    still call `db.clients.find_one(...)` will migrate individually in the
    remainder of Phase 3.1b."""
    from repositories import clients as clients_repo  # local import to avoid boot cycle
    async with AsyncSessionLocal() as pg:
        return await clients_repo.get_by_user_id(pg, user["id"])


# --------------------------------------------------------------------------- #
# Session 2b: decode + session-revocation check via PostgreSQL                #
# --------------------------------------------------------------------------- #
async def get_authenticated_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
):
    """Verify the bearer JWT + session revocation + session_version + idle/
    absolute timeouts. Reads the user + session rows from PostgreSQL."""
    if creds is None:
        raise HTTPException(status_code=401, detail="Missing auth token")

    payload = decode_token(creds.credentials, expected_type="access")

    sid = payload.get("sid")
    if not sid:
        raise HTTPException(status_code=401, detail="Session binding required; please sign in again.")

    async with AsyncSessionLocal() as pg:
        session_row = await sessions_repo.get(pg, sid)
        if not session_row:
            raise HTTPException(status_code=401, detail="Session not found")

    # Order: revoked → absolute → idle → status → session_version → THEN touch.
    from sessions import check_and_touch_session
    reason = await check_and_touch_session(session_row, get_client_ip(request))
    if reason:
        # Persist the revocation reason on the row that triggered the failure.
        try:
            async with AsyncSessionLocal() as pg:
                async with pg.begin():
                    await sessions_repo.revoke_by_id(pg, sid, reason)
        except Exception:
            pass
        raise HTTPException(status_code=401, detail=reason)

    async with AsyncSessionLocal() as pg:
        user = await users_repo.get_by_id(pg, payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account disabled")

    token_sv = payload.get("sv")
    if token_sv is not None and int(user.get("session_version") or 1) > int(token_sv):
        raise HTTPException(status_code=401, detail="session_version_stale")

    user["_session"] = session_row
    return user


get_current_user = get_authenticated_user


async def require_workforce_mfa(user=Depends(get_authenticated_user)):
    role = user.get("role")
    if role in WORKFORCE_ROLES and not user.get("mfa_bypass"):
        if not user.get("mfa_enabled"):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "must_enroll_mfa",
                    "message": "Workforce accounts must complete MFA enrollment before accessing PHI.",
                    "next": {"setup": "/api/auth/mfa/setup", "verify": "/api/auth/mfa/verify"},
                },
            )
        sess = user.get("_session") or {}
        if not sess.get("mfa_satisfied_at"):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "mfa_reauth_required",
                    "message": "MFA verification required for this session.",
                },
            )
    return user


def require_roles(*roles):
    async def dep(request: Request, user=Depends(require_workforce_mfa)):
        if user.get("must_change_password"):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "password_change_required",
                    "message": "Change your temporary password before continuing.",
                    "next": {"change_password": "/api/auth/change-password"},
                },
            )
        role = user.get("role")
        if role == "auditor" and request.method == "GET":
            try:
                await log_audit(
                    db, user["id"], user["email"], "auditor.break_glass_read",
                    resource_type="endpoint", resource_id=request.url.path,
                    severity="high", outcome="allow",
                    metadata={"emergency": True, "method": request.method},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"),
                )
            except Exception:
                pass
            return user
        if role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return dep
