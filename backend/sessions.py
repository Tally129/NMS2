"""
Session lifecycle helpers — Session 2b PostgreSQL runtime cutover.

Central home for:
  * `revoke_all_user_sessions()` — single choke-point used by password change /
    reset, MFA disable/reset, role change, account disable, admin revoke,
    logout-all, and suspected-compromise flows.
  * Opaque refresh-token issue + atomic rotation with concurrency grace.
  * Session touch (idle-timeout aware, throttled to 1 write per minute).

Every persistence call now flows through the SQLAlchemy repositories in
`repositories/*`. This module opens its own PG transaction per call so
individual routers keep their pre-migration ergonomics ("await X" without
managing sessions).

None of this file's helpers ever store or log a raw refresh token — only
`sha256(raw_token)` is persisted.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from postgres_db import AsyncSessionLocal
from repositories import refresh_tokens as tokens_repo
from repositories import user_sessions as sessions_repo
from repositories import users as users_repo

REFRESH_TTL_DAYS = int(os.environ.get("REFRESH_TOKEN_TTL_DAYS", "7"))
REFRESH_GRACE_SECONDS = int(os.environ.get("REFRESH_CONCURRENCY_GRACE_SECONDS", "10"))
WORKFORCE_IDLE_TIMEOUT_MIN = int(os.environ.get("WORKFORCE_IDLE_TIMEOUT_MIN", "15"))
WORKFORCE_ABSOLUTE_HOURS = int(os.environ.get("WORKFORCE_ABSOLUTE_SESSION_HOURS", "12"))
CLIENT_IDLE_TIMEOUT_MIN = int(os.environ.get("CLIENT_IDLE_TIMEOUT_MIN", "60"))
CLIENT_ABSOLUTE_DAYS = int(os.environ.get("CLIENT_ABSOLUTE_SESSION_DAYS", "7"))
MAX_ACTIVE_WORKFORCE_SESSIONS = int(os.environ.get("MAX_ACTIVE_WORKFORCE_SESSIONS", "5"))
MAX_ACTIVE_CLIENT_SESSIONS = int(os.environ.get("MAX_ACTIVE_CLIENT_SESSIONS", "10"))
TOUCH_THROTTLE_SECONDS = 60
WORKFORCE_ROLES = {"admin", "practitioner", "staff", "front_desk", "frontdesk", "medical_assistant", "auditor"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_opaque_refresh_token() -> str:
    return secrets.token_urlsafe(32)


# --------------------------------------------------------------------------- #
# Session policy resolution                                                    #
# --------------------------------------------------------------------------- #
def session_policy_for(role: str) -> Tuple[int, timedelta]:
    if role in WORKFORCE_ROLES:
        return WORKFORCE_IDLE_TIMEOUT_MIN, timedelta(hours=WORKFORCE_ABSOLUTE_HOURS)
    return CLIENT_IDLE_TIMEOUT_MIN, timedelta(days=CLIENT_ABSOLUTE_DAYS)


def max_active_sessions_for(role: str) -> int:
    return MAX_ACTIVE_WORKFORCE_SESSIONS if role in WORKFORCE_ROLES else MAX_ACTIVE_CLIENT_SESSIONS


# --------------------------------------------------------------------------- #
# Central revocation choke-point                                               #
# --------------------------------------------------------------------------- #
async def revoke_all_user_sessions(user_id: str, reason: str,
                                    also_bump_session_version: bool = True) -> dict:
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            sessions_revoked = await sessions_repo.revoke_all_for_user(pg, user_id, reason)
            tokens_revoked = await tokens_repo.revoke_all_for_user(pg, user_id, reason)
            if also_bump_session_version:
                await users_repo.bump_session_version(pg, user_id)
    return {"sessions_revoked": sessions_revoked, "tokens_revoked": tokens_revoked}


async def revoke_family(family_id: str, reason: str) -> int:
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            return await tokens_repo.revoke_family(pg, family_id, reason)


# --------------------------------------------------------------------------- #
# Session creation with active-limit enforcement                               #
# --------------------------------------------------------------------------- #
async def enforce_active_session_limit(user: dict) -> dict:
    role = user.get("role") or "client"
    limit = max_active_sessions_for(role)
    async with AsyncSessionLocal() as pg:
        active_count = await sessions_repo.count_active(pg, user["id"])
        if active_count < limit:
            return {"action": "none", "active_count": active_count, "limit": limit}
        if role in WORKFORCE_ROLES:
            return {"action": "reject_workforce", "active_count": active_count, "limit": limit}
        # Client: evict the oldest session
        oldest = await sessions_repo.oldest_active(pg, user["id"])
        if oldest:
            async with pg.begin():
                await sessions_repo.revoke_by_id(pg, oldest["id"], "client_evicted_oldest")
                await tokens_repo.revoke_by_session(pg, oldest["id"], "session_evicted")
        return {"action": "evicted_oldest", "evicted_session_id": (oldest or {}).get("id")}


async def list_active_sessions_sanitized(user_id: str, current_sid: Optional[str] = None) -> list:
    async with AsyncSessionLocal() as pg:
        sessions = await sessions_repo.list_active_for_user(pg, user_id, limit=20)
    out = []
    for s in sessions:
        ua = s.get("user_agent") or ""
        label = "Unknown device"
        low = ua.lower()
        if "iphone" in low or "ipad" in low:
            label = "iPhone / iPad"
        elif "android" in low:
            label = "Android device"
        elif "macintosh" in low:
            label = "Mac"
        elif "windows" in low:
            label = "Windows"
        elif "linux" in low:
            label = "Linux"
        if "chrome" in low:
            label += " · Chrome"
        elif "firefox" in low:
            label += " · Firefox"
        elif "safari" in low:
            label += " · Safari"
        last = _as_utc(s.get("last_used_at")) or _as_utc(s.get("created_at"))
        out.append({
            "session_id": s["id"],
            "device_label": label,
            "last_active_at": last.isoformat() if last else None,
            "created_at": _as_utc(s["created_at"]).isoformat(),
            "is_current": s["id"] == current_sid,
        })
    return out


# --------------------------------------------------------------------------- #
# Refresh-token family — issue + atomic rotate with concurrency grace          #
# --------------------------------------------------------------------------- #
async def issue_first_refresh(user_id: str, session_id: str,
                              family_id: str,
                              expires_at: datetime,
                              ip: Optional[str],
                              user_agent: Optional[str]) -> str:
    raw = generate_opaque_refresh_token()
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await tokens_repo.insert(
                pg,
                id=secrets.token_hex(16),
                token_hash=hash_refresh_token(raw),
                session_id=session_id,
                user_id=user_id,
                family_id=family_id,
                generation=0,
                parent_token_id=None,
                created_at=now(),
                last_used_at=None,
                expires_at=expires_at,
                used_at=None,
                replaced_by_id=None,
                revoked_at=None,
                revoke_reason=None,
                ip_created=ip,
                ip_last_used=None,
                user_agent_created=user_agent,
            )
    return raw


class RefreshOutcome:
    def __init__(self, kind: str, **extra):
        self.kind = kind  # 'rotated' | 'concurrency_grace' | 'reuse_detected' | 'unknown'
        self.__dict__.update(extra)


async def rotate_refresh(raw_token: str, ip: Optional[str],
                         user_agent: Optional[str]) -> RefreshOutcome:
    ts = now()
    token_hash = hash_refresh_token(raw_token)

    async with AsyncSessionLocal() as pg:
        # Step 1: attempt to atomically claim the token.
        async with pg.begin():
            claimed = await tokens_repo.claim_for_rotation(pg, token_hash, ts, ip)
            if claimed is not None:
                session_row = await sessions_repo.get(pg, claimed["session_id"])
                if not session_row or session_row.get("revoked_at") is not None:
                    await tokens_repo.revoke_family(pg, claimed["family_id"], "session_gone")
                    return RefreshOutcome("unknown")

                abs_exp = _as_utc(session_row.get("absolute_expires_at"))
                soft_exp = ts + timedelta(days=REFRESH_TTL_DAYS)
                expires_at = min(soft_exp, abs_exp) if abs_exp else soft_exp

                successor_raw = generate_opaque_refresh_token()
                successor_id = secrets.token_hex(16)
                await tokens_repo.insert(
                    pg,
                    id=successor_id,
                    token_hash=hash_refresh_token(successor_raw),
                    session_id=claimed["session_id"],
                    user_id=claimed["user_id"],
                    family_id=claimed["family_id"],
                    generation=claimed["generation"] + 1,
                    parent_token_id=claimed["id"],
                    created_at=ts,
                    last_used_at=None,
                    expires_at=expires_at,
                    used_at=None,
                    replaced_by_id=None,
                    revoked_at=None,
                    revoke_reason=None,
                    ip_created=ip,
                    ip_last_used=None,
                    user_agent_created=user_agent,
                )
                await tokens_repo.set_replaced_by(pg, claimed["id"], successor_id)
                return RefreshOutcome(
                    "rotated", raw=successor_raw,
                    session_id=claimed["session_id"], user_id=claimed["user_id"],
                    family_id=claimed["family_id"], expires_at=expires_at,
                )

        # Step 2: token wasn't claimable — inspect its state.
        prior = await tokens_repo.get_by_hash(pg, token_hash)
        if not prior:
            return RefreshOutcome("unknown")

        if prior.get("revoked_at") is not None:
            async with pg.begin():
                await tokens_repo.revoke_family(pg, prior["family_id"], "reuse_after_revoke")
                await sessions_repo.revoke_by_id(pg, prior["session_id"], "refresh_reuse_detected")
            return RefreshOutcome("reuse_detected", family_id=prior["family_id"],
                                  session_id=prior["session_id"], user_id=prior["user_id"])

        used_at = _as_utc(prior["used_at"])
        within_grace = used_at is not None and (ts - used_at).total_seconds() <= REFRESH_GRACE_SECONDS
        same_ua = (prior.get("user_agent_created") or "") == (user_agent or "")

        if within_grace and same_ua:
            successor_present = False
            if prior.get("replaced_by_id"):
                async with pg.begin():
                    from sqlalchemy import select
                    from postgres_models import RefreshToken
                    stmt = select(RefreshToken).where(RefreshToken.id == prior["replaced_by_id"])
                    successor_present = (await pg.execute(stmt)).scalar_one_or_none() is not None
            return RefreshOutcome("concurrency_grace",
                                  family_id=prior["family_id"],
                                  session_id=prior["session_id"],
                                  user_id=prior["user_id"],
                                  successor_present=successor_present)

        async with pg.begin():
            await tokens_repo.revoke_family(pg, prior["family_id"], "reuse_detected")
            await sessions_repo.revoke_by_id(pg, prior["session_id"], "refresh_reuse_detected")
        return RefreshOutcome("reuse_detected", family_id=prior["family_id"],
                              session_id=prior["session_id"], user_id=prior["user_id"])


# --------------------------------------------------------------------------- #
# Session touch — evaluate idle BEFORE writing, throttle writes                #
# --------------------------------------------------------------------------- #
async def check_and_touch_session(session: dict, ip: Optional[str]) -> Optional[str]:
    ts = now()
    if session.get("revoked_at") is not None:
        return "session_revoked"

    abs_exp = _as_utc(session.get("absolute_expires_at"))
    if abs_exp and abs_exp < ts:
        return "session_absolute_expired"

    idle_min = int(session.get("idle_timeout_minutes") or WORKFORCE_IDLE_TIMEOUT_MIN)
    last_used = _as_utc(session.get("last_used_at") or session.get("created_at"))
    if last_used and (ts - last_used) > timedelta(minutes=idle_min):
        return "session_idle_expired"

    if not last_used or (ts - last_used).total_seconds() > TOUCH_THROTTLE_SECONDS:
        try:
            async with AsyncSessionLocal() as pg:
                async with pg.begin():
                    await sessions_repo.touch(pg, session["id"], ip)
        except Exception:
            pass
    return None


# --------------------------------------------------------------------------- #
# Cookie settings                                                              #
# --------------------------------------------------------------------------- #
def refresh_cookie_kwargs() -> dict:
    hipaa = os.environ.get("HIPAA_MODE", "false").lower() in {"1", "true", "yes", "on"}
    return {
        "key": "nms_rt",
        "httponly": True,
        "secure": hipaa,
        "samesite": "lax",
        "path": "/api/auth/refresh",
        "max_age": REFRESH_TTL_DAYS * 86400,
    }


def clear_refresh_cookie_kwargs() -> dict:
    kw = refresh_cookie_kwargs()
    kw.update({"max_age": 0, "expires": 0})
    return kw
