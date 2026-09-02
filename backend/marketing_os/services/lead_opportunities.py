"""
Marketing-safe lead opportunity derivation.

V1 rules:
- Pure/deterministic.
- No database writes.
- No external provider calls.
- No outreach.
- No patient/clinical data.
- No direct-contact identifiers.
- Operates only on privacy-minimized Marketing OS events.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping

from marketing_os.services.measurement import (
    assert_non_phi_marketing_payload,
)


# ---------------------------------------------------------
# Deterministic event weights
# ---------------------------------------------------------

EVENT_WEIGHTS = {
    "page_view": 2,
    "service_page_view": 8,
    "content_engagement": 5,
    "cta_click": 12,
    "phone_click": 18,
    "directions_click": 10,
    "appointment_intent": 28,
    "lead_submit": 40,
    "conversion": 50,
}

HIGH_INTENT_EVENTS = frozenset(
    {
        "appointment_intent",
        "lead_submit",
        "conversion",
    }
)

ALLOWED_EVENT_TYPES = frozenset(
    EVENT_WEIGHTS
)


# ---------------------------------------------------------
# Result model
# ---------------------------------------------------------

@dataclass(frozen=True)
class LeadOpportunity:
    marketing_subject_id: str
    intent_score: int
    qualification_score: int
    opportunity_score: int
    opportunity_tier: str
    event_count: int
    high_intent_event_count: int
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    source: str | None
    medium: str | None
    campaign: str | None
    service_interest: str | None
    latest_event_type: str | None
    recommended_action: str
    explanation: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "marketing_subject_id":
                self.marketing_subject_id,
            "intent_score":
                self.intent_score,
            "qualification_score":
                self.qualification_score,
            "opportunity_score":
                self.opportunity_score,
            "opportunity_tier":
                self.opportunity_tier,
            "event_count":
                self.event_count,
            "high_intent_event_count":
                self.high_intent_event_count,
            "first_seen_at":
                (
                    self.first_seen_at.isoformat()
                    if self.first_seen_at
                    else None
                ),
            "last_seen_at":
                (
                    self.last_seen_at.isoformat()
                    if self.last_seen_at
                    else None
                ),
            "source":
                self.source,
            "medium":
                self.medium,
            "campaign":
                self.campaign,
            "service_interest":
                self.service_interest,
            "latest_event_type":
                self.latest_event_type,
            "recommended_action":
                self.recommended_action,
            "explanation":
                list(self.explanation),
        }


# ---------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------

def _text(
    value: Any,
) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()

    return cleaned or None


def _event_time(
    value: Any,
) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        raw = value.strip()

        if not raw:
            return None

        if raw.endswith("Z"):
            raw = (
                raw[:-1]
                + "+00:00"
            )

        try:
            parsed = datetime.fromisoformat(
                raw
            )
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed


def _properties(
    event: Mapping[str, Any],
) -> dict[str, Any]:
    value = (
        event.get("properties")
        or {}
    )

    if not isinstance(
        value,
        Mapping,
    ):
        return {}

    result = dict(value)

    assert_non_phi_marketing_payload(
        result
    )

    return result


def _service_interest(
    event: Mapping[str, Any],
) -> str | None:
    props = _properties(event)

    for key in (
        "service_interest",
        "service_line",
        "service",
        "offer",
        "landing_page_category",
    ):
        value = _text(
            props.get(key)
        )

        if value:
            return value

    return None


# ---------------------------------------------------------
# Deterministic scoring
# ---------------------------------------------------------

def _intent_score(
    events: list[Mapping[str, Any]],
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    seen_types: set[str] = set()

    for event in events:
        event_type = (
            _text(
                event.get("event_type")
            )
            or ""
        ).lower()

        weight = EVENT_WEIGHTS.get(
            event_type,
            0,
        )

        if weight:
            score += weight

            if event_type not in seen_types:
                reasons.append(
                    f"{event_type} signal +{weight}"
                )

                seen_types.add(
                    event_type
                )

    # Multiple-event engagement indicates
    # repeated intent but remains capped.
    if len(events) >= 3:
        score += 8
        reasons.append(
            "repeated engagement +8"
        )

    if len(events) >= 5:
        score += 7
        reasons.append(
            "sustained engagement +7"
        )

    return (
        min(score, 100),
        reasons,
    )


def _qualification_score(
    events: list[Mapping[str, Any]],
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    latest_source = None
    latest_medium = None
    service_interest = None
    campaign = None

    for event in events:
        latest_source = (
            _text(event.get("source"))
            or latest_source
        )

        latest_medium = (
            _text(event.get("medium"))
            or latest_medium
        )

        campaign = (
            _text(event.get("campaign"))
            or campaign
        )

        service_interest = (
            _service_interest(event)
            or service_interest
        )

    if latest_source:
        score += 15
        reasons.append(
            "attributable source +15"
        )

    if latest_medium:
        score += 10
        reasons.append(
            "attributable medium +10"
        )

    if campaign:
        score += 10
        reasons.append(
            "campaign attribution +10"
        )

    if service_interest:
        score += 30
        reasons.append(
            "service interest identified +30"
        )

    high_intent = sum(
        1
        for event in events
        if (
            _text(
                event.get("event_type")
            )
            or ""
        ).lower()
        in HIGH_INTENT_EVENTS
    )

    if high_intent:
        score += min(
            high_intent * 20,
            40,
        )

        reasons.append(
            "high-intent conversion signal "
            f"+{min(high_intent * 20, 40)}"
        )

    return (
        min(score, 100),
        reasons,
    )


def _tier(
    score: int,
) -> str:
    if score >= 80:
        return "high"

    if score >= 55:
        return "medium"

    return "low"


def _recommended_action(
    *,
    tier: str,
    latest_event_type: str | None,
) -> str:
    if latest_event_type == "conversion":
        return (
            "Review conversion outcome and "
            "exclude completed conversions "
            "from unnecessary lead nurture."
        )

    if tier == "high":
        return (
            "Prioritize for prompt human "
            "follow-up or booking assistance."
        )

    if tier == "medium":
        return (
            "Review for targeted nurture "
            "or a booking-focused follow-up."
        )

    return (
        "Continue marketing-safe nurture "
        "and collect additional intent signals."
    )


# ---------------------------------------------------------
# Public derivation API
# ---------------------------------------------------------

def derive_lead_opportunities(
    events: Iterable[
        Mapping[str, Any]
    ],
) -> list[dict[str, Any]]:
    """
    Group privacy-minimized events by marketing_subject_id
    and derive deterministic opportunity scores.

    Events without marketing_subject_id are intentionally
    excluded because they cannot safely represent a
    persistent lead opportunity.
    """

    grouped: dict[
        str,
        list[Mapping[str, Any]],
    ] = {}

    for raw_event in events:
        event = dict(raw_event)

        assert_non_phi_marketing_payload(
            event
        )

        subject_id = _text(
            event.get(
                "marketing_subject_id"
            )
        )

        if not subject_id:
            continue

        event_type = (
            _text(
                event.get(
                    "event_type"
                )
            )
            or ""
        ).lower()

        if (
            event_type
            not in ALLOWED_EVENT_TYPES
        ):
            continue

        grouped.setdefault(
            subject_id,
            [],
        ).append(event)

    opportunities: list[
        LeadOpportunity
    ] = []

    for (
        subject_id,
        subject_events,
    ) in grouped.items():

        subject_events.sort(
            key=lambda item: (
                _event_time(
                    item.get(
                        "occurred_at"
                    )
                )
                or datetime.min.replace(
                    tzinfo=timezone.utc
                )
            )
        )

        intent, intent_reasons = (
            _intent_score(
                subject_events
            )
        )

        qualification, qualification_reasons = (
            _qualification_score(
                subject_events
            )
        )

        opportunity_score = int(
            round(
                (
                    Decimal(intent)
                    * Decimal("0.60")
                )
                +
                (
                    Decimal(qualification)
                    * Decimal("0.40")
                )
            )
        )

        tier = _tier(
            opportunity_score
        )

        latest = (
            subject_events[-1]
            if subject_events
            else {}
        )

        times = [
            parsed
            for parsed in (
                _event_time(
                    event.get(
                        "occurred_at"
                    )
                )
                for event in subject_events
            )
            if parsed is not None
        ]

        high_intent_count = sum(
            1
            for event in subject_events
            if (
                _text(
                    event.get(
                        "event_type"
                    )
                )
                or ""
            ).lower()
            in HIGH_INTENT_EVENTS
        )

        service_interest = None

        for event in reversed(
            subject_events
        ):
            service_interest = (
                _service_interest(
                    event
                )
            )

            if service_interest:
                break

        latest_event_type = (
            _text(
                latest.get(
                    "event_type"
                )
            )
        )

        opportunities.append(
            LeadOpportunity(
                marketing_subject_id=
                    subject_id,

                intent_score=
                    intent,

                qualification_score=
                    qualification,

                opportunity_score=
                    opportunity_score,

                opportunity_tier=
                    tier,

                event_count=
                    len(
                        subject_events
                    ),

                high_intent_event_count=
                    high_intent_count,

                first_seen_at=
                    (
                        min(times)
                        if times
                        else None
                    ),

                last_seen_at=
                    (
                        max(times)
                        if times
                        else None
                    ),

                source=
                    _text(
                        latest.get(
                            "source"
                        )
                    ),

                medium=
                    _text(
                        latest.get(
                            "medium"
                        )
                    ),

                campaign=
                    _text(
                        latest.get(
                            "campaign"
                        )
                    ),

                service_interest=
                    service_interest,

                latest_event_type=
                    latest_event_type,

                recommended_action=
                    _recommended_action(
                        tier=tier,
                        latest_event_type=
                            latest_event_type,
                    ),

                explanation=tuple(
                    intent_reasons
                    + qualification_reasons
                ),
            )
        )

    opportunities.sort(
        key=lambda item: (
            -item.opportunity_score,
            item.marketing_subject_id,
        )
    )

    return [
        opportunity.as_dict()
        for opportunity
        in opportunities
    ]
