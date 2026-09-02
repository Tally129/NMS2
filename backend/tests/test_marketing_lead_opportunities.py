from __future__ import annotations

import pytest

from marketing_os.services.lead_opportunities import (
    derive_lead_opportunities,
)
from marketing_os.services.measurement import (
    MarketingDataPolicyError,
)


def event(
    *,
    subject="msub_1",
    event_type="page_view",
    occurred_at="2026-08-31T12:00:00+00:00",
    source="google",
    medium="organic",
    campaign=None,
    properties=None,
):
    return {
        "marketing_subject_id":
            subject,
        "event_type":
            event_type,
        "occurred_at":
            occurred_at,
        "source":
            source,
        "medium":
            medium,
        "campaign":
            campaign,
        "properties":
            properties or {},
    }


def test_events_without_subject_are_excluded():
    rows = derive_lead_opportunities(
        [
            event(
                subject=None,
                event_type="lead_submit",
            )
        ]
    )

    assert rows == []


def test_high_intent_lead_ranks_above_page_view():
    rows = derive_lead_opportunities(
        [
            event(
                subject="low",
                event_type="page_view",
            ),
            event(
                subject="high",
                event_type="lead_submit",
                campaign="weight-search",
                properties={
                    "service_interest":
                        "weight_management",
                },
            ),
        ]
    )

    assert [
        row["marketing_subject_id"]
        for row in rows
    ] == [
        "high",
        "low",
    ]

    assert (
        rows[0]["opportunity_score"]
        >
        rows[1]["opportunity_score"]
    )


def test_repeated_engagement_increases_intent():
    single = derive_lead_opportunities(
        [
            event(
                subject="one",
                event_type="service_page_view",
            ),
        ]
    )[0]

    repeated = derive_lead_opportunities(
        [
            event(
                subject="many",
                event_type="service_page_view",
                occurred_at=
                    "2026-08-31T12:00:00+00:00",
            ),
            event(
                subject="many",
                event_type="cta_click",
                occurred_at=
                    "2026-08-31T12:01:00+00:00",
            ),
            event(
                subject="many",
                event_type="appointment_intent",
                occurred_at=
                    "2026-08-31T12:02:00+00:00",
            ),
        ]
    )[0]

    assert (
        repeated["intent_score"]
        >
        single["intent_score"]
    )


def test_latest_event_controls_current_attribution():
    row = derive_lead_opportunities(
        [
            event(
                source="google",
                medium="cpc",
                campaign="old-campaign",
                occurred_at=
                    "2026-08-31T12:00:00+00:00",
            ),
            event(
                event_type="lead_submit",
                source="meta",
                medium="paid_social",
                campaign="new-campaign",
                occurred_at=
                    "2026-08-31T12:05:00+00:00",
            ),
        ]
    )[0]

    assert row["source"] == "meta"
    assert row["medium"] == "paid_social"
    assert row["campaign"] == "new-campaign"
    assert (
        row["latest_event_type"]
        == "lead_submit"
    )


def test_service_interest_is_marketing_safe_property():
    row = derive_lead_opportunities(
        [
            event(
                event_type="lead_submit",
                properties={
                    "service_interest":
                        "telehealth",
                },
            )
        ]
    )[0]

    assert (
        row["service_interest"]
        == "telehealth"
    )


def test_phi_is_rejected_fail_closed():
    with pytest.raises(
        MarketingDataPolicyError
    ):
        derive_lead_opportunities(
            [
                {
                    **event(),
                    "email":
                        "person@example.com",
                }
            ]
        )


def test_phi_nested_in_properties_is_rejected():
    with pytest.raises(
        MarketingDataPolicyError
    ):
        derive_lead_opportunities(
            [
                event(
                    properties={
                        "diagnosis":
                            "example",
                    },
                )
            ]
        )


def test_unknown_event_type_is_not_scored():
    rows = derive_lead_opportunities(
        [
            event(
                event_type=
                    "totally_unknown",
            )
        ]
    )

    assert rows == []


def test_scores_are_capped_at_100():
    events = []

    for index in range(20):
        events.append(
            event(
                event_type="lead_submit",
                occurred_at=(
                    "2026-08-31T12:"
                    f"{index:02d}:00+00:00"
                ),
            )
        )

    row = derive_lead_opportunities(
        events
    )[0]

    assert (
        0
        <= row["intent_score"]
        <= 100
    )

    assert (
        0
        <= row[
            "qualification_score"
        ]
        <= 100
    )

    assert (
        0
        <= row[
            "opportunity_score"
        ]
        <= 100
    )


def test_output_contains_no_contact_identifier_fields():
    row = derive_lead_opportunities(
        [
            event(
                event_type="lead_submit",
            )
        ]
    )[0]

    forbidden = {
        "email",
        "phone",
        "patient_id",
        "patient_name",
        "diagnosis",
        "medication",
        "clinical_note",
    }

    assert not (
        forbidden
        & set(row)
    )
