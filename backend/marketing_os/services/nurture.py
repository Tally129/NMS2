"""Deterministic Marketing OS Phase 8 nurture rules + config validation.

Pure/deterministic. No DB writes, no network, no external provider calls,
no automatic outreach, no AI, no PHI. Every scheduling decision, stop
decision, and offer/task mapping is derived from explicit configuration.

Configuration is validated fail-closed: malformed nested structures raise
``NurtureConfigError`` (routers translate to HTTP 422). Free-text fields
(subject/body_html/notes) are bounded in size and screened by the shared
marketing data-policy guard plus a lightweight content guard so they cannot
become an unrestricted PHI channel.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional

from marketing_os.services.lead_pipeline import LEAD_STAGES
from marketing_os.services.measurement import (
    MarketingDataPolicyError,
    assert_non_phi_marketing_payload,
)

# --------------------------------------------------------------------------- #
# Deterministic vocabularies
# --------------------------------------------------------------------------- #

TRIGGER_TYPES: tuple[str, ...] = (
    "manual",
    "lead_created",
    "status_changed",
    "appointment_requested",
    "no_show",
    "appointment_cancelled",
)

ACTION_TYPES: tuple[str, ...] = (
    "send_email",
    "create_task",
    "wait",
)

# Actions that materialize a queued row requiring human approval.
APPROVAL_ACTION_TYPES: frozenset[str] = frozenset({"send_email", "create_task"})

SEQUENCE_STATUSES: tuple[str, ...] = ("draft", "active", "archived")

ENROLLMENT_STATUSES: tuple[str, ...] = (
    "active",
    "completed",
    "stopped",
    "failed",
)

ACTION_STATUSES: tuple[str, ...] = (
    "scheduled",
    "pending_approval",
    "approved",
    "held",
    "skipped",
    "failed",
    "cancelled",
)

# Lead statuses that suppress / stop nurture by default.
DEFAULT_STOP_STATUSES: tuple[str, ...] = (
    "booked",
    "confirmed",
    "showed",
    "won",
    "lost",
)

# Task types create_task steps may schedule (subset of Lead CRM TASK_TYPES).
NURTURE_TASK_TYPES: frozenset[str] = frozenset({
    "call_lead",
    "email_lead",
    "review_qualification",
    "schedule_appointment",
    "confirm_appointment",
    "recover_no_show",
    "follow_up_later",
})

# Marketing-safe audience filter keys (bounded, non-clinical).
AUDIENCE_FILTER_KEYS: frozenset[str] = frozenset({
    "service_interest",
    "preferred_location",
    "urgency",
    "appointment_readiness",
})

EMAIL_CHANNEL = "email"
INTERNAL_CHANNEL = "internal"

# Bounds (fail-closed).
MAX_SLUG_LEN = 160
MAX_NAME_LEN = 200
MAX_STEP_KEY_LEN = 96
MAX_SUBJECT_LEN = 200
MAX_BODY_HTML_LEN = 20000
MAX_NOTES_LEN = 2000
MAX_TITLE_LEN = 200
MAX_DELAY_MINUTES = 525600  # 1 year
MAX_STEPS_PER_SEQUENCE = 50
MAX_STOP_STATUSES = 20
MAX_JSON_CHARS = 20000

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-_]{0,159}$")
_STEP_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9\-_]{0,95}$")

# Lightweight PHI content guard for free text (belt-and-suspenders on top of
# the structured marketing data-policy guard).
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(?:\+?\d[\s\-().]*){10,}")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


class NurtureConfigError(ValueError):
    """Raised when nurture configuration is malformed (fail-closed)."""


# --------------------------------------------------------------------------- #
# Primitive validators
# --------------------------------------------------------------------------- #

def _require_str(value: Any, field: str, *, max_len: int,
                 min_len: int = 1) -> str:
    if not isinstance(value, str):
        raise NurtureConfigError(f"{field} must be a string")
    cleaned = value.strip()
    if len(cleaned) < min_len:
        raise NurtureConfigError(f"{field} must not be empty")
    if len(cleaned) > max_len:
        raise NurtureConfigError(
            f"{field} exceeds max length {max_len}"
        )
    return cleaned


def _optional_str(value: Any, field: str, *, max_len: int) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise NurtureConfigError(f"{field} must be a string")
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > max_len:
        raise NurtureConfigError(f"{field} exceeds max length {max_len}")
    return cleaned


def _require_int(value: Any, field: str, *, minimum: int,
                 maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise NurtureConfigError(f"{field} must be an integer")
    if value < minimum or value > maximum:
        raise NurtureConfigError(
            f"{field} must be between {minimum} and {maximum}"
        )
    return value


def assert_marketing_safe_text(value: Optional[str], field: str) -> None:
    """Reject free text that looks like contact/PHI data."""
    if not value:
        return
    if _EMAIL_RE.search(value):
        raise MarketingDataPolicyError(
            f"{field} must not contain an email address"
        )
    if _PHONE_RE.search(value):
        raise MarketingDataPolicyError(
            f"{field} must not contain a phone number"
        )
    if _SSN_RE.search(value):
        raise MarketingDataPolicyError(
            f"{field} must not contain a national identifier"
        )


def _assert_bounded_json(value: Any, field: str) -> dict:
    """Validate a JSON object is a dict, non-PHI, and size-bounded."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise NurtureConfigError(f"{field} must be an object")
    payload = dict(value)
    # Structured PHI/contact-field guard (raises MarketingDataPolicyError).
    assert_non_phi_marketing_payload(payload)
    try:
        serialized = json.dumps(payload)
    except (TypeError, ValueError) as exc:
        raise NurtureConfigError(
            f"{field} must be JSON-serializable"
        ) from exc
    if len(serialized) > MAX_JSON_CHARS:
        raise NurtureConfigError(
            f"{field} exceeds max serialized size {MAX_JSON_CHARS}"
        )
    return payload


# --------------------------------------------------------------------------- #
# Sequence + step config validation
# --------------------------------------------------------------------------- #

def validate_slug(value: Any, field: str = "slug") -> str:
    cleaned = _require_str(value, field, max_len=MAX_SLUG_LEN)
    if not _SLUG_RE.match(cleaned):
        raise NurtureConfigError(
            f"{field} must be lowercase alphanumeric with - or _"
        )
    return cleaned


def validate_stop_statuses(value: Any) -> list[str]:
    if value is None:
        return list(DEFAULT_STOP_STATUSES)
    if not isinstance(value, list):
        raise NurtureConfigError("stop_on_statuses must be a list")
    if len(value) > MAX_STOP_STATUSES:
        raise NurtureConfigError("stop_on_statuses has too many entries")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise NurtureConfigError("stop_on_statuses entries must be strings")
        status = item.strip().lower()
        if status not in LEAD_STAGES:
            raise NurtureConfigError(f"unknown lead status: {item!r}")
        if status not in out:
            out.append(status)
    if not out:
        raise NurtureConfigError("stop_on_statuses must not be empty")
    return out


def validate_audience_config(value: Any) -> dict:
    payload = _assert_bounded_json(value, "audience_config")
    unknown = sorted(set(payload) - AUDIENCE_FILTER_KEYS)
    if unknown:
        raise NurtureConfigError(
            "unsupported audience_config fields: " + ", ".join(unknown)
        )
    normalized: dict[str, str] = {}
    for key, raw in payload.items():
        cleaned = _optional_str(raw, f"audience_config.{key}", max_len=160)
        if cleaned is not None:
            normalized[key] = cleaned
    return normalized


def validate_trigger(trigger_type: Any, trigger_config: Any) -> tuple[str, dict]:
    if not isinstance(trigger_type, str):
        raise NurtureConfigError("trigger_type must be a string")
    ttype = trigger_type.strip().lower()
    if ttype not in TRIGGER_TYPES:
        raise NurtureConfigError(f"unsupported trigger_type: {trigger_type!r}")
    config = _assert_bounded_json(trigger_config, "trigger_config")
    return ttype, config


def validate_sequence_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a create/update sequence payload fail-closed."""
    name = _require_str(payload.get("name"), "name", max_len=MAX_NAME_LEN)
    slug = validate_slug(payload.get("slug"))

    status = payload.get("status", "draft")
    if not isinstance(status, str) or status.strip().lower() not in \
            SEQUENCE_STATUSES:
        raise NurtureConfigError(f"invalid sequence status: {status!r}")

    ttype, tconfig = validate_trigger(
        payload.get("trigger_type", "manual"),
        payload.get("trigger_config", {}),
    )

    return {
        "name": name,
        "slug": slug,
        "status": status.strip().lower(),
        "trigger_type": ttype,
        "trigger_config": tconfig,
        "stop_on_statuses": validate_stop_statuses(
            payload.get("stop_on_statuses")
        ),
        "audience_config": validate_audience_config(
            payload.get("audience_config")
        ),
    }


def validate_step_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a single funnel/nurture step fail-closed."""
    step_key = _require_str(
        payload.get("step_key"), "step_key", max_len=MAX_STEP_KEY_LEN
    )
    if not _STEP_KEY_RE.match(step_key):
        raise NurtureConfigError(
            "step_key must be lowercase alphanumeric with - or _"
        )

    action_type = payload.get("action_type")
    if not isinstance(action_type, str) or \
            action_type.strip().lower() not in ACTION_TYPES:
        raise NurtureConfigError(f"invalid action_type: {action_type!r}")
    action_type = action_type.strip().lower()

    position = _require_int(
        payload.get("position", 0), "position", minimum=0, maximum=9999
    )
    delay_minutes = _require_int(
        payload.get("delay_minutes", 0),
        "delay_minutes",
        minimum=0,
        maximum=MAX_DELAY_MINUTES,
    )

    title = _optional_str(payload.get("title"), "title", max_len=MAX_TITLE_LEN)
    assert_marketing_safe_text(title, "title")

    config = _assert_bounded_json(payload.get("config", {}), "config")

    result: dict[str, Any] = {
        "step_key": step_key,
        "action_type": action_type,
        "position": position,
        "delay_minutes": delay_minutes,
        "title": title,
        "subject": None,
        "body_html": None,
        "channel": INTERNAL_CHANNEL,
        "config": config,
    }

    if action_type == "send_email":
        subject = _require_str(
            payload.get("subject"), "subject", max_len=MAX_SUBJECT_LEN
        )
        body_html = _require_str(
            payload.get("body_html"), "body_html", max_len=MAX_BODY_HTML_LEN
        )
        assert_marketing_safe_text(subject, "subject")
        assert_marketing_safe_text(body_html, "body_html")
        result["subject"] = subject
        result["body_html"] = body_html
        result["channel"] = EMAIL_CHANNEL

    elif action_type == "create_task":
        task_type = config.get("task_type")
        if not isinstance(task_type, str) or \
                task_type.strip().lower() not in NURTURE_TASK_TYPES:
            raise NurtureConfigError(
                f"create_task config.task_type invalid: {task_type!r}"
            )
        if "due_in_minutes" in config:
            _require_int(
                config["due_in_minutes"],
                "config.due_in_minutes",
                minimum=0,
                maximum=MAX_DELAY_MINUTES,
            )
        notes = _optional_str(
            config.get("notes"), "config.notes", max_len=MAX_NOTES_LEN
        )
        assert_marketing_safe_text(notes, "config.notes")
        result["channel"] = INTERNAL_CHANNEL

    # action_type == "wait": pure delay, no action materialized.
    return result


# --------------------------------------------------------------------------- #
# Deterministic scheduling + stop logic
# --------------------------------------------------------------------------- #

def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def ordered_steps(steps: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return steps deterministically ordered by (position, step_key)."""
    materialized = [dict(step) for step in steps]
    materialized.sort(
        key=lambda s: (int(s.get("position", 0)), str(s.get("step_key", "")))
    )
    return materialized


def scheduled_at_for(enrolled_at: datetime, step: Mapping[str, Any]) -> datetime:
    """Deterministic scheduled time = enrolled_at + cumulative delay."""
    delay = int(step.get("delay_minutes", 0) or 0)
    base = enrolled_at
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base + timedelta(minutes=delay)


def should_stop(lead_status: Any, stop_on_statuses: Iterable[str]) -> bool:
    """Deterministic suppression decision."""
    status = str(lead_status or "").strip().lower()
    stop = {str(s).strip().lower() for s in (stop_on_statuses or [])}
    return status in stop


def audience_matches(lead: Mapping[str, Any],
                     audience_config: Mapping[str, Any]) -> bool:
    """Deterministic audience filter. Empty config matches everything."""
    if not audience_config:
        return True
    for key, expected in audience_config.items():
        actual = lead.get(key)
        if actual is None:
            return False
        if str(actual).strip().lower() != str(expected).strip().lower():
            return False
    return True


def idempotency_key_for(enrollment_id: str, position: int) -> str:
    return f"{enrollment_id}:{int(position)}"
