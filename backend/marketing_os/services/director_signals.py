"""Marketing OS Phase 12 — deterministic Marketing Director signals.

Pure advisory logic only:
- no database access
- no network access
- no AI calls
- no patient/client/clinical data
- no external execution

The AI layer may summarize these signals later, but it must never create,
override, or reprioritize the underlying deterministic evidence.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any, Optional


SEVERITY_WEIGHT = {
    "critical": 100,
    "high": 80,
    "medium": 55,
    "low": 30,
    "info": 10,
}

VALID_SEVERITIES = frozenset(SEVERITY_WEIGHT)

SIGNAL_CATEGORIES = frozenset({
    "paid_media",
    "conversion",
    "lead_pipeline",
    "appointment_recovery",
    "experimentation",
    "search",
    "local_growth",
    "content",
})


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> Optional[int]:
    number = _number(value)
    if number is None:
        return None
    return int(number)


def _bounded_priority(value: Any) -> int:
    number = _number(value)
    if number is None:
        return 0
    return int(round(min(max(number, 0.0), 100.0)))


def _safe_text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _signal(
    *,
    signal_key: str,
    category: str,
    source_phase: str,
    severity: str,
    priority: int,
    title: str,
    summary: str,
    evidence: Mapping[str, Any],
    recommended_action: str,
    expected_impact: Optional[str] = None,
    confidence: str = "medium",
    data_quality: str = "available",
) -> dict[str, Any]:
    if category not in SIGNAL_CATEGORIES:
        raise ValueError("invalid_signal_category")
    if severity not in VALID_SEVERITIES:
        raise ValueError("invalid_signal_severity")

    return {
        "signal_key": _safe_text(signal_key, 200),
        "category": category,
        "source_phase": _safe_text(source_phase, 32),
        "severity": severity,
        "priority": _bounded_priority(priority),
        "title": _safe_text(title, 300),
        "summary": _safe_text(summary, 2000),
        "evidence": dict(evidence),
        "recommended_action": _safe_text(recommended_action, 2000),
        "expected_impact": (
            _safe_text(expected_impact, 32)
            if expected_impact
            else None
        ),
        "confidence": _safe_text(confidence, 32),
        "data_quality": _safe_text(data_quality, 32),
        "human_approval_required": True,
        "external_execution_allowed": False,
    }


def paid_media_signals(
    channels: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    signals = []

    for row in channels or []:
        provider = _safe_text(
            row.get("provider")
            or row.get("channel")
            or row.get("platform")
            or "unknown",
            64,
        ).lower()

        spend = _number(row.get("spend"))
        conversions = _number(
            row.get("conversions")
        )

        if conversions is None:
            conversions = _number(
                row.get("leads")
            )

        if conversions is None:
            conversions = 0.0
        roas = _number(row.get("roas"))
        ctr = _number(row.get("ctr"))

        if spend is not None and spend > 0 and conversions <= 0:
            signals.append(_signal(
                signal_key=f"paid_no_conversion:{provider}",
                category="paid_media",
                source_phase="4",
                severity="high",
                priority=85,
                title=f"{provider} spend has no recorded conversions",
                summary=(
                    "Paid spend is present while the normalized "
                    "conversion count is zero."
                ),
                evidence={
                    "provider": provider,
                    "spend": round(spend, 4),
                    "conversions": conversions,
                },
                recommended_action=(
                    "Review targeting, conversion tracking, landing-page "
                    "alignment, and campaign quality before increasing spend."
                ),
                expected_impact="high",
                confidence="high",
            ))

        if roas is not None and spend and spend > 0 and roas < 1.0:
            signals.append(_signal(
                signal_key=f"paid_low_roas:{provider}",
                category="paid_media",
                source_phase="4/5",
                severity="high" if roas < 0.5 else "medium",
                priority=88 if roas < 0.5 else 72,
                title=f"{provider} ROAS is below 1.0",
                summary=(
                    "Attributed revenue is currently below recorded paid "
                    "media spend."
                ),
                evidence={
                    "provider": provider,
                    "spend": round(spend, 4),
                    "roas": round(roas, 4),
                },
                recommended_action=(
                    "Review campaign economics and attribution before "
                    "reallocating or increasing budget."
                ),
                expected_impact="high",
                confidence="high",
            ))

        if ctr is not None and 0 <= ctr < 0.01:
            signals.append(_signal(
                signal_key=f"paid_low_ctr:{provider}",
                category="paid_media",
                source_phase="4",
                severity="medium",
                priority=60,
                title=f"{provider} click-through rate is weak",
                summary=(
                    "The normalized click-through rate is below the "
                    "Director low-CTR threshold."
                ),
                evidence={
                    "provider": provider,
                    "ctr": round(ctr, 6),
                    "threshold": 0.01,
                },
                recommended_action=(
                    "Review creative, audience fit, and offer relevance."
                ),
                expected_impact="medium",
                confidence="medium",
            ))

    return signals


def lead_pipeline_signals(
    lead_operations: Mapping[str, Any],
) -> list[dict[str, Any]]:
    signals = []

    overdue = (
        _integer(lead_operations.get("overdue_leads"))
        or _integer(lead_operations.get("overdue"))
        or 0
    )
    needs_attention = (
        _integer(lead_operations.get("needs_attention"))
        or 0
    )
    no_show = (
        _integer(lead_operations.get("no_show"))
        or _integer(lead_operations.get("no_shows"))
        or 0
    )

    if overdue > 0:
        signals.append(_signal(
            signal_key="lead_pipeline:overdue",
            category="lead_pipeline",
            source_phase="6",
            severity="high" if overdue >= 5 else "medium",
            priority=min(95, 60 + overdue * 5),
            title="Lead follow-up is overdue",
            summary="Open marketing leads have overdue follow-up actions.",
            evidence={"overdue_leads": overdue},
            recommended_action=(
                "Prioritize overdue Lead CRM work before adding "
                "additional top-of-funnel volume."
            ),
            expected_impact="high",
            confidence="high",
        ))

    if needs_attention > 0:
        signals.append(_signal(
            signal_key="lead_pipeline:needs_attention",
            category="lead_pipeline",
            source_phase="6",
            severity="medium",
            priority=min(80, 45 + needs_attention * 3),
            title="Marketing leads need staff attention",
            summary="The Lead CRM contains active leads requiring follow-up.",
            evidence={"needs_attention": needs_attention},
            recommended_action=(
                "Review the needs-attention queue and assign clear "
                "next actions."
            ),
            expected_impact="medium",
            confidence="high",
        ))

    if no_show > 0:
        signals.append(_signal(
            signal_key="appointment_recovery:no_show",
            category="appointment_recovery",
            source_phase="8",
            severity="high" if no_show >= 3 else "medium",
            priority=min(90, 55 + no_show * 7),
            title="No-show recovery opportunity detected",
            summary=(
                "Marketing lead activity includes no-show outcomes "
                "eligible for recovery review."
            ),
            evidence={"no_show_count": no_show},
            recommended_action=(
                "Review eligible no-show recovery enrollments and "
                "pending staff actions."
            ),
            expected_impact="medium",
            confidence="high",
        ))

    return signals


def funnel_signals(
    funnel: Mapping[str, Any],
) -> list[dict[str, Any]]:
    signals = []

    request_rate = _number(funnel.get("appointment_request_rate"))
    booking_rate = _number(
        funnel.get("booking_rate")
    )

    if booking_rate is None:
        booking_rate = _number(
            funnel.get("appointment_booking_rate")
        )
    no_show_rate = _number(funnel.get("no_show_rate"))

    if request_rate is not None and request_rate < 0.10:
        signals.append(_signal(
            signal_key="conversion:low_appointment_request_rate",
            category="conversion",
            source_phase="5/7",
            severity="medium",
            priority=65,
            title="Appointment-request conversion is weak",
            summary=(
                "The deterministic funnel shows a low appointment-request "
                "rate."
            ),
            evidence={
                "appointment_request_rate": round(request_rate, 6),
                "threshold": 0.10,
            },
            recommended_action=(
                "Review funnel friction, qualification, offer alignment, "
                "and appointment CTA clarity."
            ),
            expected_impact="high",
            confidence="medium",
        ))

    if booking_rate is not None and booking_rate < 0.50:
        signals.append(_signal(
            signal_key="conversion:low_booking_rate",
            category="conversion",
            source_phase="5/6",
            severity="medium",
            priority=68,
            title="Appointment booking rate needs attention",
            summary=(
                "Measured appointment requests are not converting to "
                "booked appointments at the Director threshold."
            ),
            evidence={
                "booking_rate": round(booking_rate, 6),
                "threshold": 0.50,
            },
            recommended_action=(
                "Review response time, setter workflow, scheduling "
                "friction, and follow-up completion."
            ),
            expected_impact="high",
            confidence="medium",
        ))

    if no_show_rate is not None and no_show_rate > 0.20:
        signals.append(_signal(
            signal_key="appointment_recovery:high_no_show_rate",
            category="appointment_recovery",
            source_phase="5/8",
            severity="high",
            priority=82,
            title="No-show rate is elevated",
            summary=(
                "The deterministic appointment funnel shows an elevated "
                "no-show rate."
            ),
            evidence={
                "no_show_rate": round(no_show_rate, 6),
                "threshold": 0.20,
            },
            recommended_action=(
                "Review no-show recovery workflow and appointment "
                "confirmation operations."
            ),
            expected_impact="high",
            confidence="high",
        ))

    return signals


def experiment_signals(
    reports: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    signals = []

    for report in reports or []:
        experiment_id = _safe_text(
            report.get("experiment_id") or report.get("id"),
            64,
        )
        recommendation = report.get("recommendation") or {}

        if not isinstance(recommendation, Mapping):
            recommendation = {}

        winner = recommendation.get("winner_variant_id")
        reason = _safe_text(recommendation.get("reason"), 100)
        status = _safe_text(report.get("status"), 32).lower()

        if winner:
            signals.append(_signal(
                signal_key=f"experiment:winner:{experiment_id}",
                category="experimentation",
                source_phase="9",
                severity="medium",
                priority=70,
                title="Experiment has an advisory winner",
                summary=(
                    "The deterministic experiment engine identified a "
                    "statistically supported winner."
                ),
                evidence={
                    "experiment_id": experiment_id,
                    "winner_variant_id": _safe_text(winner, 64),
                    "reason": reason,
                },
                recommended_action=(
                    "Review the experiment evidence before adopting the "
                    "winning variant."
                ),
                expected_impact="medium",
                confidence="high",
            ))

        elif status in {"active", "running"}:
            signals.append(_signal(
                signal_key=f"experiment:active:{experiment_id}",
                category="experimentation",
                source_phase="9",
                severity="info",
                priority=25,
                title="Experiment is actively collecting data",
                summary=(
                    "A Phase 9 experiment is active. No winner is inferred "
                    "from lifecycle status alone."
                ),
                evidence={
                    "experiment_id": experiment_id,
                    "status": status,
                },
                recommended_action=(
                    "Continue collecting experiment outcomes and review the "
                    "deterministic report before changing a variant."
                ),
                confidence="high",
                data_quality="lifecycle_only",
            ))

    return signals


def local_growth_signals(
    locations: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    signals = []

    for row in locations or []:
        location_id = _safe_text(
            row.get("location_id") or row.get("id") or "unknown",
            64,
        )
        health = _number(row.get("health_score"))
        opportunity_priority = _bounded_priority(row.get("priority"))
        opportunity_key = _safe_text(
            row.get("opportunity_key")
            or row.get("opportunity_type"),
            120,
        )

        if opportunity_key and opportunity_priority >= 60:
            signals.append(_signal(
                signal_key=(
                    f"local_growth:opportunity:"
                    f"{location_id}:{opportunity_key}"
                ),
                category="local_growth",
                source_phase="10",
                severity=(
                    "high"
                    if opportunity_priority >= 80
                    else "medium"
                ),
                priority=opportunity_priority,
                title=_safe_text(
                    row.get("title")
                    or row.get("opportunity_type")
                    or "Local growth opportunity",
                    300,
                ),
                summary=_safe_text(
                    row.get("summary")
                    or row.get("reason")
                    or "Phase 10 identified a local-growth opportunity.",
                    2000,
                ),
                evidence={
                    "location_id": location_id,
                    "opportunity_key": opportunity_key,
                    "priority": opportunity_priority,
                },
                recommended_action=_safe_text(
                    row.get("recommended_action")
                    or (
                        "Review this local-growth opportunity before "
                        "making any listing or reputation change."
                    ),
                    2000,
                ),
                expected_impact="medium",
                confidence="high",
            ))

        if health is not None and health < 60:
            signals.append(_signal(
                signal_key=f"local_growth:health:{location_id}",
                category="local_growth",
                source_phase="10",
                severity="high" if health < 40 else "medium",
                priority=int(min(95, 100 - health)),
                title="Local marketing health needs attention",
                summary=(
                    "The deterministic local-growth health score is below "
                    "the Director threshold."
                ),
                evidence={
                    "location_id": location_id,
                    "health_score": round(health, 2),
                    "threshold": 60,
                },
                recommended_action=(
                    "Review listing completeness, NAP consistency, review "
                    "velocity, response rate, and local ranking gaps."
                ),
                expected_impact="medium",
                confidence="high",
            ))

    return signals


def content_signals(
    topics: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    signals = []

    for topic in topics or []:
        priority = _bounded_priority(topic.get("priority"))
        status = _safe_text(topic.get("status"), 32).lower()

        if priority < 70 or status in {"archived", "dismissed"}:
            continue

        topic_id = _safe_text(
            topic.get("id") or topic.get("slug"),
            100,
        )
        title = _safe_text(topic.get("topic"), 300)

        signals.append(_signal(
            signal_key=f"content:priority:{topic_id}",
            category="content",
            source_phase="11",
            severity="medium" if priority < 85 else "high",
            priority=priority,
            title=f"High-priority content opportunity: {title}",
            summary=(
                "Phase 11 deterministic scoring identified this topic as "
                "a high-priority content opportunity."
            ),
            evidence={
                "topic_id": topic_id,
                "topic": title,
                "priority": priority,
                "target_keyword": _safe_text(
                    topic.get("target_keyword"),
                    200,
                ),
                "funnel_stage": _safe_text(
                    topic.get("funnel_stage"),
                    32,
                ),
            },
            recommended_action=(
                "Review the topic and decide whether to move it into the "
                "content planning workflow."
            ),
            expected_impact="medium",
            confidence="high",
        ))

    return signals


def rank_signals(
    signals: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    normalized = [dict(signal) for signal in signals or []]

    return sorted(
        normalized,
        key=lambda signal: (
            -_bounded_priority(signal.get("priority")),
            -SEVERITY_WEIGHT.get(
                str(signal.get("severity") or "info"),
                0,
            ),
            str(signal.get("signal_key") or ""),
        ),
    )


def summarize_signals(
    signals: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    ranked = rank_signals(signals)

    by_category = Counter(
        str(signal.get("category") or "unknown")
        for signal in ranked
    )
    by_severity = Counter(
        str(signal.get("severity") or "unknown")
        for signal in ranked
    )

    return {
        "total": len(ranked),
        "high_priority": sum(
            1
            for signal in ranked
            if _bounded_priority(signal.get("priority")) >= 75
        ),
        "by_category": dict(sorted(by_category.items())),
        "by_severity": dict(sorted(by_severity.items())),
        "top_signal_keys": [
            str(signal.get("signal_key"))
            for signal in ranked[:10]
        ],
    }


def build_cross_phase_signals(
    *,
    paid_media: Iterable[Mapping[str, Any]] = (),
    funnel: Mapping[str, Any] | None = None,
    lead_operations: Mapping[str, Any] | None = None,
    experiments: Iterable[Mapping[str, Any]] = (),
    local_growth: Iterable[Mapping[str, Any]] = (),
    content_topics: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:

    collected = []

    collected.extend(paid_media_signals(paid_media))
    collected.extend(funnel_signals(funnel or {}))
    collected.extend(lead_pipeline_signals(lead_operations or {}))
    collected.extend(experiment_signals(experiments))
    collected.extend(local_growth_signals(local_growth))
    collected.extend(content_signals(content_topics))

    ranked = rank_signals(collected)

    return {
        "signals": ranked,
        "summary": summarize_signals(ranked),
        "safety": {
            "advisory_only": True,
            "ai_decides_priority": False,
            "automatic_execution": False,
            "external_execution_allowed": False,
            "human_approval_required": True,
            "phi_used": False,
        },
    }
