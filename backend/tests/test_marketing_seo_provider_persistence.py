from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

from marketing_os.search.seo_provider_persistence import (
    normalize_domain,
    persist_competitor_snapshots,
    persist_domain_snapshot,
    persist_organic_keyword_snapshots,
    persist_provider_run,
)


def run(coro):
    return asyncio.run(coro)


class FakeSession:
    def __init__(self):
        self.calls = []

    async def execute(self, statement, params=None):
        self.calls.append(
            {
                "sql": str(statement),
                "params": dict(params or {}),
            }
        )


def test_normalize_domain():
    assert (
        normalize_domain("https://www.HealthGrades.com/foo")
        == "healthgrades.com"
    )
    assert normalize_domain("NATMEDSOL.COM/") == "natmedsol.com"
    assert normalize_domain(None) == ""


def test_provider_run_cost_and_completeness():
    pg = FakeSession()

    result = run(
        persist_provider_run(
            pg,
            site_id="site-1",
            report_type="ranked_keywords",
            target="natmedsol.com",
            metadata={
                "status_code": 20000,
                "task_status_code": 20000,
                "cost": 0.0132,
                "task_cost": 0.0132,
                "total_count": 932,
                "items_count": 10,
            },
            rows_normalized=10,
            requested_limit=10,
            requested_offset=0,
            complete=False,
            next_offset=10,
        )
    )

    assert result["provider"] == "dataforseo"
    assert result["rows_normalized"] == 10
    assert result["complete"] is False
    assert len(pg.calls) == 1

    params = pg.calls[0]["params"]

    assert params["provider_total_count"] == 932
    assert params["provider_items_count"] == 10
    assert params["provider_cost"] == 0.0132
    assert params["provider_task_cost"] == 0.0132
    assert params["next_offset"] == 10


def test_domain_snapshot_upsert():
    pg = FakeSession()

    result = run(
        persist_domain_snapshot(
            pg,
            site_id="site-1",
            provider_run_id="run-1",
            captured_date=date(2026, 9, 5),
            overview={
                "organic_keywords": 932,
                "estimated_organic_traffic": 455.1282,
                "estimated_paid_traffic_cost": 1563.0373,
                "positions": {
                    "pos_1": 9,
                    "pos_2_3": 15,
                    "pos_4_10": 71,
                },
                "new": 338,
                "up": 273,
                "down": 299,
                "lost": 377,
            },
        )
    )

    assert result["organic_keywords"] == 932
    assert len(pg.calls) == 1

    call = pg.calls[0]

    assert "marketing_seo_domain_snapshots" in call["sql"]
    assert "ON CONFLICT" in call["sql"]
    assert call["params"]["pos_1"] == 9
    assert call["params"]["new_keywords"] == 338
    assert call["params"]["lost_keywords"] == 377


def test_keyword_universe_separate_from_tracked():
    pg = FakeSession()

    count = run(
        persist_organic_keyword_snapshots(
            pg,
            site_id="site-1",
            provider_run_id="run-1",
            captured_date=date(2026, 9, 5),
            keywords=[
                {
                    "keyword": "holistic doctor atlanta",
                    "normalized_keyword":
                        "holistic doctor atlanta",
                    "intent": "commercial",
                    "search_volume": 590,
                    "keyword_difficulty": 41,
                    "cpc": 6.16,
                    "current_rank": 4,
                    "ranking_url":
                        "https://natmedsol.com/",
                    "serp_features": [],
                    "source": "dataforseo",
                },
                {
                    "keyword": "homeopath in atlanta",
                    "current_rank": 2,
                    "serp_features": [
                        "people_also_ask"
                    ],
                    "source": "dataforseo",
                },
            ],
        )
    )

    assert count == 2
    assert len(pg.calls) == 2

    sql = "\n".join(
        call["sql"]
        for call in pg.calls
    )

    assert (
        "marketing_seo_organic_keyword_snapshots"
        in sql
    )
    assert "INSERT INTO marketing_search_keywords" not in sql
    assert "marketing_keyword_rank_snapshots" not in sql

    assert json.loads(
        pg.calls[1]["params"]["serp_features"]
    ) == ["people_also_ask"]


def test_blank_keywords_skipped():
    pg = FakeSession()

    count = run(
        persist_organic_keyword_snapshots(
            pg,
            site_id="site-1",
            keywords=[
                {},
                {"keyword": ""},
                {"keyword": "valid keyword"},
            ],
        )
    )

    assert count == 1
    assert len(pg.calls) == 1


def test_competitor_target_filtered():
    pg = FakeSession()

    count = run(
        persist_competitor_snapshots(
            pg,
            site_id="site-1",
            target="https://www.natmedsol.com/",
            captured_date=date(2026, 9, 5),
            competitors=[
                {
                    "domain": "natmedsol.com",
                    "intersections": 932,
                    "source": "dataforseo",
                },
                {
                    "domain": "HealthGrades.com",
                    "avg_position": 31.45,
                    "intersections": 511,
                    "target_overlap_keywords": 511,
                    "competitor_overlap_keywords": 511,
                    "competitor_total_organic_keywords":
                        2990753,
                    "competitor_estimated_traffic":
                        5699220.51,
                    "source": "dataforseo",
                },
            ],
        )
    )

    assert count == 1
    assert len(pg.calls) == 1

    call = pg.calls[0]

    assert (
        "marketing_seo_competitor_snapshots"
        in call["sql"]
    )
    assert "INSERT INTO marketing_search_competitors" not in call["sql"]
    assert call["params"]["domain"] == "healthgrades.com"
    assert (
        call["params"]["competitor_total_organic_keywords"]
        == 2990753
    )


def test_service_owns_no_session_or_provider_call():
    import marketing_os.search.seo_provider_persistence as module

    source = Path(module.__file__).read_text()

    forbidden = (
        "AsyncSessionLocal",
        "create_async_engine",
        "sessionmaker",
        "pg.begin(",
        "pg.commit(",
        "await pg.commit",
        "DataForSEOIntegration(",
        "httpx.",
    )

    for item in forbidden:
        assert item not in source


def test_no_curated_table_inserts():
    import marketing_os.search.seo_provider_persistence as module

    source = Path(module.__file__).read_text()

    assert "INSERT INTO marketing_search_keywords" not in source
    assert "INSERT INTO marketing_search_competitors" not in source
