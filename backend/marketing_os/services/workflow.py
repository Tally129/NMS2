"""Controlled Marketing OS recommendation workflow.

This service records human recommendation decisions and, for an
approval, creates an internal blocked/dry-run action ledger entry.

It performs NO provider API call and NO external write.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import text


class RecommendationNotFoundError(LookupError):
    pass


class RecommendationStateError(ValueError):
    pass


def _new_id() -> str:
    return uuid.uuid4().hex


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, (date, datetime)):
        return value.isoformat()

    if isinstance(value, dict):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [
            _json_safe(item)
            for item in value
        ]

    return value


def _mapping_dict(row: Any) -> dict[str, Any]:
    return {
        key: _json_safe(value)
        for key, value in dict(row._mapping).items()
    }


async def decide_recommendation(
    pg,
    *,
    recommendation_id: str,
    decision: str,
    reason: Optional[str],
    decided_by: Optional[str],
) -> dict[str, Any]:
    """Record one human decision.

    Approved recommendations create an internal action ledger record
    with status=blocked and dry_run=true.

    No external provider execution occurs here.
    """

    normalized_decision = str(
        decision or ""
    ).strip().lower()

    if normalized_decision not in {
        "approved",
        "rejected",
    }:
        raise ValueError(
            "decision must be approved or rejected"
        )

    recommendation_result = await pg.execute(
        text(
            """
            SELECT *
            FROM marketing_recommendations
            WHERE id = :id
            FOR UPDATE
            """
        ),
        {
            "id": recommendation_id,
        },
    )

    recommendation = recommendation_result.first()

    if recommendation is None:
        raise RecommendationNotFoundError(
            "Recommendation not found"
        )

    snapshot = _mapping_dict(recommendation)

    current_status = str(
        snapshot.get("status") or ""
    ).strip().lower()

    if current_status != "pending":
        raise RecommendationStateError(
            "Recommendation has already been decided"
        )

    approval_id = _new_id()

    await pg.execute(
        text(
            """
            INSERT INTO marketing_approvals (
                id,
                recommendation_id,
                decision,
                decision_reason,
                decided_by,
                snapshot
            )
            VALUES (
                :id,
                :recommendation_id,
                :decision,
                :decision_reason,
                :decided_by,
                CAST(:snapshot AS jsonb)
            )
            """
        ),
        {
            "id": approval_id,
            "recommendation_id":
                recommendation_id,
            "decision":
                normalized_decision,
            "decision_reason":
                reason,
            "decided_by":
                decided_by,
            "snapshot":
                json.dumps(snapshot),
        },
    )

    await pg.execute(
        text(
            """
            UPDATE marketing_recommendations
            SET
                status = :decision,
                updated_at = now()
            WHERE id = :id
            """
        ),
        {
            "id": recommendation_id,
            "decision":
                normalized_decision,
        },
    )

    action_id = None
    action_status = None
    dry_run = None

    if normalized_decision == "approved":
        action_id = _new_id()
        action_status = "blocked"
        dry_run = True

        provider = str(
            snapshot.get("provider")
            or "internal"
        ).strip() or "internal"

        action_type = str(
            snapshot.get(
                "recommendation_type"
            )
            or "recommendation"
        ).strip() or "recommendation"

        proposed_action = snapshot.get(
            "proposed_action"
        )

        if isinstance(proposed_action, dict):
            request_payload = dict(
                proposed_action
            )
        elif proposed_action is None:
            request_payload = {}
        else:
            request_payload = {
                "instruction":
                    str(proposed_action),
            }

        request_payload.update(
            {
                "source":
                    "human_approved_recommendation",
                "recommendation_id":
                    recommendation_id,
                "approval_id":
                    approval_id,

                # Explicit safety boundary.
                "external_write":
                    False,
                "execution_enabled":
                    False,
                "human_approved":
                    True,
            }
        )

        await pg.execute(
            text(
                """
                INSERT INTO marketing_actions (
                    id,
                    recommendation_id,
                    approval_id,
                    provider,
                    action_type,
                    status,
                    dry_run,
                    request_payload,
                    response_payload,
                    created_by
                )
                VALUES (
                    :id,
                    :recommendation_id,
                    :approval_id,
                    :provider,
                    :action_type,
                    'blocked',
                    TRUE,
                    CAST(:request_payload AS jsonb),
                    CAST(:response_payload AS jsonb),
                    :created_by
                )
                """
            ),
            {
                "id":
                    action_id,
                "recommendation_id":
                    recommendation_id,
                "approval_id":
                    approval_id,
                "provider":
                    provider,
                "action_type":
                    action_type,
                "request_payload":
                    json.dumps(
                        request_payload
                    ),
                "response_payload":
                    json.dumps(
                        {
                            "executed":
                                False,
                            "reason":
                                "external_writes_disabled",
                        }
                    ),
                "created_by":
                    decided_by,
            },
        )

    return {
        "recommendation_id":
            recommendation_id,
        "approval_id":
            approval_id,
        "decision":
            normalized_decision,

        "action_id":
            action_id,
        "action_status":
            action_status,
        "dry_run":
            dry_run,

        "external_action_executed":
            False,
        "external_write":
            False,
    }
