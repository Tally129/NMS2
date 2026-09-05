from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import pytest

from marketing_os.integrations.dataforseo import (
    REPORT_COMPETITORS_DOMAIN,
    REPORT_DOMAIN_RANK_OVERVIEW,
    REPORT_RANKED_KEYWORDS,
)
from marketing_os.search.seo_provider_sync import (
    _page_state,
    sync_seo_provider_report,
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


class FakeAdapter:
    def __init__(self):
        self.calls = []

    async def fetch_domain_rank_overview(
        self,
        *,
        target,
        location_name,
        language_name,
    ):
        self.calls.append(
            {
                "method": "domain",
                "target": target,
                "location": location_name,
                "language": language_name,
            }
        )

        return {
            "provider": "dataforseo",
            "status_code": 20000,
            "task_status_code": 20000,
            "cost": 0.01212,
            "task_cost": 0.01212,
            "report": REPORT_DOMAIN_RANK_OVERVIEW,
            "target": "natmedsol.com",
            "location": location_name,
            "language": language_name,
            "overview": {
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
        }

    async def fetch_ranked_keywords(
        self,
        *,
        target,
        location_name,
        language_name,
        limit,
        offset,
    ):
        self.calls.append(
            {
                "method": "keywords",
                "target": target,
                "limit": limit,
                "offset": offset,
            }
        )

        return {
            "provider": "dataforseo",
            "status_code": 20000,
            "task_status_code": 20000,
            "cost": 0.0132,
            "task_cost": 0.0132,
            "total_count": 932,
            "items_count": 2,
            "report": REPORT_RANKED_KEYWORDS,
            "target": "natmedsol.com",
            "location": location_name,
            "language": language_name,
            "limit": limit,
            "offset": offset,
            "keywords": [
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
                    "location": location_name,
                    "device": "desktop",
                    "source": "dataforseo",
                },
                {
                    "keyword": "homeopath in atlanta",
                    "normalized_keyword":
                        "homeopath in atlanta",
                    "intent": "commercial",
                    "search_volume": 110,
                    "keyword_difficulty": 0,
                    "current_rank": 2,
                    "ranking_url":
                        "https://natmedsol.com/",
                    "serp_features": [],
                    "location": location_name,
                    "device": "desktop",
                    "source": "dataforseo",
                },
            ],
        }

    async def fetch_competitors_domain(
        self,
        *,
        target,
        location_name,
        language_name,
        limit,
        offset,
    ):
        self.calls.append(
            {
                "method": "competitors",
                "target": target,
                "limit": limit,
                "offset": offset,
            }
        )

        return {
            "provider": "dataforseo",
            "status_code": 20000,
            "task_status_code": 20000,
            "cost": 0.0132,
            "task_cost": 0.0132,
            "total_count": 10720,
            "items_count": 1,
            "report": REPORT_COMPETITORS_DOMAIN,
            "target": "natmedsol.com",
            "location": location_name,
            "language": language_name,
            "limit": limit,
            "offset": offset,
            "competitors": [
                {
                    "domain": "healthgrades.com",
                    "avg_position": 31.45,
                    "sum_position": 16073,
                    "intersections": 511,
                    "target_overlap_keywords": 511,
                    "competitor_overlap_keywords": 511,
                    "competitor_total_organic_keywords":
                        2990753,
                    "competitor_estimated_traffic":
                        5699220.51,
                    "source": "dataforseo",
                }
            ],
        }


def test_page_state_uses_total_count():
    complete, next_offset = _page_state(
        {
            "offset": 0,
            "limit": 100,
            "total_count": 932,
        },
        row_count=100,
    )

    assert complete is False
    assert next_offset == 100

    complete, next_offset = _page_state(
        {
            "offset": 900,
            "limit": 100,
            "total_count": 932,
        },
        row_count=32,
    )

    assert complete is True
    assert next_offset is None


def test_page_state_zero_rows_stops_progress():
    assert _page_state(
        {
            "offset": 100,
            "limit": 100,
            "total_count": 932,
        },
        row_count=0,
    ) == (True, None)


def test_domain_overview_orchestration():
    pg = FakeSession()
    adapter = FakeAdapter()

    result = run(
        sync_seo_provider_report(
            pg,
            site_id="site-1",
            target="natmedsol.com",
            adapter=adapter,
            report=REPORT_DOMAIN_RANK_OVERVIEW,
            captured_date=date(2026, 9, 5),
        )
    )

    assert len(adapter.calls) == 1
    assert adapter.calls[0]["method"] == "domain"

    assert result["rows_normalized"] == 1
    assert result["rows_persisted"] == 1
    assert result["complete"] is True
    assert result["provider_cost"] == 0.01212

    assert len(pg.calls) == 2

    sql = "\n".join(
        item["sql"]
        for item in pg.calls
    )

    assert "marketing_seo_provider_runs" in sql
    assert "marketing_seo_domain_snapshots" in sql


def test_ranked_keyword_page_orchestration():
    pg = FakeSession()
    adapter = FakeAdapter()

    result = run(
        sync_seo_provider_report(
            pg,
            site_id="site-1",
            target="natmedsol.com",
            adapter=adapter,
            report=REPORT_RANKED_KEYWORDS,
            limit=2,
            offset=0,
            captured_date=date(2026, 9, 5),
        )
    )

    assert len(adapter.calls) == 1
    assert adapter.calls[0] == {
        "method": "keywords",
        "target": "natmedsol.com",
        "limit": 2,
        "offset": 0,
    }

    assert result["rows_normalized"] == 2
    assert result["rows_persisted"] == 2
    assert result["complete"] is False
    assert result["next_offset"] == 2
    assert result["provider_total_count"] == 932
    assert result["provider_cost"] == 0.0132

    # provider run + 2 keyword rows
    assert len(pg.calls) == 3

    sql = "\n".join(
        item["sql"]
        for item in pg.calls
    )

    assert "marketing_seo_provider_runs" in sql

    assert (
        "marketing_seo_organic_keyword_snapshots"
        in sql
    )

    assert "INSERT INTO marketing_search_keywords" not in sql


def test_competitor_page_orchestration():
    pg = FakeSession()
    adapter = FakeAdapter()

    result = run(
        sync_seo_provider_report(
            pg,
            site_id="site-1",
            target="natmedsol.com",
            adapter=adapter,
            report=REPORT_COMPETITORS_DOMAIN,
            limit=1,
            offset=0,
            captured_date=date(2026, 9, 5),
        )
    )

    assert len(adapter.calls) == 1
    assert adapter.calls[0]["method"] == "competitors"

    assert result["rows_normalized"] == 1
    assert result["rows_persisted"] == 1
    assert result["complete"] is False
    assert result["next_offset"] == 1
    assert result["provider_total_count"] == 10720

    assert len(pg.calls) == 2

    sql = "\n".join(
        item["sql"]
        for item in pg.calls
    )

    assert "marketing_seo_provider_runs" in sql

    assert (
        "marketing_seo_competitor_snapshots"
        in sql
    )

    assert (
        "INSERT INTO marketing_search_competitors"
        not in sql
    )


def test_unsupported_report_fails_before_provider_call():
    pg = FakeSession()
    adapter = FakeAdapter()

    with pytest.raises(ValueError):
        run(
            sync_seo_provider_report(
                pg,
                site_id="site-1",
                target="natmedsol.com",
                adapter=adapter,
                report="not_a_report",
            )
        )

    assert adapter.calls == []
    assert pg.calls == []


def test_invalid_offset_fails_before_provider_call():
    pg = FakeSession()
    adapter = FakeAdapter()

    with pytest.raises(ValueError):
        run(
            sync_seo_provider_report(
                pg,
                site_id="site-1",
                target="natmedsol.com",
                adapter=adapter,
                report=REPORT_RANKED_KEYWORDS,
                offset=-1,
            )
        )

    assert adapter.calls == []
    assert pg.calls == []


def test_orchestrator_owns_no_db_session_or_transaction():
    import marketing_os.search.seo_provider_sync as module

    source = Path(module.__file__).read_text()

    forbidden = (
        "AsyncSessionLocal",
        "postgres_db",
        "create_async_engine",
        "sessionmaker",
        "pg.begin(",
        "pg.commit(",
        "await pg.commit",
    )

    for value in forbidden:
        assert value not in source


def test_orchestrator_has_no_autonomous_scheduler():
    import marketing_os.search.seo_provider_sync as module

    source = Path(module.__file__).read_text().lower()

    forbidden = (
        "apscheduler",
        "add_job(",
        "crontrigger",
        "backgroundscheduler",
    )

    for value in forbidden:
        assert value not in source
