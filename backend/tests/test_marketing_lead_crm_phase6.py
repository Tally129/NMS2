"""Phase 6 — Lead CRM + Appointment Setter workspace.

Covers deterministic pipeline transitions, stage validation, lead creation
from marketing-safe opportunities, owner assignment semantics (service-level),
task types/statuses, overdue calculations, speed-to-lead math, setter metrics
null-vs-zero, PHI rejection, Director advisory behavior, and safety.
"""
from datetime import datetime, timedelta, timezone

import pytest

from marketing_os.services import lead_pipeline as LP
from marketing_os.services.measurement import MarketingDataPolicyError
from marketing_os.services.director import (
    build_marketing_brief,
    recommend_lead_operations,
)


def _dt(minutes_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago))


# --------------------------------------------------------------------------- #
# Pipeline transitions
# --------------------------------------------------------------------------- #

def test_all_stages_defined():
    assert LP.LEAD_STAGES[0] == "new"
    assert "won" in LP.LEAD_STAGES and "lost" in LP.LEAD_STAGES


def test_valid_transition_allowed():
    LP.validate_transition("new", "contacted")
    LP.validate_transition("booked", "showed")
    LP.validate_transition("showed", "won")


def test_invalid_transition_rejected():
    with pytest.raises(LP.LeadTransitionError):
        LP.validate_transition("new", "won")  # cannot skip to won
    with pytest.raises(LP.LeadTransitionError):
        LP.validate_transition("showed", "booked")  # backwards not allowed


def test_terminal_stage_cannot_transition():
    with pytest.raises(LP.LeadTransitionError):
        LP.validate_transition("won", "lost")
    with pytest.raises(LP.LeadTransitionError):
        LP.validate_transition("lost", "new")


def test_unknown_stage_rejected():
    with pytest.raises(LP.LeadTransitionError):
        LP.validate_transition("new", "banana")
    with pytest.raises(LP.LeadTransitionError):
        LP.validate_transition("same", "same")


def test_same_stage_rejected():
    with pytest.raises(LP.LeadTransitionError):
        LP.validate_transition("new", "new")


# --------------------------------------------------------------------------- #
# Lead creation from opportunities + PHI rejection
# --------------------------------------------------------------------------- #

def test_lead_fields_from_opportunity_maps_marketing_safe():
    opp = {
        "marketing_subject_id": "sub_1",
        "source": "google", "medium": "cpc", "campaign": "brand",
        "service_interest": "wellness", "opportunity_score": 82,
        "qualification_score": 70,
    }
    fields = LP.lead_fields_from_opportunity(opp)
    assert fields["marketing_subject_id"] == "sub_1"
    assert fields["priority"] == "high"
    assert fields["opportunity_score"] == 82
    assert fields["campaign_name"] == "brand"


def test_lead_fields_requires_subject():
    with pytest.raises(MarketingDataPolicyError):
        LP.lead_fields_from_opportunity({"source": "google"})


def test_lead_fields_rejects_phi():
    with pytest.raises(MarketingDataPolicyError):
        LP.lead_fields_from_opportunity({
            "marketing_subject_id": "sub_1",
            "email": "patient@example.com",
        })


def test_priority_from_score():
    assert LP.priority_from_score(90) == "high"
    assert LP.priority_from_score(60) == "medium"
    assert LP.priority_from_score(10) == "low"
    assert LP.priority_from_score(None) == "medium"


# --------------------------------------------------------------------------- #
# Speed-to-lead
# --------------------------------------------------------------------------- #

def test_response_seconds_computed():
    lead = {
        "lead_created_at": _dt(10).isoformat(),
        "first_contact_at": _dt(6).isoformat(),  # 4 minutes later
    }
    assert LP.response_seconds(lead) == pytest.approx(240, abs=2)


def test_response_seconds_null_without_timestamps():
    assert LP.response_seconds({"lead_created_at": _dt(5).isoformat()}) is None
    assert LP.response_seconds({}) is None


def test_speed_to_lead_metrics_math():
    leads = [
        {"first_response_seconds": 120},   # within 5 min
        {"first_response_seconds": 600},   # within 15 min
        {"first_response_seconds": 5400},  # over 1 hour
    ]
    m = LP.speed_to_lead_metrics(leads)
    assert m["measured_leads"] == 3
    assert m["median_speed_to_lead_seconds"] == 600.0
    assert m["pct_contacted_within_5_min"] == pytest.approx(1 / 3, abs=1e-4)
    assert m["pct_contacted_within_15_min"] == pytest.approx(2 / 3, abs=1e-4)
    assert m["pct_contacted_within_1_hour"] == pytest.approx(2 / 3, abs=1e-4)


def test_speed_to_lead_unavailable_when_no_timestamps():
    m = LP.speed_to_lead_metrics([{"lead_status": "new"}])
    assert m["measured_leads"] == 0
    assert m["average_speed_to_lead_seconds"] is None
    assert m["pct_contacted_within_5_min"] is None


# --------------------------------------------------------------------------- #
# Setter metrics
# --------------------------------------------------------------------------- #

def test_setter_metrics_empty_is_null_not_zero():
    m = LP.setter_metrics([], [])
    assert m["total_leads"] == 0
    assert m["contact_rate"] is None
    assert m["booking_rate"] is None
    assert m["show_rate"] is None


def test_setter_metrics_counts_and_rates():
    leads = [
        {"id": "1", "lead_status": "new", "assigned_owner_id": "o1"},
        {"id": "2", "lead_status": "contacted", "assigned_owner_id": "o1"},
        {"id": "3", "lead_status": "booked", "assigned_owner_id": "o2"},
        {"id": "4", "lead_status": "showed", "assigned_owner_id": "o2"},
    ]
    m = LP.setter_metrics(leads, [])
    assert m["total_leads"] == 4
    assert m["total_new_leads"] == 1
    # contacted stages: contacted, booked, showed = 3
    assert m["uncontacted_leads"] == 1
    assert m["contact_rate"] == 0.75
    assert m["booking_rate"] == 0.5  # booked + showed = 2 of 4
    assert m["show_rate"] == 0.5     # showed=1 of booked-stages=2
    owners = {o["owner_id"]: o["count"] for o in m["bookings_by_owner"]}
    assert owners["o2"] == 2


def test_overdue_leads_from_open_past_due_task():
    leads = [{"id": "1", "lead_status": "new"}]
    tasks = [{
        "lead_id": "1", "status": "open",
        "due_at": _dt(120).isoformat(),  # 2 hours overdue
    }]
    m = LP.setter_metrics(leads, tasks)
    assert m["overdue_leads"] == 1


def test_completed_task_not_overdue():
    leads = [{"id": "1", "lead_status": "new"}]
    tasks = [{"lead_id": "1", "status": "completed",
              "due_at": _dt(120).isoformat()}]
    m = LP.setter_metrics(leads, tasks)
    assert m["overdue_leads"] == 0


# --------------------------------------------------------------------------- #
# Task + qualification vocab
# --------------------------------------------------------------------------- #

def test_task_and_qualification_vocab():
    assert "call_lead" in LP.TASK_TYPES
    assert "recover_no_show" in LP.TASK_TYPES
    assert set(LP.TASK_STATUSES) == {"open", "completed", "cancelled"}
    assert "qualified" in LP.QUALIFICATION_STATUSES


# --------------------------------------------------------------------------- #
# Director advisory behavior
# --------------------------------------------------------------------------- #

def test_director_lead_ops_recommends_uncontacted_backlog():
    metrics = {
        "total_leads": 20, "uncontacted_leads": 12, "overdue_leads": 6,
        "booking_rate": 0.10, "show_rate": 0.5,
        "speed_to_lead": {"measured_leads": 10,
                          "pct_contacted_within_5_min": 0.2},
    }
    recs = recommend_lead_operations(metrics)
    titles = [r["title"] for r in recs]
    assert any("uncontacted" in t.lower() for t in titles)
    assert any("backlog" in t.lower() for t in titles)
    assert all(r["advisory_only"] and r["requires_human_approval"]
               and r["external_write"] is False for r in recs)


def test_director_lead_ops_no_recs_when_empty():
    assert recommend_lead_operations(None) == []
    assert recommend_lead_operations(LP.setter_metrics([], [])) == []


def test_director_brief_includes_lead_operations():
    metrics = LP.setter_metrics(
        [{"id": "1", "lead_status": "new"}], []
    )
    brief = build_marketing_brief(lead_operations=metrics)
    assert brief["lead_operations"] is not None
    assert brief["lead_operations"]["total_leads"] == 1


# --------------------------------------------------------------------------- #
# Safety
# --------------------------------------------------------------------------- #

def test_pipeline_module_has_no_external_write_paths():
    import inspect
    src = inspect.getsource(LP)
    for banned in ("requests.", "httpx.", "urllib", "execute_action",
                   "smtplib", "send_message"):
        assert banned not in src
