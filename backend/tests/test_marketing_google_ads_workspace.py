from datetime import date

import pytest
from types import SimpleNamespace

from marketing_os.integrations.google_ads import (
    GoogleAdsIntegration,
)


def _enum(name):
    return SimpleNamespace(
        name=name
    )


class FakeService:
    def __init__(self, responses):
        self.responses = []

        if (
            responses
            and isinstance(
                responses[0],
                list,
            )
        ):
            self.responses = [
                list(item)
                for item in responses
            ]
        else:
            self.responses = [
                list(responses)
            ]

        self.calls = []

    def search(
        self,
        *,
        customer_id,
        query,
    ):
        self.calls.append(
            {
                "customer_id":
                    customer_id,
                "query":
                    query,
            }
        )

        index = len(
            self.calls
        ) - 1

        if index >= len(
            self.responses
        ):
            return []

        return list(
            self.responses[index]
        )


class FakeClient:
    def __init__(self, service):
        self.service = service

    def get_service(self, name):
        assert name == "GoogleAdsService"

        return self.service


def _campaign_row():
    return SimpleNamespace(
        campaign=SimpleNamespace(
            id=123,
            name="Example Search",
            status=_enum("ENABLED"),
            advertising_channel_type=
                _enum("SEARCH"),
            campaign_budget=(
                "customers/101/"
                "campaignBudgets/456"
            ),
            contains_eu_political_advertising=
                _enum(
                    "DOES_NOT_CONTAIN_"
                    "EU_POLITICAL_ADVERTISING"
                ),
        ),
        campaign_budget=SimpleNamespace(
            id=456,
            name="Example Budget",
            amount_micros=5_000_000,
            reference_count=1,
            explicitly_shared=True,
        ),
    )


def _metric_row():
    return SimpleNamespace(
        campaign=SimpleNamespace(
            id=123,
        ),
        metrics=SimpleNamespace(
            impressions=100,
            clicks=10,
            cost_micros=20_000_000,
            conversions=2,
            conversions_value=50,
        ),
    )


def test_workspace_campaign_queries_are_read_only():
    service = FakeService(
        [
            [
                _campaign_row(),
            ],
            [
                _metric_row(),
            ],
        ]
    )

    integration = GoogleAdsIntegration(
        account={
            "external_account_id":
                "101",
            "configuration": {},
        },
        client=FakeClient(
            service
        ),
    )

    rows = (
        integration
        ._workspace_campaigns_sync(
            start_date=date(
                2026,
                9,
                1,
            ),
            end_date=date(
                2026,
                9,
                30,
            ),
        )
    )

    assert len(rows) == 1

    item = rows[0]

    assert item["campaign_id"] == "123"
    assert item["status"] == "ENABLED"
    assert item["channel_type"] == "SEARCH"

    assert (
        item["budget"]["daily_budget"]
        == 5.0
    )

    assert (
        item["budget"]["reference_count"]
        == 1
    )

    assert (
        item["metrics"]["impressions"]
        == 100
    )

    assert (
        item["metrics"]["clicks"]
        == 10
    )

    assert (
        item["metrics"]["ctr"]
        == 0.1
    )

    assert (
        item["metrics"]["average_cpc"]
        == 2.0
    )

    assert (
        item["metrics"]["cpa"]
        == 10.0
    )

    assert (
        item["metrics"]["roas"]
        == 2.5
    )

    assert len(service.calls) == 2

    inventory_query = (
        service.calls[0]["query"]
    )

    performance_query = (
        service.calls[1]["query"]
    )

    assert "FROM campaign" in inventory_query
    assert "metrics." not in inventory_query
    assert "segments.date" not in inventory_query
    assert "campaign.start_date" not in inventory_query
    assert "campaign.end_date" not in inventory_query

    assert "FROM campaign" in performance_query
    assert "metrics.impressions" in performance_query
    assert "segments.date BETWEEN" in performance_query
    assert "campaign.start_date" not in performance_query
    assert "campaign.end_date" not in performance_query

    for query in (
        inventory_query,
        performance_query,
    ):
        lowered = query.lower()

        assert "mutate" not in lowered
        assert "update " not in lowered
        assert "insert " not in lowered
        assert "delete " not in lowered


def test_workspace_zero_activity_campaign_is_preserved():
    service = FakeService(
        [
            [
                _campaign_row(),
            ],
            [],
        ]
    )

    integration = GoogleAdsIntegration(
        account={
            "external_account_id":
                "101",
            "configuration": {},
        },
        client=FakeClient(
            service
        ),
    )

    rows = (
        integration
        ._workspace_campaigns_sync(
            start_date=date(
                2026,
                9,
                1,
            ),
            end_date=date(
                2026,
                9,
                30,
            ),
        )
    )

    assert len(rows) == 1

    metrics = rows[0]["metrics"]

    assert metrics == {
        "impressions": 0,
        "clicks": 0,
        "ctr": None,
        "spend": 0.0,
        "average_cpc": None,
        "conversions": 0.0,
        "conversion_value": 0.0,
        "cpa": None,
        "roas": None,
    }


@pytest.mark.asyncio
async def test_workspace_overview_aggregates_campaigns(
    monkeypatch,
):
    integration = GoogleAdsIntegration(
        account={
            "external_account_id":
                "101",
            "configuration": {},
        },
        client=FakeClient(
            FakeService([])
        ),
    )

    async def fake_campaigns(
        *,
        start_date,
        end_date,
    ):
        del start_date
        del end_date

        return [
            {
                "status": "ENABLED",
                "metrics": {
                    "impressions": 100,
                    "clicks": 10,
                    "spend": 20.0,
                    "conversions": 2.0,
                    "conversion_value": 50.0,
                },
            },
            {
                "status": "PAUSED",
                "metrics": {
                    "impressions": 50,
                    "clicks": 5,
                    "spend": 5.0,
                    "conversions": 1.0,
                    "conversion_value": 10.0,
                },
            },
        ]

    monkeypatch.setattr(
        integration,
        "workspace_campaigns",
        fake_campaigns,
    )

    result = (
        await integration.workspace_overview(
            start_date=date(
                2026,
                9,
                1,
            ),
            end_date=date(
                2026,
                9,
                30,
            ),
        )
    )

    assert result["campaign_count"] == 2
    assert result["enabled_campaigns"] == 1
    assert result["paused_campaigns"] == 1

    assert (
        result["metrics"]["impressions"]
        == 150
    )

    assert (
        result["metrics"]["clicks"]
        == 15
    )

    assert (
        result["metrics"]["spend"]
        == 25.0
    )

    assert (
        result["metrics"]["conversions"]
        == 3.0
    )

    assert (
        result["metrics"]["conversion_value"]
        == 60.0
    )
