"""
Centralized audit event schema with tamper-evident hash chaining.

Session 2b: audit rows moved from MongoDB to PostgreSQL. The `db` argument
retained for API compatibility (callers pass Motor's `db` handle) is now
ignored — every write goes through the `repositories.audit` PG layer. Chain
integrity is guarded by a PostgreSQL transaction-scoped advisory lock so
concurrent inserts across workers still form a valid chain.

Every audit row includes:
  id            — unique row id (uuid)
  ts            — UTC timestamp
  user_id       — actor's user id (None for anonymous)
  user_email    — actor's email (retained; not PHI on its own here)
  action        — namespaced dotted string ("auth.login", "note.finalize", …)
  resource_type — subject noun ("client", "note", "file", …) or None
  resource_id   — subject id or None
  severity      — "info" | "warning" | "high" | "critical"
  outcome       — "allow" | "deny" | "success" | "failure" | "error"
  ip            — client IP if resolvable
  user_agent    — UA header
  metadata      — arbitrary dict; automatically redacted before write
  prev_hash     — SHA-256(prev_row canonical JSON), first row = "GENESIS"
  hash          — SHA-256 of this row (before hash field), enabling chain
                  verification

Required actions (in `REQUIRED_ACTIONS`) MUST land in the audit log. If the
insert fails, `log_audit` raises — routers relying on it will fail-closed on
the operation.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("nms.audit")

REQUIRED_ACTIONS = frozenset({
    "auth.login", "auth.login_fail", "auth.logout", "auth.logout_all",
    "auth.refresh_reuse_detected", "auth.password_change",
    "auth.password_reset_request", "auth.password_reset",
    "auth.mfa_enable", "auth.mfa_disable_denied",
    "admin.create_user", "admin.update_role", "admin.deactivate_user",
    "admin.session_revoke", "admin.session_revoke_all",
    "breakglass.activate", "breakglass.expire", "breakglass.revoke",
    "note.finalize", "note.amend", "file.delete",
})

_SENSITIVE_KEYS = re.compile(
    r"(password|token|secret|cookie|otp|totp|code|mfa_secret|refresh|"
    r"access_token|authorization)",
    re.IGNORECASE,
)
_OPAQUE_TOKEN = re.compile(r"^[A-Za-z0-9_\-]{24,}$")


def _redact(value: Any, key: Optional[str] = None) -> Any:
    if isinstance(value, dict):
        return {k: _redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    if isinstance(value, str):
        if key and _SENSITIVE_KEYS.search(key):
            return "[REDACTED]"
        if isinstance(value, str) and len(value) >= 32 and _OPAQUE_TOKEN.match(value):
            return "[REDACTED-OPAQUE]"
        return value
    return value


def _stringify(value: Any) -> Any:
    if isinstance(value, datetime):
        v = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        v = v.astimezone(timezone.utc)
        us = v.microsecond
        ms = (us // 1000) * 1000
        v = v.replace(microsecond=ms)
        return v.isoformat(timespec="milliseconds")
    return value


def _canonical(row: Dict[str, Any]) -> str:
    def default(o):
        return _stringify(o)

    def walk(obj):
        if isinstance(obj, dict):
            return {k: walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [walk(v) for v in obj]
        return _stringify(obj)
    return json.dumps(walk(row), sort_keys=True, separators=(",", ":"), default=default)


async def log_audit(
    db,  # noqa: ARG001 — kept for signature compat, ignored (Session 2b)
    user_id: Optional[str],
    user_email: Optional[str],
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    severity: str = "info",
    outcome: str = "success",
):
    """Write one audit row to PostgreSQL. Raises `RuntimeError` when a REQUIRED
    action fails to persist; best-effort otherwise. The `db` parameter is
    accepted only for backward compatibility with pre-migration callers."""
    # Local imports keep audit importable even if PG bootstrap fails at
    # module-load time (e.g., during Alembic autogenerate).
    from postgres_db import AsyncSessionLocal
    from repositories import audit as audit_repo

    redacted_meta = _redact(metadata or {})
    now = datetime.now(timezone.utc)
    row: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "ts": now,
        "user_id": user_id,
        "user_email": user_email,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "severity": severity if severity in {"info", "warning", "high", "critical"} else "info",
        "outcome": outcome if outcome in {"allow", "deny", "success", "failure", "error"} else "success",
        "ip": ip,
        "user_agent": user_agent,
        "metadata": redacted_meta,
    }

    required = action in REQUIRED_ACTIONS
    try:
        async with AsyncSessionLocal() as pg:
            async with pg.begin():
                await audit_repo.acquire_chain_lock(pg)
                row["prev_hash"] = await audit_repo.prev_hash(pg)
                row["hash"] = hashlib.sha256(_canonical(row).encode("utf-8")).hexdigest()
                await audit_repo.insert(pg, row)
                if row["severity"] in {"high", "critical"}:
                    try:
                        await audit_repo.insert_security_event(pg, {
                            "id": str(uuid.uuid4()), "ts": now, "audit_id": row["id"],
                            "action": action, "severity": row["severity"],
                            "outcome": row["outcome"], "user_id": user_id,
                            "resource_type": resource_type, "resource_id": resource_id,
                        })
                    except Exception:
                        # Alerting is best-effort; must not break the audit path.
                        pass
    except Exception as e:
        logger.error("audit insert failed action=%s required=%s err=%s",
                     action, required, type(e).__name__)
        if required:
            raise RuntimeError(f"required audit event '{action}' failed to persist") from e
        return None
    return row


def get_client_ip(request) -> Optional[str]:
    try:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
        return request.client.host if request.client else None
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Chain verification (admin diagnostic) — reads from PostgreSQL now.          #
# --------------------------------------------------------------------------- #
async def verify_audit_chain(db, limit: int = 5000) -> Dict[str, Any]:  # noqa: ARG001
    """Verify each audit row's self-hash. Same per-row semantics as the Mongo
    implementation, but reads from PostgreSQL via `repositories.audit`."""
    from postgres_db import AsyncSessionLocal
    from repositories import audit as audit_repo

    async with AsyncSessionLocal() as pg:
        rows = await audit_repo.list_ordered(pg, limit=limit)
    first_break = None
    checked = 0
    for r in rows:
        row_copy = {k: v for k, v in r.items() if k not in {"seq", "hash"}}
        expected = hashlib.sha256(_canonical(row_copy).encode("utf-8")).hexdigest()
        if r.get("hash") != expected:
            first_break = r.get("id")
            break
        checked += 1
    return {"ok": first_break is None, "checked": checked, "first_break": first_break}
