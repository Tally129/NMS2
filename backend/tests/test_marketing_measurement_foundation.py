from decimal import Decimal

import pytest

from marketing_os.services.measurement import (
    MarketingDataPolicyError,
    assert_non_phi_marketing_payload,
    derive_metric_rates,
    last_touch_attribution,
    normalize_conversion_payload,
)


def test_safe_non_phi_payload():

    payload = {
        "event_type": "appointment_intent",
        "session_id": "anonymous-session-123",
        "source": "google",
        "medium": "organic",
        "campaign": "hyperbaric-therapy",
        "properties": {
            "page_path": "/services/hyperbaric",
            "cta": "request-appointment",
        },
    }

    assert_non_phi_marketing_payload(payload)


@pytest.mark.parametrize(
    "field",
    [
        "patient_id",
        "email",
        "phone",
        "date_of_birth",
        "diagnosis",
        "medications",
        "medical_record_number",
    ],
)
def test_phi_fields_rejected(field):

    payload = {
        "event_type": "lead_submit",
        "properties": {
            field: "DO-NOT-STORE",
        },
    }

    with pytest.raises(
        MarketingDataPolicyError
    ):
        assert_non_phi_marketing_payload(
            payload
        )


def test_nested_phi_rejected():

    payload = {
        "event_type": "conversion",
        "properties": {
            "analytics": {
                "patient_name": "DO-NOT-STORE",
            },
        },
    }

    with pytest.raises(
        MarketingDataPolicyError
    ):
        assert_non_phi_marketing_payload(
            payload
        )


def test_conversion_normalization():

    conversion = normalize_conversion_payload(
        {
            "event_type": "CTA_CLICK",
            "session_id": "anon-1",
            "source": "google",
            "medium": "organic",
            "campaign": "b12",
            "value": "25.00",
            "currency": "usd",
            "properties": {
                "page_path": "/services/b12",
            },
        }
    )

    assert conversion.event_type == "cta_click"
    assert conversion.source == "google"
    assert conversion.medium == "organic"
    assert conversion.value == Decimal("25.00")
    assert conversion.currency == "USD"


def test_unknown_event_rejected():

    with pytest.raises(
        MarketingDataPolicyError
    ):
        normalize_conversion_payload(
            {
                "event_type":
                    "unknown_private_event",
            }
        )


def test_last_touch_attribution():

    conversion = normalize_conversion_payload(
        {
            "event_type": "conversion",
            "source": "google",
            "medium": "cpc",
            "campaign": "wellness",
            "value": "150",
            "currency": "USD",
        }
    )

    result = last_touch_attribution(
        conversion,
        provider="google_ads",
        external_campaign_id="campaign-123",
    )

    assert result.model == "last_touch"
    assert result.credit == Decimal("1")
    assert result.attributed_value == Decimal("150")
    assert result.provider == "google_ads"


def test_metric_calculations():

    metrics = derive_metric_rates(
        impressions=1000,
        clicks=100,
        spend=Decimal("200"),
        leads=20,
        conversions=10,
        conversion_value=Decimal("1000"),
    )

    assert metrics["ctr"] == Decimal("0.1")
    assert metrics["cpc"] == Decimal("2")
    assert metrics["cpl"] == Decimal("10")
    assert (
        metrics["conversion_rate"]
        == Decimal("0.1")
    )
    assert metrics["roas"] == Decimal("5")


def test_zero_denominators():

    metrics = derive_metric_rates(
        impressions=0,
        clicks=0,
        spend=Decimal("0"),
        leads=0,
        conversions=0,
        conversion_value=Decimal("0"),
    )

    assert metrics["ctr"] is None
    assert metrics["cpc"] is None
    assert metrics["cpl"] is None
    assert metrics["conversion_rate"] is None
    assert metrics["roas"] is None
