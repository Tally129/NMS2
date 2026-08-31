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
    budgets: Iterable[Mapping[str, Any]] = (),
    performance: Iterable[Mapping[str, Any]] = (),
    budget_performance: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build an advisory cross-channel marketing brief.

    ``performance`` contains provider/channel aggregates used
    for channel-level analysis.

    ``budget_performance`` contains raw campaign/day aggregate
    rows. Budget-specific financial analysis uses only rows
    explicitly mapped through ``budget.allocation.campaigns``.

    No campaign-name matching or channel-wide inference is used.
    """

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

    normalized_budgets = [
        dict(budget)
        for budget in budgets
    ]

    raw_budget_performance = [
        dict(item)
        for item in budget_performance
    ]

    goal_by_id = {
        str(goal.get("id")): goal
        for goal in normalized_goals
        if goal.get("id")
    }

    def clean_text(
        value: Any,
    ) -> str | None:
        if value is None:
            return None

        cleaned = str(value).strip()

        return cleaned or None

    def normalized_campaign_mapping(
        budget: Mapping[str, Any],
    ) -> tuple[
        list[dict[str, str]],
        list[str],
    ]:
        allocation = (
            budget.get("allocation")
            or {}
        )

        if not isinstance(allocation, Mapping):
            return [], [
                "allocation must be an object"
            ]

        campaigns = allocation.get(
            "campaigns",
            [],
        )

        if campaigns is None:
            campaigns = []

        if not isinstance(campaigns, list):
            return [], [
                "allocation.campaigns must be a list"
            ]

        mappings: list[dict[str, str]] = []
        errors: list[str] = []

        for index, raw in enumerate(campaigns):
            if not isinstance(raw, Mapping):
                errors.append(
                    "allocation.campaigns"
                    f"[{index}] must be an object"
                )
                continue

            nms_campaign_id = clean_text(
                raw.get("nms_campaign_id")
            )

            provider = clean_text(
                raw.get("provider")
            )

            external_campaign_id = clean_text(
                raw.get(
                    "external_campaign_id"
                )
            )

            if nms_campaign_id:
                mappings.append(
                    {
                        "nms_campaign_id":
                            nms_campaign_id,
                    }
                )
                continue

            if (
                provider
                and external_campaign_id
            ):
                mappings.append(
                    {
                        "provider":
                            provider.lower(),
                        "external_campaign_id":
                            external_campaign_id,
                    }
                )
                continue

            errors.append(
                "allocation.campaigns"
                f"[{index}] must define either "
                "nms_campaign_id or both provider "
                "and external_campaign_id"
            )

        return mappings, errors

    def date_key(
        value: Any,
    ) -> str | None:
        """Normalize a date/date-like value to YYYY-MM-DD.

        Marketing DB rows use real date objects. The
        helper also supports ISO strings for deterministic
        unit tests.

        Invalid or absent values fail closed when a budget
        period boundary is configured.
        """

        if value is None:
            return None

        isoformat = getattr(
            value,
            "isoformat",
            None,
        )

        if callable(isoformat):
            try:
                value = isoformat()
            except (TypeError, ValueError):
                return None

        cleaned = str(value).strip()

        if len(cleaned) < 10:
            return None

        candidate = cleaned[:10]

        if (
            len(candidate) != 10
            or candidate[4] != "-"
            or candidate[7] != "-"
            or not (
                candidate[:4]
                + candidate[5:7]
                + candidate[8:10]
            ).isdigit()
        ):
            return None

        return candidate


    def row_in_budget_period(
        row: Mapping[str, Any],
        budget: Mapping[str, Any],
    ) -> bool:
        """Return True only for rows inside the budget period.

        Boundaries are inclusive.

        Existing unit-test budgets that intentionally omit
        period dates remain unbounded. Production budgets
        have both boundaries.
        """

        period_start = date_key(
            budget.get("period_start")
        )

        period_end = date_key(
            budget.get("period_end")
        )

        if (
            period_start is None
            and period_end is None
        ):
            return True

        metric_date = date_key(
            row.get("metric_date")
        )

        if metric_date is None:
            return False

        if (
            period_start is not None
            and metric_date < period_start
        ):
            return False

        if (
            period_end is not None
            and metric_date > period_end
        ):
            return False

        return True


    def row_matches_mapping(
        row: Mapping[str, Any],
        mapping: Mapping[str, str],
    ) -> bool:
        mapped_nms_id = mapping.get(
            "nms_campaign_id"
        )

        if mapped_nms_id:
            return (
                clean_text(
                    row.get("nms_campaign_id")
                )
                == mapped_nms_id
            )

        provider = clean_text(
            row.get("provider")
        )

        external_campaign_id = clean_text(
            row.get("external_campaign_id")
        )

        return (
            provider is not None
            and provider.lower()
            == mapping.get("provider")
            and external_campaign_id
            == mapping.get(
                "external_campaign_id"
            )
        )

    budget_analysis = []

    for budget in normalized_budgets:
        goal_id = (
            str(budget.get("goal_id"))
            if budget.get("goal_id")
            else None
        )

        linked_goal = (
            goal_by_id.get(goal_id)
            if goal_id
            else None
        )

        approved_amount = _number(
            budget.get("approved_amount")
        )

        spent_amount = _number(
            budget.get("spent_amount")
        )

        remaining_amount = max(
            approved_amount - spent_amount,
            0.0,
        )

        daily_cap_raw = budget.get(
            "daily_cap"
        )

        target_cpl_raw = budget.get(
            "target_cpl"
        )

        target_cac_raw = budget.get(
            "target_cac"
        )

        minimum_roas_raw = budget.get(
            "minimum_roas"
        )

        configured_targets = {
            "daily_cap": (
                _number(daily_cap_raw)
                if daily_cap_raw is not None
                else None
            ),
            "target_cpl": (
                _number(target_cpl_raw)
                if target_cpl_raw is not None
                else None
            ),
            "target_cac": (
                _number(target_cac_raw)
                if target_cac_raw is not None
                else None
            ),
            "minimum_roas": (
                _number(minimum_roas_raw)
                if minimum_roas_raw
                is not None
                else None
            ),
        }

        mappings, mapping_errors = (
            normalized_campaign_mapping(
                budget
            )
        )

        matched_rows: list[
            dict[str, Any]
        ] = []

        # Fail closed. If any mapping entry is invalid,
        # no budget-specific performance is accepted.
        if mappings and not mapping_errors:
            for row in raw_budget_performance:
                if (
                    row_in_budget_period(
                        row,
                        budget,
                    )
                    and any(
                        row_matches_mapping(
                            row,
                            mapping,
                        )
                        for mapping in mappings
                    )
                ):
                    matched_rows.append(row)

        mapped_impressions = 0
        mapped_clicks = 0
        mapped_leads = 0
        mapped_conversions = 0.0
        mapped_spend = 0.0
        mapped_revenue = 0.0

        for row in matched_rows:
            try:
                mapped_impressions += int(
                    row.get("impressions")
                    or 0
                )
            except (TypeError, ValueError):
                pass

            try:
                mapped_clicks += int(
                    row.get("clicks")
                    or 0
                )
            except (TypeError, ValueError):
                pass

            try:
                mapped_leads += int(
                    row.get("leads")
                    or 0
                )
            except (TypeError, ValueError):
                pass

            try:
                mapped_conversions += float(
                    row.get("conversions")
                    or 0
                )
            except (TypeError, ValueError):
                pass

            try:
                mapped_spend += float(
                    row.get("spend")
                    or 0
                )
            except (TypeError, ValueError):
                pass

            try:
                mapped_revenue += float(
                    row.get(
                        "conversion_value"
                    )
                    or 0
                )
            except (TypeError, ValueError):
                pass

        mapped_cpl = (
            mapped_spend / mapped_leads
            if mapped_leads > 0
            else None
        )

        mapped_cac = (
            mapped_spend
            / mapped_conversions
            if mapped_conversions > 0
            else None
        )

        mapped_roas = (
            mapped_revenue / mapped_spend
            if mapped_spend > 0
            else None
        )

        if mapping_errors:
            mapping_status = (
                "invalid_mapping"
            )

        elif not mappings:
            mapping_status = "unmapped"

        elif matched_rows:
            mapping_status = "mapped"

        else:
            mapping_status = (
                "mapped_no_performance"
            )

        performance_available = bool(
            matched_rows
        )

        budget_analysis.append(
            {
                "budget_id":
                    budget.get("id"),
                "budget_name":
                    budget.get("name"),
                "goal_id":
                    goal_id,
                "goal_name": (
                    linked_goal.get("name")
                    if linked_goal
                    else None
                ),
                "status":
                    budget.get("status"),
                "period_start":
                    budget.get(
                        "period_start"
                    ),
                "period_end":
                    budget.get(
                        "period_end"
                    ),
                "approved_amount": round(
                    approved_amount,
                    2,
                ),
                "spent_amount": round(
                    spent_amount,
                    2,
                ),
                "remaining_amount": round(
                    remaining_amount,
                    2,
                ),
                "targets":
                    configured_targets,

                # Distinguish global Marketing OS
                # performance availability from explicit
                # budget performance linkage.
                "marketing_performance_available":
                    bool(
                        raw_budget_performance
                    ),

                "budget_performance_mapped":
                    bool(mappings)
                    and not mapping_errors,

                "performance_available":
                    performance_available,

                "performance_status":
                    mapping_status,

                "mapping_status":
                    mapping_status,

                "mapping": {
                    "campaigns":
                        mappings,
                    "errors":
                        mapping_errors,
                },

                "mapped_performance": {
                    "row_count":
                        len(matched_rows),
                    "impressions":
                        mapped_impressions,
                    "clicks":
                        mapped_clicks,
                    "leads":
                        mapped_leads,
                    "conversions": round(
                        mapped_conversions,
                        4,
                    ),
                    "spend": round(
                        mapped_spend,
                        2,
                    ),
                    "revenue": round(
                        mapped_revenue,
                        2,
                    ),
                    "cpl": (
                        round(mapped_cpl, 2)
                        if mapped_cpl
                        is not None
                        else None
                    ),
                    "cac": (
                        round(mapped_cac, 2)
                        if mapped_cac
                        is not None
                        else None
                    ),
                    "roas": (
                        round(mapped_roas, 4)
                        if mapped_roas
                        is not None
                        else None
                    ),
                },
            }
        )

        missing_targets = [
            label
            for label, raw_value in (
                ("CPL", target_cpl_raw),
                ("CAC", target_cac_raw),
                (
                    "minimum ROAS",
                    minimum_roas_raw,
                ),
            )
            if raw_value is None
        ]

        if missing_targets:
            target_names = ", ".join(
                missing_targets
            )

            recommendations.append(
                {
                    "type":
                        "budget_configuration",
                    "channel":
                        "internal",
                    "priority":
                        55,
                    "title": (
                        "Complete performance targets for "
                        f"{budget.get('name') or 'marketing budget'}"
                    ),
                    "reason": (
                        "This budget does not yet define "
                        f"{target_names}. The Marketing "
                        "Director will not invent financial "
                        "performance thresholds."
                    ),
                    "proposed_action": (
                        "Review the budget and explicitly "
                        "set only the CPL, CAC, and minimum "
                        "ROAS targets that the business "
                        "wants the Director to enforce."
                    ),
                    "goal_id":
                        goal_id,
                    "budget_id":
                        budget.get("id"),
                    "advisory_only":
                        True,
                    "requires_human_approval":
                        True,
                    "external_write":
                        False,
                }
            )

    recommendations.sort(
        key=lambda item: (
            -int(item["priority"]),
            item["channel"],
            item["type"],
        )
    )

    return {
        "status": "advisory",
        "goals": normalized_goals,
        "budgets": normalized_budgets,
        "budget_analysis": budget_analysis,
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
