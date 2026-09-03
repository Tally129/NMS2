import asyncio

from marketing_os.services.director_ai import (
    build_director_summary,
    deterministic_summary,
)
from marketing_os.services.director_signals import (
    build_cross_phase_signals,
    rank_signals,
)


def test_director_signal_ranking_is_deterministic():
    signals = [
        {
            "signal_key": "low",
            "priority": 20,
            "severity": "info",
        },
        {
            "signal_key": "high",
            "priority": 90,
            "severity": "high",
        },
        {
            "signal_key": "medium",
            "priority": 60,
            "severity": "medium",
        },
    ]

    ranked = rank_signals(signals)

    assert [row["signal_key"] for row in ranked] == [
        "high",
        "medium",
        "low",
    ]


def test_paid_spend_without_conversion_creates_high_signal():
    result = build_cross_phase_signals(
        paid_media=[
            {
                "provider": "google_ads",
                "spend": 500,
                "conversions": 0,
            }
        ]
    )

    signals = result["signals"]

    assert signals
    assert signals[0]["signal_key"] == (
        "paid_no_conversion:google_ads"
    )
    assert signals[0]["priority"] == 85
    assert signals[0]["human_approval_required"] is True
    assert signals[0]["external_execution_allowed"] is False


def test_high_priority_content_becomes_director_signal():
    result = build_cross_phase_signals(
        content_topics=[
            {
                "id": "topic-1",
                "topic": "Functional Medicine Atlanta",
                "priority": 92,
                "status": "idea",
                "target_keyword": "functional medicine atlanta",
                "funnel_stage": "consideration",
            }
        ]
    )

    signals = result["signals"]

    assert len(signals) == 1
    assert signals[0]["category"] == "content"
    assert signals[0]["priority"] == 92
    assert signals[0]["source_phase"] == "11"


def test_local_opportunity_is_advisory_only():
    result = build_cross_phase_signals(
        local_growth=[
            {
                "location_id": "roswell",
                "opportunity_key": "missing_directory",
                "opportunity_type": "missing_directory",
                "priority": 80,
                "title": "Directory coverage gap",
            }
        ]
    )

    signal = result["signals"][0]

    assert signal["category"] == "local_growth"
    assert signal["human_approval_required"] is True
    assert signal["external_execution_allowed"] is False


def test_active_experiment_does_not_fabricate_winner():
    result = build_cross_phase_signals(
        experiments=[
            {
                "id": "experiment-1",
                "status": "active",
            }
        ]
    )

    signal = result["signals"][0]

    assert signal["signal_key"] == "experiment:active:experiment-1"
    assert signal["data_quality"] == "lifecycle_only"
    assert "winner" not in signal["signal_key"]


def test_deterministic_summary_requires_human_review():
    result = deterministic_summary({
        "signals": [
            {
                "signal_key": "x",
                "priority": 90,
                "title": "High priority issue",
                "recommended_action": "Review it.",
            }
        ],
        "summary": {
            "total": 1,
            "high_priority": 1,
        },
    })

    assert result["source"] == "deterministic"
    assert result["signal_count"] == 1
    assert result["high_priority_count"] == 1
    assert result["human_review_required"] is True
    assert result["external_execution_allowed"] is False


def test_ai_not_requested_never_calls_provider():
    signals = {
        "signals": [],
        "summary": {
            "total": 0,
            "high_priority": 0,
        },
    }

    summary, status = asyncio.run(
        build_director_summary(
            signals,
            use_ai=False,
        )
    )

    assert status == "not_requested"
    assert summary["source"] == "deterministic"


def test_director_safety_envelope():
    result = build_cross_phase_signals()

    assert result["safety"] == {
        "advisory_only": True,
        "ai_decides_priority": False,
        "automatic_execution": False,
        "external_execution_allowed": False,
        "human_approval_required": True,
        "phi_used": False,
    }


def test_paid_zero_conversion_is_not_replaced_by_leads():
    from marketing_os.services.director_signals import (
        paid_media_signals,
    )

    signals = paid_media_signals([
        {
            "provider": "google_ads",
            "spend": 100,
            "conversions": 0,
            "leads": 10,
        }
    ])

    signal = next(
        item
        for item in signals
        if item["signal_key"]
        == "paid_no_conversion:google_ads"
    )

    assert signal["evidence"]["conversions"] == 0
    assert signal["evidence"]["spend"] == 100


def test_zero_booking_rate_is_not_replaced_by_secondary_rate():
    from marketing_os.services.director_signals import (
        funnel_signals,
    )

    signals = funnel_signals({
        "booking_rate": 0,
        "appointment_booking_rate": 0.8,
    })

    signal = next(
        item
        for item in signals
        if item["signal_key"]
        == "conversion:low_booking_rate"
    )

    assert signal["evidence"]["booking_rate"] == 0
    assert signal["evidence"]["threshold"] == 0.50
