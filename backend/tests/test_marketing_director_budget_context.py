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
        == "awaiting_performance_data"
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
