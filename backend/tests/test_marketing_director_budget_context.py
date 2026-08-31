from marketing_os.services.director import (
    build_marketing_brief,
)


GOAL_ID = "goal_patient_acquisition"
BUDGET_ID = "budget_weight_management"


def test_budget_context_without_performance():
    brief = build_marketing_brief(
        goals=[
            {
                "id": GOAL_ID,
                "name": "Qualified Patient Acquisition",
                "status": "active",
            }
        ],
        budgets=[
            {
                "id": BUDGET_ID,
                "goal_id": GOAL_ID,
                "name": "Weight management",
                "approved_amount": 50,
                "spent_amount": 0,
                "daily_cap": 10,
                "target_cpl": None,
                "target_cac": None,
                "minimum_roas": None,
                "status": "draft",
            }
        ],
        performance=[],
    )

    assert brief["channel_analysis"] == []

    assert len(brief["budget_analysis"]) == 1

    analysis = brief["budget_analysis"][0]

    assert analysis["budget_id"] == BUDGET_ID
    assert analysis["goal_id"] == GOAL_ID

    assert (
        analysis["goal_name"]
        == "Qualified Patient Acquisition"
    )

    assert analysis["approved_amount"] == 50
    assert analysis["spent_amount"] == 0
    assert analysis["remaining_amount"] == 50

    assert analysis["targets"]["daily_cap"] == 10
    assert analysis["targets"]["target_cpl"] is None
    assert analysis["targets"]["target_cac"] is None

    assert (
        analysis["targets"]["minimum_roas"]
        is None
    )

    assert (
        analysis["performance_available"]
        is False
    )

    assert (
        analysis["performance_status"]
        == "unmapped"
    )

    assert (
        analysis["mapping_status"]
        == "unmapped"
    )

    assert (
        analysis["budget_performance_mapped"]
        is False
    )


def test_missing_targets_are_not_invented():
    brief = build_marketing_brief(
        goals=[
            {
                "id": GOAL_ID,
                "name": "Qualified Patient Acquisition",
            }
        ],
        budgets=[
            {
                "id": BUDGET_ID,
                "goal_id": GOAL_ID,
                "name": "Weight management",
                "approved_amount": 50,
                "spent_amount": 0,
                "daily_cap": 10,
                "target_cpl": None,
                "target_cac": None,
                "minimum_roas": None,
                "status": "draft",
            }
        ],
        performance=[],
    )

    recommendations = brief["recommendations"]

    setup = [
        item
        for item in recommendations
        if item["type"] == "budget_configuration"
    ]

    assert len(setup) == 1

    item = setup[0]

    assert item["goal_id"] == GOAL_ID
    assert item["budget_id"] == BUDGET_ID

    assert "CPL" in item["reason"]
    assert "CAC" in item["reason"]
    assert "minimum ROAS" in item["reason"]

    assert item["external_write"] is False
    assert item["advisory_only"] is True
    assert item["requires_human_approval"] is True


def test_configured_targets_are_preserved():
    brief = build_marketing_brief(
        goals=[
            {
                "id": GOAL_ID,
                "name": "Qualified Patient Acquisition",
            }
        ],
        budgets=[
            {
                "id": BUDGET_ID,
                "goal_id": GOAL_ID,
                "name": "Weight management",
                "approved_amount": 50,
                "spent_amount": 12.5,
                "daily_cap": 10,
                "target_cpl": 25,
                "target_cac": 50,
                "minimum_roas": 2,
                "status": "active",
            }
        ],
        performance=[],
    )

    analysis = brief["budget_analysis"][0]

    assert analysis["remaining_amount"] == 37.5
    assert analysis["targets"]["daily_cap"] == 10
    assert analysis["targets"]["target_cpl"] == 25
    assert analysis["targets"]["target_cac"] == 50

    assert (
        analysis["targets"]["minimum_roas"]
        == 2
    )

    assert not any(
        item["type"] == "budget_configuration"
        for item in brief["recommendations"]
    )


def test_existing_channel_rules_still_work():
    brief = build_marketing_brief(
        goals=[],
        budgets=[],
        performance=[
            {
                "channel": "google",
                "impressions": 1000,
                "clicks": 5,
                "conversions": 0,
                "spend": 25,
                "revenue": 0,
            }
        ],
    )

    types = {
        item["type"]
        for item in brief["recommendations"]
    }

    assert "creative" in types
    assert "efficiency" in types

    for item in brief["recommendations"]:
        assert item["external_write"] is False
        assert item["requires_human_approval"] is True


def test_unrelated_marketing_data_does_not_map_to_budget():
    brief = build_marketing_brief(
        goals=[],
        budgets=[
            {
                "id": BUDGET_ID,
                "name": "Weight management",
                "approved_amount": 50,
                "spent_amount": 0,
                "target_cpl": 20,
                "target_cac": 40,
                "minimum_roas": 2,
                "allocation": {
                    "campaigns": [
                        {
                            "provider": "google",
                            "external_campaign_id":
                                "google-weight-1",
                        }
                    ]
                },
                "status": "active",
            }
        ],
        performance=[
            {
                "channel": "meta",
                "impressions": 5000,
                "clicks": 100,
                "conversions": 10,
                "spend": 100,
                "revenue": 500,
            }
        ],
        budget_performance=[
            {
                "provider": "meta",
                "external_campaign_id":
                    "meta-other-1",
                "impressions": 5000,
                "clicks": 100,
                "leads": 20,
                "conversions": 10,
                "spend": 100,
                "conversion_value": 500,
            }
        ],
    )

    analysis = brief["budget_analysis"][0]

    assert (
        analysis["marketing_performance_available"]
        is True
    )

    assert (
        analysis["budget_performance_mapped"]
        is True
    )

    assert (
        analysis["performance_available"]
        is False
    )

    assert (
        analysis["mapping_status"]
        == "mapped_no_performance"
    )

    assert (
        analysis["mapped_performance"]["row_count"]
        == 0
    )

    assert (
        analysis["mapped_performance"]["spend"]
        == 0
    )


def test_exact_provider_campaign_mapping():
    brief = build_marketing_brief(
        goals=[],
        budgets=[
            {
                "id": BUDGET_ID,
                "name": "Weight management",
                "approved_amount": 100,
                "spent_amount": 0,
                "target_cpl": 20,
                "target_cac": 50,
                "minimum_roas": 2,
                "allocation": {
                    "campaigns": [
                        {
                            "provider": "google",
                            "external_campaign_id":
                                "weight-123",
                        }
                    ]
                },
                "status": "active",
            }
        ],
        budget_performance=[
            {
                "provider": "google",
                "external_campaign_id":
                    "weight-123",
                "impressions": 1000,
                "clicks": 50,
                "leads": 5,
                "conversions": 2,
                "spend": 50,
                "conversion_value": 150,
            },
            {
                "provider": "GOOGLE",
                "external_campaign_id":
                    "weight-123",
                "impressions": 500,
                "clicks": 20,
                "leads": 5,
                "conversions": 1,
                "spend": 25,
                "conversion_value": 75,
            },
            {
                "provider": "google",
                "external_campaign_id":
                    "other-999",
                "impressions": 9999,
                "clicks": 999,
                "leads": 99,
                "conversions": 99,
                "spend": 999,
                "conversion_value": 9999,
            },
        ],
    )

    analysis = brief["budget_analysis"][0]
    metrics = analysis["mapped_performance"]

    assert analysis["mapping_status"] == "mapped"
    assert analysis["performance_available"] is True

    assert metrics["row_count"] == 2
    assert metrics["impressions"] == 1500
    assert metrics["clicks"] == 70
    assert metrics["leads"] == 10
    assert metrics["conversions"] == 3
    assert metrics["spend"] == 75
    assert metrics["revenue"] == 225
    assert metrics["cpl"] == 7.5
    assert metrics["cac"] == 25
    assert metrics["roas"] == 3


def test_exact_nms_campaign_mapping():
    brief = build_marketing_brief(
        goals=[],
        budgets=[
            {
                "id": BUDGET_ID,
                "name": "Weight management",
                "approved_amount": 100,
                "spent_amount": 0,
                "allocation": {
                    "campaigns": [
                        {
                            "nms_campaign_id":
                                "nms_weight_1",
                        }
                    ]
                },
                "status": "active",
            }
        ],
        budget_performance=[
            {
                "provider": "google",
                "external_campaign_id":
                    "external-a",
                "nms_campaign_id":
                    "nms_weight_1",
                "impressions": 100,
                "clicks": 10,
                "leads": 2,
                "conversions": 1,
                "spend": 20,
                "conversion_value": 60,
            },
            {
                "provider": "meta",
                "external_campaign_id":
                    "external-b",
                "nms_campaign_id":
                    "another_campaign",
                "impressions": 1000,
                "clicks": 100,
                "leads": 20,
                "conversions": 10,
                "spend": 200,
                "conversion_value": 1000,
            },
        ],
    )

    analysis = brief["budget_analysis"][0]

    assert analysis["mapping_status"] == "mapped"

    assert (
        analysis["mapped_performance"]["row_count"]
        == 1
    )

    assert (
        analysis["mapped_performance"]["spend"]
        == 20
    )


def test_invalid_campaign_mapping_fails_closed():
    brief = build_marketing_brief(
        goals=[],
        budgets=[
            {
                "id": BUDGET_ID,
                "name": "Weight management",
                "approved_amount": 100,
                "spent_amount": 0,
                "allocation": {
                    "campaigns": [
                        {
                            "provider": "google",
                        }
                    ]
                },
                "status": "active",
            }
        ],
        budget_performance=[
            {
                "provider": "google",
                "external_campaign_id":
                    "some-campaign",
                "impressions": 1000,
                "clicks": 100,
                "leads": 10,
                "conversions": 5,
                "spend": 100,
                "conversion_value": 500,
            }
        ],
    )

    analysis = brief["budget_analysis"][0]

    assert (
        analysis["mapping_status"]
        == "invalid_mapping"
    )

    assert (
        analysis["budget_performance_mapped"]
        is False
    )

    assert (
        analysis["performance_available"]
        is False
    )

    assert (
        analysis["mapped_performance"]["row_count"]
        == 0
    )

    assert analysis["mapping"]["errors"]


def test_budget_mapping_respects_budget_period():
    brief = build_marketing_brief(
        goals=[],
        budgets=[
            {
                "id": BUDGET_ID,
                "name": "Weight management",
                "period_start": "2026-08-31",
                "period_end": "2026-09-04",
                "approved_amount": 100,
                "spent_amount": 0,
                "target_cpl": 20,
                "target_cac": 50,
                "minimum_roas": 2,
                "allocation": {
                    "campaigns": [
                        {
                            "provider": "google",
                            "external_campaign_id":
                                "weight-period-1",
                        }
                    ]
                },
                "status": "active",
            }
        ],
        budget_performance=[
            # Before budget period: must be ignored.
            {
                "metric_date": "2026-08-30",
                "provider": "google",
                "external_campaign_id":
                    "weight-period-1",
                "impressions": 1000,
                "clicks": 100,
                "leads": 10,
                "conversions": 5,
                "spend": 500,
                "conversion_value": 5000,
            },

            # Start boundary: included.
            {
                "metric_date": "2026-08-31",
                "provider": "google",
                "external_campaign_id":
                    "weight-period-1",
                "impressions": 100,
                "clicks": 10,
                "leads": 2,
                "conversions": 1,
                "spend": 20,
                "conversion_value": 60,
            },

            # Inside period: included.
            {
                "metric_date": "2026-09-02",
                "provider": "google",
                "external_campaign_id":
                    "weight-period-1",
                "impressions": 200,
                "clicks": 20,
                "leads": 3,
                "conversions": 1,
                "spend": 30,
                "conversion_value": 90,
            },

            # End boundary: included.
            {
                "metric_date": "2026-09-04",
                "provider": "google",
                "external_campaign_id":
                    "weight-period-1",
                "impressions": 300,
                "clicks": 30,
                "leads": 5,
                "conversions": 2,
                "spend": 50,
                "conversion_value": 150,
            },

            # After budget period: must be ignored.
            {
                "metric_date": "2026-09-05",
                "provider": "google",
                "external_campaign_id":
                    "weight-period-1",
                "impressions": 1000,
                "clicks": 100,
                "leads": 10,
                "conversions": 5,
                "spend": 500,
                "conversion_value": 5000,
            },

            # Exact campaign but no metric date:
            # fail closed when budget dates exist.
            {
                "provider": "google",
                "external_campaign_id":
                    "weight-period-1",
                "impressions": 999,
                "clicks": 99,
                "leads": 99,
                "conversions": 99,
                "spend": 999,
                "conversion_value": 9999,
            },
        ],
    )

    analysis = brief["budget_analysis"][0]
    metrics = analysis["mapped_performance"]

    assert analysis["mapping_status"] == "mapped"
    assert analysis["performance_available"] is True

    assert metrics["row_count"] == 3

    assert metrics["impressions"] == 600
    assert metrics["clicks"] == 60
    assert metrics["leads"] == 10
    assert metrics["conversions"] == 4

    assert metrics["spend"] == 100
    assert metrics["revenue"] == 300

    assert metrics["cpl"] == 10
    assert metrics["cac"] == 25
    assert metrics["roas"] == 3
