from marketing_os.services.executive_command_center import (
    build_channel_health,
    build_executive_command_center,
    build_executive_kpis,
    build_growth_funnel,
    build_pipeline_health,
)


def test_unknown_kpis_remain_null():
    result = build_executive_kpis(
        paid_media=[],
        funnel={},
        revenue={},
    )

    assert result["spend"] is None
    assert result["leads"] is None
    assert result["conversions"] is None
    assert result["cpl"] is None
    assert result["cac_cpa"] is None
    assert result["revenue"] is None
    assert result["roas"] is None


def test_explicit_zero_is_preserved():
    result = build_executive_kpis(
        paid_media=[
            {
                "provider": "google_ads",
                "spend": 0,
                "revenue": 0,
            }
        ],
        funnel={
            "leads": 0,
            "completed": 0,
        },
        revenue={},
    )

    assert result["spend"] == 0
    assert result["leads"] == 0
    assert result["conversions"] == 0
    assert result["revenue"] == 0
    assert result["cpl"] is None
    assert result["cac_cpa"] is None
    assert result["roas"] is None


def test_executive_kpi_math():
    result = build_executive_kpis(
        paid_media=[
            {
                "provider": "google_ads",
                "spend": 500,
            },
            {
                "provider": "meta",
                "spend": 250,
            },
        ],
        funnel={
            "leads": 30,
            "completed": 10,
        },
        revenue={
            "revenue": 3000,
        },
    )

    assert result["spend"] == 750
    assert result["leads"] == 30
    assert result["conversions"] == 10
    assert result["cpl"] == 25
    assert result["cac_cpa"] == 75
    assert result["revenue"] == 3000
    assert result["roas"] == 4


def test_growth_funnel_rates():
    result = build_growth_funnel({
        "leads": 100,
        "appointment_requests": 40,
        "booked": 20,
        "completed": 15,
        "no_show": 5,
    })

    assert result["lead_to_request_rate"] == 0.4
    assert result["request_to_booking_rate"] == 0.5
    assert result["booking_to_completion_rate"] == 0.75


def test_channel_health_uses_director_priority():
    result = build_channel_health(
        [
            {
                "provider": "google_ads",
                "spend": 500,
                "roas": 0.4,
            }
        ],
        {
            "signals": [
                {
                    "category": "paid_media",
                    "priority": 88,
                    "evidence": {
                        "provider": "google_ads",
                    },
                }
            ]
        },
    )

    google = next(
        row
        for row in result
        if row["channel"] == "google_ads"
    )

    assert google["status"] == "critical"
    assert google["highest_priority"] == 88


def test_pipeline_health_counts():
    result = build_pipeline_health({
        "needs_attention": 4,
        "overdue_leads": 3,
        "no_show": 2,
    })

    assert result == {
        "needs_attention": 4,
        "overdue_followups": 3,
        "no_show_recovery": 2,
    }


def test_command_center_is_read_only_and_advisory():
    result = build_executive_command_center(
        paid_media=[],
        funnel={},
        lead_operations={},
        director_signals={
            "signals": [],
            "summary": {},
        },
        director_summary={},
        revenue={},
    )

    assert result["safety"] == {
        "read_only": True,
        "advisory_only": True,
        "automatic_execution": False,
        "human_approval_required": True,
        "external_execution_allowed": False,
        "phi_used": False,
    }
