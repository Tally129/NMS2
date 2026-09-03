"""Deterministic Phase 8B appointment-recovery event rules (pure).

Maps already-sanitized, marketing-safe appointment lifecycle events (produced
by ``appointment_normalize``) to a deterministic recovery decision. No DB, no
network, no AI, no PHI. This module never reads clinical data — it only works
with normalized ``event_type`` strings.

Decisions:
    enroll   -> eligible for recovery/nurture enrollment (with trigger_type)
    suppress -> stop active recovery (a positive/terminal appointment signal)
    ignore   -> recognized but no recovery action
"""

from __future__ import annotations

from typing import Optional

# Normalized appointment event_type -> nurture sequence trigger_type.
EVENT_TO_TRIGGER: dict[str, str] = {
    "appointment_request": "appointment_requested",
    "appointment_no_show": "no_show",
    "appointment_cancelled": "appointment_cancelled",
}

# Events that indicate the subject converted / no longer needs recovery.
SUPPRESSION_EVENTS: frozenset[str] = frozenset({
    "appointment_booked",
    "appointment_completed",
})

DECISION_ENROLL = "enroll"
DECISION_SUPPRESS = "suppress"
DECISION_IGNORE = "ignore"


def classify_event(event_type: str) -> tuple[str, Optional[str]]:
    """Return (decision, trigger_type). Deterministic and total.

    - enroll   -> ("enroll", trigger_type)
    - suppress -> ("suppress", None)
    - ignore   -> ("ignore", None)
    """
    key = str(event_type or "").strip().lower()
    if key in EVENT_TO_TRIGGER:
        return DECISION_ENROLL, EVENT_TO_TRIGGER[key]
    if key in SUPPRESSION_EVENTS:
        return DECISION_SUPPRESS, None
    return DECISION_IGNORE, None
