"""Unified Lead → Appointment → Revenue journey & attribution engine.

Deterministic, explainable, and privacy-minimized. Operates ONLY on
marketing-safe conversion events (marketing_conversion_events) and
aggregate spend rows (marketing_daily_metrics). No PHI, no clinical data,
no external writes, no network calls, no probabilistic/AI attribution.

Key rules:
- Subjects are opaque ``marketing_subject_id`` values only.
- A funnel stage with no tracked events anywhere is reported as
  ``None`` (unavailable) — never fabricated as zero. Once a stage is
  tracked, per-segment absence is a real ``0``.
- Revenue is recognized ONLY from ``purchase`` events carrying a real
  ``value`` (never appointment value estimates, never generic events).
- Rates return ``None`` when a required stage is unavailable or the
  denominator is zero.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Optional


# --------------------------------------------------------------------------- #
# Stage + event definitions
# --------------------------------------------------------------------------- #

STAGE_EVENT_TYPES: dict[str, frozenset[str]] = {
    "lead": frozenset({"lead_submit"}),
    "appointment_intent": frozenset({"appointment_intent"}),
    "appointment_request": frozenset({"appointment_request"}),
    "appointment_booked": frozenset({"appointment_booked"}),
    "appointment_completed": frozenset({"appointment_completed"}),
    "no_show": frozenset({"appointment_no_show"}),
}

FUNNEL_ORDER: tuple[str, ...] = (
    "lead",
    "appointment_intent",
    "appointment_request",
    "appointment_booked",
    "appointment_completed",
    "no_show",
)

# Only real first-party paid revenue. Never appointment value estimates.
REVENUE_EVENT_TYPES: frozenset[str] = frozenset({"purchase"})

_EVENT_TO_STAGE: dict[str, str] = {
    event_type: stage
    for stage, event_types in STAGE_EVENT_TYPES.items()
    for event_type in event_types
}

# Deterministic source/provider -> canonical paid channel key.
SOURCE_TO_CHANNEL: dict[str, str] = {
    "google": "google_ads",
    "google_ads": "google_ads",
    "adwords": "google_ads",
    "meta": "meta_ads",
    "meta_ads": "meta_ads",
    "facebook": "meta_ads",
    "fb": "meta_ads",
    "instagram": "meta_ads",
    "ig": "meta_ads",
    "microsoft": "microsoft_ads",
    "microsoft_ads": "microsoft_ads",
    "bing": "microsoft_ads",
}


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #

def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _dec(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _event_time(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _rate(
    numerator: Optional[Decimal | int | float],
    denominator: Optional[Decimal | int | float],
) -> Optional[float]:
    if numerator is None or denominator is None:
        return None
    denom = Decimal(str(denominator))
    if denom == 0:
        return None
    return round(float(Decimal(str(numerator)) / denom), 6)


def normalize_channel(
    source: Optional[str],
    medium: Optional[str] = None,
    provider: Optional[str] = None,
) -> Optional[str]:
    """Resolve a canonical channel key from provider/source (deterministic)."""
    for candidate in (provider, source):
        key = _text(candidate)
        if not key:
            continue
        lowered = key.lower()
        if lowered in SOURCE_TO_CHANNEL:
            return SOURCE_TO_CHANNEL[lowered]
    # Fall back to the raw source so organic / referral channels still roll up.
    src = _text(source)
    return src.lower() if src else None


# --------------------------------------------------------------------------- #
# Journeys
# --------------------------------------------------------------------------- #

def _normalize_event(raw: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    subject = _text(raw.get("marketing_subject_id"))
    event_type = (_text(raw.get("event_type")) or "").lower()
    if not event_type:
        return None
    return {
        "event_type": event_type,
        "occurred_at": _event_time(raw.get("occurred_at")),
        "marketing_subject_id": subject,
        "source": _text(raw.get("source")),
        "medium": _text(raw.get("medium")),
        "campaign": _text(raw.get("campaign")),
        "provider": _text(raw.get("provider")),
        "value": _dec(raw.get("value")),
        "stage": _EVENT_TO_STAGE.get(event_type),
    }


def build_journeys(
    events: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Group events by opaque subject and order touches chronologically."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in events:
        event = _normalize_event(raw)
        if event is None or not event["marketing_subject_id"]:
            continue
        grouped.setdefault(event["marketing_subject_id"], []).append(event)

    journeys: list[dict[str, Any]] = []
    _min = datetime.min.replace(tzinfo=timezone.utc)

    for subject, subject_events in grouped.items():
        subject_events.sort(key=lambda e: (e["occurred_at"] or _min))

        first_touch = _attributable_touch(subject_events, first=True)
        last_touch = _attributable_touch(subject_events, first=False)

        stages_reached = [
            stage
            for stage in FUNNEL_ORDER
            if any(e["stage"] == stage for e in subject_events)
        ]

        journeys.append({
            "marketing_subject_id": subject,
            "event_count": len(subject_events),
            "first_seen_at": _iso(subject_events[0]["occurred_at"]),
            "last_seen_at": _iso(subject_events[-1]["occurred_at"]),
            "first_touch": first_touch,
            "last_touch": last_touch,
            "stages_reached": stages_reached,
            "touches": [
                {
                    "event_type": e["event_type"],
                    "occurred_at": _iso(e["occurred_at"]),
                    "source": e["source"],
                    "medium": e["medium"],
                    "campaign": e["campaign"],
                    "channel": normalize_channel(
                        e["source"], e["medium"], e["provider"]
                    ),
                }
                for e in subject_events
            ],
        })

    journeys.sort(key=lambda j: j["marketing_subject_id"])
    return journeys


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _attributable_touch(
    subject_events: list[dict[str, Any]],
    *,
    first: bool,
) -> Optional[dict[str, Any]]:
    ordered = subject_events if first else list(reversed(subject_events))
    for event in ordered:
        if event["source"] or event["campaign"] or event["provider"]:
            return {
                "source": event["source"],
                "medium": event["medium"],
                "campaign": event["campaign"],
                "channel": normalize_channel(
                    event["source"], event["medium"], event["provider"]
                ),
                "occurred_at": _iso(event["occurred_at"]),
            }
    return None


# --------------------------------------------------------------------------- #
# Funnel
# --------------------------------------------------------------------------- #

def _tracked_stages(
    events: list[dict[str, Any]],
) -> set[str]:
    return {e["stage"] for e in events if e["stage"]}


def compute_funnel(
    events: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Deterministic Lead → Appointment funnel with honest null stages."""
    normalized = [
        e for e in (_normalize_event(raw) for raw in events) if e is not None
    ]
    tracked = _tracked_stages(normalized)

    # Distinct opaque subjects per stage (subjects without id are excluded).
    subjects_by_stage: dict[str, set[str]] = {s: set() for s in FUNNEL_ORDER}
    for e in normalized:
        if e["stage"] and e["marketing_subject_id"]:
            subjects_by_stage[e["stage"]].add(e["marketing_subject_id"])

    counts: dict[str, Optional[int]] = {}
    for stage in FUNNEL_ORDER:
        counts[stage] = (
            len(subjects_by_stage[stage]) if stage in tracked else None
        )

    rates = {
        "lead_to_booking_rate": _rate(
            counts["appointment_booked"], counts["lead"]
        ),
        "booking_to_show_rate": _rate(
            counts["appointment_completed"], counts["appointment_booked"]
        ),
        "lead_to_show_rate": _rate(
            counts["appointment_completed"], counts["lead"]
        ),
        "request_to_booking_rate": _rate(
            counts["appointment_booked"], counts["appointment_request"]
        ),
        "no_show_rate": _rate(
            counts["no_show"], counts["appointment_booked"]
        ),
    }

    return {
        "stages": counts,
        "rates": rates,
        "available_stages": sorted(tracked),
    }


# --------------------------------------------------------------------------- #
# Attribution rollups
# --------------------------------------------------------------------------- #

def _outcome_subjects(
    journeys: list[dict[str, Any]],
    outcome_stage: str,
) -> list[dict[str, Any]]:
    return [j for j in journeys if outcome_stage in j["stages_reached"]]


def attribute_outcome(
    events: Iterable[Mapping[str, Any]],
    *,
    outcome_stage: str,
    model: str = "last_touch",
    dimension: str = "channel",
) -> dict[str, Any]:
    """Credit an outcome (e.g. appointment_booked) to first/last touch.

    ``dimension`` is one of ``channel``, ``source``, ``campaign``.
    Returns deterministic per-key credit counts and the attribution method.
    """
    if model not in ("first_touch", "last_touch"):
        raise ValueError(f"unsupported attribution model: {model!r}")
    if dimension not in ("channel", "source", "campaign"):
        raise ValueError(f"unsupported dimension: {dimension!r}")

    journeys = build_journeys(events)
    rollup: dict[str, int] = {}

    for journey in _outcome_subjects(journeys, outcome_stage):
        touch = journey["first_touch" if model == "first_touch" else
                        "last_touch"]
        key = _dimension_key(touch, dimension)
        rollup[key] = rollup.get(key, 0) + 1

    return {
        "outcome": outcome_stage,
        "attribution_model": model,
        "attribution_source": "deterministic_marketing_events",
        "dimension": dimension,
        "credited": [
            {"key": key, "attributed_count": count}
            for key, count in sorted(
                rollup.items(), key=lambda kv: (-kv[1], kv[0])
            )
        ],
    }


def _dimension_key(
    touch: Optional[Mapping[str, Any]],
    dimension: str,
) -> str:
    if not touch:
        return "unattributed"
    return _text(touch.get(dimension)) or "unattributed"


# --------------------------------------------------------------------------- #
# Revenue (real first-party paid revenue only)
# --------------------------------------------------------------------------- #

def compute_revenue(
    events: Iterable[Mapping[str, Any]],
    *,
    model: str = "last_touch",
) -> dict[str, Any]:
    """Attribute REAL purchase revenue to first/last touch dimensions.

    Only ``purchase`` events carrying a non-null ``value`` are counted.
    Appointment value estimates and unpaid amounts are never included.
    """
    if model not in ("first_touch", "last_touch"):
        raise ValueError(f"unsupported attribution model: {model!r}")

    normalized = [
        e for e in (_normalize_event(raw) for raw in events) if e is not None
    ]
    has_revenue_tracking = any(
        e["event_type"] in REVENUE_EVENT_TYPES for e in normalized
    )

    # Map each subject to its attributable touch.
    journeys = {j["marketing_subject_id"]: j for j in build_journeys(events)}

    by_channel: dict[str, Decimal] = {}
    by_source: dict[str, Decimal] = {}
    by_campaign: dict[str, Decimal] = {}
    total = Decimal(0)
    purchase_count = 0

    for event in normalized:
        if event["event_type"] not in REVENUE_EVENT_TYPES:
            continue
        value = event["value"]
        if value is None:
            continue  # no fabricated revenue
        purchase_count += 1
        total += value

        journey = journeys.get(event["marketing_subject_id"])
        touch = None
        if journey:
            touch = journey[
                "first_touch" if model == "first_touch" else "last_touch"
            ]
        # Fall back to the purchase event's own attribution.
        channel = (
            _dimension_key(touch, "channel")
            if touch
            else (normalize_channel(
                event["source"], event["medium"], event["provider"]
            ) or "unattributed")
        )
        source = (
            _dimension_key(touch, "source") if touch
            else (event["source"] or "unattributed")
        )
        campaign = (
            _dimension_key(touch, "campaign") if touch
            else (event["campaign"] or "unattributed")
        )
        by_channel[channel] = by_channel.get(channel, Decimal(0)) + value
        by_source[source] = by_source.get(source, Decimal(0)) + value
        by_campaign[campaign] = by_campaign.get(campaign, Decimal(0)) + value

    if not has_revenue_tracking:
        # No first-party revenue data at all -> honest unavailable state.
        return {
            "attribution_model": model,
            "attribution_source": "first_party_purchase_events",
            "revenue_available": False,
            "total_attributed_revenue": None,
            "purchase_count": None,
            "by_channel": None,
            "by_source": None,
            "by_campaign": None,
        }

    return {
        "attribution_model": model,
        "attribution_source": "first_party_purchase_events",
        "revenue_available": True,
        "total_attributed_revenue": float(total),
        "purchase_count": purchase_count,
        "by_channel": _decimal_rollup(by_channel),
        "by_source": _decimal_rollup(by_source),
        "by_campaign": _decimal_rollup(by_campaign),
    }


def _decimal_rollup(mapping: dict[str, Decimal]) -> list[dict[str, Any]]:
    return [
        {"key": key, "attributed_revenue": float(amount)}
        for key, amount in sorted(
            mapping.items(), key=lambda kv: (-kv[1], kv[0])
        )
    ]


# --------------------------------------------------------------------------- #
# Channel economics (join spend with outcomes + real revenue)
# --------------------------------------------------------------------------- #

def _spend_by_channel(
    spend_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Decimal]:
    spend: dict[str, Decimal] = {}
    for row in spend_rows:
        channel = normalize_channel(
            row.get("channel"), None, row.get("provider")
        )
        if not channel:
            continue
        amount = _dec(row.get("spend")) or Decimal(0)
        spend[channel] = spend.get(channel, Decimal(0)) + amount
    return spend


def compute_channel_economics(
    events: Iterable[Mapping[str, Any]],
    spend_rows: Iterable[Mapping[str, Any]] = (),
    *,
    model: str = "last_touch",
) -> dict[str, Any]:
    """Per-channel cost-per-booked / cost-per-completed / ROAS.

    ROAS uses ONLY real attributed purchase revenue. Any metric whose
    inputs are unavailable stays ``None`` (never fabricated as zero).
    """
    event_list = list(events)
    spend = _spend_by_channel(spend_rows)

    booked = attribute_outcome(
        event_list, outcome_stage="appointment_booked",
        model=model, dimension="channel",
    )
    completed = attribute_outcome(
        event_list, outcome_stage="appointment_completed",
        model=model, dimension="channel",
    )
    revenue = compute_revenue(event_list, model=model)

    funnel = compute_funnel(event_list)
    booked_tracked = funnel["stages"]["appointment_booked"] is not None
    completed_tracked = funnel["stages"]["appointment_completed"] is not None

    booked_map = {c["key"]: c["attributed_count"] for c in booked["credited"]}
    completed_map = {
        c["key"]: c["attributed_count"] for c in completed["credited"]
    }
    revenue_map = (
        {r["key"]: r["attributed_revenue"] for r in (revenue["by_channel"] or [])}
        if revenue["revenue_available"] else {}
    )

    channels = sorted(
        set(spend) | set(booked_map) | set(completed_map) | set(revenue_map)
    )

    rows: list[dict[str, Any]] = []
    for channel in channels:
        channel_spend = spend.get(channel)
        booked_count = booked_map.get(channel, 0) if booked_tracked else None
        completed_count = (
            completed_map.get(channel, 0) if completed_tracked else None
        )
        attributed_revenue = (
            revenue_map.get(channel, 0.0)
            if revenue["revenue_available"] else None
        )
        rows.append({
            "channel": channel,
            "spend": float(channel_spend) if channel_spend is not None else None,
            "booked_appointments": booked_count,
            "completed_appointments": completed_count,
            "attributed_revenue": attributed_revenue,
            "cost_per_booked_appointment": _rate(channel_spend, booked_count),
            "cost_per_completed_appointment": _rate(
                channel_spend, completed_count
            ),
            "roas": (
                _rate(attributed_revenue, channel_spend)
                if revenue["revenue_available"] else None
            ),
        })

    return {
        "attribution_model": model,
        "revenue_available": revenue["revenue_available"],
        "channels": rows,
    }


# --------------------------------------------------------------------------- #
# Unified overview
# --------------------------------------------------------------------------- #

def build_attribution_overview(
    events: Iterable[Mapping[str, Any]],
    spend_rows: Iterable[Mapping[str, Any]] = (),
    *,
    model: str = "last_touch",
) -> dict[str, Any]:
    event_list = list(events)
    return {
        "attribution_model": model,
        "funnel": compute_funnel(event_list),
        "channels": compute_channel_economics(
            event_list, spend_rows, model=model
        ),
        "revenue": compute_revenue(event_list, model=model),
        "booked_attribution": attribute_outcome(
            event_list, outcome_stage="appointment_booked",
            model=model, dimension="channel",
        ),
        "completed_attribution": attribute_outcome(
            event_list, outcome_stage="appointment_completed",
            model=model, dimension="channel",
        ),
        "safety": {
            "external_writes": False,
            "automatic_budget_changes": False,
            "automatic_campaign_creation": False,
            "automatic_publishing": False,
            "human_approval_required": True,
            "phi_used": False,
            "attribution_type": "deterministic",
        },
    }
