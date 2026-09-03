"""Phase 14 controlled execution policy.

Pure deterministic policy logic.

No provider calls.
No DB access.
No network access.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


SUPPORTED_PROVIDERS = {
    "google_ads",
    "meta_ads",
    "microsoft_ads",
}

ALLOWED_ACTIONS = {
    "campaign.pause",
    "campaign.resume",
    "campaign.create",
    "budget.update",
    "ad.create",
    "ad.update",
}

TERMINAL_STATUSES = {
    "executed",
    "rejected",
    "cancelled",
    "failed",
}


def canonical_provider(value: Any) -> str:
    provider = str(value or "").strip().lower()

    aliases = {
        "google": "google_ads",
        "googleads": "google_ads",
        "meta": "meta_ads",
        "facebook": "meta_ads",
        "facebook_ads": "meta_ads",
        "microsoft": "microsoft_ads",
        "bing": "microsoft_ads",
        "bing_ads": "microsoft_ads",
    }

    return aliases.get(provider, provider)


def build_idempotency_key(
    *,
    provider: str,
    action_type: str,
    target_type: str,
    target_id: str | None,
    payload: Mapping[str, Any],
) -> str:
    normalized = {
        "provider": canonical_provider(provider),
        "action_type": str(action_type or "").strip().lower(),
        "target_type": str(target_type or "").strip().lower(),
        "target_id": str(target_id or "").strip(),
        "payload": dict(payload or {}),
    }

    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


def validate_execution_request(
    *,
    provider: str,
    action_type: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    provider = canonical_provider(provider)
    action_type = str(action_type or "").strip().lower()

    errors = []

    if provider not in SUPPORTED_PROVIDERS:
        errors.append("unsupported_provider")

    if action_type not in ALLOWED_ACTIONS:
        errors.append("unsupported_action")

    if not isinstance(payload, Mapping):
        errors.append("invalid_payload")

    return {
        "valid": not errors,
        "errors": errors,
        "provider": provider,
        "action_type": action_type,
    }


def evaluate_execution_policy(
    *,
    provider: str,
    action_type: str,
    request_status: str,
    dry_run: bool,
    provider_enabled: bool,
    provider_dry_run_only: bool,
    provider_human_approval_required: bool,
    approved: bool,
    provider_allowed_actions: Any = None,
) -> dict[str, Any]:
    provider = canonical_provider(provider)
    action_type = str(action_type or "").strip().lower()
    request_status = str(request_status or "").strip().lower()

    validation = validate_execution_request(
        provider=provider,
        action_type=action_type,
        payload={},
    )

    reasons = []

    if not validation["valid"]:
        reasons.extend(validation["errors"])

    if request_status in TERMINAL_STATUSES:
        reasons.append("terminal_request_status")

    if not provider_enabled:
        reasons.append("provider_execution_disabled")

    if provider_dry_run_only and not dry_run:
        reasons.append("provider_dry_run_only")

    # Global Marketing OS invariant:
    # provider policy may never bypass human approval.
    if not approved:
        reasons.append("human_approval_required")

    allowed_actions = {
        str(value or "").strip().lower()
        for value in (
            provider_allowed_actions
            if isinstance(provider_allowed_actions, (list, tuple, set))
            else []
        )
        if str(value or "").strip()
    }

    if action_type not in allowed_actions:
        reasons.append("action_not_allowed_by_provider_policy")

    # Phase 14 safety baseline:
    # real execution remains impossible until adapters explicitly enable it.
    if not dry_run:
        reasons.append("live_execution_not_enabled")

    return {
        "allowed": not reasons,
        "reasons": reasons,
        "provider": provider,
        "action_type": action_type,
        "dry_run": bool(dry_run),
        "human_approval_required": True,
        "live_execution_enabled": False,
    }


def next_request_status(
    current_status: str,
    event: str,
) -> str:
    current = str(current_status or "draft").lower()
    event = str(event or "").lower()

    transitions = {
        ("draft", "submit"): "pending_approval",
        ("pending_approval", "approve"): "approved",
        ("pending_approval", "reject"): "rejected",
        ("approved", "execute"): "executing",
        ("executing", "succeed"): "executed",
        ("executing", "fail"): "failed",
        ("draft", "cancel"): "cancelled",
        ("pending_approval", "cancel"): "cancelled",
        ("approved", "cancel"): "cancelled",
    }

    result = transitions.get((current, event))

    if result is None:
        raise ValueError(
            f"invalid_execution_transition:{current}:{event}"
        )

    return result


__all__ = [
    "SUPPORTED_PROVIDERS",
    "ALLOWED_ACTIONS",
    "TERMINAL_STATUSES",
    "canonical_provider",
    "build_idempotency_key",
    "validate_execution_request",
    "evaluate_execution_policy",
    "next_request_status",
]
