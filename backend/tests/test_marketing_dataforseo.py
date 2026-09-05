"""Focused tests for the read-only DataForSEO SEO provider.

No live provider calls.
No production credentials.
No database access.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from marketing_os.integrations.base import MarketingIntegration
from marketing_os.integrations.dataforseo import (
    DataForSEOError,
    DataForSEOIntegration,
    LOGIN_ENV,
    PASSWORD_ENV,
    credential_readiness,
    normalize_ranked_keywords,
    normalize_target,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(
            {
                "url": url,
                "json": kwargs.get("json"),
                "auth": kwargs.get("auth"),
                "headers": kwargs.get("headers"),
                "timeout": kwargs.get("timeout"),
            }
        )
        return FakeResponse(
            self.payload,
            status_code=self.status_code,
        )


def run(coro):
    return asyncio.run(coro)


def clear_credentials(monkeypatch):
    monkeypatch.delenv(LOGIN_ENV, raising=False)
    monkeypatch.delenv(PASSWORD_ENV, raising=False)


RANKED_RESPONSE = {
    "version": "0.1",
    "status_code": 20000,
    "status_message": "Ok.",
    "cost": 0.0132,
    "tasks_count": 1,
    "tasks_error": 0,
    "tasks": [
        {
            "status_code": 20000,
            "status_message": "Ok.",
            "cost": 0.0132,
            "result": [
                {
                    "target": "natmedsol.com",
                    "total_count": 932,
                    "items_count": 2,
                    "items": [
                        {
                            "keyword_data": {
                                "keyword": "naturopath near me",
                                "keyword_info": {
                                    "search_volume": 1600,
                                    "cpc": 4.25,
                                },
                                "keyword_properties": {
                                    "keyword_difficulty": 37,
                                },
                                "search_intent_info": {
                                    "main_intent": "commercial",
                                },
                            },
                            "ranked_serp_element": {
                                "serp_item": {
                                    "type": "organic",
                                    "rank_group": 5,
                                    "rank_absolute": 5,
                                    "url": (
                                        "https://www.natmedsol.com/"
                                        "naturopathic-medicine/"
                                    ),
                                }
                            },
                        },
                        {
                            "keyword_data": {
                                "keyword": "natural medical solutions",
                                "keyword_info": {
                                    "search_volume": 320,
                                    "cpc": 1.15,
                                },
                                "keyword_properties": {
                                    "keyword_difficulty": 12,
                                },
                                "search_intent_info": {
                                    "main_intent": "navigational",
                                },
                            },
                            "ranked_serp_element": {
                                "serp_item": {
                                    "type": "organic",
                                    "rank_group": 1,
                                    "rank_absolute": 1,
                                    "url": "https://www.natmedsol.com/",
                                }
                            },
                        },
                    ],
                }
            ],
        }
    ],
}


DOMAIN_RESPONSE = {
    "status_code": 20000,
    "status_message": "Ok.",
    "cost": 0.012,
    "tasks_count": 1,
    "tasks_error": 0,
    "tasks": [
        {
            "status_code": 20000,
            "status_message": "Ok.",
            "cost": 0.012,
            "result": [
                {
                    "target": "natmedsol.com",
                    "total_count": 1,
                    "items_count": 1,
                    "items": [
                        {
                            "target": "natmedsol.com",
                            "metrics": {
                                "organic": {
                                    "pos_1": 10,
                                    "pos_2_3": 20,
                                    "pos_4_10": 50,
                                    "count": 932,
                                    "etv": 455.12,
                                    "estimated_paid_traffic_cost": 1563.03,
                                    "is_new": 338,
                                    "is_up": 273,
                                    "is_down": 299,
                                    "is_lost": 377,
                                }
                            },
                        }
                    ],
                }
            ],
        }
    ],
}


COMPETITOR_RESPONSE = {
    "status_code": 20000,
    "status_message": "Ok.",
    "cost": 0.012,
    "tasks_count": 1,
    "tasks_error": 0,
    "tasks": [
        {
            "status_code": 20000,
            "status_message": "Ok.",
            "cost": 0.012,
            "result": [
                {
                    "target": "natmedsol.com",
                    "total_count": 2,
                    "items_count": 2,
                    "items": [
                        {
                            "domain": "example-one.com",
                            "avg_position": 12.2,
                        },
                        {
                            "domain": "example-two.com",
                            "avg_position": 18.4,
                        },
                    ],
                }
            ],
        }
    ],
}


def test_adapter_is_marketing_integration():
    adapter = DataForSEOIntegration(client=FakeClient(RANKED_RESPONSE))
    assert isinstance(adapter, MarketingIntegration)
    assert adapter.provider == "dataforseo"


def test_readiness_not_connected(monkeypatch):
    clear_credentials(monkeypatch)

    result = credential_readiness()

    assert result["status"] == "not_connected"
    assert result["connected"] is False
    assert result["read_only"] is True
    assert result["external_write"] is False


def test_readiness_partial_configuration(monkeypatch):
    clear_credentials(monkeypatch)
    monkeypatch.setenv(LOGIN_ENV, "api@example.com")

    result = credential_readiness()

    assert result["status"] == "configuration_incomplete"
    assert result["connected"] is False


def test_readiness_connected_and_never_exposes_credentials(monkeypatch):
    clear_credentials(monkeypatch)

    monkeypatch.setenv(LOGIN_ENV, "api-secret-login@example.com")
    monkeypatch.setenv(PASSWORD_ENV, "super-secret-api-password")

    result = credential_readiness()
    blob = json.dumps(result)

    assert result["connected"] is True
    assert result["read_only"] is True
    assert result["external_write"] is False

    assert "api-secret-login@example.com" not in blob
    assert "super-secret-api-password" not in blob


def test_health_is_local_only(monkeypatch):
    clear_credentials(monkeypatch)
    monkeypatch.setenv(LOGIN_ENV, "api@example.com")
    monkeypatch.setenv(PASSWORD_ENV, "password")

    fake = FakeClient(RANKED_RESPONSE)
    adapter = DataForSEOIntegration(client=fake)

    result = run(adapter.health())

    assert result["connected"] is True
    assert fake.calls == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("natmedsol.com", "natmedsol.com"),
        ("www.natmedsol.com", "natmedsol.com"),
        ("https://www.natmedsol.com/", "natmedsol.com"),
        ("https://natmedsol.com/services/x", "natmedsol.com"),
    ],
)
def test_normalize_target(raw, expected):
    assert normalize_target(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "localhost",
        "not a domain",
    ],
)
def test_normalize_target_rejects_invalid(raw):
    with pytest.raises(ValueError):
        normalize_target(raw)


def test_ranked_keyword_normalization():
    rows = normalize_ranked_keywords(
        RANKED_RESPONSE,
        location="United States",
    )

    assert len(rows) == 2

    first = rows[0]

    assert first["keyword"] == "naturopath near me"
    assert first["normalized_keyword"] == "naturopath near me"
    assert first["intent"] == "commercial"
    assert first["search_volume"] == 1600
    assert first["keyword_difficulty"] == 37
    assert first["cpc"] == 4.25
    assert first["current_rank"] == 5
    assert first["source"] == "dataforseo"
    assert first["metric_type"] == "organic_serp_rank"
    assert first["is_tracked"] is False


def test_ranked_keywords_builds_exact_read_request(monkeypatch):
    clear_credentials(monkeypatch)

    monkeypatch.setenv(LOGIN_ENV, "api@example.com")
    monkeypatch.setenv(PASSWORD_ENV, "password")

    fake = FakeClient(RANKED_RESPONSE)

    adapter = DataForSEOIntegration(
        client=fake,
        base_url="https://api.dataforseo.com/v3",
    )

    result = run(
        adapter.fetch_ranked_keywords(
            target="https://www.natmedsol.com/",
            location_name="United States",
            language_name="English",
            limit=10,
            offset=0,
        )
    )

    assert len(fake.calls) == 1

    call = fake.calls[0]

    assert call["url"].endswith(
        "/dataforseo_labs/google/ranked_keywords/live"
    )

    assert call["json"] == [
        {
            "target": "natmedsol.com",
            "location_name": "United States",
            "language_name": "English",
            "limit": 10,
            "offset": 0,
        }
    ]

    assert call["auth"] == ("api@example.com", "password")

    assert result["provider"] == "dataforseo"
    assert result["report"] == "ranked_keywords"
    assert result["target"] == "natmedsol.com"
    assert result["total_count"] == 932
    assert result["items_count"] == 2
    assert result["cost"] == 0.0132
    assert result["task_cost"] == 0.0132
    assert len(result["keywords"]) == 2
    assert result["read_only"] is True
    assert result["external_write"] is False


def test_domain_overview_request(monkeypatch):
    clear_credentials(monkeypatch)

    monkeypatch.setenv(LOGIN_ENV, "api@example.com")
    monkeypatch.setenv(PASSWORD_ENV, "password")

    fake = FakeClient(DOMAIN_RESPONSE)
    adapter = DataForSEOIntegration(client=fake)

    result = run(
        adapter.fetch_domain_rank_overview(
            target="natmedsol.com",
        )
    )

    assert fake.calls[0]["url"].endswith(
        "/dataforseo_labs/google/domain_rank_overview/live"
    )
    assert result["report"] == "domain_rank_overview"
    assert result["cost"] == 0.012
    assert result["overview"]["organic_keywords"] == 932
    assert result["overview"]["estimated_organic_traffic"] == 455.12
    assert result["overview"]["positions"]["pos_1"] == 10


def test_competitors_request(monkeypatch):
    clear_credentials(monkeypatch)

    monkeypatch.setenv(LOGIN_ENV, "api@example.com")
    monkeypatch.setenv(PASSWORD_ENV, "password")

    fake = FakeClient(COMPETITOR_RESPONSE)
    adapter = DataForSEOIntegration(client=fake)

    result = run(
        adapter.fetch_competitors_domain(
            target="natmedsol.com",
            limit=25,
        )
    )

    assert fake.calls[0]["url"].endswith(
        "/dataforseo_labs/google/competitors_domain/live"
    )
    assert fake.calls[0]["json"][0]["limit"] == 25
    assert result["report"] == "competitors_domain"
    assert len(result["competitors"]) == 2
    assert result["competitors"][0]["domain"] == "example-one.com"
    assert result["competitors"][1]["domain"] == "example-two.com"


def test_fetch_performance_dispatches(monkeypatch):
    clear_credentials(monkeypatch)

    monkeypatch.setenv(LOGIN_ENV, "api@example.com")
    monkeypatch.setenv(PASSWORD_ENV, "password")

    fake = FakeClient(RANKED_RESPONSE)
    adapter = DataForSEOIntegration(client=fake)

    result = run(
        adapter.fetch_performance(
            report="ranked_keywords",
            target="natmedsol.com",
            limit=10,
        )
    )

    assert result["report"] == "ranked_keywords"


def test_fetch_performance_rejects_unknown_report(monkeypatch):
    clear_credentials(monkeypatch)

    monkeypatch.setenv(LOGIN_ENV, "api@example.com")
    monkeypatch.setenv(PASSWORD_ENV, "password")

    adapter = DataForSEOIntegration(
        client=FakeClient(RANKED_RESPONSE)
    )

    with pytest.raises(ValueError):
        run(
            adapter.fetch_performance(
                report="something_dangerous",
                target="natmedsol.com",
            )
        )


@pytest.mark.parametrize("limit", [0, 1001])
def test_limit_guard(limit, monkeypatch):
    clear_credentials(monkeypatch)

    monkeypatch.setenv(LOGIN_ENV, "api@example.com")
    monkeypatch.setenv(PASSWORD_ENV, "password")

    adapter = DataForSEOIntegration(
        client=FakeClient(RANKED_RESPONSE)
    )

    with pytest.raises(ValueError):
        run(
            adapter.fetch_ranked_keywords(
                target="natmedsol.com",
                limit=limit,
            )
        )


def test_missing_credentials_blocks_provider_call(monkeypatch):
    clear_credentials(monkeypatch)

    fake = FakeClient(RANKED_RESPONSE)
    adapter = DataForSEOIntegration(client=fake)

    with pytest.raises(DataForSEOError):
        run(
            adapter.fetch_ranked_keywords(
                target="natmedsol.com",
            )
        )

    assert fake.calls == []


def test_provider_http_failure_is_sanitized(monkeypatch):
    clear_credentials(monkeypatch)

    monkeypatch.setenv(LOGIN_ENV, "api@example.com")
    monkeypatch.setenv(PASSWORD_ENV, "top-secret-password")

    fake = FakeClient(
        {"detail": "anything"},
        status_code=401,
    )

    adapter = DataForSEOIntegration(client=fake)

    with pytest.raises(DataForSEOError) as caught:
        run(
            adapter.fetch_ranked_keywords(
                target="natmedsol.com",
            )
        )

    message = str(caught.value)

    assert "top-secret-password" not in message
    assert "api@example.com" not in message


def test_provider_task_failure_is_sanitized(monkeypatch):
    clear_credentials(monkeypatch)

    monkeypatch.setenv(LOGIN_ENV, "api@example.com")
    monkeypatch.setenv(PASSWORD_ENV, "password")

    response = {
        "status_code": 20000,
        "status_message": "Ok.",
        "cost": 0,
        "tasks_count": 1,
        "tasks_error": 1,
        "tasks": [
            {
                "status_code": 40501,
                "status_message": "Provider task failed",
                "cost": 0,
                "result": None,
            }
        ],
    }

    adapter = DataForSEOIntegration(
        client=FakeClient(response)
    )

    with pytest.raises(DataForSEOError):
        run(
            adapter.fetch_ranked_keywords(
                target="natmedsol.com",
            )
        )


def test_execute_action_remains_blocked():
    adapter = DataForSEOIntegration(
        client=FakeClient(RANKED_RESPONSE)
    )

    with pytest.raises(RuntimeError):
        run(adapter.execute_action(action="anything"))


def test_default_bootstrap_registers_dataforseo():
    from marketing_os.integrations.bootstrap import register_default_integrations
    from marketing_os.integrations.registry import (
        create_integration,
        registered_providers,
    )

    providers = register_default_integrations()

    assert "dataforseo" in providers
    assert "dataforseo" in registered_providers()

    integration = create_integration(
        "dataforseo",
        client=FakeClient(RANKED_RESPONSE),
    )

    assert isinstance(integration, DataForSEOIntegration)
    assert integration.provider == "dataforseo"


LIVE_DOMAIN_RESPONSE = {
    "status_code": 20000,
    "status_message": "Ok.",
    "cost": 0.01212,
    "tasks_count": 1,
    "tasks_error": 0,
    "tasks": [
        {
            "status_code": 20000,
            "status_message": "Ok.",
            "cost": 0.01212,
            "result": [
                {
                    "target": "natmedsol.com",
                    "total_count": 1,
                    "items_count": 1,
                    "items": [
                        {
                            "target": "natmedsol.com",
                            "metrics": {
                                "organic": {
                                    "pos_1": 9,
                                    "pos_2_3": 15,
                                    "pos_4_10": 71,
                                    "pos_11_20": 112,
                                    "count": 932,
                                    "etv": 455.1282200995629,
                                    "estimated_paid_traffic_cost":
                                        1563.0372644978925,
                                    "is_new": 338,
                                    "is_up": 273,
                                    "is_down": 299,
                                    "is_lost": 377,
                                }
                            },
                        }
                    ],
                }
            ],
        }
    ],
}


LIVE_COMPETITOR_RESPONSE = {
    "status_code": 20000,
    "status_message": "Ok.",
    "cost": 0.0132,
    "tasks_count": 1,
    "tasks_error": 0,
    "tasks": [
        {
            "status_code": 20000,
            "status_message": "Ok.",
            "cost": 0.0132,
            "result": [
                {
                    "target": "natmedsol.com",
                    "total_count": 2,
                    "items_count": 2,
                    "items": [
                        {
                            "domain": "natmedsol.com",
                            "avg_position": 41.49,
                            "sum_position": 38676,
                            "intersections": 932,
                            "metrics": {
                                "organic": {"count": 932}
                            },
                            "competitor_metrics": {
                                "organic": {"count": 932}
                            },
                            "full_domain_metrics": {
                                "organic": {
                                    "count": 932,
                                    "etv": 455.12,
                                }
                            },
                        },
                        {
                            "domain": "healthgrades.com",
                            "avg_position": 31.45,
                            "sum_position": 16073,
                            "intersections": 511,
                            "metrics": {
                                "organic": {"count": 511}
                            },
                            "competitor_metrics": {
                                "organic": {"count": 511}
                            },
                            "full_domain_metrics": {
                                "organic": {
                                    "count": 2990753,
                                    "etv": 5699220.51,
                                }
                            },
                        },
                    ],
                }
            ],
        }
    ],
}


def test_live_shape_domain_overview_normalizes_nested_items(monkeypatch):
    clear_credentials(monkeypatch)
    monkeypatch.setenv(LOGIN_ENV, "api@example.com")
    monkeypatch.setenv(PASSWORD_ENV, "password")

    adapter = DataForSEOIntegration(
        client=FakeClient(LIVE_DOMAIN_RESPONSE)
    )

    result = run(
        adapter.fetch_domain_rank_overview(
            target="natmedsol.com",
        )
    )

    overview = result["overview"]

    assert overview["organic_keywords"] == 932
    assert overview["estimated_organic_traffic"] == 455.1282200995629
    assert overview["positions"]["pos_1"] == 9
    assert overview["positions"]["pos_2_3"] == 15
    assert overview["positions"]["pos_4_10"] == 71
    assert overview["new"] == 338
    assert overview["up"] == 273
    assert overview["down"] == 299
    assert overview["lost"] == 377


def test_live_shape_competitors_filters_target_domain(monkeypatch):
    clear_credentials(monkeypatch)
    monkeypatch.setenv(LOGIN_ENV, "api@example.com")
    monkeypatch.setenv(PASSWORD_ENV, "password")

    adapter = DataForSEOIntegration(
        client=FakeClient(LIVE_COMPETITOR_RESPONSE)
    )

    result = run(
        adapter.fetch_competitors_domain(
            target="natmedsol.com",
            limit=10,
        )
    )

    competitors = result["competitors"]

    assert len(competitors) == 1
    assert competitors[0]["domain"] == "healthgrades.com"
    assert competitors[0]["intersections"] == 511
    assert competitors[0]["target_overlap_keywords"] == 511
    assert competitors[0]["competitor_total_organic_keywords"] == 2990753
