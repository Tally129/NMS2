"""SEO intelligence phase 2 — normalizers, extended bounded sync, governed
refresh planning, scheduler kill-switch, GSC completeness persistence.

Pure tests: fake adapter + fake session. No network, no PostgreSQL.
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from marketing_os.integrations.dataforseo import (
    GAP_MISSING, GAP_STRONG, GAP_UNTAPPED, GAP_WEAK, REPORT_BACKLINKS,
    REPORT_BACKLINKS_SUMMARY, REPORT_KEYWORD_GAP, REPORT_SERP_RANK, classify_gap,
    normalize_backlink_summary, normalize_backlinks, normalize_domain_intersection,
    normalize_ranked_keywords, normalize_serp_rank,
)
from marketing_os.search import seo_refresh
from marketing_os.search.gsc_sync import sync_search_console
from marketing_os.search.seo_provider_sync import (
    SUPPORTED_REPORTS, sync_seo_provider_report_bounded,
)


def run(coro):
    return asyncio.run(coro)


def _envelope(items, total_count=None, items_count=None, extra=None):
    result = {"items": items, "items_count": items_count if items_count is not None else len(items),
              "total_count": total_count if total_count is not None else len(items)}
    result.update(extra or {})
    return {"status_code": 20000, "cost": 0.0101, "tasks": [
        {"status_code": 20000, "cost": 0.0101, "result": [result]}]}


# ------------------------------------------------------------- normalizers


def test_classify_gap_buckets():
    assert classify_gap(None, 5) == GAP_MISSING
    assert classify_gap(4, None) == GAP_UNTAPPED
    assert classify_gap(3, 9) == GAP_STRONG
    assert classify_gap(12, 2) == GAP_WEAK
    assert classify_gap(7, 7) == "shared"


def test_normalize_domain_intersection_reads_both_slots():
    env = _envelope([
        {"keyword_data": {"keyword": "IV Therapy Scottsdale",
                          "keyword_info": {"search_volume": 320, "cpc": 6.5},
                          "keyword_properties": {"keyword_difficulty": 22},
                          "search_intent_info": {"main_intent": "commercial"}},
         "first_domain_serp_element": {"serp_item": {"rank_absolute": 3, "url": "https://www.natmedsol.com/iv/", "etv": 40.2}},
         "second_domain_serp_element": {"serp_item": {"rank_absolute": 8, "url": "https://rival.com/iv", "etv": 10}}},
        {"keyword_data": {"keyword": "  "}},  # dropped
    ])
    rows = normalize_domain_intersection(env, target="www.natmedsol.com", competitor="https://rival.com/")
    assert len(rows) == 1
    r = rows[0]
    assert r["normalized_keyword"] == "iv therapy scottsdale"
    assert r["target_domain"] == "natmedsol.com" and r["competitor_domain"] == "rival.com"
    assert (r["target_rank"], r["competitor_rank"]) == (3, 8)
    assert r["gap_type"] == GAP_STRONG
    assert r["search_volume"] == 320 and r["cpc"] == 6.5 and r["intent"] == "commercial"
    assert r["target_etv"] == 40.2

    swapped = normalize_domain_intersection(env, target="natmedsol.com", competitor="rival.com", target_is_first=False)
    assert (swapped[0]["target_rank"], swapped[0]["competitor_rank"]) == (8, 3)
    assert swapped[0]["gap_type"] == GAP_WEAK


def test_normalize_backlink_summary_and_rows():
    env = _envelope([{"target": "natmedsol.com", "rank": 210, "backlinks": 1500, "referring_domains": 240,
                      "referring_pages": 900, "referring_main_domains": 230, "referring_ips": 200,
                      "broken_backlinks": 12, "referring_links_attributes": {"nofollow": 300},
                      "referring_links_types": {"anchor": 1400, "image": 100}}])
    s = normalize_backlink_summary(env, target="natmedsol.com")
    assert s["backlinks"] == 1500 and s["referring_domains"] == 240
    assert s["nofollow_links"] == 300 and s["dofollow_links"] == 1200
    assert s["referring_links_types"]["anchor"] == 1400
    assert normalize_backlink_summary({"tasks": []}, target="x.com") == {}

    env2 = _envelope([{"url_from": "https://blog.example.com/post", "domain_from": "blog.example.com",
                       "url_to": "https://www.natmedsol.com/", "anchor": "Natural Medical Solutions",
                       "dofollow": True, "is_new": True, "is_lost": False, "first_seen": "2026-08-01 10:00:00 +00:00",
                       "last_seen": "2026-09-01 10:00:00 +00:00", "domain_from_rank": 350, "item_type": "anchor"},
                      {"url_from": ""}])
    rows = normalize_backlinks(env2, target="natmedsol.com")
    assert len(rows) == 1 and rows[0]["dofollow"] is True and rows[0]["is_new"] is True
    assert rows[0]["domain_from_rank"] == 350


def test_normalize_serp_rank_finds_target_and_features():
    env = {"tasks": [{"result": [{"se_results_count": 1234567, "check_url": "https://google.com/?q=x",
                                  "datetime": "2026-09-06 01:00:00 +00:00", "items": [
        {"type": "people_also_ask", "rank_absolute": 1},
        {"type": "organic", "rank_group": 1, "rank_absolute": 2, "domain": "rival.com", "url": "https://rival.com/"},
        {"type": "local_pack", "rank_absolute": 3},
        {"type": "organic", "rank_group": 2, "rank_absolute": 4, "domain": "www.natmedsol.com", "url": "https://www.natmedsol.com/iv/"},
    ]}]}]}
    obs = normalize_serp_rank(env, keyword="iv therapy", target_domain="natmedsol.com")
    assert obs["found"] is True and obs["position"] == 4 and obs["rank_group"] == 2
    assert obs["ranking_url"].endswith("/iv/")
    assert obs["serp_features"] == ["people_also_ask", "local_pack"]
    assert obs["se_results_count"] == 1234567 and obs["depth"] == 4

    missing = normalize_serp_rank(env, keyword="iv therapy", target_domain="other.com")
    assert missing["found"] is False and missing["position"] is None


def test_ranked_keywords_capture_previous_rank_change_and_etv_only_when_present():
    env = _envelope([
        {"keyword_data": {"keyword": "naturopath phoenix", "keyword_info": {"search_volume": 100}},
         "ranked_serp_element": {"serp_item": {"rank_absolute": 5, "url": "https://www.natmedsol.com/",
                                               "etv": 12.5, "rank_changes": {"previous_rank_absolute": 9, "is_new": False}}}},
        {"keyword_data": {"keyword": "iv drip", "keyword_info": {"search_volume": 50}},
         "ranked_serp_element": {"serp_item": {"rank_absolute": 11, "url": "https://www.natmedsol.com/iv/"}}},
    ])
    rows = normalize_ranked_keywords(env)
    assert rows[0]["previous_rank"] == 9 and rows[0]["rank_change"] == 4 and rows[0]["estimated_traffic"] == 12.5
    assert rows[1]["previous_rank"] is None and rows[1]["rank_change"] is None and rows[1]["estimated_traffic"] is None


# ------------------------------------------------- extended bounded sync


class _Row(dict):
    """dict that also quacks like a SQLAlchemy Row for _serialize_row."""

    @property
    def _mapping(self):
        return dict(self)


class _Result:
    def __init__(self, row=None, rows=None, scalar=None):
        self._row = _Row(row) if isinstance(row, dict) else row
        self._rows, self._scalar = [_Row(r) for r in (rows or [])], scalar

    def mappings(self):
        return self

    def first(self):
        return self._row

    def all(self):
        return self._rows

    def scalar(self):
        return self._scalar


class FakeSession:
    def __init__(self, tracked=None):
        self.calls = []
        self.tracked = tracked

    async def execute(self, statement, params=None):
        sql = str(statement)
        p = dict(params or {})
        self.calls.append({"sql": sql, "params": p})
        if "FROM marketing_seo_tracked_keywords WHERE id" in sql:
            return _Result(row=self.tracked)
        if "RETURNING" in sql:
            return _Result(row={**p, "id": p.get("id", "row-1")})
        return _Result()

    async def commit(self):
        self.calls.append({"sql": "COMMIT", "params": {}})

    async def rollback(self):
        self.calls.append({"sql": "ROLLBACK", "params": {}})


def _gap_items(n):
    return [{"keyword_data": {"keyword": f"kw {i}", "keyword_info": {"search_volume": 10}},
             "first_domain_serp_element": {"serp_item": {"rank_absolute": 5}},
             "second_domain_serp_element": {"serp_item": {"rank_absolute": 9}}} for i in range(n)]


class FakeAdapter:
    def __init__(self):
        self.calls = []

    async def fetch_domain_intersection(self, **kw):
        self.calls.append(("gap", kw))
        # Provider consumed 100 items; one is unusable -> 99 normalized rows.
        items = _gap_items(99) + [{"keyword_data": {"keyword": ""}}]
        env = _envelope(items, total_count=250, items_count=100)
        return {"provider": "dataforseo", "status_code": 20000, "task_status_code": 20000,
                "cost": 0.0101, "task_cost": 0.0101, "items_count": 100, "total_count": 250,
                "report": REPORT_KEYWORD_GAP, "target": kw["target"], "limit": kw["limit"], "offset": kw["offset"],
                "gap_rows": normalize_domain_intersection(env, target=kw["target"], competitor=kw["competitor"],
                                                          target_is_first=kw["target_is_first"])}

    async def fetch_backlinks_summary(self, **kw):
        self.calls.append(("summary", kw))
        env = _envelope([{"target": kw["target"], "backlinks": 10, "referring_domains": 4}])
        return {"provider": "dataforseo", "status_code": 20000, "task_status_code": 20000, "cost": 0.02,
                "task_cost": 0.02, "items_count": 1, "total_count": 1, "report": REPORT_BACKLINKS_SUMMARY,
                "target": kw["target"], "summary": normalize_backlink_summary(env, target=kw["target"])}

    async def fetch_serp_rank(self, **kw):
        self.calls.append(("serp", kw))
        env = {"tasks": [{"result": [{"items": [{"type": "organic", "rank_absolute": 6, "rank_group": 6,
                                                  "domain": "natmedsol.com", "url": "https://natmedsol.com/"}]}]}]}
        return {"provider": "dataforseo", "status_code": 20000, "task_status_code": 20000, "cost": 0.002,
                "task_cost": 0.002, "items_count": 1, "total_count": 1, "report": REPORT_SERP_RANK,
                "target": kw["target"], "observation": normalize_serp_rank(env, keyword=kw["keyword"],
                                                                            target_domain=kw["target"])}


def test_supported_reports_include_phase2():
    assert {REPORT_KEYWORD_GAP, REPORT_BACKLINKS, REPORT_BACKLINKS_SUMMARY, REPORT_SERP_RANK} <= set(SUPPORTED_REPORTS)


def test_keyword_gap_sync_paginates_by_consumed_items_not_stored_rows():
    pg, adapter = FakeSession(), FakeAdapter()
    result = run(sync_seo_provider_report_bounded(
        pg, site_id="s1", target="natmedsol.com", adapter=adapter, report=REPORT_KEYWORD_GAP,
        limit=100, start_offset=0, max_pages=1, max_total_cost=0.5,
        options={"competitor_domain": "rival.com", "mode": "shared"}))
    assert result["pages"] == 1
    assert result["rows_normalized"] == 99
    assert result["next_offset"] == 100          # consumed items, NOT 99
    assert result["complete"] is False
    assert result["stop_reason"] == "page_ceiling"
    call = adapter.calls[0][1]
    assert call["intersections"] is True and call["target_is_first"] is True
    run_inserts = [c for c in pg.calls if "INSERT INTO marketing_seo_provider_runs" in c["sql"]]
    assert run_inserts and run_inserts[0]["params"]["report_type"] == REPORT_KEYWORD_GAP
    assert run_inserts[0]["params"]["provider_total_count"] == 250
    gap_inserts = [c for c in pg.calls if "INSERT INTO marketing_seo_keyword_gap_snapshots" in c["sql"]]
    assert len(gap_inserts) == 99 and gap_inserts[0]["params"]["gap_type"] == GAP_STRONG


def test_keyword_gap_missing_mode_swaps_slots_and_forces_bucket():
    pg, adapter = FakeSession(), FakeAdapter()
    run(sync_seo_provider_report_bounded(
        pg, site_id="s1", target="natmedsol.com", adapter=adapter, report=REPORT_KEYWORD_GAP,
        limit=100, max_pages=1, options={"competitor_domain": "rival.com", "mode": "missing"}))
    call = adapter.calls[0][1]
    assert call["intersections"] is False and call["target_is_first"] is False
    gap_inserts = [c for c in pg.calls if "INSERT INTO marketing_seo_keyword_gap_snapshots" in c["sql"]]
    assert all(c["params"]["gap_type"] == GAP_MISSING and c["params"]["target_rank"] is None for c in gap_inserts)


def test_keyword_gap_requires_competitor():
    with pytest.raises(ValueError):
        run(sync_seo_provider_report_bounded(FakeSession(), site_id="s1", target="natmedsol.com",
                                             adapter=FakeAdapter(), report=REPORT_KEYWORD_GAP, limit=10))


def test_backlinks_summary_is_single_request_even_if_more_pages_allowed():
    pg, adapter = FakeSession(), FakeAdapter()
    result = run(sync_seo_provider_report_bounded(
        pg, site_id="s1", target="natmedsol.com", adapter=adapter, report=REPORT_BACKLINKS_SUMMARY,
        limit=1, max_pages=5, max_total_cost=1.0))
    assert result["pages"] == 1 and result["complete"] is True and result["next_offset"] is None
    assert len(adapter.calls) == 1
    assert any("INSERT INTO marketing_seo_backlink_summary_snapshots" in c["sql"] for c in pg.calls)


def test_serp_rank_uses_tracked_keyword_and_persists_observation():
    tracked = {"id": "tk1", "keyword": "iv therapy", "normalized_keyword": "iv therapy",
               "target_domain": "natmedsol.com", "location": "United States", "language": "English",
               "device": "mobile", "is_active": True}
    pg, adapter = FakeSession(tracked=tracked), FakeAdapter()
    result = run(sync_seo_provider_report_bounded(
        pg, site_id="s1", target="natmedsol.com", adapter=adapter, report=REPORT_SERP_RANK, limit=100,
        max_pages=3, options={"tracked_keyword_id": "tk1"}))
    assert result["pages"] == 1 and result["complete"] is True
    assert adapter.calls[0][1]["device"] == "mobile"
    obs = [c for c in pg.calls if "INSERT INTO marketing_seo_rank_observations" in c["sql"]]
    assert len(obs) == 1 and obs[0]["params"]["position"] == 6 and obs[0]["params"]["found"] is True


def test_serp_rank_without_tracked_keyword_fails_closed():
    with pytest.raises(ValueError):
        run(sync_seo_provider_report_bounded(FakeSession(tracked=None), site_id="s1", target="natmedsol.com",
                                             adapter=FakeAdapter(), report=REPORT_SERP_RANK, limit=100,
                                             options={"tracked_keyword_id": "nope"}))


# ------------------------------------------------------ governed refresh


SITE = {"id": "s1", "normalized_url": "natmedsol.com", "site_url": "https://www.natmedsol.com/"}


def test_plan_refresh_validates_and_describes_without_calls(monkeypatch):
    monkeypatch.delenv("DATAFORSEO_LOGIN", raising=False)
    plan = seo_refresh.plan_refresh(report_type="ranked_keywords", site=SITE, start_offset=1000,
                                    limit=1000, max_pages=1, max_total_cost=0.25)
    assert plan["start_offset"] == 1000 and plan["max_requests"] == 1
    assert plan["tables"] == ["marketing_seo_provider_runs", "marketing_seo_organic_keyword_snapshots"]
    assert plan["provider_ready"] is False
    single = seo_refresh.plan_refresh(report_type="backlinks_summary", site=SITE, max_pages=7, start_offset=50)
    assert single["max_pages"] == 1 and single["start_offset"] == 0
    for bad in (dict(report_type="nope"), dict(report_type="ranked_keywords", max_pages=99),
                dict(report_type="ranked_keywords", max_total_cost=50), dict(report_type="keyword_gap"),
                dict(report_type="serp_rank")):
        with pytest.raises(ValueError):
            seo_refresh.plan_refresh(site=SITE, **bad)


def test_execute_refresh_surfaces_provider_error_without_raising():
    class Boom:
        async def fetch_backlinks_summary(self, **kw):
            raise RuntimeError("DataForSEO 40200 payment required")

    pg = FakeSession()
    plan = seo_refresh.plan_refresh(report_type="backlinks_summary", site=SITE)
    out = run(seo_refresh.execute_refresh(pg, plan=plan, adapter=Boom(), actor={"id": "u1"}))
    assert out["status"] == "error" and "payment required" in out["error"]
    assert out["requests_made"] == 0 and out["provider_run_ids"] == []


def test_execute_refresh_success_reports_runs_and_cost():
    pg, adapter = FakeSession(), FakeAdapter()
    plan = seo_refresh.plan_refresh(report_type="backlinks_summary", site=SITE)
    out = run(seo_refresh.execute_refresh(pg, plan=plan, adapter=adapter, actor={"id": "u1"}))
    assert out["status"] == "completed", out["error"]
    assert out["requests_made"] == 1
    assert len(out["provider_run_ids"]) == 1 and out["total_cost"] == pytest.approx(0.02)


def test_scheduler_tick_is_noop_when_disabled(monkeypatch):
    monkeypatch.setenv(seo_refresh.REFRESH_ENABLED_ENV, "false")
    out = run(seo_refresh.run_due_seo_refreshes(session_factory=lambda: (_ for _ in ()).throw(AssertionError("no db"))))
    assert out["enabled"] is False and out["ran"] == []


def test_scheduler_tick_requires_credentials(monkeypatch):
    monkeypatch.setenv(seo_refresh.REFRESH_ENABLED_ENV, "true")
    monkeypatch.delenv("DATAFORSEO_LOGIN", raising=False)
    monkeypatch.delenv("DATAFORSEO_PASSWORD", raising=False)
    out = run(seo_refresh.run_due_seo_refreshes(session_factory=lambda: (_ for _ in ()).throw(AssertionError("no db"))))
    assert out["enabled"] is True and out["ran"] == [] and "credentials" in out["reason"]


# ------------------------------------------------- GSC completeness persistence


class GscSession:
    def __init__(self):
        self.runs = []

    def begin(self):
        s = self

        class _Ctx:
            async def __aenter__(self):
                return s

            async def __aexit__(self, *exc):
                return False
        return _Ctx()

    async def execute(self, stmt, params=None):
        if "marketing_gsc_sync_runs" in str(stmt).lower():
            self.runs.append(dict(params or {}))
        return _Result()


class PagedGsc:
    provider = "google_search_console"

    def __init__(self, n_queries):
        self.n = n_queries

    def fetch_search_analytics(self, *, start_date, end_date, dimensions, row_limit=1000, start_row=0,
                               data_state="final"):
        if dimensions[0] == "query":
            rows = [{"keys": [f"q{i}"], "clicks": 1, "impressions": 2, "ctr": 0.5, "position": 3.0}
                    for i in range(start_row, min(self.n, start_row + row_limit))]
            return {"rows": rows}
        return {"rows": []}


def test_gsc_run_persists_completeness_and_pagination_json():
    pg = GscSession()
    out = run(sync_search_console(pg, site_id="s1", adapter=PagedGsc(2500), start_date="2026-08-01",
                                  end_date="2026-09-01", row_limit=1000))
    assert out["status"] == "completed" and out["complete"] is True and out["completeness"] == "complete"
    assert out["pages_consumed"] == 3 + 1 + 1  # 3 query pages + 1 empty daily + 1 empty page
    assert len(pg.runs) == 1
    stored = pg.runs[0]
    assert stored["complete"] is True and stored["pages_consumed"] == 5 and stored["safety_ceiling_reached"] is False
    pagination = json.loads(stored["pagination"])
    assert pagination["queries"]["rows"] == 2500 and pagination["queries"]["complete"] is True
    assert pagination["queries"]["next_start_row"] is None


def test_gsc_run_unknown_completeness_when_provider_read_fails():
    class Boom:
        provider = "google_search_console"

        def fetch_search_analytics(self, **kw):
            raise RuntimeError("quota")

    pg = GscSession()
    out = run(sync_search_console(pg, site_id="s1", adapter=Boom(), start_date="2026-08-01", end_date="2026-09-01"))
    assert out["status"] == "error" and out["completeness"] == "unknown"
    assert pg.runs[0]["complete"] is None and pg.runs[0]["pagination"] is None
