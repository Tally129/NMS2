from datetime import date
from decimal import Decimal

import pytest

from marketing_os.services.performance import (
    daily_metric_id,
    normalize_daily_performance,
    persist_daily_performance,
)


def _payload(**overrides):

    payload = {
        "metric_date": "2026-08-25",
        "provider": "Google",
        "external_campaign_id": "campaign-123",
        "campaign_name": "Wellness Search",
        "impressions": 1000,
        "clicks": 80,
        "spend": "125.50",
        "leads": 12,
        "conversions": 5,
        "conversion_value": "600.00",
        "raw_metrics": {
            "average_position": "1.8",
        },
    }

    payload.update(overrides)

    return payload


def test_normalize_daily_performance():

    metric = normalize_daily_performance(
        _payload()
    )

    assert metric.metric_date == date(
        2026,
        8,
        25,
    )
    assert metric.provider == "google"
    assert (
        metric.external_campaign_id
        == "campaign-123"
    )
    assert metric.impressions == 1000
    assert metric.clicks == 80
    assert metric.spend == Decimal("125.50")
    assert metric.leads == 12
    assert metric.conversions == 5
    assert (
        metric.conversion_value
        == Decimal("600.00")
    )


def test_defaults_optional_metrics_to_zero():

    metric = normalize_daily_performance(
        {
            "metric_date": "2026-08-25",
            "provider": "meta",
            "external_campaign_id": "abc",
        }
    )

    assert metric.impressions == 0
    assert metric.clicks == 0
    assert metric.spend == Decimal("0")
    assert metric.leads == 0
    assert metric.conversions == 0
    assert metric.conversion_value == Decimal("0")
    assert metric.raw_metrics == {}


@pytest.mark.parametrize(
    "field",
    [
        "impressions",
        "clicks",
        "spend",
        "leads",
        "conversions",
        "conversion_value",
    ],
)
def test_rejects_negative_metrics(field):

    with pytest.raises(
        ValueError,
        match="nonnegative",
    ):
        normalize_daily_performance(
            _payload(**{field: -1})
        )


def test_rejects_missing_provider():

    with pytest.raises(
        ValueError,
        match="provider is required",
    ):
        normalize_daily_performance(
            _payload(provider=None)
        )


def test_rejects_missing_external_campaign_id():

    with pytest.raises(
        ValueError,
        match="external_campaign_id is required",
    ):
        normalize_daily_performance(
            _payload(
                external_campaign_id=None
            )
        )


def test_rejects_unknown_fields():

    with pytest.raises(
        ValueError,
        match="Unsupported performance fields",
    ):
        normalize_daily_performance(
            _payload(
                patient_name="should-not-exist"
            )
        )


def test_rejects_phi_inside_raw_metrics():

    with pytest.raises(Exception):
        normalize_daily_performance(
            _payload(
                raw_metrics={
                    "patient_name": "Jane Doe",
                }
            )
        )


def test_metric_id_is_deterministic():

    first = daily_metric_id(
        metric_date=date(2026, 8, 25),
        provider="Google",
        external_campaign_id="campaign-123",
    )

    second = daily_metric_id(
        metric_date=date(2026, 8, 25),
        provider="google",
        external_campaign_id="campaign-123",
    )

    assert first == second
    assert first.startswith("mdm_")


def test_metric_id_changes_by_date():

    first = daily_metric_id(
        metric_date=date(2026, 8, 25),
        provider="google",
        external_campaign_id="campaign-123",
    )

    second = daily_metric_id(
        metric_date=date(2026, 8, 26),
        provider="google",
        external_campaign_id="campaign-123",
    )

    assert first != second


class _Result:

    def __init__(self, value):
        self.value = value

    def first(self):
        return (self.value,)


class _Session:

    def __init__(self):
        self.calls = []

    async def execute(
        self,
        statement,
        params,
    ):
        self.calls.append(
            (
                str(statement),
                params,
            )
        )

        return _Result(params["id"])


@pytest.mark.asyncio
async def test_persistence_uses_database_upsert():

    session = _Session()

    result = await persist_daily_performance(
        session,
        _payload(),
    )

    assert len(session.calls) == 1

    sql, params = session.calls[0]

    assert (
        "INSERT INTO marketing_daily_metrics"
        in sql
    )
    assert "ON CONFLICT" in sql
    assert "DO UPDATE SET" in sql

    assert params["provider"] == "google"
    assert (
        params["external_campaign_id"]
        == "campaign-123"
    )

    assert result["provider"] == "google"
    assert result[
        "external_campaign_id"
    ] == "campaign-123"


@pytest.mark.asyncio
async def test_same_identity_produces_same_id():

    first_session = _Session()
    second_session = _Session()

    first = await persist_daily_performance(
        first_session,
        _payload(impressions=100),
    )

    second = await persist_daily_performance(
        second_session,
        _payload(impressions=200),
    )

    assert (
        first["daily_metric_id"]
        == second["daily_metric_id"]
    )
