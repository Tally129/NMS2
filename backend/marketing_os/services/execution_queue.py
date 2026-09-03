"""Phase 14 approval queue helpers.

Live execution remains hard-disabled.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from marketing_os.services.execution_policy import (
    build_idempotency_key,
    canonical_provider,
    evaluate_execution_policy,
    next_request_status,
    validate_execution_request,
    validate_execution_target,
)
from marketing_os.services.provider_adapters import (
    get_provider_adapter,
)


def prepare_execution_request(
    *,
    provider: str,
    action_type: str,
    target_type: str,
    target_id: str | None,
    payload: Mapping[str, Any],
    dry_run: bool = True,
) -> dict[str, Any]:
    provider = canonical_provider(provider)

    validation = validate_execution_request(
        provider=provider,
        action_type=action_type,
        payload=payload,
    )

    target_validation = validate_execution_target(
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
    )

    combined_errors = list(
        validation["errors"]
    )

    if not target_validation["valid"]:
        combined_errors.extend(
            target_validation["errors"]
        )

    if combined_errors:
        return {
            "valid": False,
            "errors": combined_errors,
            "payload_policy": (
                validation.get("payload_policy")
                or {}
            ),
            "target_policy": target_validation,
        }

    target_type = target_validation[
        "target_type"
    ]
    target_id = target_validation[
        "target_id"
    ]

    idempotency_key = build_idempotency_key(
        provider=provider,
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
        payload=payload,
    )

    return {
        "valid": True,
        "request": {
            "id": uuid.uuid4().hex,
            "provider": provider,
            "action_type": validation["action_type"],
            "target_type": target_type,
            "target_id": target_id,
            "request_payload": dict(payload or {}),
            "idempotency_key": idempotency_key,
            "dry_run": bool(dry_run),
            "status": "draft",
            "human_approval_required": True,
        },
    }


def submit_for_approval(
    request: Mapping[str, Any],
) -> dict[str, Any]:
    result = dict(request)

    result["status"] = next_request_status(
        result.get("status") or "draft",
        "submit",
    )

    return result


def decide_request(
    request: Mapping[str, Any],
    *,
    decision: str,
) -> dict[str, Any]:
    result = dict(request)

    decision = str(decision or "").strip().lower()

    if decision not in {"approve", "reject"}:
        raise ValueError("invalid_approval_decision")

    result["status"] = next_request_status(
        result.get("status"),
        decision,
    )

    return result


async def perform_dry_run(
    request: Mapping[str, Any],
    *,
    provider_enabled: bool,
    provider_dry_run_only: bool,
    provider_human_approval_required: bool,
    provider_allowed_actions: Any = None,
) -> dict[str, Any]:
    approved = (
        str(request.get("status") or "").lower()
        == "approved"
    )

    policy = evaluate_execution_policy(
        provider=request.get("provider"),
        action_type=request.get("action_type"),
        request_status=request.get("status"),
        dry_run=bool(request.get("dry_run", True)),
        provider_enabled=provider_enabled,
        provider_dry_run_only=provider_dry_run_only,
        provider_human_approval_required=(
            provider_human_approval_required
        ),
        approved=approved,
        provider_allowed_actions=provider_allowed_actions,
    )

    if not policy["allowed"]:
        return {
            "allowed": False,
            "policy": policy,
            "result": None,
        }

    adapter = get_provider_adapter(
        request.get("provider")
    )

    result = adapter.dry_run(
        action_type=request.get("action_type"),
        target_type=request.get("target_type"),
        target_id=request.get("target_id"),
        payload=request.get("request_payload") or {},
    )

    return {
        "allowed": True,
        "policy": policy,
        "result": result,
    }


__all__ = [
    "prepare_execution_request",
    "submit_for_approval",
    "decide_request",
    "perform_dry_run",
]
