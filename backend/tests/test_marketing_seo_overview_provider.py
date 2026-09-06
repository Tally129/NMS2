"""SEO Overview wiring of CACHED rank-provider (DataForSEO Labs) state.

Pure/deterministic tests:

* ``summarize_provider_dataset`` describes completeness honestly from the
  persisted provider-run ledger (never invents totals or percentages).
* ``build_search_overview`` exposes the cached domain snapshot under the
  provider's own source label, while GSC metrics remain separate.
* The ``/marketing-os/search/overview`` route reads PostgreSQL cache only
  and never touches a provider adapter.
"""

from __future__ import annotations

import asyncio
import sys
import types

from fastapi import APIRouter

from marketing_os.search.overview import (
    PROVIDER_DATASET_COMPLETE,
    PROVIDER_DATASET_INCOMPLETE,
    PROVIDER_DATASET_NOT_CONNECTED,
    PROVIDER_DATASET_UNKNOWN,
    build_search_overview,
    summarize_provider_dataset,
)


# ---------------------------------------------------------------------------
# summarize_provider_dataset
# ---------------------------------------------------------------------------


def _run(**overrides):
    base = {
        "id": "run-1",
        "report_type": "ranked_keywords",
        "status": "completed",
        "requested_limit": 1000,
        "requested_offset": 0,
        "provider_items_count": 1000,
        "provider_total_count": 1017,
        "rows_normalized": 1000,
        "complete": False,
        "next_offset": 1000,
        "error": None,
        "finished_at": "2026-09-05T03:30:00+00:00",
        "created_at": "2026-09-05T03:30:00+00:00",
    }
    base.update(overrides)
    return base


def test_dataset_incomplete_with_next_offset_is_not_alarming():
    summary = summarize_provider_dataset(
        snapshot={"captured_date": "2026-09-05"},
        runs=[_run()],
        keyword_rows_stored=1000,
        keyword_captured_date="2026-09-05",
    )
    assert summary["connected"] is True
    assert summary["status"] == PROVIDER_DATASET_INCOMPLETE
    assert summary["complete"] is False
    assert summary["next_offset"] == 1000
    assert summary["provider_total_count"] == 1017
    assert summary["keyword_rows_stored"] == 1000
    assert summary["keywords_remaining"] == 17
    # 1000 / 1017 is mathematically valid -> percentage allowed.
    assert summary["percent_complete"] == 98.3
    assert "available to sync" in summary["message"]
    assert "lost" in summary["message"]  # explicitly says NOT lost rankings
    assert summary["last_error"] is None


def test_dataset_complete_when_latest_completed_run_is_complete():
    runs = [
        _run(
            id="run-2",
            requested_offset=1000,
            provider_items_count=17,
            rows_normalized=17,
            complete=True,
            next_offset=None,
        ),
        _run(),
    ]
    summary = summarize_provider_dataset(
        snapshot={"captured_date": "2026-09-05"},
        runs=runs,
        keyword_rows_stored=1017,
    )
    assert summary["status"] == PROVIDER_DATASET_COMPLETE
    assert summary["complete"] is True
    assert summary["next_offset"] is None
    assert summary["percent_complete"] == 100.0
    assert summary["keywords_remaining"] == 0


def test_percent_not_fabricated_without_valid_total():
    # No provider total stored -> no percentage.
    summary = summarize_provider_dataset(
        snapshot={"captured_date": "2026-09-05"},
        runs=[_run(provider_total_count=None)],
        keyword_rows_stored=1000,
    )
    assert summary["status"] == PROVIDER_DATASET_INCOMPLETE
    assert summary["percent_complete"] is None
    assert summary["keywords_remaining"] is None

    # Stored rows exceed the provider total -> percentage would be invalid.
    summary = summarize_provider_dataset(
        snapshot={"captured_date": "2026-09-05"},
        runs=[_run(provider_total_count=900)],
        keyword_rows_stored=1000,
    )
    assert summary["percent_complete"] is None
    assert summary["keywords_remaining"] is None


def test_failed_latest_run_surfaces_error_but_uses_last_completed_state():
    runs = [
        _run(
            id="run-err",
            status="error",
            error="DataForSEOError: provider unavailable",
            requested_offset=1000,
            provider_items_count=None,
            rows_normalized=0,
            complete=False,
            next_offset=None,
        ),
        _run(),
    ]
    summary = summarize_provider_dataset(
        snapshot={"captured_date": "2026-09-05"},
        runs=runs,
        keyword_rows_stored=1000,
    )
    assert summary["status"] == PROVIDER_DATASET_INCOMPLETE
    assert summary["next_offset"] == 1000
    assert summary["last_error"] == "DataForSEOError: provider unavailable"
    assert summary["latest_run"]["status"] == "error"
    assert summary["latest_completed_run"]["id"] == "run-1"


def test_dataset_unknown_without_ranked_keyword_runs():
    summary = summarize_provider_dataset(
        snapshot={"captured_date": "2026-09-05"},
        runs=[],
        keyword_rows_stored=0,
    )
    assert summary["connected"] is True
    assert summary["status"] == PROVIDER_DATASET_UNKNOWN
    assert summary["complete"] is None


def test_dataset_not_connected_when_nothing_cached():
    summary = summarize_provider_dataset()
    assert summary["connected"] is False
    assert summary["status"] == PROVIDER_DATASET_NOT_CONNECTED
    assert summary["percent_complete"] is None
    assert summary["latest_run"] is None


def test_non_ranked_runs_are_ignored():
    summary = summarize_provider_dataset(
        snapshot={"captured_date": "2026-09-05"},
        runs=[_run(report_type="competitors_domain", complete=True)],
        keyword_rows_stored=10,
    )
    # Competitor runs must not describe keyword completeness.
    assert summary["status"] == PROVIDER_DATASET_UNKNOWN


# ---------------------------------------------------------------------------
# build_search_overview
# ---------------------------------------------------------------------------

SITE = {"id": "s1", "site_url": "https://www.natmedsol.com/"}

SNAPSHOT = {
    "provider": "dataforseo",
    "captured_date": "2026-09-05",
    "location": "United States",
    "language": "English",
    "device": "desktop",
    "organic_keywords": 1017,
    "estimated_organic_traffic": "455.128220",
    "new_keywords": 41,
    "up_keywords": 120,
    "down_keywords": 98,
    "lost_keywords": 33,
}

GSC = {
    "connected": True,
    "clicks": 812,
    "impressions": 55000,
    "ctr": 0.014764,
    "average_position": 18.4,
    "search_queries": 3315,
}


def test_overview_exposes_cached_provider_snapshot_separately_from_gsc():
    overview = build_search_overview(
        site=SITE,
        gsc_summary=GSC,
        seo_provider={
            "provider": "dataforseo",
            "snapshot": SNAPSHOT,
            "runs": [_run()],
            "keyword_rows_stored": 1000,
            "keyword_captured_date": "2026-09-05",
        },
    )
    m = overview["metrics"]
    assert overview["connections"]["rank_provider"] is True
    assert overview["connections"]["search_console"] is True

    # Rank-provider metrics: value + provider source (NOT GSC).
    assert m["organic_keywords"] == {
        "value": 1017, "connected": True, "source": "dataforseo",
    }
    assert m["estimated_organic_traffic"]["value"] == 455.12822
    assert m["estimated_organic_traffic"]["source"] == "dataforseo"
    assert m["provider_new_keywords"]["value"] == 41
    assert m["provider_up_keywords"]["value"] == 120
    assert m["provider_down_keywords"]["value"] == 98
    assert m["provider_lost_keywords"]["value"] == 33

    # GSC metrics remain first-party and untouched.
    assert m["gsc_search_queries"] == {
        "value": 3315, "connected": True, "source": "google_search_console",
    }
    assert m["organic_clicks"]["source"] == "google_search_console"
    assert m["gsc_search_queries"]["value"] != m["organic_keywords"]["value"]

    # Completeness block is present.
    assert overview["provider_dataset"]["status"] == "incomplete"
    assert overview["provider_dataset"]["next_offset"] == 1000
    assert overview["provider_snapshot"]["captured_date"] == "2026-09-05"


def test_overview_without_cached_provider_stays_honestly_not_connected():
    overview = build_search_overview(site=SITE, gsc_summary=GSC)
    m = overview["metrics"]
    assert overview["connections"]["rank_provider"] is False
    assert m["organic_keywords"] == {
        "value": None, "connected": False, "source": "rank_provider",
    }
    assert m["provider_lost_keywords"]["connected"] is False
    assert overview["provider_dataset"]["status"] == "not_connected"
    assert overview["provider_snapshot"] is None
    # GSC values must never leak into provider metrics.
    assert m["gsc_search_queries"]["value"] == 3315


def test_overview_no_site_includes_provider_dataset_block():
    overview = build_search_overview(site=None)
    assert overview["connected"] is False
    assert overview["provider_dataset"]["status"] == "not_connected"
    for key in (
        "provider_new_keywords", "provider_up_keywords",
        "provider_down_keywords", "provider_lost_keywords",
    ):
        assert overview["metrics"][key]["connected"] is False


# ---------------------------------------------------------------------------
# Route: /marketing-os/search/overview reads cache only
# ---------------------------------------------------------------------------


def _install_stubs():
    if "deps" not in sys.modules:
        deps_stub = types.ModuleType("deps")
        deps_stub.api = APIRouter(prefix="/api")

        def _require_roles(*roles):
            async def dependency():
                return {"id": "test-user", "role": "admin"}

            return dependency

        deps_stub.require_roles = _require_roles
        sys.modules["deps"] = deps_stub
    if "postgres_db" not in sys.modules:
        postgres_stub = types.ModuleType("postgres_db")

        def _unconfigured():
            raise AssertionError("real AsyncSessionLocal must not be used")

        postgres_stub.AsyncSessionLocal = _unconfigured
        sys.modules["postgres_db"] = postgres_stub


class _FakeRows:
    def __init__(self, row=None, scalar=0):
        self._row, self._scalar = row, scalar

    def mappings(self):
        return self

    def first(self):
        return self._row

    def scalar(self):
        return self._scalar


class _FakeSession:
    """Raw-SQL cache reads used by the overview (competitors / gap counts)."""

    async def execute(self, statement, params=None):
        sql = str(statement)
        if "marketing_seo_competitor_snapshots" in sql:
            return _FakeRows(row={"count": 3, "common_keywords": 610,
                                  "captured_date": __import__("datetime").date(2026, 9, 5)})
        return _FakeRows(scalar=42)


class _FakeSessionContext:
    async def __aenter__(self):
        return _FakeSession()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_overview_route_reads_only_cached_provider_state(monkeypatch):
    _install_stubs()
    from marketing_os.routers import search as module

    monkeypatch.setattr(
        module, "AsyncSessionLocal", lambda: _FakeSessionContext()
    )

    async def fake_resolve_site(pg, site_id):
        return SITE

    async def fake_keywords(pg, site_id, tracked_only=True):
        return []

    async def fake_audit(pg, site_id):
        return None

    async def fake_gsc(pg, site_id):
        return GSC

    reads = []

    async def fake_snapshot(pg, **kw):
        reads.append(("snapshot", kw))
        return SNAPSHOT

    async def fake_runs(pg, **kw):
        reads.append(("runs", kw))
        return {"items": [_run()], "total": 1}

    async def fake_kw_page(pg, **kw):
        reads.append(("keywords", kw))
        return {"captured_date": "2026-09-05", "items": [], "total": 1000}

    monkeypatch.setattr(module, "_resolve_site", fake_resolve_site)
    monkeypatch.setattr(module, "_load_keywords", fake_keywords)
    monkeypatch.setattr(module, "_latest_audit", fake_audit)
    monkeypatch.setattr(module, "_gsc_overview_summary", fake_gsc)
    monkeypatch.setattr(
        module, "load_cached_seo_domain_snapshot", fake_snapshot
    )
    monkeypatch.setattr(module, "load_cached_seo_provider_runs", fake_runs)
    monkeypatch.setattr(module, "load_cached_seo_keywords", fake_kw_page)

    import marketing_os.search.seo_intel_store as store

    async def fake_bl(pg, **kw):
        return {"provider": "dataforseo", "backlinks": 1842, "referring_domains": 263,
                "captured_date": "2026-09-05", "sampled": {"new_sampled": 14, "lost_sampled": 8}}

    async def fake_rt(pg, **kw):
        return {"tracked": 5, "observed": 5, "top_3": 1, "top_10": 3, "top_20": 4,
                "improved": 2, "declined": 1, "average_position": 9.4}

    monkeypatch.setattr(store, "latest_backlink_summary", fake_bl)
    monkeypatch.setattr(store, "rank_tracking_summary", fake_rt)

    # Any provider adapter usage would be a paid call: make it impossible.
    import marketing_os.integrations.dataforseo as dfs

    def _boom(*a, **k):
        raise AssertionError("overview must never call DataForSEO")

    monkeypatch.setattr(dfs.DataForSEOIntegration, "_post", _boom)

    result = asyncio.run(
        module.search_overview(site_id=None, user={"id": "u1"})
    )

    assert result["connected"] is True
    assert result["metrics"]["organic_keywords"]["value"] == 1017
    assert result["metrics"]["organic_keywords"]["source"] == "dataforseo"
    assert result["metrics"]["gsc_search_queries"]["value"] == 3315
    assert result["provider_dataset"]["status"] == "incomplete"
    assert result["provider_dataset"]["keyword_rows_stored"] == 1000
    assert result["provider_dataset"]["next_offset"] == 1000

    m = result["metrics"]
    assert m["organic_competitors"] == {"value": 3, "connected": True, "source": "dataforseo"}
    assert m["competitor_common_keywords"]["value"] == 610
    assert m["keyword_opportunities"]["value"] == 42
    assert m["backlink_count"] == {"value": 1842, "connected": True, "source": "dataforseo"}
    assert m["backlink_new_links_sampled"]["value"] == 14
    assert m["rt_tracked_keywords"] == {"value": 5, "connected": True, "source": "dataforseo_serp"}
    assert m["rt_top_10"]["value"] == 3 and m["rt_average_position"]["value"] == 9.4
    # Still no GSC leakage into any provider metric.
    assert m["gsc_search_queries"]["source"] == "google_search_console"

    kinds = [k for k, _ in reads]
    assert kinds == ["snapshot", "runs", "keywords"]
    runs_kw = dict(reads[1][1])
    assert runs_kw["report_type"] == "ranked_keywords"
    kw_kw = dict(reads[2][1])
    assert kw_kw["limit"] == 1  # count only; no bulk keyword load
