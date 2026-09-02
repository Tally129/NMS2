"""Marketing OS Phase 7 — funnel qualification + offer matching.

Unit tests only. No network, DB, external provider, clinical, or PHI access.
"""

import pytest

from marketing_os.services import funnel_qualification as FQ
from marketing_os.services.measurement import MarketingDataPolicyError


def _answers(**overrides):
    data = {
        "service_interest": "wellness",
        "urgency": "soon",
        "preferred_location": "Roswell",
        "preferred_contact_window": "morning",
        "appointment_readiness": "ready_now",
        "timeline": "within_30_days",
        "contact_consent": True,
    }
    data.update(overrides)
    return data


def _rules():
    return [
        {
            "field": "appointment_readiness",
            "operator": "equals",
            "value": "ready_now",
            "points": 35,
        },
        {
            "field": "timeline",
            "operator": "in",
            "values": ["within_7_days", "within_30_days"],
            "points": 25,
        },
        {
            "field": "contact_consent",
            "operator": "truthy",
            "points": 20,
        },
        {
            "field": "urgency",
            "operator": "equals",
            "value": "soon",
            "points": 20,
        },
    ]


def _offers():
    return [
        {
            "id": "offer_general",
            "status": "active",
            "service_interest": "wellness",
            "min_qualification_score": 50,
            "eligible_locations": [],
        },
        {
            "id": "offer_roswell_high",
            "status": "active",
            "service_interest": "wellness",
            "min_qualification_score": 80,
            "eligible_locations": ["Roswell"],
        },
        {
            "id": "offer_inactive",
            "status": "draft",
            "service_interest": "wellness",
            "min_qualification_score": 0,
            "eligible_locations": [],
        },
    ]


def test_normalizes_marketing_safe_answers():
    normalized = FQ.normalize_qualification_answers(
        _answers(service_interest="  wellness  ")
    )

    assert normalized["service_interest"] == "wellness"
    assert normalized["contact_consent"] is True


def test_rejects_contact_details_and_phi():
    with pytest.raises(MarketingDataPolicyError):
        FQ.normalize_qualification_answers({
            "email": "person@example.com",
        })

    with pytest.raises(MarketingDataPolicyError):
        FQ.normalize_qualification_answers({
            "symptoms": "fatigue",
        })


def test_rejects_unknown_fields_even_if_nonclinical():
    with pytest.raises(MarketingDataPolicyError):
        FQ.normalize_qualification_answers({
            "favorite_color": "blue",
        })


def test_score_is_deterministic_and_clamped():
    score = FQ.score_qualification(
        _answers(),
        _rules(),
    )

    assert score == 100

    score2 = FQ.score_qualification(
        _answers(),
        [
            {
                "field": "contact_consent",
                "operator": "truthy",
                "points": 150,
            }
        ],
    )

    assert score2 == 100


def test_status_thresholds():
    assert FQ.qualification_status_from_score(85) == "qualified"
    assert FQ.qualification_status_from_score(55) == "in_review"
    assert FQ.qualification_status_from_score(20) == "unqualified"


def test_invalid_thresholds_fail_closed():
    with pytest.raises(FQ.QualificationRuleError):
        FQ.qualification_status_from_score(
            70,
            qualify_at=50,
            review_at=80,
        )


def test_offer_matching_prefers_more_specific_high_threshold():
    winner = FQ.match_offer(
        _answers(),
        100,
        _offers(),
    )

    assert winner is not None
    assert winner["id"] == "offer_roswell_high"


def test_offer_matching_respects_location_and_score():
    winner = FQ.match_offer(
        _answers(preferred_location="Alpharetta"),
        60,
        _offers(),
    )

    assert winner is not None
    assert winner["id"] == "offer_general"


def test_evaluate_builds_existing_marketing_lead_patch():
    result = FQ.evaluate_qualification(
        answers=_answers(),
        scoring_rules=_rules(),
        offers=_offers(),
    )

    assert result["qualification_score"] == 100
    assert result["qualification_status"] == "qualified"
    assert result["matched_offer_id"] == "offer_roswell_high"

    patch = result["lead_patch"]

    assert patch["service_interest"] == "wellness"
    assert patch["preferred_location"] == "Roswell"
    assert patch["appointment_readiness"] == "ready_now"
    assert patch["qualification_score"] == 100
    assert patch["qualification_status"] == "qualified"
    assert patch["priority"] == "high"
    assert patch["offer_id"] == "offer_roswell_high"

    # Marketing OS must not manufacture patient/contact fields.
    assert "client_id" not in patch
    assert "patient_id" not in patch
    assert "email" not in patch
    assert "phone" not in patch
