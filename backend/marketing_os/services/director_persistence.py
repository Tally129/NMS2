"""Phase 12 Marketing Director persistence.

Persists deterministic advisory signals and brief snapshots only.

No AI calls.
No external provider calls.
No patient/client/clinical identifiers.
No autonomous execution.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text


def director_snapshot_key() -> str:
    """Use one deterministic Director snapshot per UTC hour."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:00Z")


async def persist_director_snapshot(
    pg,
    *,
    director_signals: Mapping[str, Any],
    deterministic_brief: Mapping[str, Any],
    source_counts: Mapping[str, Any],
    created_by: str | None,
) -> dict[str, Any]:
    snapshot_key = director_snapshot_key()

    signals = director_signals.get("signals") or []
    if not isinstance(signals, list):
        signals = []

    persisted_signal_count = 0

    for signal in signals[:200]:
        if not isinstance(signal, Mapping):
            continue

        signal_key = str(signal.get("signal_key") or "").strip()[:200]
        if not signal_key:
            continue

        await pg.execute(
            text("""
                INSERT INTO marketing_director_signals (
                    id,
                    signal_key,
                    snapshot_key,
                    category,
                    source_phase,
                    severity,
                    priority,
                    title,
                    summary,
                    evidence,
                    recommended_action,
                    expected_impact,
                    confidence,
                    data_quality,
                    status,
                    human_approval_required,
                    external_execution_allowed,
                    created_by
                )
                VALUES (
                    :id,
                    :signal_key,
                    :snapshot_key,
                    :category,
                    :source_phase,
                    :severity,
                    :priority,
                    :title,
                    :summary,
                    CAST(:evidence AS jsonb),
                    :recommended_action,
                    :expected_impact,
                    :confidence,
                    :data_quality,
                    'open',
                    true,
                    false,
                    :created_by
                )
                ON CONFLICT (
                    signal_key,
                    snapshot_key
                )
                DO UPDATE SET
                    category = EXCLUDED.category,
                    source_phase = EXCLUDED.source_phase,
                    severity = EXCLUDED.severity,
                    priority = EXCLUDED.priority,
                    title = EXCLUDED.title,
                    summary = EXCLUDED.summary,
                    evidence = EXCLUDED.evidence,
                    recommended_action = EXCLUDED.recommended_action,
                    expected_impact = EXCLUDED.expected_impact,
                    confidence = EXCLUDED.confidence,
                    data_quality = EXCLUDED.data_quality,
                    human_approval_required = true,
                    external_execution_allowed = false,
                    updated_at = now()
            """),
            {
                "id": uuid.uuid4().hex,
                "signal_key": signal_key,
                "snapshot_key": snapshot_key,
                "category": str(
                    signal.get("category") or "unknown"
                )[:64],
                "source_phase": str(
                    signal.get("source_phase") or "unknown"
                )[:32],
                "severity": str(
                    signal.get("severity") or "info"
                )[:24],
                "priority": int(signal.get("priority") or 0),
                "title": str(
                    signal.get("title") or "Marketing signal"
                )[:300],
                "summary": str(
                    signal.get("summary") or ""
                )[:2000] or None,
                "evidence": json.dumps(
                    signal.get("evidence") or {},
                    default=str,
                ),
                "recommended_action": str(
                    signal.get("recommended_action") or ""
                )[:2000] or None,
                "expected_impact": (
                    str(signal.get("expected_impact"))[:32]
                    if signal.get("expected_impact")
                    else None
                ),
                "confidence": (
                    str(signal.get("confidence"))[:32]
                    if signal.get("confidence")
                    else None
                ),
                "data_quality": (
                    str(signal.get("data_quality"))[:32]
                    if signal.get("data_quality")
                    else None
                ),
                "created_by": created_by,
            },
        )

        persisted_signal_count += 1

    signal_summary = director_signals.get("summary") or {}

    director_summary = deterministic_brief.get(
        "director_summary"
    ) or {}
    if not isinstance(director_summary, Mapping):
        director_summary = {}

    director_ai_status = str(
        deterministic_brief.get("director_ai_status")
        or "not_requested"
    )[:32]

    ai_summary = None
    if director_ai_status == "generated":
        value = director_summary.get("executive_summary")
        if value:
            ai_summary = str(value)[:4000]

    await pg.execute(
        text("""
            INSERT INTO marketing_director_briefs (
                id,
                snapshot_key,
                status,
                deterministic_summary,
                signal_summary,
                ai_summary,
                ai_status,
                source_counts,
                human_approval_required,
                external_execution_allowed,
                created_by
            )
            VALUES (
                :id,
                :snapshot_key,
                'ready',
                CAST(:deterministic_summary AS jsonb),
                CAST(:signal_summary AS jsonb),
                :ai_summary,
                :ai_status,
                CAST(:source_counts AS jsonb),
                true,
                false,
                :created_by
            )
            ON CONFLICT (snapshot_key)
            DO UPDATE SET
                status = 'ready',
                deterministic_summary =
                    EXCLUDED.deterministic_summary,
                signal_summary =
                    EXCLUDED.signal_summary,
                source_counts =
                    EXCLUDED.source_counts,
                ai_summary =
                    EXCLUDED.ai_summary,
                ai_status =
                    EXCLUDED.ai_status,
                human_approval_required = true,
                external_execution_allowed = false,
                updated_at = now()
        """),
        {
            "id": uuid.uuid4().hex,
            "snapshot_key": snapshot_key,
            "deterministic_summary": json.dumps(
                dict(deterministic_brief),
                default=str,
            ),
            "signal_summary": json.dumps(
                signal_summary,
                default=str,
            ),
            "source_counts": json.dumps(
                dict(source_counts),
                default=str,
            ),
            "ai_summary": ai_summary,
            "ai_status": director_ai_status,
            "created_by": created_by,
        },
    )

    return {
        "snapshot_key": snapshot_key,
        "signals_persisted": persisted_signal_count,
        "brief_persisted": True,
        "ai_status": director_ai_status,
        "human_approval_required": True,
        "external_execution_allowed": False,
    }
