"""Deterministic Marketing OS lead pipeline + setter operations.

Pure/deterministic. No DB writes, no network, no external provider calls,
no automatic outreach, no PHI. Stage transitions are validated by explicit
rules — never inferred by AI. Metrics distinguish unavailable (``None``)
from a real zero and never fabricate timestamps.
"""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Any, Iterable, Mapping, Optional

from marketing_os.services.measurement import (
    MarketingDataPolicyError,
    assert_non_phi_marketing_payload,
)


# --------------------------------------------------------------------------- #
# Pipeline stages + deterministic transitions
# --------------------------------------------------------------------------- #

LEAD_STAGES: tuple[str, ...] = (
    "new",
    "contact_attempted",
    "contacted",
    "qualified",
    "nurture",
    "appointment_requested",
    "booked",
    "confirmed",
    "showed",
    "no_show",
    "won",
    "lost",
)

# Terminal stages allow no further transitions.
_TERMINAL = {"won", "lost"}

# Deterministic allowed transitions (staff action or deterministic event).
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "new": frozenset({"contact_attempted", "contacted", "nurture",
                      "appointment_requested", "lost"}),
    "contact_attempted": frozenset({"contact_attempted", "contacted",
                                    "nurture", "appointment_requested",
                                    "lost"}),
    "contacted": frozenset({"qualified", "nurture", "appointment_requested",
                            "lost"}),
    "qualified": frozenset({"nurture", "appointment_requested", "booked",
                            "lost"}),
    "nurture": frozenset({"contacted", "qualified", "appointment_requested",
                          "lost"}),
    "appointment_requested": frozenset({"booked", "nurture", "lost"}),
    "booked": frozenset({"confirmed", "showed", "no_show", "lost"}),
    "confirmed": frozenset({"showed", "no_show", "lost"}),
    "showed": frozenset({"won", "lost"}),
    "no_show": frozenset({"appointment_requested", "booked", "nurture",
                          "lost"}),
    "won": frozenset(),
    "lost": frozenset(),
}

TASK_TYPES: tuple[str, ...] = (
    "call_lead",
    "email_lead",
    "review_qualification",
    "schedule_appointment",
    "confirm_appointment",
    "recover_no_show",
    "follow_up_later",
)

TASK_STATUSES: tuple[str, ...] = ("open", "completed", "cancelled")

QUALIFICATION_STATUSES: tuple[str, ...] = (
    "unqualified",
    "in_review",
    "qualified",
    "disqualified",
)

PRIORITIES: tuple[str, ...] = ("low", "medium", "high")


class LeadTransitionError(ValueError):
    """Raised when a lead stage transition is not deterministically allowed."""


def validate_transition(current: str, target: str) -> None:
    current = (current or "").strip().lower()
    target = (target or "").strip().lower()
    if target not in LEAD_STAGES:
        raise LeadTransitionError(f"unknown lead stage: {target!r}")
    if current not in LEAD_STAGES:
        raise LeadTransitionError(f"unknown current stage: {current!r}")
    if current == target:
        raise LeadTransitionError("lead is already in the requested stage")
    if current in _TERMINAL:
        raise LeadTransitionError(
            f"{current!r} is terminal and cannot transition"
        )
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise LeadTransitionError(
            f"transition {current!r} -> {target!r} is not allowed"
        )


def priority_from_score(score: Optional[int]) -> str:
    if score is None:
        return "medium"
    if score >= 80:
        return "high"
    if score >= 55:
        return "medium"
    return "low"


# --------------------------------------------------------------------------- #
# Lead creation from marketing-safe opportunities
# --------------------------------------------------------------------------- #

def lead_fields_from_opportunity(
    opportunity: Mapping[str, Any],
) -> dict[str, Any]:
    """Map a derived lead-opportunity into marketing-safe lead fields.

    Rejects any PHI. Requires an opaque ``marketing_subject_id``.
    """
    assert_non_phi_marketing_payload(dict(opportunity))

    subject = str(opportunity.get("marketing_subject_id") or "").strip()
    if not subject:
        raise MarketingDataPolicyError(
            "lead requires an opaque marketing_subject_id"
        )

    score = opportunity.get("opportunity_score")
    return {
        "marketing_subject_id": subject,
        "source": opportunity.get("source"),
        "medium": opportunity.get("medium"),
        "campaign_name": opportunity.get("campaign"),
        "service_interest": opportunity.get("service_interest"),
        "opportunity_score": score,
        "qualification_score": opportunity.get("qualification_score"),
        "priority": priority_from_score(score),
    }


# --------------------------------------------------------------------------- #
# Speed-to-lead
# --------------------------------------------------------------------------- #

def _parse_dt(value: Any) -> Optional[datetime]:
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


def response_seconds(lead: Mapping[str, Any]) -> Optional[int]:
    """Seconds from lead creation to first contact. Null if unavailable."""
    created = _parse_dt(lead.get("lead_created_at")) or _parse_dt(
        lead.get("created_at")
    )
    contacted = _parse_dt(lead.get("first_contact_at"))
    if created is None or contacted is None:
        return None
    delta = (contacted - created).total_seconds()
    if delta < 0:
        return None
    return int(delta)


def _pct(count: int, total: int) -> Optional[float]:
    if total <= 0:
        return None
    return round(count / total, 4)


def speed_to_lead_metrics(
    leads: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Deterministic speed-to-lead metrics. Unavailable stays null."""
    durations: list[int] = []
    for lead in leads:
        stored = lead.get("first_response_seconds")
        seconds = stored if isinstance(stored, int) else response_seconds(lead)
        if seconds is not None:
            durations.append(seconds)

    measured = len(durations)
    if measured == 0:
        return {
            "measured_leads": 0,
            "average_speed_to_lead_seconds": None,
            "median_speed_to_lead_seconds": None,
            "pct_contacted_within_5_min": None,
            "pct_contacted_within_15_min": None,
            "pct_contacted_within_1_hour": None,
        }

    return {
        "measured_leads": measured,
        "average_speed_to_lead_seconds": round(sum(durations) / measured, 2),
        "median_speed_to_lead_seconds": float(median(durations)),
        "pct_contacted_within_5_min": _pct(
            sum(1 for d in durations if d <= 300), measured
        ),
        "pct_contacted_within_15_min": _pct(
            sum(1 for d in durations if d <= 900), measured
        ),
        "pct_contacted_within_1_hour": _pct(
            sum(1 for d in durations if d <= 3600), measured
        ),
    }


# --------------------------------------------------------------------------- #
# Setter metrics
# --------------------------------------------------------------------------- #

_CONTACTED_STAGES = {
    "contacted", "qualified", "nurture", "appointment_requested",
    "booked", "confirmed", "showed", "no_show", "won", "lost",
}
_QUALIFIED_STAGES = {
    "qualified", "appointment_requested", "booked", "confirmed",
    "showed", "no_show", "won",
}
_BOOKED_STAGES = {"booked", "confirmed", "showed", "no_show", "won"}
_SHOWED_STAGES = {"showed", "won"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def setter_metrics(
    leads: list[Mapping[str, Any]],
    tasks: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Operational setter metrics. Distinguishes unavailable from zero."""
    total = len(leads)
    now = _now()

    if total == 0:
        # No leads tracked at all -> rates unavailable (null), not zero.
        base_null = {
            "total_leads": 0,
            "total_new_leads": 0,
            "uncontacted_leads": 0,
            "overdue_leads": 0,
            "contact_rate": None,
            "qualification_rate": None,
            "booking_rate": None,
            "show_rate": None,
            "won_rate": None,
            "leads_by_owner": [],
            "bookings_by_owner": [],
            "speed_to_lead": speed_to_lead_metrics([]),
        }
        return base_null

    statuses = [(lead.get("lead_status") or "new").lower() for lead in leads]

    new_leads = sum(1 for s in statuses if s == "new")
    contacted = sum(1 for s in statuses if s in _CONTACTED_STAGES)
    uncontacted = total - contacted
    qualified = sum(1 for s in statuses if s in _QUALIFIED_STAGES)
    booked = sum(1 for s in statuses if s in _BOOKED_STAGES)
    showed = sum(1 for s in statuses if s in _SHOWED_STAGES)
    won = sum(1 for s in statuses if s == "won")

    # Overdue leads: an open task past due, or a next_action_at in the past.
    overdue_lead_ids: set[str] = set()
    tasks_by_lead: dict[str, list[Mapping[str, Any]]] = {}
    for task in tasks:
        tasks_by_lead.setdefault(str(task.get("lead_id")), []).append(task)
        due = _parse_dt(task.get("due_at"))
        if (
            (task.get("status") or "open").lower() == "open"
            and due is not None and due < now
        ):
            overdue_lead_ids.add(str(task.get("lead_id")))
    for lead in leads:
        nxt = _parse_dt(lead.get("next_action_at"))
        if nxt is not None and nxt < now and (
            (lead.get("lead_status") or "new").lower() not in _TERMINAL
        ):
            overdue_lead_ids.add(str(lead.get("id")))

    # By-owner rollups (only assigned leads; unassigned grouped separately).
    owner_leads: dict[str, int] = {}
    owner_bookings: dict[str, int] = {}
    for lead, status in zip(leads, statuses):
        owner = lead.get("assigned_owner_id") or "unassigned"
        owner_leads[owner] = owner_leads.get(owner, 0) + 1
        if status in _BOOKED_STAGES:
            owner_bookings[owner] = owner_bookings.get(owner, 0) + 1

    return {
        "total_leads": total,
        "total_new_leads": new_leads,
        "uncontacted_leads": uncontacted,
        "overdue_leads": len(overdue_lead_ids),
        "contact_rate": _pct(contacted, total),
        "qualification_rate": _pct(qualified, total),
        "booking_rate": _pct(booked, total),
        "show_rate": _pct(showed, booked) if booked else None,
        "won_rate": _pct(won, total),
        "leads_by_owner": [
            {"owner_id": owner, "count": count}
            for owner, count in sorted(
                owner_leads.items(), key=lambda kv: (-kv[1], kv[0])
            )
        ],
        "bookings_by_owner": [
            {"owner_id": owner, "count": count}
            for owner, count in sorted(
                owner_bookings.items(), key=lambda kv: (-kv[1], kv[0])
            )
        ],
        "speed_to_lead": speed_to_lead_metrics(leads),
    }
