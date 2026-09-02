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
from typing import Any, Iterable, Mapping, Optional


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


def recommend_from_outcomes(
    funnel: Optional[Mapping[str, Any]] = None,
    channel_economics: Optional[Mapping[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Advisory recommendations from first-party lead/appointment outcomes.

    Recommendations are generated ONLY where real outcome data exists.
    Unavailable (``None``) stages/metrics never trigger a recommendation,
    so disconnected or untracked stages are never treated as zero.
    """

    recommendations: list[dict[str, Any]] = []

    funnel = funnel or {}
    stages = funnel.get("stages") or {}
    rates = funnel.get("rates") or {}

    leads = stages.get("lead")
    booked = stages.get("appointment_booked")

    lead_to_booking = rates.get("lead_to_booking_rate")
    booking_to_show = rates.get("booking_to_show_rate")
    request_to_booking = rates.get("request_to_booking_rate")

    # Strong lead volume but weak lead -> booking conversion.
    if (
        isinstance(leads, int) and leads >= 10
        and lead_to_booking is not None
        and lead_to_booking < 0.15
    ):
        recommendations.append(_recommendation(
            recommendation_type="conversion",
            channel="funnel",
            priority=88,
            title="Improve lead-to-booking conversion",
            reason=(
                "Lead volume is healthy but a low share of leads become "
                "booked appointments."
            ),
            proposed_action=(
                "Review intake response time, booking friction, and "
                "follow-up cadence. No spend change is proposed."
            ),
        ))

    # Strong booked rate but poor show rate.
    if booking_to_show is not None and booking_to_show < 0.6 and (
        isinstance(booked, int) and booked >= 5
    ):
        recommendations.append(_recommendation(
            recommendation_type="retention",
            channel="funnel",
            priority=84,
            title="Reduce appointment no-shows",
            reason=(
                "Appointments are being booked but a low share are "
                "completed (shown)."
            ),
            proposed_action=(
                "Review reminders and confirmation flow. Advisory only."
            ),
        ))

    # Weak landing/request -> booking conversion.
    if request_to_booking is not None and request_to_booking < 0.3 and (
        isinstance(stages.get("appointment_request"), int)
        and stages["appointment_request"] >= 5
    ):
        recommendations.append(_recommendation(
            recommendation_type="conversion",
            channel="funnel",
            priority=78,
            title="Investigate weak request-to-booking conversion",
            reason=(
                "Many appointment requests are not converting into booked "
                "appointments."
            ),
            proposed_action=(
                "Review landing-page alignment, scheduling availability, "
                "and request handling."
            ),
        ))

    economics = channel_economics or {}
    revenue_available = bool(economics.get("revenue_available"))

    for row in economics.get("channels", []) or []:
        channel = str(row.get("channel") or "unknown")
        spend = row.get("spend")
        booked_count = row.get("booked_appointments")
        completed_count = row.get("completed_appointments")
        attributed_revenue = row.get("attributed_revenue")
        roas = row.get("roas")

        # High spend but zero booked appointments (booking IS tracked).
        if (
            isinstance(spend, (int, float)) and spend > 0
            and booked_count == 0
        ):
            recommendations.append(_recommendation(
                recommendation_type="efficiency",
                channel=channel,
                priority=92,
                title=f"Review {channel} spend with no booked appointments",
                reason=(
                    "This channel has recorded spend but no attributed "
                    "booked appointments."
                ),
                proposed_action=(
                    "Investigate tracking, targeting, and landing "
                    "experience before any budget decision. Advisory only."
                ),
            ))

        # Channel generating appointments but little/no real revenue.
        if (
            revenue_available
            and isinstance(booked_count, int) and booked_count >= 3
            and (attributed_revenue is not None and attributed_revenue <= 0)
        ):
            recommendations.append(_recommendation(
                recommendation_type="revenue",
                channel=channel,
                priority=80,
                title=f"{channel} books appointments but shows no revenue",
                reason=(
                    "Attributed booked appointments are not yet linked to "
                    "real first-party revenue."
                ),
                proposed_action=(
                    "Verify revenue attribution and downstream conversion. "
                    "Advisory only."
                ),
            ))

        # High-ROAS channel with real revenue and completed appointments.
        if (
            revenue_available and roas is not None and roas >= 3.0
            and isinstance(completed_count, int) and completed_count >= 3
        ):
            recommendations.append(_recommendation(
                recommendation_type="growth",
                channel=channel,
                priority=72,
                title=f"Evaluate scaling {channel} (high attributed ROAS)",
                reason=(
                    "This channel shows strong attributed revenue from "
                    "completed appointments."
                ),
                proposed_action=(
                    "Prepare a conservative scaling proposal for human "
                    "approval. Do not change budget automatically."
                ),
            ))

    return recommendations


def recommend_lead_operations(
    metrics: Optional[Mapping[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Advisory operational insights for the setter/lead workspace.

    Recommendations only. The Director never assigns staff, changes lead
    status, contacts leads, or books/changes appointments. Insights are
    generated only where real data exists; unavailable (``None``) metrics
    never trigger a recommendation.
    """
    metrics = metrics or {}
    recs: list[dict[str, Any]] = []

    total = metrics.get("total_leads") or 0
    uncontacted = metrics.get("uncontacted_leads")
    overdue = metrics.get("overdue_leads")
    booking_rate = metrics.get("booking_rate")
    show_rate = metrics.get("show_rate")
    speed = metrics.get("speed_to_lead") or {}
    within5 = speed.get("pct_contacted_within_5_min")

    if isinstance(uncontacted, int) and total and uncontacted >= 5 and (
        uncontacted / total >= 0.4
    ):
        recs.append(_recommendation(
            recommendation_type="operations",
            channel="lead_ops",
            priority=90,
            title="High volume of uncontacted leads",
            reason=(
                "A large share of leads have not yet been contacted."
            ),
            proposed_action=(
                "Prioritize the New Leads and Needs Attention queues. "
                "Advisory only — no automatic outreach."
            ),
        ))

    if isinstance(overdue, int) and overdue >= 5:
        recs.append(_recommendation(
            recommendation_type="operations",
            channel="lead_ops",
            priority=86,
            title="Lead follow-up backlog is increasing",
            reason=f"{overdue} leads have overdue follow-up tasks.",
            proposed_action=(
                "Work the Follow Up Today queue to clear overdue tasks."
            ),
        ))

    if within5 is not None and within5 < 0.5 and (
        speed.get("measured_leads") or 0
    ) >= 5:
        recs.append(_recommendation(
            recommendation_type="operations",
            channel="lead_ops",
            priority=82,
            title="Speed-to-lead needs improvement",
            reason=(
                "Fewer than half of measured leads are contacted within "
                "5 minutes."
            ),
            proposed_action=(
                "Tighten first-response workflow for new leads."
            ),
        ))

    if booking_rate is not None and booking_rate < 0.15 and total >= 10:
        recs.append(_recommendation(
            recommendation_type="operations",
            channel="lead_ops",
            priority=80,
            title="Leads are converting to bookings at a low rate",
            reason=(
                "Booking rate across current leads is low relative to "
                "lead volume."
            ),
            proposed_action=(
                "Review qualification and scheduling assistance steps."
            ),
        ))

    if show_rate is not None and show_rate < 0.6:
        recs.append(_recommendation(
            recommendation_type="operations",
            channel="lead_ops",
            priority=78,
            title="High no-show volume requires follow-up",
            reason="A low share of booked leads are showing.",
            proposed_action=(
                "Prioritize the No Show and Confirm Appointment queues."
            ),
        ))

    return recs




def build_marketing_brief(
    *,
    goals: Iterable[Mapping[str, Any]] = (),
    budgets: Iterable[Mapping[str, Any]] = (),
    performance: Iterable[Mapping[str, Any]] = (),
    budget_performance: Iterable[Mapping[str, Any]] = (),
    paid_media: Optional[Mapping[str, Any]] = None,
    funnel: Optional[Mapping[str, Any]] = None,
    channel_economics: Optional[Mapping[str, Any]] = None,
    revenue: Optional[Mapping[str, Any]] = None,
    lead_operations: Optional[Mapping[str, Any]] = None,
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

    # First-party lead -> appointment -> revenue outcome recommendations.
    recommendations.extend(
        recommend_from_outcomes(funnel, channel_economics)
    )

    # Operational setter/lead-workspace insights (advisory only).
    recommendations.extend(
        recommend_lead_operations(lead_operations)
    )

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
        "paid_media": (
            dict(paid_media) if paid_media is not None else None
        ),
        "journey_outcomes": {
            "funnel": dict(funnel) if funnel is not None else None,
            "channel_economics": (
                dict(channel_economics)
                if channel_economics is not None else None
            ),
            "revenue": dict(revenue) if revenue is not None else None,
        },
        "lead_operations": (
            dict(lead_operations) if lead_operations is not None else None
        ),
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
