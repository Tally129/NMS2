"""Phase 4 — Meta Ads + Microsoft Advertising read-only providers.

Covers normalization, provider bootstrap/registration idempotency, the
no-network readiness contract, honest null metrics, the unified paid-media
overview, Director behavior with real vs disconnected data, read-only
enforcement, and the unchanged safety policy.
"""
import asyncio

import pytest

from marketing_os.integrations import meta_ads, microsoft_ads
from marketing_os.integrations.base import MarketingIntegration
from marketing_os.integrations.bootstrap import register_default_integrations
from marketing_os.integrations.paid_normalize import normalize_campaign_row
from marketing_os.integrations.registry import (
    create_integration,
    registered_providers,
)
from marketing_os.services.director import build_marketing_brief
from marketing_os.services.paid_media import (
    PAID_PROVIDERS,
    build_paid_media_overview,
    paid_performance_signals,
    provider_readiness,
)


META_ENV = (
    "META_ADS_ACCESS_TOKEN",
    "META_ADS_ACCOUNT_ID",
    "META_ADS_APP_ID",
    "META_ADS_APP_SECRET",
)

MSFT_ENV = (
    "MICROSOFT_ADS_DEVELOPER_TOKEN",
    "MICROSOFT_ADS_ACCOUNT_ID",
    "MICROSOFT_ADS_CUSTOMER_ID",
    "MICROSOFT_ADS_REFRESH_TOKEN",
    "MICROSOFT_ADS_CLIENT_ID",
)


def _clear(monkeypatch, names):
    for name in names:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _restore_registry():
    """Keep the global integration registry clean for other test modules.

    These tests intentionally register the default paid providers; undo
    that afterwards so exact-equality assertions elsewhere are unaffected.
    """
    from marketing_os.integrations.registry import (
        registered_providers as _rp,
        unregister_integration as _unreg,
    )

    before = set(_rp())
    yield
    for provider in set(_rp()) - before:
        _unreg(provider)


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #

def test_meta_normalization_computes_derived_rates():
    row = {
        "account_id": "act_123",
        "campaign_id": "c1",
        "campaign_name": "IV Therapy",
        "spend": "200.00",
        "impressions": 10000,
        "clicks": 400,
        "conversions": 20,
        "revenue": "1000.00",
    }
    out = normalize_campaign_row("meta_ads", row)

    assert out["provider"] == "meta_ads"
    assert out["spend"] == 200.0
    assert out["impressions"] == 10000
    assert out["clicks"] == 400
    assert out["ctr"] == pytest.approx(0.04)
    assert out["cpc"] == pytest.approx(0.5)
    assert out["cpa"] == pytest.approx(10.0)
    assert out["roas"] == pytest.approx(5.0)


def test_microsoft_normalization_leaves_missing_metrics_null():
    row = {
        "account_id": "9988",
        "campaign_id": "c9",
        "campaign_name": "Search Brand",
        # no spend / impressions / clicks / conversions / revenue
    }
    out = normalize_campaign_row("microsoft_ads", row)

    assert out["provider"] == "microsoft_ads"
    # Unavailable metrics must remain None (never fabricated as zero).
    for field in (
        "spend",
        "impressions",
        "clicks",
        "ctr",
        "cpc",
        "cpa",
        "revenue",
        "roas",
    ):
        assert out[field] is None


def test_normalization_no_revenue_means_no_roas():
    row = {"spend": "50", "clicks": 10, "impressions": 100}
    out = normalize_campaign_row("meta_ads", row)
    assert out["roas"] is None  # no attributed revenue -> no ROAS


# --------------------------------------------------------------------------- #
# Bootstrap / registration
# --------------------------------------------------------------------------- #

def test_bootstrap_registers_all_paid_providers():
    providers = register_default_integrations()
    for provider in ("google_ads", "meta_ads", "microsoft_ads"):
        assert provider in providers


def test_bootstrap_is_idempotent():
    first = register_default_integrations()
    second = register_default_integrations()
    assert first == second
    # No duplicate keys — registered_providers returns a sorted unique tuple.
    assert len(set(second)) == len(second)


def test_registration_performs_no_network_call(monkeypatch):
    # Clearing credentials must not matter: registration never touches env
    # or network. Registered adapters resolve without calling out.
    _clear(monkeypatch, META_ENV)
    register_default_integrations()
    integration = create_integration("meta_ads")
    assert isinstance(integration, MarketingIntegration)
    assert integration.provider == "meta_ads"


# --------------------------------------------------------------------------- #
# Readiness (no network)
# --------------------------------------------------------------------------- #

def test_meta_readiness_not_connected_without_credentials(monkeypatch):
    _clear(monkeypatch, META_ENV)
    r = provider_readiness("meta_ads")
    assert r["connected"] is False
    assert r["status"] == "not_connected"
    assert r["read_only"] is True
    assert r["external_write"] is False


def test_meta_readiness_incomplete_configuration(monkeypatch):
    _clear(monkeypatch, META_ENV)
    monkeypatch.setenv("META_ADS_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("META_ADS_ACCOUNT_ID", "act_1")
    # app_id/secret missing -> incomplete
    r = provider_readiness("meta_ads")
    assert r["status"] == "configuration_incomplete"
    assert r["connected"] is False


def test_microsoft_readiness_connected_with_full_credentials(monkeypatch):
    _clear(monkeypatch, MSFT_ENV)
    monkeypatch.setenv("MICROSOFT_ADS_DEVELOPER_TOKEN", "dev")
    monkeypatch.setenv("MICROSOFT_ADS_ACCOUNT_ID", "1")
    monkeypatch.setenv("MICROSOFT_ADS_REFRESH_TOKEN", "rt")
    monkeypatch.setenv("MICROSOFT_ADS_CLIENT_ID", "cid")
    r = provider_readiness("microsoft_ads")
    assert r["connected"] is True
    assert r["status"] == "connected"


# --------------------------------------------------------------------------- #
# Unified paid-media overview
# --------------------------------------------------------------------------- #

def test_overview_all_disconnected_has_null_metrics(monkeypatch):
    _clear(monkeypatch, META_ENV)
    _clear(monkeypatch, MSFT_ENV)
    overview = build_paid_media_overview([])
    assert [p["provider"] for p in overview["providers"]] == list(
        PAID_PROVIDERS
    )
    for entry in overview["providers"]:
        assert entry["has_data"] is False
        assert entry["metrics"] is None  # unknown, never zero
    assert overview["external_writes_enabled"] is False
    assert overview["human_approval_required"] is True


def test_overview_aggregates_stored_rows():
    rows = [
        {
            "provider": "meta_ads",
            "impressions": 1000,
            "clicks": 50,
            "spend": "100.00",
            "conversions": "5",
            "conversion_value": "500.00",
        },
        {
            "provider": "meta_ads",
            "impressions": 1000,
            "clicks": 50,
            "spend": "100.00",
            "conversions": "5",
            "conversion_value": "500.00",
        },
    ]
    overview = build_paid_media_overview(rows)
    meta = next(
        p for p in overview["providers"] if p["provider"] == "meta_ads"
    )
    assert meta["has_data"] is True
    assert meta["metrics"]["spend"] == 200.0
    assert meta["metrics"]["impressions"] == 2000
    assert meta["metrics"]["clicks"] == 100
    assert meta["metrics"]["ctr"] == pytest.approx(0.05)
    assert meta["metrics"]["cpa"] == pytest.approx(20.0)
    assert meta["metrics"]["roas"] == pytest.approx(5.0)

    # Other providers still honestly empty.
    msft = next(
        p for p in overview["providers"] if p["provider"] == "microsoft_ads"
    )
    assert msft["has_data"] is False
    assert msft["metrics"] is None


# --------------------------------------------------------------------------- #
# Director integration
# --------------------------------------------------------------------------- #

def test_director_recommends_only_for_channels_with_data():
    rows = [
        {
            "provider": "meta_ads",
            "impressions": 10000,
            "clicks": 500,
            "spend": "300.00",
            "conversions": "25",
            "conversion_value": "1500.00",
        }
    ]
    overview = build_paid_media_overview(rows)
    signals = paid_performance_signals(overview)
    brief = build_marketing_brief(performance=signals, paid_media=overview)

    channels = {rec["channel"] for rec in brief["recommendations"]}
    # meta_ads has data -> can appear; disconnected providers must not.
    assert "microsoft_ads" not in channels
    assert "google_ads" not in channels
    assert brief["paid_media"] is not None


def test_director_no_recommendations_for_disconnected_providers(monkeypatch):
    _clear(monkeypatch, META_ENV)
    _clear(monkeypatch, MSFT_ENV)
    overview = build_paid_media_overview([])
    signals = paid_performance_signals(overview)
    assert signals == []  # disconnected/empty channels produce no signal

    brief = build_marketing_brief(performance=signals, paid_media=overview)
    paid_channels = {"google_ads", "meta_ads", "microsoft_ads"}
    rec_channels = {rec["channel"] for rec in brief["recommendations"]}
    assert paid_channels.isdisjoint(rec_channels)

    # Providers are still surfaced honestly in the informational block.
    surfaced = {p["provider"] for p in brief["paid_media"]["providers"]}
    assert surfaced == paid_channels


# --------------------------------------------------------------------------- #
# Read-only enforcement + safety policy
# --------------------------------------------------------------------------- #

def test_paid_adapters_have_no_external_write_method():
    for cls, provider in (
        (meta_ads.MetaAdsIntegration, "meta_ads"),
        (microsoft_ads.MicrosoftAdsIntegration, "microsoft_ads"),
    ):
        adapter = cls()
        assert adapter.provider == provider
        with pytest.raises(RuntimeError):
            asyncio.get_event_loop().run_until_complete(
                adapter.execute_action()
            )


def test_safety_policy_flags_unchanged():
    overview = build_paid_media_overview([])
    assert overview["read_only"] is True
    assert overview["external_writes_enabled"] is False
    assert overview["automatic_budget_changes_enabled"] is False
    assert overview["automatic_campaign_creation_enabled"] is False
    assert overview["human_approval_required"] is True

    brief = build_marketing_brief(paid_media=overview)
    safety = brief["safety"]
    assert safety["external_writes"] is False
    assert safety["automatic_budget_changes"] is False
    assert safety["automatic_campaign_creation"] is False
    assert safety["automatic_publishing"] is False
    assert safety["human_approval_required"] is True
