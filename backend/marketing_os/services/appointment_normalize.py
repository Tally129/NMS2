"""Marketing-safe appointment lifecycle normalization.

Converts appointment lifecycle signals into privacy-minimized Marketing OS
conversion payloads. This module NEVER reads or stores PHI: it accepts only
an opaque ``marketing_subject_id`` plus non-clinical marketing dimensions.
It does not query clinical scheduling tables directly and does not modify
appointment workflow.

Only the following lifecycle stages are recognized:
    request created      -> appointment_request
    appointment booked   -> appointment_booked
    appointment completed/show -> appointment_completed
    no-show              -> appointment_no_show
    cancelled            -> appointment_cancelled

Revenue is NEVER derived here. Appointment value estimates are not revenue.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from marketing_os.services.measurement import (
    MarketingDataPolicyError,
    assert_non_phi_marketing_payload,
)

# Map raw appointment lifecycle status -> marketing conversion event_type.
STATUS_TO_EVENT: dict[str, str] = {
    # request lifecycle
    "new": "appointment_request",
    "request": "appointment_request",
    "requested": "appointment_request",
    "pending": "appointment_request",
    "submitted": "appointment_request",
    # booked / scheduled
    "approved": "appointment_booked",
    "booked": "appointment_booked",
    "scheduled": "appointment_booked",
    "confirmed": "appointment_booked",
    # completed / show
    "completed": "appointment_completed",
    "complete": "appointment_completed",
    "show": "appointment_completed",
    "showed": "appointment_completed",
    "checked_out": "appointment_completed",
    # no-show / cancel
    "no_show": "appointment_no_show",
    "noshow": "appointment_no_show",
    "cancelled": "appointment_cancelled",
    "canceled": "appointment_cancelled",
    "declined": "appointment_cancelled",
}

SUPPORTED_EVENTS = frozenset(STATUS_TO_EVENT.values())

# Fields that may accompany an appointment signal (all marketing-safe).
_ALLOWED_DIMENSIONS = (
    "source",
    "medium",
    "campaign",
    "content",
    "term",
    "external_click_id",
    "session_id",
)


def event_type_for_status(status: Any) -> Optional[str]:
    """Deterministically map an appointment status to an event type."""
    key = str(status or "").strip().lower().replace("-", "_").replace(" ", "_")
    return STATUS_TO_EVENT.get(key)


def normalize_appointment_signal(
    signal: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a marketing-safe conversion payload for an appointment stage.

    Requires an opaque ``marketing_subject_id`` and a recognized status.
    Raises ``MarketingDataPolicyError`` for PHI, missing subject, or an
    unrecognized status. ``service_category`` (a non-clinical marketing
    label such as a landing-page category) is optional and stored under
    ``properties``; raw clinical ``service`` names are rejected as PHI-risk
    only if they appear under prohibited keys.
    """
    # Reject any prohibited/PHI fields up front.
    assert_non_phi_marketing_payload(signal)

    subject_id = str(signal.get("marketing_subject_id") or "").strip()
    if not subject_id:
        raise MarketingDataPolicyError(
            "appointment signal requires an opaque marketing_subject_id"
        )

    event_type = event_type_for_status(signal.get("status"))
    if event_type is None:
        raise MarketingDataPolicyError(
            f"unrecognized appointment status: {signal.get('status')!r}"
        )

    properties: dict[str, Any] = {
        "appointment_stage": event_type,
        "normalized_from": "appointment_lifecycle",
    }
    category = signal.get("service_category")
    if category is not None:
        properties["service_interest"] = str(category).strip()

    assert_non_phi_marketing_payload(properties)

    payload: dict[str, Any] = {
        "event_type": event_type,
        "marketing_subject_id": subject_id,
        "properties": properties,
    }
    for field in _ALLOWED_DIMENSIONS:
        value = signal.get(field)
        if value is not None and str(value).strip():
            payload[field] = str(value).strip()

    return payload
