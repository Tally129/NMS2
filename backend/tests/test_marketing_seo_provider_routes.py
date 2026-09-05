from __future__ import annotations

import asyncio
import sys
import types
from datetime import date
from pathlib import Path

from fastapi import APIRouter


# ---------------------------------------------------------------------------
# Import isolation
# ---------------------------------------------------------------------------
#
# marketing_os.routers.search normally imports:
#   deps.api / deps.require_roles
#   postgres_db.AsyncSessionLocal
#
# The production modules intentionally require application/database
# configuration at import time. These route-contract tests must remain
# deterministic and must never construct an engine or touch PostgreSQL.
#
# Install the smallest interface-compatible stubs BEFORE importing the
# router module.
# ---------------------------------------------------------------------------

deps_stub = types.ModuleType("deps")
deps_stub.api = APIRouter(prefix="/api")


def _require_roles(*roles):
    async def dependency():
        return {
            "id": "test-user",
            "role": "admin",
        }

    return dependency


deps_stub.require_roles = _require_roles

postgres_stub = types.ModuleType("postgres_db")


def _unconfigured_session_factory():
    raise AssertionError(
        "real AsyncSessionLocal must not be used in route tests"
    )


postgres_stub.AsyncSessionLocal = _unconfigured_session_factory

sys.modules["deps"] = deps_stub
sys.modules["postgres_db"] = postgres_stub

from marketing_os.routers import search as module


def run(coro):
    return asyncio.run(coro)


class FakeSession:
    pass


class FakeSessionContext:
    async def __aenter__(self):
        return FakeSession()

    async def __aexit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        return False


def fake_session_factory():
    return FakeSessionContext()


def install_common(
    monkeypatch,
    *,
    site=None,
):
    async def fake_resolve_site(pg, site_id):
        assert isinstance(pg, FakeSession)
        return site

    monkeypatch.setattr(
        module,
        "AsyncSessionLocal",
        fake_session_factory,
    )

    monkeypatch.setattr(
        module,
        "_resolve_site",
        fake_resolve_site,
    )


def test_domain_route_reads_cached_snapshot(monkeypatch):
    site = {
        "id": "site-1",
        "site_url": "https://www.natmedsol.com/",
    }

    install_common(
        monkeypatch,
        site=site,
    )

    calls = []

    async def fake_read(pg, **kwargs):
        calls.append(kwargs)

        return {
            "organic_keywords": 932,
            "estimated_organic_traffic": 455.1282,
            "captured_date": "2026-09-05",
        }

    monkeypatch.setattr(
        module,
        "load_cached_seo_domain_snapshot",
        fake_read,
    )

    result = run(
        module.seo_provider_domain_overview(
            site_id=None,
            provider="dataforseo",
            location="United States",
            language="English",
            device="desktop",
            user={"id": "user-1"},
        )
    )

    assert result["connected"] is True
    assert result["has_snapshot"] is True
    assert result["site"]["id"] == "site-1"

    assert (
        result["snapshot"]["organic_keywords"]
        == 932
    )

    assert calls == [
        {
            "site_id": "site-1",
            "provider": "dataforseo",
            "location": "United States",
            "language": "English",
            "device": "desktop",
        }
    ]


def test_domain_route_handles_empty_cache(monkeypatch):
    site = {"id": "site-1"}

    install_common(
        monkeypatch,
        site=site,
    )

    async def fake_read(pg, **kwargs):
        return None

    monkeypatch.setattr(
        module,
        "load_cached_seo_domain_snapshot",
        fake_read,
    )

    result = run(
        module.seo_provider_domain_overview(
            site_id=None,
            provider="dataforseo",
            location="United States",
            language="English",
            device="desktop",
            user={"id": "user-1"},
        )
    )

    assert result["connected"] is True
    assert result["has_snapshot"] is False
    assert result["snapshot"] is None


def test_keyword_route_passes_cache_filters(monkeypatch):
    site = {"id": "site-1"}

    install_common(
        monkeypatch,
        site=site,
    )

    calls = []

    async def fake_read(pg, **kwargs):
        calls.append(kwargs)

        return {
            "captured_date": "2026-09-05",
            "items": [
                {
                    "keyword":
                        "holistic doctor atlanta",
                    "current_rank": 4,
                }
            ],
            "total": 932,
            "limit": 25,
            "offset": 50,
            "has_more": True,
        }

    monkeypatch.setattr(
        module,
        "load_cached_seo_keywords",
        fake_read,
    )

    capture = date(2026, 9, 5)

    result = run(
        module.seo_provider_organic_keywords(
            site_id="site-1",
            provider="dataforseo",
            location="United States",
            language="English",
            device="desktop",
            captured_date=capture,
            limit=25,
            offset=50,
            user={"id": "user-1"},
        )
    )

    assert result["connected"] is True
    assert result["has_snapshot"] is True
    assert result["total"] == 932
    assert result["has_more"] is True

    assert calls == [
        {
            "site_id": "site-1",
            "provider": "dataforseo",
            "location": "United States",
            "language": "English",
            "device": "desktop",
            "captured_date": capture,
            "limit": 25,
            "offset": 50,
        }
    ]


def test_competitor_route_reads_discovered_cache(
    monkeypatch,
):
    site = {"id": "site-1"}

    install_common(
        monkeypatch,
        site=site,
    )

    async def fake_read(pg, **kwargs):
        return {
            "captured_date": "2026-09-05",
            "items": [
                {
                    "domain": "healthgrades.com",
                    "intersections": 511,
                }
            ],
            "total": 10,
            "limit": 100,
            "offset": 0,
            "has_more": False,
        }

    monkeypatch.setattr(
        module,
        "load_cached_seo_competitors",
        fake_read,
    )

    result = run(
        module.seo_provider_competitors(
            site_id=None,
            provider="dataforseo",
            location="United States",
            language="English",
            device="desktop",
            captured_date=None,
            limit=100,
            offset=0,
            user={"id": "user-1"},
        )
    )

    assert result["connected"] is True
    assert result["has_snapshot"] is True

    assert (
        result["items"][0]["domain"]
        == "healthgrades.com"
    )


def test_provider_runs_route_exposes_cached_cost_history(
    monkeypatch,
):
    site = {"id": "site-1"}

    install_common(
        monkeypatch,
        site=site,
    )

    calls = []

    async def fake_read(pg, **kwargs):
        calls.append(kwargs)

        return {
            "items": [
                {
                    "id": "run-1",
                    "provider_cost": 0.0132,
                }
            ],
            "total": 4,
            "limit": 10,
            "offset": 0,
            "has_more": False,
        }

    monkeypatch.setattr(
        module,
        "load_cached_seo_provider_runs",
        fake_read,
    )

    result = run(
        module.seo_provider_runs(
            site_id=None,
            provider="dataforseo",
            report_type="ranked_keywords",
            limit=10,
            offset=0,
            user={"id": "user-1"},
        )
    )

    assert result["connected"] is True
    assert result["has_history"] is True
    assert result["total"] == 4
    assert result["items"][0]["provider_cost"] == 0.0132

    assert calls == [
        {
            "site_id": "site-1",
            "provider": "dataforseo",
            "report_type": "ranked_keywords",
            "limit": 10,
            "offset": 0,
        }
    ]


def test_no_site_returns_disconnected_without_cache_read(
    monkeypatch,
):
    install_common(
        monkeypatch,
        site=None,
    )

    async def forbidden(*args, **kwargs):
        raise AssertionError(
            "cache reader should not be called"
        )

    monkeypatch.setattr(
        module,
        "load_cached_seo_keywords",
        forbidden,
    )

    result = run(
        module.seo_provider_organic_keywords(
            site_id=None,
            provider="dataforseo",
            location="United States",
            language="English",
            device="desktop",
            captured_date=None,
            limit=100,
            offset=0,
            user={"id": "user-1"},
        )
    )

    assert result == {
        "connected": False,
        "not_connected_reason":
            "no_marketing_site_configured",
        "has_snapshot": False,
        "captured_date": None,
        "items": [],
        "total": 0,
        "limit": 100,
        "offset": 0,
        "has_more": False,
    }


def test_cached_routes_are_get_and_authenticated():
    source = Path(module.__file__).read_text()

    routes = (
        "/marketing-os/search/seo/domain-overview",
        "/marketing-os/search/seo/organic-keywords",
        "/marketing-os/search/seo/competitors",
        "/marketing-os/search/seo/provider-runs",
    )

    for route in routes:
        assert f'@api.get("{route}")' in source

    block = source.split(
        "# Cached SEO provider intelligence (READ-ONLY)",
        1,
    )[1].split(
        "# Technical site audit (READ-ONLY)",
        1,
    )[0]

    assert block.count(
        "Depends(require_roles(*MARKETING_ROLES))"
    ) == 4

    assert "@api.post(" not in block
    assert "@api.put(" not in block
    assert "@api.patch(" not in block
    assert "@api.delete(" not in block


def test_cached_route_block_has_no_refresh_or_provider_call():
    source = Path(module.__file__).read_text()

    block = source.split(
        "# Cached SEO provider intelligence (READ-ONLY)",
        1,
    )[1].split(
        "# Technical site audit (READ-ONLY)",
        1,
    )[0]

    forbidden = (
        "sync_seo_provider_report",
        "sync_seo_provider_report_bounded",
        "DataForSEOIntegration",
        "fetch_ranked_keywords",
        "fetch_domain_rank_overview",
        "fetch_competitors_domain",
        "httpx.",
        "requests.",
        "pg.begin(",
        "pg.commit(",
        "await pg.commit",
        "INSERT INTO",
        "UPDATE marketing_",
        "DELETE FROM",
    )

    for value in forbidden:
        assert value not in block
