"""Phase 5 — Unified Lead → Appointment → Revenue attribution.

Deterministic, PHI-free coverage for first/last-touch attribution, appointment
attribution, revenue attribution, funnel calculations, unavailable-stage null
handling, no unpaid-invoice revenue, PHI rejection, opaque subject linkage,
source/campaign/channel rollups, cost-per-booked/completed, ROAS on real
revenue only, advisory Director behavior, safety policy, and no external writes.
"""
from datetime import datetime, timezone

import pytest

from marketing_os.services import journey as J
from marketing_os.services.appointment_normalize import (
    event_type_for_status,
    normalize_appointment_signal,
)
from marketing_os.services.director import (
    build_marketing_brief,
    recommend_from_outcomes,
)
from marketing_os.services.measurement import (
    MarketingDataPolicyError,
    NormalizedConversion,
    first_touch_attribution,
    last_touch_attribution,
)


def _ev(subject, event_type, *, source=None, campaign=None, value=None, day=1,
        provider=None, medium=None):
    return {
        "marketing_subject_id": subject,
        "event_type": event_type,
        "source": source,
        "medium": medium,
        "campaign": campaign,
        "provider": provider,
        "value": value,
        "occurred_at": datetime(2026, 6, day, tzinfo=timezone.utc),
    }


def _conv(source, medium=None):
    return NormalizedConversion(
        event_type="conversion", marketing_subject_id="s",
        session_id=None, external_click_id=None, source=source, medium=medium,
        campaign=None, content=None, term=None, value=None, currency=None,
        properties={},
    )


# --------------------------------------------------------------------------- #
# First / last touch attribution
# --------------------------------------------------------------------------- #

def test_first_touch_vs_last_touch_pick_different_touches():
    events = [
        _ev("s1", "page_view", source="google", medium="cpc", day=1),
        _ev("s1", "page_view", source="facebook", medium="social", day=2),
        _ev("s1", "appointment_booked", source="facebook", day=3),
    ]
    first = J.attribute_outcome(
        events, outcome_stage="appointment_booked",
        model="first_touch", dimension="channel",
    )
    last = J.attribute_outcome(
        events, outcome_stage="appointment_booked",
        model="last_touch", dimension="channel",
    )
    assert first["attribution_model"] == "first_touch"
    assert first["credited"][0]["key"] == "google_ads"
    assert last["credited"][0]["key"] == "meta_ads"


def test_measurement_touch_helpers_are_deterministic():
    conv = _conv("google", "cpc")
    assert last_touch_attribution(conv).model == "last_touch"
    assert first_touch_attribution(conv).model == "first_touch"
    assert first_touch_attribution(conv).credit == 1


def test_attribution_source_is_recorded_explicitly():
    events = [_ev("s1", "appointment_booked", source="google")]
    out = J.attribute_outcome(
        events, outcome_stage="appointment_booked",
        model="last_touch", dimension="source",
    )
    assert out["attribution_source"] == "deterministic_marketing_events"
    assert out["dimension"] == "source"


def test_invalid_model_and_dimension_rejected():
    with pytest.raises(ValueError):
        J.attribute_outcome([], outcome_stage="lead", model="nope")
    with pytest.raises(ValueError):
        J.attribute_outcome([], outcome_stage="lead", dimension="nope")


# --------------------------------------------------------------------------- #
# Appointment attribution + normalization
# --------------------------------------------------------------------------- #

def test_appointment_status_maps_to_lifecycle_events():
    assert event_type_for_status("new") == "appointment_request"
    assert event_type_for_status("confirmed") == "appointment_booked"
    assert event_type_for_status("completed") == "appointment_completed"
    assert event_type_for_status("no-show") == "appointment_no_show"
    assert event_type_for_status("canceled") == "appointment_cancelled"
    assert event_type_for_status("banana") is None


def test_appointment_normalize_requires_opaque_subject():
    with pytest.raises(MarketingDataPolicyError):
        normalize_appointment_signal({"status": "confirmed"})


def test_appointment_normalize_rejects_phi():
    with pytest.raises(MarketingDataPolicyError):
        normalize_appointment_signal({
            "marketing_subject_id": "sub_1",
            "status": "confirmed",
            "email": "patient@example.com",
        })


def test_appointment_normalize_produces_marketing_safe_payload():
    payload = normalize_appointment_signal({
        "marketing_subject_id": "sub_opaque_1",
        "status": "no-show",
        "source": "google",
        "campaign": "brand",
        "service_category": "wellness",
    })
    assert payload["event_type"] == "appointment_no_show"
    assert payload["marketing_subject_id"] == "sub_opaque_1"
    assert payload["source"] == "google"
    assert payload["properties"]["service_interest"] == "wellness"
    # No PHI keys present.
    assert "email" not in payload and "full_name" not in payload


# --------------------------------------------------------------------------- #
# Funnel — deterministic + unavailable stays null
# --------------------------------------------------------------------------- #

def test_funnel_counts_distinct_subjects_and_rates():
    events = [
        _ev("a", "lead_submit"), _ev("b", "lead_submit"),
        _ev("a", "appointment_booked"),
        _ev("a", "appointment_completed"),
    ]
    funnel = J.compute_funnel(events)
    assert funnel["stages"]["lead"] == 2
    assert funnel["stages"]["appointment_booked"] == 1
    assert funnel["stages"]["appointment_completed"] == 1
    assert funnel["rates"]["lead_to_booking_rate"] == 0.5
    assert funnel["rates"]["booking_to_show_rate"] == 1.0
    assert funnel["rates"]["lead_to_show_rate"] == 0.5


def test_funnel_unavailable_stage_is_null_not_zero():
    # Only leads tracked; booking/show stages never appear -> null.
    events = [_ev("a", "lead_submit"), _ev("b", "lead_submit")]
    funnel = J.compute_funnel(events)
    assert funnel["stages"]["lead"] == 2
    assert funnel["stages"]["appointment_booked"] is None
    assert funnel["stages"]["appointment_completed"] is None
    assert funnel["rates"]["lead_to_booking_rate"] is None
    assert funnel["rates"]["lead_to_show_rate"] is None


def test_funnel_zero_denominator_rate_is_null():
    # Bookings tracked but no leads -> lead_to_booking denominator null.
    events = [_ev("a", "appointment_booked")]
    funnel = J.compute_funnel(events)
    assert funnel["stages"]["appointment_booked"] == 1
    assert funnel["stages"]["lead"] is None
    assert funnel["rates"]["lead_to_booking_rate"] is None


# --------------------------------------------------------------------------- #
# Opaque subject linkage
# --------------------------------------------------------------------------- #

def test_journeys_exclude_events_without_opaque_subject():
    events = [
        _ev("s1", "lead_submit", source="google"),
        _ev(None, "lead_submit", source="google"),
    ]
    journeys = J.build_journeys(events)
    assert len(journeys) == 1
    assert journeys[0]["marketing_subject_id"] == "s1"


# --------------------------------------------------------------------------- #
# Revenue — real first-party only
# --------------------------------------------------------------------------- #

def test_revenue_only_from_purchase_events_with_value():
    events = [
        _ev("s1", "appointment_completed", source="google"),
        _ev("s1", "purchase", source="google", value="500", day=2),
    ]
    rev = J.compute_revenue(events)
    assert rev["revenue_available"] is True
    assert rev["total_attributed_revenue"] == 500.0
    assert rev["by_channel"][0]["key"] == "google_ads"


def test_appointment_completed_is_not_revenue():
    # An appointment value estimate must never be counted as revenue.
    events = [
        _ev("s1", "appointment_completed", source="google", value="999"),
    ]
    rev = J.compute_revenue(events)
    assert rev["revenue_available"] is False
    assert rev["total_attributed_revenue"] is None


def test_no_revenue_data_returns_unavailable_not_zero():
    events = [_ev("s1", "lead_submit"), _ev("s1", "appointment_booked")]
    rev = J.compute_revenue(events)
    assert rev["revenue_available"] is False
    assert rev["total_attributed_revenue"] is None
    assert rev["by_channel"] is None


def test_purchase_without_value_is_ignored():
    events = [_ev("s1", "purchase", source="google", value=None)]
    rev = J.compute_revenue(events)
    # Revenue tracking exists (purchase event present) but value is null.
    assert rev["revenue_available"] is True
    assert rev["total_attributed_revenue"] == 0.0
    assert rev["purchase_count"] == 0


# --------------------------------------------------------------------------- #
# Channel economics — cost per booked/completed + ROAS
# --------------------------------------------------------------------------- #

def test_channel_economics_cost_and_roas_on_real_revenue():
    events = [
        _ev("s1", "lead_submit", source="google", day=1),
        _ev("s1", "appointment_booked", source="google", day=2),
        _ev("s1", "appointment_completed", source="google", day=3),
        _ev("s1", "purchase", source="google", value="400", day=4),
    ]
    spend = [{"provider": "google_ads", "spend": "100"}]
    econ = J.compute_channel_economics(events, spend)
    row = next(r for r in econ["channels"] if r["channel"] == "google_ads")
    assert row["spend"] == 100.0
    assert row["booked_appointments"] == 1
    assert row["completed_appointments"] == 1
    assert row["cost_per_booked_appointment"] == 100.0
    assert row["cost_per_completed_appointment"] == 100.0
    assert row["attributed_revenue"] == 400.0
    assert row["roas"] == 4.0


def test_channel_economics_roas_null_without_real_revenue():
    events = [
        _ev("s1", "appointment_booked", source="google"),
    ]
    spend = [{"provider": "google_ads", "spend": "100"}]
    econ = J.compute_channel_economics(events, spend)
    row = next(r for r in econ["channels"] if r["channel"] == "google_ads")
    assert row["roas"] is None
    assert row["attributed_revenue"] is None
    assert row["cost_per_booked_appointment"] == 100.0


def test_channel_economics_cost_per_booked_null_when_zero_booked():
    events = [_ev("s1", "lead_submit", source="google")]
    spend = [{"provider": "google_ads", "spend": "100"}]
    econ = J.compute_channel_economics(events, spend)
    row = next(r for r in econ["channels"] if r["channel"] == "google_ads")
    # Booking stage untracked -> booked None -> cost per booked null.
    assert row["booked_appointments"] is None
    assert row["cost_per_booked_appointment"] is None


# --------------------------------------------------------------------------- #
# Rollups by source / campaign / channel
# --------------------------------------------------------------------------- #

def test_source_campaign_channel_rollups():
    events = [
        _ev("s1", "appointment_booked", source="google", campaign="g1"),
        _ev("s2", "appointment_booked", source="google", campaign="g2"),
        _ev("s3", "appointment_booked", source="bing", campaign="b1"),
    ]
    by_channel = J.attribute_outcome(
        events, outcome_stage="appointment_booked", dimension="channel",
    )["credited"]
    by_campaign = J.attribute_outcome(
        events, outcome_stage="appointment_booked", dimension="campaign",
    )["credited"]
    channel_map = {c["key"]: c["attributed_count"] for c in by_channel}
    assert channel_map["google_ads"] == 2
    assert channel_map["microsoft_ads"] == 1
    assert {c["key"] for c in by_campaign} == {"g1", "g2", "b1"}


# --------------------------------------------------------------------------- #
# Director advisory behavior
# --------------------------------------------------------------------------- #

def test_director_recommends_high_spend_no_booking():
    funnel = J.compute_funnel([
        _ev(f"s{i}", "appointment_booked", source="google") for i in range(3)
    ])
    econ = {
        "revenue_available": False,
        "channels": [
            {"channel": "meta_ads", "spend": 300.0,
             "booked_appointments": 0, "completed_appointments": 0,
             "attributed_revenue": None, "roas": None},
        ],
    }
    recs = recommend_from_outcomes(funnel, econ)
    assert any(r["type"] == "efficiency" and r["channel"] == "meta_ads"
               for r in recs)
    assert all(r["advisory_only"] and r["requires_human_approval"]
               and r["external_write"] is False for r in recs)


def test_director_no_outcome_recs_for_unavailable_stages():
    # Nothing tracked -> no fabricated recommendations from outcomes.
    recs = recommend_from_outcomes(J.compute_funnel([]), None)
    assert recs == []


def test_director_brief_includes_journey_outcomes():
    funnel = J.compute_funnel([_ev("s1", "lead_submit")])
    brief = build_marketing_brief(funnel=funnel, channel_economics=None,
                                  revenue=None)
    assert "journey_outcomes" in brief
    assert brief["journey_outcomes"]["funnel"] is not None


# --------------------------------------------------------------------------- #
# Safety + no external writes
# --------------------------------------------------------------------------- #

def test_overview_safety_flags():
    overview = J.build_attribution_overview([], [])
    safety = overview["safety"]
    assert safety["external_writes"] is False
    assert safety["automatic_budget_changes"] is False
    assert safety["automatic_campaign_creation"] is False
    assert safety["automatic_publishing"] is False
    assert safety["human_approval_required"] is True
    assert safety["phi_used"] is False
    assert safety["attribution_type"] == "deterministic"


def test_journey_module_has_no_external_write_paths():
    import inspect
    src = inspect.getsource(J)
    for banned in ("requests.", "httpx.", "urllib", "INSERT ", "UPDATE ",
                   "DELETE ", "execute_action"):
        assert banned not in src, f"unexpected write/network token: {banned}"
