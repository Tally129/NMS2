"""Phase 8B deterministic appointment-recovery event rules — pure unit tests."""

import pytest

from marketing_os.services import nurture_events as ev
from marketing_os.services.appointment_normalize import (
    event_type_for_status,
    normalize_appointment_signal,
)
from marketing_os.services.measurement import MarketingDataPolicyError


# --------------------------------------------------------------------------- #
# classify_event — deterministic + total
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("event_type,trigger", [
    ("appointment_request", "appointment_requested"),
    ("appointment_no_show", "no_show"),
    ("appointment_cancelled", "appointment_cancelled"),
])
def test_classify_enroll_events(event_type, trigger):
    decision, tt = ev.classify_event(event_type)
    assert decision == ev.DECISION_ENROLL
    assert tt == trigger


@pytest.mark.parametrize("event_type", [
    "appointment_booked",
    "appointment_completed",
])
def test_classify_suppression_events(event_type):
    decision, tt = ev.classify_event(event_type)
    assert decision == ev.DECISION_SUPPRESS
    assert tt is None


@pytest.mark.parametrize("event_type", ["", "unknown", "something_else"])
def test_classify_ignore_events(event_type):
    decision, tt = ev.classify_event(event_type)
    assert decision == ev.DECISION_IGNORE
    assert tt is None


def test_classify_is_case_insensitive():
    assert ev.classify_event("APPOINTMENT_NO_SHOW")[0] == ev.DECISION_ENROLL


# --------------------------------------------------------------------------- #
# Reuse of appointment_normalize (no duplication)
# --------------------------------------------------------------------------- #

def test_status_maps_to_recovery_event():
    assert event_type_for_status("no-show") == "appointment_no_show"
    assert event_type_for_status("cancelled") == "appointment_cancelled"
    assert event_type_for_status("requested") == "appointment_request"


def test_normalize_requires_opaque_subject():
    with pytest.raises(MarketingDataPolicyError):
        normalize_appointment_signal({"status": "no_show"})


def test_normalize_rejects_phi_fields():
    with pytest.raises(MarketingDataPolicyError):
        normalize_appointment_signal({
            "marketing_subject_id": "subj_1",
            "status": "no_show",
            "email": "patient@example.com",
        })


def test_normalize_no_show_signal_is_marketing_safe():
    out = normalize_appointment_signal({
        "marketing_subject_id": "subj_1",
        "status": "no_show",
        "source": "google",
        "medium": "cpc",
        "service_category": "wellness",
    })
    assert out["event_type"] == "appointment_no_show"
    assert out["marketing_subject_id"] == "subj_1"
    # No PHI / contact keys leaked into the normalized payload.
    flat = str(out).lower()
    assert "@" not in flat
    assert "phone" not in flat


def test_full_pipeline_no_show_enrolls():
    normalized = normalize_appointment_signal({
        "marketing_subject_id": "subj_x",
        "status": "no_show",
    })
    decision, trigger = ev.classify_event(normalized["event_type"])
    assert decision == ev.DECISION_ENROLL
    assert trigger == "no_show"


def test_full_pipeline_booked_suppresses():
    normalized = normalize_appointment_signal({
        "marketing_subject_id": "subj_x",
        "status": "booked",
    })
    decision, _ = ev.classify_event(normalized["event_type"])
    assert decision == ev.DECISION_SUPPRESS
