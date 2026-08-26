"""Marketing Director intelligence service.

Pure decision-support logic.

This module:
- performs no external writes;
- performs no publishing;
- performs no campaign creation;
- performs no budget mutation;
- does not require PHI.

It converts marketing goals and aggregate performance signals into
ranked advisory recommendations for later human approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class MarketingSignal:
    channel: str
    impressions: int = 0
    clicks: int = 0
    conversions: float = 0.0
    spend: float = 0.0
    revenue: float = 0.0

    @property
    def ctr(self) -> float:
        if self.impressions <= 0:
            return 0.0

        return self.clicks / self.impressions

    @property
    def conversion_rate(self) -> float:
        if self.clicks <= 0:
            return 0.0

        return self.conversions / self.clicks

    @property
    def cpc(self) -> float:
        if self.clicks <= 0:
            return 0.0

        return self.spend / self.clicks

    @property
    def cpa(self) -> float:
        if self.conversions <= 0:
            return 0.0

        return self.spend / self.conversions

    @property
    def roas(self) -> float:
        if self.spend <= 0:
            return 0.0

        return self.revenue / self.spend


def _number(
    value: Any,
    *,
    default: float = 0.0,
) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default

    return max(result, 0.0)


def normalize_signal(
    value: Mapping[str, Any],
) -> MarketingSignal:
    return MarketingSignal(
        channel=str(
            value.get("channel") or "unknown"
        ).strip().lower(),
        impressions=int(
            _number(value.get("impressions"))
        ),
        clicks=int(
            _number(value.get("clicks"))
        ),
        conversions=_number(
            value.get("conversions")
        ),
        spend=_number(
            value.get("spend")
        ),
        revenue=_number(
            value.get("revenue")
        ),
    )


def score_signal(
    signal: MarketingSignal,
) -> float:
    """Produce a bounded comparative performance score."""

    ctr_score = min(
        signal.ctr / 0.03,
        2.0,
    )

    conversion_score = min(
        signal.conversion_rate / 0.05,
        2.0,
    )

    roas_score = min(
        signal.roas / 3.0,
        2.0,
    )

    score = (
        ctr_score * 0.30
        + conversion_score * 0.35
        + roas_score * 0.35
    )

    return round(score, 4)


def analyze_channel(
    signal: MarketingSignal,
) -> dict[str, Any]:

    score = score_signal(signal)

    if signal.impressions == 0:
        status = "insufficient_data"

    elif score >= 1.25:
        status = "strong"

    elif score >= 0.75:
        status = "healthy"

    elif score >= 0.40:
        status = "needs_attention"

    else:
        status = "weak"

    return {
        "channel": signal.channel,
        "status": status,
        "score": score,
        "metrics": {
            "impressions": signal.impressions,
            "clicks": signal.clicks,
            "conversions": signal.conversions,
            "spend": round(signal.spend, 2),
            "revenue": round(signal.revenue, 2),
            "ctr": round(signal.ctr, 4),
            "conversion_rate": round(
                signal.conversion_rate,
                4,
            ),
            "cpc": round(signal.cpc, 2),
            "cpa": round(signal.cpa, 2),
            "roas": round(signal.roas, 2),
        },
    }


def _recommendation(
    *,
    recommendation_type: str,
    channel: str,
    priority: int,
    title: str,
    reason: str,
    proposed_action: str,
) -> dict[str, Any]:

    return {
        "type": recommendation_type,
        "channel": channel,
        "priority": priority,
        "title": title,
        "reason": reason,
        "proposed_action": proposed_action,

        # Safety contract.
        "advisory_only": True,
        "requires_human_approval": True,
        "external_write": False,
    }


def recommend_for_channel(
    signal: MarketingSignal,
) -> list[dict[str, Any]]:

    analysis = analyze_channel(signal)
    recommendations: list[dict[str, Any]] = []

    if signal.impressions <= 0:

        recommendations.append(
            _recommendation(
                recommendation_type="measurement",
                channel=signal.channel,
                priority=90,
                title=(
                    f"Establish {signal.channel} "
                    "performance measurement"
                ),
                reason=(
                    "There is not enough performance "
                    "data to evaluate this channel."
                ),
                proposed_action=(
                    "Verify analytics, conversion "
                    "tracking, and attribution before "
                    "making spend decisions."
                ),
            )
        )

        return recommendations

    if signal.ctr < 0.01:

        recommendations.append(
            _recommendation(
                recommendation_type="creative",
                channel=signal.channel,
                priority=80,
                title=(
                    f"Improve {signal.channel} "
                    "creative engagement"
                ),
                reason=(
                    "Click-through rate is below the "
                    "initial decision threshold."
                ),
                proposed_action=(
                    "Develop new hooks, creative angles, "
                    "headlines, and calls to action for "
                    "human review."
                ),
            )
        )

    if (
        signal.clicks >= 20
        and signal.conversion_rate < 0.02
    ):

        recommendations.append(
            _recommendation(
                recommendation_type="conversion",
                channel=signal.channel,
                priority=85,
                title=(
                    f"Investigate {signal.channel} "
                    "conversion friction"
                ),
                reason=(
                    "Traffic is being generated but the "
                    "conversion rate is low."
                ),
                proposed_action=(
                    "Review landing-page alignment, "
                    "offer clarity, trust signals, and "
                    "conversion path."
                ),
            )
        )

    if (
        signal.spend > 0
        and signal.roas < 1.0
    ):

        recommendations.append(
            _recommendation(
                recommendation_type="efficiency",
                channel=signal.channel,
                priority=95,
                title=(
                    f"Review inefficient "
                    f"{signal.channel} spend"
                ),
                reason=(
                    "Attributed revenue is currently "
                    "below recorded spend."
                ),
                proposed_action=(
                    "Analyze targeting, offer, creative, "
                    "and attribution before proposing "
                    "any budget change."
                ),
            )
        )

    if (
        signal.spend > 0
        and signal.roas >= 3.0
        and signal.conversions >= 3
    ):

        recommendations.append(
            _recommendation(
                recommendation_type="growth",
                channel=signal.channel,
                priority=70,
                title=(
                    f"Evaluate scaling "
                    f"{signal.channel}"
                ),
                reason=(
                    "The channel shows strong attributed "
                    "return and multiple conversions."
                ),
                proposed_action=(
                    "Prepare a conservative scaling "
                    "proposal for human approval. "
                    "Do not change budget automatically."
                ),
            )
        )

    if not recommendations:

        recommendations.append(
            _recommendation(
                recommendation_type="monitor",
                channel=signal.channel,
                priority=40,
                title=(
                    f"Continue monitoring "
                    f"{signal.channel}"
                ),
                reason=(
                    "Current aggregate performance does "
                    "not trigger an intervention rule."
                ),
                proposed_action=(
                    "Continue collecting performance "
                    "data and reassess as new conversion "
                    "information becomes available."
                ),
            )
        )

    return recommendations


def build_marketing_brief(
    *,
    goals: Iterable[Mapping[str, Any]] = (),
    performance: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build an advisory cross-channel marketing brief."""

    signals = [
        normalize_signal(item)
        for item in performance
    ]

    analyses = [
        analyze_channel(signal)
        for signal in signals
    ]

    recommendations = [
        recommendation
        for signal in signals
        for recommendation in recommend_for_channel(
            signal
        )
    ]

    recommendations.sort(
        key=lambda item: (
            -int(item["priority"]),
            item["channel"],
            item["type"],
        )
    )

    normalized_goals = [
        dict(goal)
        for goal in goals
    ]

    return {
        "status": "advisory",
        "goals": normalized_goals,
        "channel_analysis": analyses,
        "recommendations": recommendations,
        "safety": {
            "phi_required": False,
            "external_writes": False,
            "automatic_budget_changes": False,
            "automatic_campaign_creation": False,
            "automatic_publishing": False,
            "human_approval_required": True,
        },
    }


def marketing_director_health() -> dict[str, Any]:
    return {
        "status": "ready",
        "mode": "advisory",
        "phi_required": False,
        "external_writes": False,
        "human_approval_required": True,
    }
