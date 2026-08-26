from __future__ import annotations

from datetime import date

import pytest

from marketing_os.integrations.base import (
    MarketingIntegration,
)
from marketing_os.integrations.registry import (
    create_integration,
    normalize_provider,
    register_integration,
    registered_providers,
    unregister_integration,
)
from marketing_os.services import performance_sync


class FakeIntegration(MarketingIntegration):
    provider = "fake"

    def __init__(
        self,
        *,
        account,
        records=None,
    ):
        self.account = account
        self.records = records or []
        self.fetch_calls = []
        self.execute_calls = []

    async def health(self) -> dict:
        return {
            "status": "ok",
            "provider": self.provider,
        }

    async def fetch_performance(
        self,
        **kwargs,
    ) -> dict:
        self.fetch_calls.append(kwargs)

        return {
            "records": list(self.records),
        }

    async def execute_action(
        self,
        **kwargs,
    ) -> dict:
        self.execute_calls.append(kwargs)

        raise AssertionError(
            "sync must never call execute_action"
        )


@pytest.fixture(autouse=True)
def clean_fake_registry():
    unregister_integration("fake")

    yield

    unregister_integration("fake")


def test_normalize_provider():
    assert normalize_provider(" Meta ") == "meta"

    with pytest.raises(ValueError):
        normalize_provider("")

    with pytest.raises(ValueError):
        normalize_provider("x" * 65)


def test_register_and_create_integration():
    register_integration(
        "fake",
        lambda **kwargs: FakeIntegration(
            **kwargs
        ),
    )

    integration = create_integration(
        "FAKE",
        account={"id": "acct"},
    )

    assert isinstance(
        integration,
        FakeIntegration,
    )

    assert registered_providers() == (
        "fake",
    )


def test_duplicate_registration_rejected():
    factory = lambda **kwargs: FakeIntegration(
        **kwargs
    )

    register_integration(
        "fake",
        factory,
    )

    with pytest.raises(ValueError):
        register_integration(
            "fake",
            factory,
        )


def test_unregistered_provider_rejected():
    with pytest.raises(LookupError):
        create_integration(
            "fake",
            account={},
        )


def test_factory_provider_mismatch_rejected():
    class WrongProvider(FakeIntegration):
        provider = "wrong"

    register_integration(
        "fake",
        lambda **kwargs: WrongProvider(
            **kwargs
        ),
    )

    with pytest.raises(ValueError):
        create_integration(
            "fake",
            account={},
        )


@pytest.mark.asyncio
async def test_sync_rejects_disabled_account():
    account = {
        "id": "acct_1",
        "provider": "fake",
        "external_account_id": "external_1",
        "status": "connected",
        "read_enabled": False,
        "write_enabled": False,
        "configuration": {},
    }

    with pytest.raises(PermissionError):
        await performance_sync.sync_channel_account(
            object(),
            account,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
        )


@pytest.mark.asyncio
async def test_sync_rejects_disconnected_account():
    account = {
        "id": "acct_1",
        "provider": "fake",
        "external_account_id": "external_1",
        "status": "disconnected",
        "read_enabled": True,
        "write_enabled": False,
        "configuration": {},
    }

    with pytest.raises(PermissionError):
        await performance_sync.sync_channel_account(
            object(),
            account,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
        )


@pytest.mark.asyncio
async def test_sync_rejects_invalid_date_range():
    account = {
        "id": "acct_1",
        "provider": "fake",
        "external_account_id": "external_1",
        "status": "connected",
        "read_enabled": True,
        "write_enabled": False,
        "configuration": {},
    }

    with pytest.raises(ValueError):
        await performance_sync.sync_channel_account(
            object(),
            account,
            start_date=date(2026, 8, 3),
            end_date=date(2026, 8, 2),
        )


@pytest.mark.asyncio
async def test_sync_never_requires_write_enabled(
    monkeypatch,
):
    account = {
        "id": "acct_1",
        "provider": "fake",
        "external_account_id": "external_1",
        "status": "connected",
        "read_enabled": True,
        "write_enabled": False,
        "configuration": {},
    }

    integration = FakeIntegration(
        account=account,
        records=[],
    )

    monkeypatch.setattr(
        performance_sync,
        "create_integration",
        lambda provider, **kwargs: integration,
    )

    class Result:
        pass

    class Session:
        def __init__(self):
            self.calls = []

        async def execute(
            self,
            statement,
            params=None,
        ):
            self.calls.append(
                (
                    str(statement),
                    params,
                )
            )
            return Result()

    session = Session()

    result = (
        await performance_sync.sync_channel_account(
            session,
            account,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
        )
    )

    assert result["records_persisted"] == 0
    assert integration.execute_calls == []
    assert len(integration.fetch_calls) == 1
    assert len(session.calls) == 1
    assert (
        "UPDATE marketing_channel_accounts"
        in session.calls[0][0]
    )


@pytest.mark.asyncio
async def test_sync_persists_provider_records(
    monkeypatch,
):
    account = {
        "id": "acct_1",
        "provider": "fake",
        "external_account_id": "external_1",
        "status": "active",
        "read_enabled": True,
        "write_enabled": False,
        "configuration": {},
    }

    integration = FakeIntegration(
        account=account,
        records=[
            {
                "metric_date": "2026-08-01",
                "external_campaign_id": "camp_1",
                "campaign_name": "Campaign One",
                "impressions": 100,
                "clicks": 10,
                "spend": "20.00",
                "leads": 2,
                "conversions": 1,
                "conversion_value": "50.00",
                "raw_metrics": {
                    "objective": "LEADS",
                },
            }
        ],
    )

    monkeypatch.setattr(
        performance_sync,
        "create_integration",
        lambda provider, **kwargs: integration,
    )

    persisted_payloads = []

    async def fake_persist(
        session,
        payload,
    ):
        persisted_payloads.append(
            dict(payload)
        )

        return {
            "daily_metric_id": "mdm_test",
        }

    monkeypatch.setattr(
        performance_sync,
        "persist_daily_performance",
        fake_persist,
    )

    class Result:
        pass

    class Session:
        async def execute(
            self,
            statement,
            params=None,
        ):
            return Result()

    result = (
        await performance_sync.sync_channel_account(
            Session(),
            account,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1),
        )
    )

    assert result["records_received"] == 1
    assert result["records_persisted"] == 1
    assert result["daily_metric_ids"] == [
        "mdm_test"
    ]

    assert persisted_payloads[0][
        "provider"
    ] == "fake"

    assert persisted_payloads[0][
        "channel_account_id"
    ] == "acct_1"

    assert integration.execute_calls == []


@pytest.mark.asyncio
async def test_provider_mismatch_rejected(
    monkeypatch,
):
    account = {
        "id": "acct_1",
        "provider": "fake",
        "external_account_id": "external_1",
        "status": "connected",
        "read_enabled": True,
        "write_enabled": False,
        "configuration": {},
    }

    integration = FakeIntegration(
        account=account,
        records=[
            {
                "metric_date": "2026-08-01",
                "provider": "other",
                "external_campaign_id": "camp",
            }
        ],
    )

    monkeypatch.setattr(
        performance_sync,
        "create_integration",
        lambda provider, **kwargs: integration,
    )

    with pytest.raises(ValueError):
        await performance_sync.sync_channel_account(
            object(),
            account,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1),
        )


def test_performance_record_shape_rejected():
    with pytest.raises(ValueError):
        performance_sync._performance_records(
            {"wrong": []}
        )

    with pytest.raises(ValueError):
        performance_sync._performance_records(
            {"records": "not-a-list"}
        )


@pytest.mark.asyncio
async def test_get_readable_accounts_provider_filter():
    captured = {}

    class Mappings:
        def all(self):
            return []

    class Result:
        def mappings(self):
            return Mappings()

    class Session:
        async def execute(
            self,
            statement,
            params=None,
        ):
            captured["sql"] = str(statement)
            captured["params"] = params
            return Result()

    accounts = (
        await performance_sync
        .get_readable_channel_accounts(
            Session(),
            provider=" META ",
        )
    )

    assert accounts == []
    assert captured["params"] == {
        "provider": "meta"
    }

    assert "read_enabled = TRUE" in (
        captured["sql"]
    )

    assert "lower(provider) = :provider" in (
        captured["sql"]
    )


@pytest.mark.asyncio
async def test_sync_readable_accounts_empty():
    class Mappings:
        def all(self):
            return []

    class Result:
        def mappings(self):
            return Mappings()

    class Session:
        async def execute(
            self,
            statement,
            params=None,
        ):
            return Result()

    result = (
        await performance_sync.sync_readable_accounts(
            Session(),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
        )
    )

    assert result == {
        "status": "read_only",
        "start_date": "2026-08-01",
        "end_date": "2026-08-02",
        "accounts_found": 0,
        "accounts_synced": 0,
        "records_persisted": 0,
        "accounts": [],
    }
