from datetime import date
from decimal import Decimal

import pytest

from marketing_os.services.campaign_inventory import (
    CAMPAIGN_INVENTORY_SQL,
    list_campaign_inventory,
    serialize_campaign_inventory_row,
)


def test_serialize_campaign_inventory_row():
    row = {
        "provider": " GOOGLE_ADS ",
        "external_campaign_id":
            " 123456 ",
        "nms_campaign_id":
            " nms_weight ",
        "campaign_name":
            " Weight Search ",
        "first_seen":
            date(2026, 8, 31),
        "last_seen":
            date(2026, 9, 4),
        "metric_days":
            5,
        "recorded_spend":
            Decimal("49.75"),
    }

    assert (
        serialize_campaign_inventory_row(
            row
        )
        == {
            "provider":
                "google_ads",
            "external_campaign_id":
                "123456",
            "nms_campaign_id":
                "nms_weight",
            "campaign_name":
                "Weight Search",
            "first_seen":
                "2026-08-31",
            "last_seen":
                "2026-09-04",
            "metric_days":
                5,
            "recorded_spend":
                49.75,
        }
    )


def test_serialize_rejects_missing_provider():
    with pytest.raises(
        ValueError,
        match="provider is required",
    ):
        serialize_campaign_inventory_row(
            {
                "provider": "",
                "external_campaign_id":
                    "123",
            }
        )


def test_serialize_rejects_missing_campaign_id():
    with pytest.raises(
        ValueError,
        match="external_campaign_id is required",
    ):
        serialize_campaign_inventory_row(
            {
                "provider":
                    "google_ads",
                "external_campaign_id":
                    "",
            }
        )


def test_inventory_query_is_read_only():
    upper = (
        CAMPAIGN_INVENTORY_SQL.upper()
    )

    assert "SELECT" in upper
    assert (
        "FROM MARKETING_DAILY_METRICS"
        in upper
    )

    forbidden = (
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "ALTER ",
        "DROP ",
        "TRUNCATE ",
        "CREATE ",
        "MUTATE",
    )

    for token in forbidden:
        assert token not in upper


def test_inventory_query_groups_exact_identity():
    upper = (
        CAMPAIGN_INVENTORY_SQL.upper()
    )

    assert "PROVIDER" in upper
    assert "EXTERNAL_CAMPAIGN_ID" in upper
    assert "NMS_CAMPAIGN_ID" in upper
    assert "CAMPAIGN_NAME" in upper
    assert "MIN(METRIC_DATE)" in upper
    assert "MAX(METRIC_DATE)" in upper
    assert "SUM(SPEND)" in upper


@pytest.mark.asyncio
async def test_list_campaign_inventory_empty():
    captured = {}

    class Result:
        def __iter__(self):
            return iter([])

    class Session:
        async def execute(
            self,
            statement,
            params=None,
        ):
            captured["sql"] = str(
                statement
            )
            captured["params"] = params

            return Result()

    rows = await list_campaign_inventory(
        Session()
    )

    assert rows == []

    assert (
        "marketing_daily_metrics"
        in captured["sql"]
    )

    assert captured["params"] is None


@pytest.mark.asyncio
async def test_list_campaign_inventory_rows():
    class Result:
        def __iter__(self):
            return iter(
                [
                    {
                        "provider":
                            "google_ads",
                        "external_campaign_id":
                            "987654",
                        "nms_campaign_id":
                            None,
                        "campaign_name":
                            "Weight Search",
                        "first_seen":
                            date(
                                2026,
                                8,
                                31,
                            ),
                        "last_seen":
                            date(
                                2026,
                                9,
                                2,
                            ),
                        "metric_days":
                            3,
                        "recorded_spend":
                            Decimal(
                                "30.50"
                            ),
                    }
                ]
            )

    class Session:
        async def execute(
            self,
            statement,
            params=None,
        ):
            return Result()

    rows = await list_campaign_inventory(
        Session()
    )

    assert rows == [
        {
            "provider":
                "google_ads",
            "external_campaign_id":
                "987654",
            "nms_campaign_id":
                None,
            "campaign_name":
                "Weight Search",
            "first_seen":
                "2026-08-31",
            "last_seen":
                "2026-09-02",
            "metric_days":
                3,
            "recorded_spend":
                30.5,
        }
    ]
