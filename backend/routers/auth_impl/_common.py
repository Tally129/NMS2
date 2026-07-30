"""Shared imports + helpers for the split auth submodules.

Every route in `routers/auth.py` was moved into a topical file under
`routers/auth_impl/` during Session 1 of the PG migration. Behaviour is
identical to the pre-refactor code — this file merely centralises the
imports and helper functions so each submodule stays small.

DO NOT change persistence semantics here without a matching update to the
tests. This module still targets MongoDB. The runtime cutover to
PostgreSQL is a separate task (Session 2).
"""
# `import *` skips underscore-prefixed names by default; the auth submodules
# rely on `_email_hash`, `_hash_token`, `_create_session`, etc. Listing every
# public identifier we want re-exported here lets the topical modules do
# `from ._common import *` cleanly.
__all__ = [
    # stdlib re-exports
    "hashlib", "os", "secrets", "uuid", "datetime", "timedelta", "timezone",
    "Optional", "urlencode",
    # third-party re-exports
    "httpx", "Depends", "HTTPException", "Request", "Response", "RedirectResponse",
    # backend re-exports
    "get_client_ip", "log_audit",
    "decode_token", "generate_mfa_secret", "hash_password", "make_access_token",
    "make_refresh_token", "mfa_provisioning_uri", "validate_password_strength",
    "verify_mfa", "verify_password",
    "WORKFORCE_ROLES", "api", "db", "get_authenticated_user", "to_user_out",
    "LoginIn", "MfaVerifyIn", "PasswordChange", "ProfileUpdate", "RefreshIn",
    "TokenOut", "UserCreate", "UserOut", "new_id",
    "check_and_touch_session", "clear_refresh_cookie_kwargs",
    "enforce_active_session_limit", "hash_refresh_token", "issue_first_refresh",
    "list_active_sessions_sanitized", "refresh_cookie_kwargs",
    "revoke_all_user_sessions", "revoke_family", "rotate_refresh",
    "session_policy_for",
    # module-local constants + helpers
    "SESSION_TTL", "RESET_TOKEN_TTL_MIN",
    "_hipaa_mode", "_email_hash", "_hash_token", "_create_session",
    "_set_refresh_cookie", "_clear_refresh_cookie",
    "_revoke_all_sessions", "_revoke_session",
    "json_dumps_body",
]

import hashlib
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from audit import get_client_ip, log_audit
from auth_utils import (
    decode_token, generate_mfa_secret, hash_password, make_access_token,
    make_refresh_token, mfa_provisioning_uri, validate_password_strength,
    verify_mfa, verify_password,
)
from deps import (
    WORKFORCE_ROLES, api, db, get_authenticated_user, to_user_out,
)
from models import (
    LoginIn, MfaVerifyIn, PasswordChange, ProfileUpdate, RefreshIn, TokenOut,
    UserCreate, UserOut, new_id,
)
from sessions import (
    check_and_touch_session, clear_refresh_cookie_kwargs,
    enforce_active_session_limit, hash_refresh_token, issue_first_refresh,
    list_active_sessions_sanitized, refresh_cookie_kwargs,
    revoke_all_user_sessions, revoke_family, rotate_refresh, session_policy_for,
)

# --------------------------------------------------------------------------- #
# Session helpers                                                              #
# --------------------------------------------------------------------------- #
SESSION_TTL = timedelta(days=7)          # matches refresh lifetime
RESET_TOKEN_TTL_MIN = int(os.environ.get("PASSWORD_RESET_TOKEN_TTL_MIN", "30"))


def _hipaa_mode() -> bool:
    return os.environ.get("HIPAA_MODE", "false").lower() in {"1", "true", "yes", "on"}


def _email_hash(email: str) -> str:
    return hashlib.sha256((email or "").lower().strip().encode()).hexdigest()


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def _create_session(user_doc: dict, request: Request, *, mfa_satisfied: bool) -> tuple[str, str, str]:
    """Insert a new user_sessions row + first opaque refresh token.
    Returns (sid, family_id, raw_refresh_token). The RAW token is meant only
    for the immediate Set-Cookie header — it is never persisted plaintext.
    """
    now = datetime.now(timezone.utc)
    sid = new_id()
    family_id = new_id()
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent") if request else None
    role = user_doc.get("role") or "client"
    idle_min, absolute_lifetime = session_policy_for(role)
    absolute_expires_at = now + absolute_lifetime
    await db.user_sessions.insert_one({
        "id": sid,
        "user_id": user_doc["id"],
        "created_at": now,
        "last_used_at": now,
        # legacy field kept for backwards-compat readers
        "expires_at": absolute_expires_at,
        # Sprint 2: explicit policy fields (frozen at session creation)
        "idle_timeout_minutes": idle_min,
        "absolute_expires_at": absolute_expires_at,
        "revoked_at": None,
        "revoke_reason": None,
        "session_version": int(user_doc.get("session_version") or 1),
        "ip_first": ip,
        "ip_last": ip,
        "user_agent": ua,
        "mfa_satisfied_at": now if mfa_satisfied else None,
        "family_id": family_id,
    })
    raw = await issue_first_refresh(
        user_id=user_doc["id"], session_id=sid, family_id=family_id,
        expires_at=absolute_expires_at, ip=ip, user_agent=ua,
    )
    return sid, family_id, raw


def _set_refresh_cookie(resp: Response, raw: str) -> None:
    resp.set_cookie(value=raw, **refresh_cookie_kwargs())


def _clear_refresh_cookie(resp: Response) -> None:
    resp.set_cookie(value="", **clear_refresh_cookie_kwargs())


async def _revoke_all_sessions(user_id: str, reason: str) -> int:
    r = await revoke_all_user_sessions(user_id, reason)
    return r["sessions_revoked"]


async def _revoke_session(sid: str, reason: str) -> None:
    await db.user_sessions.update_one(
        {"id": sid, "revoked_at": None},
        {"$set": {"revoked_at": datetime.now(timezone.utc), "revoke_reason": reason}},
    )
    await db.refresh_tokens.update_many(
        {"session_id": sid, "revoked_at": None},
        {"$set": {"revoked_at": datetime.now(timezone.utc), "revoke_reason": reason}},
    )


def json_dumps_body(obj) -> bytes:
    """Datetime-aware JSON encoder used by every response that needs to
    set both a cookie AND a JSON body via a raw `Response`."""
    import json
    def _default(o):
        if isinstance(o, datetime): return o.isoformat()
        raise TypeError
    return json.dumps(obj, default=_default).encode("utf-8")
