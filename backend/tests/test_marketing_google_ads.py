from datetime import date
from types import SimpleNamespace

import pytest

from marketing_os.integrations.google_ads import (
    GoogleAdsIntegration,
    _clean_customer_id,
    _micros_to_decimal,
    _row_to_record,
)


def ns(**kwargs):
    return SimpleNamespace(**kwargs)


class FakeGoogleAdsService:

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def search(self, *, customer_id, query):
        self.calls.append(
            {
                "customer_id": customer_id,
                "query": query,
            }
        )
        return list(self.rows)


class FakeGoogleAdsClient:

    def __init__(self, rows):
        self.service = FakeGoogleAdsService(rows)
        self.services_requested = []

    def get_service(self, name):
        self.services_requested.append(name)

        assert name == "GoogleAdsService"

        return self.service


def fake_row():
    return ns(
        segments=ns(
            date="2026-08-25",
        ),
        campaign=ns(
            id=123456789,
            name="NMS Search",
        ),
        metrics=ns(
            impressions=1200,
            clicks=90,
            cost_micros=125500000,
            conversions=7.625,
            conversions_value=700.25,
        ),
    )


def account():
    return {
        "id": "mca_google_test",
        "provider": "google_ads",
        "external_account_id": "123-456-7890",
        "account_name": "NMS Google Ads",
        "status": "connected",
        "read_enabled": True,
        "write_enabled": False,
        "configuration": {},
    }


def test_clean_customer_id_removes_hyphens():
    assert (
        _clean_customer_id("123-456-7890")
        == "1234567890"
    )


def test_clean_customer_id_rejects_invalid():
    with pytest.raises(ValueError):
        _clean_customer_id("not-an-account")


def test_micros_to_decimal():
    assert str(
        _micros_to_decimal(125500000)
    ) == "125.5"


def test_row_normalization():
    result = _row_to_record(fake_row())

    assert result["metric_date"] == "2026-08-25"
    assert result["external_campaign_id"] == "123456789"
    assert result["campaign_name"] == "NMS Search"
    assert result["impressions"] == 1200
    assert result["clicks"] == 90
    assert result["spend"] == "125.5"
    assert result["conversions"] == "7.625"
    assert result["conversion_value"] == "700.25"
    assert result["leads"] == 0
    assert (
        result["raw_metrics"]["cost_micros"]
        == 125500000
    )


def test_adapter_is_read_only_by_default():
    integration = GoogleAdsIntegration(
        account=account(),
        client=FakeGoogleAdsClient([]),
    )

    with pytest.raises(RuntimeError):
        import asyncio

        asyncio.run(
            integration.execute_action(
                action="create_campaign"
            )
        )


@pytest.mark.asyncio
async def test_health_with_fake_client():
    integration = GoogleAdsIntegration(
        account=account(),
        client=FakeGoogleAdsClient([]),
    )

    result = await integration.health()

    assert result["status"] == "ready"
    assert result["provider"] == "google_ads"
    assert result["read_only"] is True
    assert result["customer_id"] == "1234567890"


@pytest.mark.asyncio
async def test_fetch_performance_uses_read_query():
    client = FakeGoogleAdsClient(
        [fake_row()]
    )

    integration = GoogleAdsIntegration(
        account=account(),
        client=client,
    )

    result = await integration.fetch_performance(
        account_id="1234567890",
        start_date=date(2026, 8, 25),
        end_date=date(2026, 8, 25),
    )

    assert result["provider"] == "google_ads"
    assert result["customer_id"] == "1234567890"
    assert len(result["records"]) == 1

    record = result["records"][0]

    assert record["impressions"] == 1200
    assert record["clicks"] == 90
    assert record["spend"] == "125.5"

    assert client.services_requested == [
        "GoogleAdsService"
    ]

    assert len(client.service.calls) == 1

    call = client.service.calls[0]

    assert call["customer_id"] == "1234567890"

    query = call["query"]

    assert "FROM campaign" in query
    assert "segments.date" in query
    assert "metrics.impressions" in query
    assert "metrics.clicks" in query
    assert "metrics.cost_micros" in query
    assert "metrics.conversions" in query
    assert "metrics.conversions_value" in query

    assert "2026-08-25" in query


@pytest.mark.asyncio
async def test_fetch_rejects_different_customer():
    integration = GoogleAdsIntegration(
        account=account(),
        client=FakeGoogleAdsClient([]),
    )

    with pytest.raises(PermissionError):
        await integration.fetch_performance(
            account_id="9999999999",
            start_date=date(2026, 8, 25),
            end_date=date(2026, 8, 25),
        )


@pytest.mark.asyncio
async def test_fetch_rejects_reverse_date_range():
    integration = GoogleAdsIntegration(
        account=account(),
        client=FakeGoogleAdsClient([]),
    )

    with pytest.raises(ValueError):
        await integration.fetch_performance(
            account_id="1234567890",
            start_date=date(2026, 8, 26),
            end_date=date(2026, 8, 25),
        )


@pytest.mark.asyncio
async def test_missing_sdk_or_credentials_is_fail_closed():
    def unavailable():
        raise RuntimeError(
            "Google Ads credentials are not configured"
        )

    integration = GoogleAdsIntegration(
        account=account(),
        client_factory=unavailable,
    )

    result = await integration.health()

    assert result["status"] == "unavailable"
    assert result["read_only"] is True

    with pytest.raises(RuntimeError):
        await integration.fetch_performance(
            account_id="1234567890",
            start_date=date(2026, 8, 25),
            end_date=date(2026, 8, 25),
        )
