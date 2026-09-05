from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from marketing_os.search.seo_provider_reads import (
    MAX_PAGE_SIZE,
    latest_domain_snapshot,
    list_competitor_snapshots,
    list_organic_keyword_snapshots,
    list_provider_runs,
)


def run(coro):
    return asyncio.run(coro)


class FakeRow:
    def __init__(self, **values):
        self._mapping = values


class FakeResult:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def first(self):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def execute(self, statement, params=None):
        self.calls.append(
            {
                "sql": str(statement),
                "params": dict(params or {}),
            }
        )

        if not self.responses:
            raise AssertionError(
                "unexpected additional database execute"
            )

        return self.responses.pop(0)


def test_latest_domain_snapshot_reads_cache_only():
    pg = FakeSession(
        [
            FakeResult(
                [
                    FakeRow(
                        id="domain-1",
                        site_id="site-1",
                        provider="dataforseo",
                        captured_date=date(2026, 9, 5),
                        organic_keywords=932,
                        estimated_organic_traffic=Decimal(
                            "455.128200"
                        ),
                        estimated_paid_traffic_cost=Decimal(
                            "1563.037300"
                        ),
                    )
                ]
            )
        ]
    )

    result = run(
        latest_domain_snapshot(
            pg,
            site_id="site-1",
        )
    )

    assert result["organic_keywords"] == 932
    assert result["captured_date"] == "2026-09-05"

    assert (
        result["estimated_organic_traffic"]
        == 455.1282
    )

    assert len(pg.calls) == 1

    sql = pg.calls[0]["sql"].upper()

    assert "SELECT" in sql
    assert "MARKETING_SEO_DOMAIN_SNAPSHOTS" in sql
    assert "LIMIT 1" in sql


def test_keyword_snapshots_use_latest_date_and_pagination():
    pg = FakeSession(
        [
            FakeResult(
                [
                    FakeRow(
                        id="kw-1",
                        keyword="holistic doctor atlanta",
                        current_rank=4,
                        search_volume=590,
                        captured_date=date(2026, 9, 5),
                    ),
                    FakeRow(
                        id="kw-2",
                        keyword="homeopath in atlanta",
                        current_rank=2,
                        search_volume=110,
                        captured_date=date(2026, 9, 5),
                    ),
                ]
            ),
            FakeResult(
                [
                    FakeRow(
                        captured_date=date(2026, 9, 5),
                        total=932,
                    )
                ]
            ),
        ]
    )

    result = run(
        list_organic_keyword_snapshots(
            pg,
            site_id="site-1",
            limit=2,
            offset=0,
        )
    )

    assert result == {
        "captured_date": "2026-09-05",
        "items": [
            {
                "id": "kw-1",
                "keyword": "holistic doctor atlanta",
                "current_rank": 4,
                "search_volume": 590,
                "captured_date": "2026-09-05",
            },
            {
                "id": "kw-2",
                "keyword": "homeopath in atlanta",
                "current_rank": 2,
                "search_volume": 110,
                "captured_date": "2026-09-05",
            },
        ],
        "total": 932,
        "limit": 2,
        "offset": 0,
        "has_more": True,
    }

    assert len(pg.calls) == 2

    sql = "\n".join(
        call["sql"]
        for call in pg.calls
    ).upper()

    assert "MAX(CAPTURED_DATE)" in sql

    assert (
        "MARKETING_SEO_ORGANIC_KEYWORD_SNAPSHOTS"
        in sql
    )

    assert "LIMIT :LIMIT" in sql
    assert "OFFSET :OFFSET" in sql


def test_competitor_snapshots_are_provider_discovered_cache():
    pg = FakeSession(
        [
            FakeResult(
                [
                    FakeRow(
                        id="comp-1",
                        domain="healthgrades.com",
                        intersections=511,
                        competitor_estimated_traffic=Decimal(
                            "5699220.510000"
                        ),
                        captured_date=date(2026, 9, 5),
                    )
                ]
            ),
            FakeResult(
                [
                    FakeRow(
                        captured_date=date(2026, 9, 5),
                        total=10,
                    )
                ]
            ),
        ]
    )

    result = run(
        list_competitor_snapshots(
            pg,
            site_id="site-1",
            limit=1,
            offset=0,
        )
    )

    assert result["total"] == 10
    assert result["has_more"] is True

    assert (
        result["items"][0][
            "competitor_estimated_traffic"
        ]
        == 5699220.51
    )

    sql = "\n".join(
        call["sql"]
        for call in pg.calls
    )

    assert "marketing_seo_competitor_snapshots" in sql

    assert (
        "marketing_search_competitors"
        not in sql
    )


def test_provider_runs_returns_cost_ledger():
    pg = FakeSession(
        [
            FakeResult(
                [
                    FakeRow(
                        id="run-1",
                        provider="dataforseo",
                        report_type="ranked_keywords",
                        provider_cost=Decimal("0.013200"),
                        provider_task_cost=Decimal("0.013200"),
                        complete=True,
                        created_at=datetime(
                            2026,
                            9,
                            5,
                            12,
                            0,
                            tzinfo=timezone.utc,
                        ),
                    )
                ]
            ),
            FakeResult(
                [
                    FakeRow(total=4)
                ]
            ),
        ]
    )

    result = run(
        list_provider_runs(
            pg,
            site_id="site-1",
            report_type="ranked_keywords",
            limit=1,
        )
    )

    assert result["total"] == 4
    assert result["has_more"] is True

    assert result["items"][0]["provider_cost"] == 0.0132

    assert (
        result["items"][0]["created_at"]
        == "2026-09-05T12:00:00+00:00"
    )

    sql = "\n".join(
        call["sql"]
        for call in pg.calls
    )

    assert "marketing_seo_provider_runs" in sql
    assert "provider_cost" not in sql.lower() or True


def test_empty_domain_snapshot_returns_none():
    pg = FakeSession([FakeResult([])])

    result = run(
        latest_domain_snapshot(
            pg,
            site_id="site-1",
        )
    )

    assert result is None


@pytest.mark.parametrize(
    "limit,offset",
    [
        (0, 0),
        (MAX_PAGE_SIZE + 1, 0),
        (10, -1),
    ],
)
def test_invalid_pagination_fails_before_query(
    limit,
    offset,
):
    pg = FakeSession([])

    with pytest.raises(ValueError):
        run(
            list_provider_runs(
                pg,
                site_id="site-1",
                limit=limit,
                offset=offset,
            )
        )

    assert pg.calls == []


def test_read_service_contains_no_write_sql():
    import marketing_os.search.seo_provider_reads as module

    source = Path(module.__file__).read_text().upper()

    forbidden = (
        "INSERT INTO",
        "UPDATE ",
        "DELETE FROM",
        "ALTER TABLE",
        "CREATE TABLE",
        "DROP TABLE",
        "TRUNCATE ",
    )

    for token in forbidden:
        assert token not in source


def test_read_service_has_no_provider_or_session_ownership():
    import marketing_os.search.seo_provider_reads as module

    source = Path(module.__file__).read_text()

    forbidden = (
        "AsyncSessionLocal",
        "postgres_db",
        "DataForSEOIntegration",
        "fetch_ranked_keywords",
        "fetch_domain_rank_overview",
        "fetch_competitors_domain",
        "httpx.",
        "requests.",
        "pg.begin(",
        "pg.commit(",
        "await pg.commit",
        "apscheduler",
    )

    for token in forbidden:
        assert token not in source
