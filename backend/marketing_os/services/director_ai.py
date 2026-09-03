"""Phase 12 AI Marketing Director summary layer.

AI is optional and advisory only.

Rules:
- deterministic signals/priorities are computed before this module
- no PHI
- no patient/client/clinical identifiers
- no external execution
- no campaign/budget/listing/content mutation
- Bedrock is accessed only through the existing llm_client abstraction
- any AI failure falls back to deterministic wording
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from llm_client import PromptTemplate, run_template, safe_extract_json


DIRECTOR_TEMPLATE = PromptTemplate(
    feature="marketing_director",
    system=(
        "You are an advisory marketing executive summarizer. "
        "You receive only sanitized business marketing signals that were "
        "already scored and prioritized deterministically. "
        "Do not change priorities, severity, evidence, or rankings. "
        "Do not invent metrics, projections, facts, clinical claims, or "
        "patient information. "
        "Do not recommend autonomous publishing, messaging, campaign "
        "creation, budget changes, listing edits, experiment changes, or "
        "appointment actions. "
        "Return JSON only with these keys: "
        "executive_summary, urgent_issues, top_opportunities, "
        "recommended_focus. "
        "Each list must contain short plain-language strings. "
        "Human review is always required."
    ),
    max_tokens=1600,
    temperature=0.2,
)


def deterministic_summary(
    director_signals: Mapping[str, Any],
) -> dict[str, Any]:
    signals = director_signals.get("signals") or []
    summary = director_signals.get("summary") or {}

    if not isinstance(signals, list):
        signals = []

    high = [
        signal
        for signal in signals
        if isinstance(signal, Mapping)
        and int(signal.get("priority") or 0) >= 75
    ]

    top = [
        signal
        for signal in signals[:5]
        if isinstance(signal, Mapping)
    ]

    if top:
        executive = (
            f"Marketing Director identified {len(signals)} active signals, "
            f"including {len(high)} high-priority items. "
            "Review the highest-priority evidence before making changes."
        )
    else:
        executive = (
            "No high-confidence Director issues are currently available "
            "from the connected marketing data."
        )

    return {
        "executive_summary": executive,
        "urgent_issues": [
            str(signal.get("title") or "")[:300]
            for signal in high[:5]
            if signal.get("title")
        ],
        "top_opportunities": [
            str(signal.get("title") or "")[:300]
            for signal in top[:5]
            if signal.get("title")
        ],
        "recommended_focus": [
            str(signal.get("recommended_action") or "")[:500]
            for signal in top[:5]
            if signal.get("recommended_action")
        ],
        "signal_count": int(summary.get("total") or len(signals)),
        "high_priority_count": int(
            summary.get("high_priority") or len(high)
        ),
        "source": "deterministic",
        "human_review_required": True,
        "external_execution_allowed": False,
    }


def _bounded_ai_payload(
    director_signals: Mapping[str, Any],
) -> str:
    signals = director_signals.get("signals") or []

    bounded = []
    for signal in signals[:12]:
        if not isinstance(signal, Mapping):
            continue

        evidence = signal.get("evidence")
        if not isinstance(evidence, Mapping):
            evidence = {}

        safe_evidence = {}
        for key, value in list(evidence.items())[:12]:
            if isinstance(value, (str, int, float, bool)) or value is None:
                safe_evidence[str(key)[:80]] = (
                    str(value)[:300]
                    if isinstance(value, str)
                    else value
                )

        bounded.append({
            "signal_key": str(
                signal.get("signal_key") or ""
            )[:200],
            "category": str(
                signal.get("category") or ""
            )[:64],
            "severity": str(
                signal.get("severity") or ""
            )[:24],
            "priority": int(
                signal.get("priority") or 0
            ),
            "title": str(
                signal.get("title") or ""
            )[:300],
            "summary": str(
                signal.get("summary") or ""
            )[:700],
            "recommended_action": str(
                signal.get("recommended_action") or ""
            )[:700],
            "expected_impact": str(
                signal.get("expected_impact") or ""
            )[:32],
            "confidence": str(
                signal.get("confidence") or ""
            )[:32],
            "data_quality": str(
                signal.get("data_quality") or ""
            )[:32],
            "evidence": safe_evidence,
        })

    payload = {
        "instructions": {
            "preserve_existing_priority_order": True,
            "invent_metrics": False,
            "autonomous_actions": False,
            "human_review_required": True,
        },
        "signals": bounded,
    }

    return json.dumps(payload, separators=(",", ":"))


def _validate_ai_summary(
    data: Any,
    fallback: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise ValueError("invalid_model_response")

    def text_value(key: str, limit: int) -> str:
        value = data.get(key)
        if not isinstance(value, (str, int, float)):
            return ""
        return str(value).strip()[:limit]

    def text_list(key: str) -> list[str]:
        value = data.get(key)
        if not isinstance(value, list):
            return []

        result = []
        for item in value[:8]:
            if isinstance(item, (str, int, float)):
                cleaned = str(item).strip()[:500]
                if cleaned:
                    result.append(cleaned)
        return result

    executive = text_value(
        "executive_summary",
        1600,
    )

    if not executive:
        raise ValueError("invalid_model_response")

    return {
        "executive_summary": executive,
        "urgent_issues": text_list("urgent_issues"),
        "top_opportunities": text_list("top_opportunities"),
        "recommended_focus": text_list("recommended_focus"),
        "signal_count": fallback["signal_count"],
        "high_priority_count": fallback["high_priority_count"],
        "source": "bedrock",
        "human_review_required": True,
        "external_execution_allowed": False,
    }


async def build_director_summary(
    director_signals: Mapping[str, Any],
    *,
    use_ai: bool,
) -> tuple[dict[str, Any], str]:
    """Return summary + status. AI failure never breaks the Director."""

    fallback = deterministic_summary(director_signals)

    if not use_ai:
        return fallback, "not_requested"

    try:
        raw = await run_template(
            DIRECTOR_TEMPLATE,
            _bounded_ai_payload(director_signals),
            session_id="marketing.director",
        )

        parsed = safe_extract_json(raw)
        return (
            _validate_ai_summary(parsed, fallback),
            "generated",
        )

    except Exception:
        result = dict(fallback)
        result["source"] = "deterministic_fallback"
        return result, "fallback"


__all__ = [
    "deterministic_summary",
    "build_director_summary",
]
