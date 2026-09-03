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

from marketing_os.services.measurement import (
    find_prohibited_fields,
)


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


# Phase 14 execution payloads must remain both non-PHI and bounded.
# These are dry-run contracts only; live provider execution remains disabled.
EXECUTION_CREDENTIAL_FIELDS = frozenset({
    "password",
    "secret",
    "client_secret",
    "access_token",
    "refresh_token",
    "api_key",
    "private_key",
    "authorization",
    "bearer_token",
    "credential",
    "credentials",
})


ACTION_PAYLOAD_FIELDS = {
    "campaign.pause": frozenset({
        "reason",
    }),
    "campaign.resume": frozenset({
        "reason",
    }),
    "campaign.create": frozenset({
        "name",
        "objective",
        "status",
        "daily_budget",
        "total_budget",
        "currency",
        "start_date",
        "end_date",
        "reason",
    }),
    "budget.update": frozenset({
        "amount",
        "daily_budget",
        "total_budget",
        "currency",
        "reason",
    }),
    "ad.create": frozenset({
        "name",
        "headline",
        "description",
        "destination_url",
        "status",
        "creative_id",
        "campaign_id",
        "ad_group_id",
        "reason",
    }),
    "ad.update": frozenset({
        "name",
        "headline",
        "description",
        "destination_url",
        "status",
        "creative_id",
        "campaign_id",
        "ad_group_id",
        "reason",
    }),
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


def _normalized_payload_key(value: Any) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )


def _find_execution_credentials(
    value: Any,
    *,
    path: str = "",
) -> list[str]:
    violations: list[str] = []

    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = _normalized_payload_key(raw_key)

            child_path = (
                f"{path}.{key}"
                if path
                else key
            )

            if key in EXECUTION_CREDENTIAL_FIELDS:
                violations.append(child_path)

            violations.extend(
                _find_execution_credentials(
                    child,
                    path=child_path,
                )
            )

    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            child_path = (
                f"{path}[{index}]"
                if path
                else f"[{index}]"
            )

            violations.extend(
                _find_execution_credentials(
                    child,
                    path=child_path,
                )
            )

    return violations


def validate_execution_payload(
    *,
    action_type: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    action_type = str(
        action_type or ""
    ).strip().lower()

    errors: list[str] = []

    if not isinstance(payload, Mapping):
        return {
            "valid": False,
            "errors": ["invalid_payload"],
            "prohibited_fields": [],
            "credential_fields": [],
            "unexpected_fields": [],
        }

    prohibited = sorted(
        set(find_prohibited_fields(payload))
    )

    credentials = sorted(
        set(_find_execution_credentials(payload))
    )

    if prohibited:
        errors.append("prohibited_marketing_fields")

    if credentials:
        errors.append("credential_fields_prohibited")

    allowed_fields = ACTION_PAYLOAD_FIELDS.get(
        action_type
    )

    unexpected: list[str] = []

    if allowed_fields is not None:
        for raw_key in payload.keys():
            key = _normalized_payload_key(raw_key)

            if key not in allowed_fields:
                unexpected.append(key)

    unexpected = sorted(set(unexpected))

    if unexpected:
        errors.append("unexpected_payload_fields")

    return {
        "valid": not errors,
        "errors": errors,
        "prohibited_fields": prohibited,
        "credential_fields": credentials,
        "unexpected_fields": unexpected,
    }


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

    payload_validation = validate_execution_payload(
        action_type=action_type,
        payload=payload,
    )

    if not payload_validation["valid"]:
        errors.extend(
            payload_validation["errors"]
        )

    return {
        "valid": not errors,
        "errors": errors,
        "provider": provider,
        "action_type": action_type,
        "payload_policy": payload_validation,
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
    "ACTION_PAYLOAD_FIELDS",
    "EXECUTION_CREDENTIAL_FIELDS",
    "validate_execution_payload",
    "validate_execution_request",
    "evaluate_execution_policy",
    "next_request_status",
]
