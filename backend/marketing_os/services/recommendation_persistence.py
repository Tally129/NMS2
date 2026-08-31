"""Persistence for deterministic Marketing Director recommendations.

Recommendations remain advisory and require human approval.

This module:
- creates no external campaigns;
- changes no budgets;
- publishes nothing;
- calls no provider APIs;
- executes no marketing actions.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from sqlalchemy import text


def _stable_recommendation_id(
    *,
    recommendation_type: str,
    channel: str,
    title: str,
) -> str:
    """Stable identity prevents repeated Director briefs from
    generating duplicate pending recommendations."""

    raw = "|".join(
        [
            str(recommendation_type or "").strip().lower(),
            str(channel or "").strip().lower(),
            str(title or "").strip().lower(),
        ]
    )

    digest = hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:40]

    return f"mrec_{digest}"


def _priority_name(
    value: Any,
) -> str:
    """Normalize numeric Director priority to DB priority label."""

    try:
        score = int(value)
    except (TypeError, ValueError):
        score = 50

    if score >= 90:
        return "critical"

    if score >= 75:
        return "high"

    if score >= 50:
        return "medium"

    return "low"


async def persist_director_recommendations(
    pg,
    *,
    recommendations: Iterable[Mapping[str, Any]],
    created_by: str | None = None,
) -> dict[str, Any]:
    """Insert new pending recommendations without duplicating existing ones."""

    inserted = []
    existing = []

    for item in recommendations:
        recommendation = dict(item)

        recommendation_type = str(
            recommendation.get("type")
            or recommendation.get("recommendation_type")
            or "general"
        ).strip().lower()

        channel = str(
            recommendation.get("channel")
            or "internal"
        ).strip().lower()

        title = str(
            recommendation.get("title")
            or "Marketing recommendation"
        ).strip()

        recommendation_id = (
            _stable_recommendation_id(
                recommendation_type=
                    recommendation_type,
                channel=channel,
                title=title,
            )
        )

        proposed_action = recommendation.get(
            "proposed_action"
        )

        if isinstance(proposed_action, dict):
            proposed_payload = dict(
                proposed_action
            )
        elif proposed_action is None:
            proposed_payload = {}
        else:
            proposed_payload = {
                "instruction":
                    str(proposed_action),
            }

        proposed_payload.update(
            {
                "advisory_only":
                    True,
                "requires_human_approval":
                    True,
                "external_write":
                    False,
                "channel":
                    channel,
            }
        )

        goal_id = recommendation.get(
            "goal_id"
        )

        budget_id = recommendation.get(
            "budget_id"
        )

        evidence = {
            "channel":
                channel,
            "director_generated":
                True,
            "goal_id":
                goal_id,
            "budget_id":
                budget_id,
            "generated_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),
        }

        model_metadata = {
            "engine":
                "deterministic_marketing_director",
            "external_write":
                False,
            "human_approval_required":
                True,
        }

        result = await pg.execute(
            text(
                """
                INSERT INTO marketing_recommendations (
                    id,
                    goal_id,
                    recommendation_type,
                    title,
                    summary,
                    reason,
                    priority,
                    status,
                    provider,
                    proposed_action,
                    evidence,
                    model_metadata,
                    created_by
                )
                VALUES (
                    :id,
                    :goal_id,
                    :recommendation_type,
                    :title,
                    :summary,
                    :reason,
                    :priority,
                    'pending',
                    :provider,
                    CAST(:proposed_action AS jsonb),
                    CAST(:evidence AS jsonb),
                    CAST(:model_metadata AS jsonb),
                    :created_by
                )
                ON CONFLICT (id)
                DO NOTHING
                RETURNING id
                """
            ),
            {
                "id":
                    recommendation_id,
                "goal_id":
                    goal_id,
                "recommendation_type":
                    recommendation_type,
                "title":
                    title,
                "summary":
                    recommendation.get(
                        "reason"
                    ),
                "reason":
                    recommendation.get(
                        "reason"
                    ),
                "priority":
                    _priority_name(
                        recommendation.get(
                            "priority"
                        )
                    ),
                "provider":
                    channel,
                "proposed_action":
                    json.dumps(
                        proposed_payload
                    ),
                "evidence":
                    json.dumps(
                        evidence
                    ),
                "model_metadata":
                    json.dumps(
                        model_metadata
                    ),
                "created_by":
                    created_by,
            },
        )

        row = result.first()

        if row:
            inserted.append(
                recommendation_id
            )
        else:
            existing.append(
                recommendation_id
            )

    return {
        "inserted_count":
            len(inserted),
        "existing_count":
            len(existing),
        "inserted_ids":
            inserted,
        "existing_ids":
            existing,
        "external_write":
            False,
        "human_approval_required":
            True,
    }
