"""Focused tests for Phase 2 — Google Search Console + Rank Tracking.

Deterministic; no live Google calls (fakes/mocks only), no production creds.
"""

from __future__ import annotations

import builtins
import json

import pytest

from marketing_os.capabilities import CAPABILITIES
from marketing_os.policy import DEFAULT_POLICY
from marketing_os.services.measurement import PROHIBITED_MARKETING_FIELDS
from marketing_os.search import gsc
from marketing_os.search.gsc import (
    GoogleSearchConsoleAdapter,
    PROPERTY_ENV,
    SA_FILE_ENV,
    SA_JSON_ENV,
    aggregate_totals,
    build_client,
    credential_readiness,
    normalize_rows,
    query_search_analytics,
    top_by_clicks,
)
from marketing_os.search.gsc_recommendations import build_gsc_recommendations
from marketing_os.search.gsc_sync import sync_search_console
from marketing_os.search.rank_tracking import (
    classify_movement,
    compute_rank_history,
    summarize_movements,
)

VALID_SA = json.dumps({
    "client_email": "svc@example.iam.gserviceaccount.com",
    "private_key": "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----",
    "token_uri": "https://oauth2.googleapis.com/token",
})


def _clear_env(monkeypatch):
    for var in (PROPERTY_ENV, SA_JSON_ENV, SA_FILE_ENV):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------- readiness

def test_readiness_not_connected(monkeypatch):
    _clear_env(monkeypatch)
    r = credential_readiness()
    assert r["status"] == "not_connected"
    assert r["connected"] is False
    assert r["read_only"] is True
    assert r["external_write"] is False


def test_readiness_configuration_incomplete_property_only(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(PROPERTY_ENV, "sc-domain:example.com")
    r = credential_readiness()
    assert r["status"] == "configuration_incomplete"
    assert r["property_configured"] is True
    assert r["credentials_present"] is False


def test_readiness_missing_credential_fields(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(PROPERTY_ENV, "sc-domain:example.com")
    monkeypatch.setenv(SA_JSON_ENV, json.dumps({"client_email": "a"}))
    r = credential_readiness()
    assert r["status"] == "configuration_incomplete"
    assert r["credentials_valid_format"] is False
    assert "private_key" in r["missing_credential_fields"]


def test_readiness_connected(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(PROPERTY_ENV, "sc-domain:example.com")
    monkeypatch.setenv(SA_JSON_ENV, VALID_SA)
    r = credential_readiness()
    assert r["status"] == "connected"
    assert r["connected"] is True


def test_readiness_never_exposes_credentials(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(PROPERTY_ENV, "sc-domain:example.com")
    monkeypatch.setenv(SA_JSON_ENV, VALID_SA)
    blob = json.dumps(credential_readiness())
    assert "private_key" not in blob or "BEGIN PRIVATE KEY" not in blob
    assert "svc@example" not in blob


# -------------------------------------------------- disconnected / no network

def test_build_client_raises_when_disconnected(monkeypatch):
    _clear_env(monkeypatch)
    with pytest.raises(RuntimeError):
        build_client()


def test_no_google_import_during_registration_and_readiness(monkeypatch):
    real_import = builtins.__import__

    def guard(name, *args, **kwargs):
        if name.split(".")[0] in {"googleapiclient", "google"}:
            raise AssertionError(f"unexpected google import: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    # Construction + readiness must never import Google.
    adapter = GoogleSearchConsoleAdapter(client=object())
    adapter.readiness()
    credential_readiness()


def test_build_client_uses_injected_factory_without_google(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(PROPERTY_ENV, "sc-domain:example.com")
    monkeypatch.setenv(SA_JSON_ENV, VALID_SA)

    real_import = builtins.__import__

    def guard(name, *args, **kwargs):
        if name.split(".")[0] in {"googleapiclient", "google"}:
            raise AssertionError("factory path must not import google")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    sentinel = object()
    assert build_client(client_factory=lambda: sentinel) is sentinel


# ------------------------------------------------------------- read-only API

class _Exec:
    def __init__(self, resp):
        self._resp = resp

    def execute(self):
        return self._resp


class _SA:
    def __init__(self, resp, calls):
        self._resp = resp
        self._calls = calls

    def query(self, *, siteUrl, body):
        self._calls.append((siteUrl, body))
        return _Exec(self._resp)


class FakeClient:
    """Only exposes read-only searchanalytics().query() — no write methods."""

    def __init__(self, resp):
        self._resp = resp
        self.calls: list = []

    def searchanalytics(self):
        return _SA(self._resp, self.calls)


RESP = {
    "rows": [
        {"keys": ["book appointment online"], "clicks": 10,
         "impressions": 200, "ctr": 0.05, "position": 4.2},
        {"keys": ["naturopath near me"], "clicks": 3,
         "impressions": 500, "ctr": 0.006, "position": 12.5},
    ]
}


def test_query_builds_read_only_request():
    client = FakeClient(RESP)
    out = query_search_analytics(
        client, property_id="sc-domain:example.com",
        start_date="2026-08-01", end_date="2026-08-28",
        dimensions=["query"],
    )
    site_url, body = client.calls[0]
    assert site_url == "sc-domain:example.com"
    assert body["type"] == "web"
    assert body["dimensions"] == ["query"]
    assert body["dataState"] == "final"
    assert out["rows"][0]["clicks"] == 10
    # FakeClient has no write methods.
    assert not hasattr(client, "sitemaps")
    assert not hasattr(client, "sites")


def test_query_rejects_bad_dimensions_and_rowlimit():
    client = FakeClient(RESP)
    with pytest.raises(ValueError):
        query_search_analytics(
            client, property_id="p", start_date="a", end_date="b",
            dimensions=["not_a_dim"],
        )
    with pytest.raises(ValueError):
        query_search_analytics(
            client, property_id="p", start_date="a", end_date="b",
            dimensions=["query"], row_limit=0,
        )


def test_adapter_execute_action_is_blocked():
    with pytest.raises(RuntimeError):
        GoogleSearchConsoleAdapter(client=object()).execute_action()


# --------------------------------------------------------- normalization

def test_normalize_rows_maps_dimensions_and_types():
    rows = normalize_rows(RESP, ["query"])
    assert rows[0]["query"] == "book appointment online"
    assert rows[0]["clicks"] == 10
    assert rows[0]["impressions"] == 200
    assert rows[0]["position"] == 4.2
    assert rows[0]["source"] == "google_search_console"


def test_aggregate_totals_impression_weighted_position():
    rows = normalize_rows(RESP, ["query"])
    totals = aggregate_totals(rows)
    assert totals["clicks"] == 13
    assert totals["impressions"] == 700
    # impression-weighted: (4.2*200 + 12.5*500)/700
    assert totals["average_position"] == round((4.2 * 200 + 12.5 * 500) / 700, 2)
    assert totals["metric_type"] == "gsc_average_position"


def test_top_by_clicks_ordering():
    rows = normalize_rows(RESP, ["query"])
    top = top_by_clicks(rows, "query", limit=1)
    assert top[0]["query"] == "book appointment online"


# ------------------------------------------------------- rank tracking math

def test_compute_rank_history_gain():
    snaps = [
        {"captured_date": "2026-08-01", "position": 9.0},
        {"captured_date": "2026-08-15", "position": 6.0},
        {"captured_date": "2026-08-28", "position": 4.0},
    ]
    hist = compute_rank_history(
        snaps, source="google_search_console",
        metric_type="gsc_average_position",
    )
    assert hist["current_position"] == 4.0
    assert hist["previous_position"] == 6.0
    assert hist["best_position"] == 4.0
    assert hist["change"] == 2.0        # improved by 2 positions
    assert hist["movement"] == "gain"
    assert hist["last_checked"] == "2026-08-28"
    assert len(hist["history"]) == 3


def test_compute_rank_history_loss_and_new_and_empty():
    loss = compute_rank_history(
        [{"captured_date": "1", "position": 3.0},
         {"captured_date": "2", "position": 8.0}],
        source="manual", metric_type="serp_rank",
    )
    assert loss["movement"] == "loss"
    new = compute_rank_history(
        [{"captured_date": "1", "position": 5.0}],
        source="manual", metric_type="serp_rank",
    )
    assert new["movement"] == "new"
    empty = compute_rank_history(
        [], source="manual", metric_type="serp_rank"
    )
    assert empty["movement"] == "unranked"


def test_gsc_position_and_serp_rank_are_distinct():
    gsc_hist = compute_rank_history(
        [{"captured_date": "1", "position": 4.2}],
        source="google_search_console",
        metric_type="gsc_average_position",
    )
    serp_hist = compute_rank_history(
        [{"captured_date": "1", "position": 3}],
        source="manual", metric_type="serp_rank",
    )
    assert gsc_hist["metric_type"] != serp_hist["metric_type"]
    assert gsc_hist["source"] != serp_hist["source"]


def test_summarize_movements_and_classify():
    assert classify_movement(2) == "gain"
    assert classify_movement(-2) == "loss"
    assert classify_movement(0) == "unchanged"
    assert classify_movement(None) == "new"
    items = [{"movement": "gain"}, {"movement": "loss"},
             {"movement": "unchanged"}, {"movement": "unranked"}]
    s = summarize_movements(items)
    assert s == {"gains": 1, "losses": 1, "unchanged": 1, "new": 0,
                 "unranked": 1}


# ------------------------------------------------------------ sync (fakes)

class FakeAdapter:
    provider = "google_search_console"

    def __init__(self, by_dim):
        self._by_dim = by_dim
        self.calls = 0

    def fetch_search_analytics(self, *, start_date, end_date, dimensions,
                               row_limit=1000, start_row=0,
                               data_state="final"):
        self.calls += 1
        return {"rows": self._by_dim.get(dimensions[0], [])}


class FakeSession:
    """Emulates ON CONFLICT upsert semantics keyed by natural keys."""

    def __init__(self):
        self.daily: dict = {}
        self.queries: dict = {}
        self.pages: dict = {}
        self.runs: list = []

    def begin(self):
        session = self

        class _Ctx:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *exc):
                return False

        return _Ctx()

    async def execute(self, stmt, params=None):
        sql = str(stmt).lower()
        p = params or {}
        if "marketing_gsc_daily_metrics" in sql and "insert" in sql:
            self.daily[(p["site_id"], str(p["metric_date"]))] = p
        elif "marketing_gsc_query_metrics" in sql and "insert" in sql:
            self.queries[(p["site_id"], str(p["captured_date"]),
                          p["normalized_query"])] = p
        elif "marketing_gsc_page_metrics" in sql and "insert" in sql:
            self.pages[(p["site_id"], str(p["captured_date"]),
                        p["page"])] = p
        elif "marketing_gsc_sync_runs" in sql and "insert" in sql:
            self.runs.append(p)

        class _R:
            def first(self_inner):
                return None

        return _R()


SYNC_DATA = {
    "date": [{"keys": ["2026-08-28"], "clicks": 5, "impressions": 100,
              "ctr": 0.05, "position": 6.0}],
    "query": [
        {"keys": ["book appointment online"], "clicks": 4,
         "impressions": 80, "ctr": 0.05, "position": 5.0},
        {"keys": ["naturopath"], "clicks": 1, "impressions": 20,
         "ctr": 0.05, "position": 9.0},
    ],
    "page": [{"keys": ["https://example.com/"], "clicks": 5,
              "impressions": 100, "ctr": 0.05, "position": 6.0}],
}


@pytest.mark.asyncio
async def test_sync_is_read_only_and_idempotent():
    session = FakeSession()
    adapter = FakeAdapter(SYNC_DATA)

    first = await sync_search_console(
        session, site_id="site1", adapter=adapter,
        start_date="2026-08-01", end_date="2026-08-28",
    )
    assert first["status"] == "completed"
    assert first["rows_synced"] == 4       # 1 daily + 2 query + 1 page
    q_after_first = len(session.queries)

    # Re-run identical window -> upsert dedupe -> stable counts.
    await sync_search_console(
        session, site_id="site1", adapter=adapter,
        start_date="2026-08-01", end_date="2026-08-28",
    )
    assert len(session.queries) == q_after_first   # idempotent
    assert len(session.daily) == 1
    assert len(session.pages) == 1
    assert len(session.runs) == 2                   # 2 audit trail runs


@pytest.mark.asyncio
async def test_sync_records_read_error_without_raising():
    class Boom:
        def fetch_search_analytics(self, **kwargs):
            raise RuntimeError("network down")

    session = FakeSession()
    result = await sync_search_console(
        session, site_id="s", adapter=Boom(),
        start_date="2026-08-01", end_date="2026-08-28",
    )
    assert result["status"] == "error"
    assert "network down" in result["error"]
    assert len(session.runs) == 1


# --------------------------------------------------- advisory recommendations

def test_gsc_recommendations_are_advisory():
    query_rows = [
        {"query": "clinic services", "clicks": 1, "impressions": 500,
         "ctr": 0.002, "position": 8.0},
        {"query": "detox program", "clicks": 2, "impressions": 300,
         "ctr": 0.006, "position": 15.0},
    ]
    recs = build_gsc_recommendations(
        query_rows=query_rows,
        rank_items=[{"keyword": "detox program", "movement": "loss",
                     "metric_type": "gsc_average_position",
                     "source": "google_search_console",
                     "previous_position": 5.0, "current_position": 12.0}],
    )
    assert recs
    for r in recs:
        assert r["advisory_only"] is True
        assert r["requires_human_approval"] is True
        assert r["external_write"] is False
    titles = {r["title"] for r in recs}
    assert "Improve CTR on high-impression query" in titles
    assert "Investigate ranking decline" in titles


# ------------------------------------------------------------ safety + no PHI

def test_gsc_models_have_no_phi_columns():
    from postgres_models.marketing_gsc import (
        MarketingGscDailyMetric,
        MarketingGscPageMetric,
        MarketingGscQueryMetric,
        MarketingGscSyncRun,
    )
    for model in (MarketingGscSyncRun, MarketingGscDailyMetric,
                  MarketingGscQueryMetric, MarketingGscPageMetric):
        cols = {c.name for c in model.__table__.columns}
        assert not (cols & PROHIBITED_MARKETING_FIELDS), model


def test_gsc_capability_is_read_only():
    cap = CAPABILITIES["google_search_console"]
    assert cap["mode"] == "read_only"
    assert cap["write_enabled"] is False
    assert cap["external_write_enabled"] is False
    assert cap["phi_stored"] is False
    assert cap["position_is_serp_rank"] is False


def test_safety_policy_unchanged():
    assert DEFAULT_POLICY.external_writes_enabled is False
    assert DEFAULT_POLICY.automatic_budget_changes_enabled is False
    assert DEFAULT_POLICY.automatic_campaign_creation_enabled is False
    assert DEFAULT_POLICY.automatic_publishing_enabled is False
    assert DEFAULT_POLICY.human_approval_required is True
