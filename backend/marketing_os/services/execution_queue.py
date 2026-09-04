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
    evaluate_live_execution_policy,
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
    operation_token: str | None = None,
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
        operation_token=operation_token,
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


def execution_request_matches_existing(
    existing: Mapping[str, Any],
    incoming: Mapping[str, Any],
    *,
    actor: str,
) -> bool:
    """Return True only for an exact retry of one operation token."""

    def value(mapping, key):
        try:
            return mapping.get(key)
        except AttributeError:
            return mapping[key]

    existing_payload = (
        value(existing, "request_payload")
        or {}
    )

    incoming_payload = (
        value(incoming, "request_payload")
        or {}
    )

    return (
        str(value(existing, "provider") or "")
        == str(value(incoming, "provider") or "")
        and
        str(value(existing, "action_type") or "")
        == str(value(incoming, "action_type") or "")
        and
        str(value(existing, "target_type") or "")
        == str(value(incoming, "target_type") or "")
        and
        (value(existing, "target_id") or None)
        == (value(incoming, "target_id") or None)
        and
        existing_payload == incoming_payload
        and
        str(value(existing, "created_by") or "")
        == str(actor or "")
        and
        bool(value(existing, "dry_run"))
        == bool(value(incoming, "dry_run"))
    )


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


async def perform_live_execution(
    request: Mapping[str, Any],
    *,
    adapter: Any,
    provider_enabled: bool,
    provider_dry_run_only: bool,
    provider_human_approval_required: bool,
    provider_allowed_actions: Any = None,
) -> dict[str, Any]:
    """Execute one already-approved provider mutation.

    The caller supplies the concrete live provider adapter.
    This keeps account/credential resolution outside the policy
    engine and makes the execution service independently testable.
    """

    approved = (
        str(request.get("status") or "").lower()
        == "approved"
        and bool(request.get("approved_by"))
        and bool(request.get("approved_at"))
    )

    if bool(request.get("dry_run", True)):
        return {
            "allowed": False,
            "policy": {
                "allowed": False,
                "live_execution": True,
                "dry_run": False,
                "reasons": [
                    "request_marked_dry_run",
                ],
            },
            "result": None,
        }

    policy = evaluate_live_execution_policy(
        provider=request.get("provider"),
        action_type=request.get("action_type"),
        request_status=request.get("status"),
        provider_enabled=provider_enabled,
        provider_dry_run_only=provider_dry_run_only,
        provider_human_approval_required=(
            provider_human_approval_required
        ),
        approved=approved,
        provider_allowed_actions=(
            provider_allowed_actions
        ),
    )

    if not policy["allowed"]:
        return {
            "allowed": False,
            "policy": policy,
            "result": None,
        }

    if adapter is None:
        raise RuntimeError(
            "live_provider_adapter_required"
        )

    execute_action = getattr(
        adapter,
        "execute_action",
        None,
    )

    if not callable(execute_action):
        raise RuntimeError(
            "provider_adapter_execute_action_missing"
        )

    result = await execute_action(
        action_type=request.get("action_type"),
        target_type=request.get("target_type"),
        target_id=request.get("target_id"),
        payload=request.get("request_payload") or {},
    )

    if not isinstance(result, Mapping):
        raise RuntimeError(
            "invalid_provider_execution_result"
        )

    result = dict(result)

    if result.get("external_write_performed") is not True:
        raise RuntimeError(
            "provider_did_not_confirm_external_write"
        )

    if result.get("verified") is not True:
        raise RuntimeError(
            "provider_write_not_verified"
        )

    return {
        "allowed": True,
        "policy": policy,
        "result": result,
        # The live route consumes both provider confirmation
        # flags from the top-level outcome. Keep the complete
        # nested provider result while exposing the verified
        # contract required by the finalization route.
        "external_write_performed": (
            result["external_write_performed"]
        ),
        "verified": result["verified"],
    }



__all__ = [
    "prepare_execution_request",
    "execution_request_matches_existing",
    "submit_for_approval",
    "decide_request",
    "perform_dry_run",
    "perform_live_execution",
]
