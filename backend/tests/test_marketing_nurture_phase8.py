"""Phase 8A deterministic nurture rules — pure unit tests (no DB/network)."""

from datetime import datetime, timedelta, timezone

import pytest

from marketing_os.services.measurement import MarketingDataPolicyError
from marketing_os.services import nurture as rules
from marketing_os.services.nurture import NurtureConfigError
from marketing_os.services.nurture_dispatch import (
    OUTREACH_HOLD_REASON,
    email_hold_decision,
)


# --------------------------------------------------------------------------- #
# Sequence validation
# --------------------------------------------------------------------------- #

def test_valid_sequence_defaults_stop_statuses():
    out = rules.validate_sequence_payload({
        "name": "Recovery",
        "slug": "recovery-seq",
    })
    assert out["trigger_type"] == "manual"
    assert out["status"] == "draft"
    assert set(out["stop_on_statuses"]) == set(rules.DEFAULT_STOP_STATUSES)
    assert out["audience_config"] == {}


def test_sequence_rejects_bad_slug():
    with pytest.raises(NurtureConfigError):
        rules.validate_sequence_payload({"name": "x", "slug": "Bad Slug!"})


def test_sequence_rejects_unknown_trigger():
    with pytest.raises(NurtureConfigError):
        rules.validate_sequence_payload({
            "name": "x", "slug": "ok-slug", "trigger_type": "telepathy",
        })


def test_sequence_rejects_unknown_stop_status():
    with pytest.raises(NurtureConfigError):
        rules.validate_sequence_payload({
            "name": "x", "slug": "ok-slug",
            "stop_on_statuses": ["booked", "not_a_status"],
        })


def test_audience_config_rejects_unknown_field():
    with pytest.raises(NurtureConfigError):
        rules.validate_sequence_payload({
            "name": "x", "slug": "ok-slug",
            "audience_config": {"favorite_color": "blue"},
        })


def test_audience_config_rejects_phi_key():
    # measurement guard rejects prohibited/PHI-ish keys inside bounded json
    with pytest.raises((MarketingDataPolicyError, NurtureConfigError)):
        rules.validate_sequence_payload({
            "name": "x", "slug": "ok-slug",
            "audience_config": {"email": "a@b.com"},
        })


# --------------------------------------------------------------------------- #
# Step validation
# --------------------------------------------------------------------------- #

def test_email_step_requires_subject_and_body():
    with pytest.raises(NurtureConfigError):
        rules.validate_step_payload({
            "step_key": "s1", "action_type": "send_email",
        })


def test_email_step_ok():
    out = rules.validate_step_payload({
        "step_key": "welcome",
        "action_type": "send_email",
        "delay_minutes": 0,
        "subject": "We saved your spot",
        "body_html": "<p>Hello there, ready to book?</p>",
    })
    assert out["channel"] == "email"
    assert out["subject"].startswith("We saved")


def test_email_step_rejects_email_address_in_body():
    with pytest.raises(MarketingDataPolicyError):
        rules.validate_step_payload({
            "step_key": "welcome",
            "action_type": "send_email",
            "subject": "hi",
            "body_html": "<p>contact me at john.doe@example.com</p>",
        })


def test_email_step_rejects_phone_in_subject():
    with pytest.raises(MarketingDataPolicyError):
        rules.validate_step_payload({
            "step_key": "welcome",
            "action_type": "send_email",
            "subject": "call 404-555-1212 now",
            "body_html": "<p>hi</p>",
        })


def test_email_step_rejects_oversize_body():
    with pytest.raises(NurtureConfigError):
        rules.validate_step_payload({
            "step_key": "welcome",
            "action_type": "send_email",
            "subject": "hi",
            "body_html": "x" * (rules.MAX_BODY_HTML_LEN + 1),
        })


def test_create_task_requires_valid_task_type():
    with pytest.raises(NurtureConfigError):
        rules.validate_step_payload({
            "step_key": "t1", "action_type": "create_task",
            "config": {"task_type": "not_a_task"},
        })


def test_create_task_ok():
    out = rules.validate_step_payload({
        "step_key": "t1", "action_type": "create_task",
        "config": {"task_type": "recover_no_show", "due_in_minutes": 60},
    })
    assert out["channel"] == "internal"


def test_step_rejects_negative_delay():
    with pytest.raises(NurtureConfigError):
        rules.validate_step_payload({
            "step_key": "t1", "action_type": "wait", "delay_minutes": -5,
        })


def test_step_rejects_bad_action_type():
    with pytest.raises(NurtureConfigError):
        rules.validate_step_payload({
            "step_key": "t1", "action_type": "phone_call",
        })


# --------------------------------------------------------------------------- #
# Scheduling + stop logic
# --------------------------------------------------------------------------- #

def test_scheduled_at_cumulative():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    step = {"delay_minutes": 90}
    assert rules.scheduled_at_for(base, step) == base + timedelta(minutes=90)


def test_ordered_steps_sorts_by_position():
    steps = [
        {"position": 2, "step_key": "b"},
        {"position": 0, "step_key": "a"},
        {"position": 1, "step_key": "c"},
    ]
    ordered = rules.ordered_steps(steps)
    assert [s["step_key"] for s in ordered] == ["a", "c", "b"]


@pytest.mark.parametrize("status", ["booked", "confirmed", "showed", "won",
                                    "lost"])
def test_should_stop_default_statuses(status):
    assert rules.should_stop(status, rules.DEFAULT_STOP_STATUSES) is True


@pytest.mark.parametrize("status", ["new", "contacted", "nurture",
                                    "appointment_requested", "no_show"])
def test_should_not_stop_active_statuses(status):
    assert rules.should_stop(status, rules.DEFAULT_STOP_STATUSES) is False


def test_audience_matches_empty_matches_all():
    assert rules.audience_matches({"service_interest": "x"}, {}) is True


def test_audience_matches_filters():
    lead = {"service_interest": "Wellness", "preferred_location": "Roswell"}
    assert rules.audience_matches(
        lead, {"service_interest": "wellness"}
    ) is True
    assert rules.audience_matches(
        lead, {"service_interest": "weightloss"}
    ) is False


def test_audience_missing_field_no_match():
    assert rules.audience_matches({}, {"service_interest": "x"}) is False


def test_idempotency_key_stable():
    assert rules.idempotency_key_for("enr1", 3) == "enr1:3"


# --------------------------------------------------------------------------- #
# Dispatch decision — email always held in Phase 8A
# --------------------------------------------------------------------------- #

def test_email_hold_decision_never_sends():
    decision = email_hold_decision()
    assert decision["sent"] is False
    assert decision["status"] == "held"
    assert decision["delivery_status"] == OUTREACH_HOLD_REASON
    assert decision["hold_reason"] == OUTREACH_HOLD_REASON
