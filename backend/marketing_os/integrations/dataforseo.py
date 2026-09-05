"""DataForSEO — READ-ONLY SEO intelligence provider.

Provider key: ``dataforseo``.

Security / governance contract:
- credentials come only from environment
- readiness performs no network call
- credential values are never returned
- all provider operations are reads
- no PostgreSQL access
- no provider-side mutations
- MarketingIntegration.execute_action() remains blocked

Initial supported DataForSEO Labs reports:
- Google ranked keywords
- Google domain rank overview
- Google organic competitors
"""

from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
from urllib.parse import urlparse

from .base import MarketingIntegration


PROVIDER = "dataforseo"

LOGIN_ENV = "DATAFORSEO_LOGIN"
PASSWORD_ENV = "DATAFORSEO_PASSWORD"
BASE_URL_ENV = "DATAFORSEO_BASE_URL"

DEFAULT_BASE_URL = "https://api.dataforseo.com/v3"
DEFAULT_LOCATION = "United States"
DEFAULT_LANGUAGE = "English"
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_RESULTS_LIMIT = 1000

STATE_NOT_CONNECTED = "not_connected"
STATE_CONFIG_INCOMPLETE = "configuration_incomplete"
STATE_CONNECTED = "connected"

REPORT_RANKED_KEYWORDS = "ranked_keywords"
REPORT_DOMAIN_RANK_OVERVIEW = "domain_rank_overview"
REPORT_COMPETITORS_DOMAIN = "competitors_domain"

SUPPORTED_REPORTS = frozenset(
    {
        REPORT_RANKED_KEYWORDS,
        REPORT_DOMAIN_RANK_OVERVIEW,
        REPORT_COMPETITORS_DOMAIN,
    }
)


class DataForSEOError(RuntimeError):
    """Safe provider error that never contains credentials."""


def credential_readiness() -> dict[str, Any]:
    """Return local credential readiness without making a network call."""

    login = (os.environ.get(LOGIN_ENV) or "").strip()
    password = (os.environ.get(PASSWORD_ENV) or "").strip()

    if not login and not password:
        status = STATE_NOT_CONNECTED
    elif not (login and password):
        status = STATE_CONFIG_INCOMPLETE
    else:
        status = STATE_CONNECTED

    return {
        "provider": PROVIDER,
        "status": status,
        "connected": status == STATE_CONNECTED,
        "login_configured": bool(login),
        "password_configured": bool(password),
        "read_only": True,
        "external_write": False,
        "env": {
            "login": LOGIN_ENV,
            "password": PASSWORD_ENV,
            "base_url": BASE_URL_ENV,
        },
    }


def normalize_target(value: Any) -> str:
    """Normalize a website/domain to DataForSEO's bare-domain target form."""

    raw = str(value or "").strip().lower()

    if not raw:
        raise ValueError("target is required")

    candidate = raw

    if "://" in candidate:
        parsed = urlparse(candidate)
        candidate = parsed.netloc or parsed.path
    else:
        candidate = candidate.split("/", 1)[0]

    candidate = candidate.split("@")[-1]
    candidate = candidate.split(":", 1)[0]

    if candidate.startswith("www."):
        candidate = candidate[4:]

    candidate = candidate.strip().strip(".")

    if not candidate or "." not in candidate:
        raise ValueError("target must be a valid domain")

    if any(ch.isspace() for ch in candidate):
        raise ValueError("target must not contain whitespace")

    return candidate


def _coerce_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _money_float(value: Any) -> Optional[float]:
    number = _coerce_decimal(value)
    return float(number) if number is not None else None


def _result_items(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract the first task/result object's ``items`` collection safely."""

    tasks = envelope.get("tasks") or []
    if not tasks:
        return []

    result = tasks[0].get("result") or []
    if not result:
        return []

    result_obj = result[0] if isinstance(result[0], dict) else {}
    items = result_obj.get("items") or []

    return [item for item in items if isinstance(item, dict)]


def _first_result_item(
    envelope: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Return the first item nested under the first result object."""

    items = _result_items(envelope)
    return items[0] if items else None


def normalize_domain_overview(
    envelope: dict[str, Any],
) -> dict[str, Any]:
    """Normalize live DataForSEO domain-rank-overview output."""

    item = _first_result_item(envelope) or {}

    metrics = item.get("metrics") or {}
    organic = metrics.get("organic") or {}

    if not organic:
        organic = item.get("organic") or {}

    return {
        "target": item.get("target"),
        "organic_keywords": _coerce_int(organic.get("count")),
        "estimated_organic_traffic": _money_float(organic.get("etv")),
        "estimated_paid_traffic_cost": _money_float(
            organic.get("estimated_paid_traffic_cost")
        ),
        "positions": {
            "pos_1": _coerce_int(organic.get("pos_1")),
            "pos_2_3": _coerce_int(organic.get("pos_2_3")),
            "pos_4_10": _coerce_int(organic.get("pos_4_10")),
            "pos_11_20": _coerce_int(organic.get("pos_11_20")),
            "pos_21_30": _coerce_int(organic.get("pos_21_30")),
            "pos_31_40": _coerce_int(organic.get("pos_31_40")),
            "pos_41_50": _coerce_int(organic.get("pos_41_50")),
            "pos_51_60": _coerce_int(organic.get("pos_51_60")),
            "pos_61_70": _coerce_int(organic.get("pos_61_70")),
            "pos_71_80": _coerce_int(organic.get("pos_71_80")),
            "pos_81_90": _coerce_int(organic.get("pos_81_90")),
            "pos_91_100": _coerce_int(organic.get("pos_91_100")),
        },
        "new": _coerce_int(organic.get("is_new")),
        "up": _coerce_int(organic.get("is_up")),
        "down": _coerce_int(organic.get("is_down")),
        "lost": _coerce_int(organic.get("is_lost")),
        "source": PROVIDER,
    }


def normalize_competitors(
    envelope: dict[str, Any],
    *,
    target: str,
) -> list[dict[str, Any]]:
    """Normalize competitor-domain results and remove the target itself."""

    target_domain = normalize_target(target)
    rows: list[dict[str, Any]] = []

    for item in _result_items(envelope):
        domain = normalize_target(item.get("domain") or "")

        if domain == target_domain:
            continue

        target_metrics = (
            (item.get("metrics") or {}).get("organic") or {}
        )
        competitor_metrics = (
            (item.get("competitor_metrics") or {}).get("organic") or {}
        )
        full_metrics = (
            (item.get("full_domain_metrics") or {}).get("organic") or {}
        )

        rows.append(
            {
                "domain": domain,
                "avg_position": item.get("avg_position"),
                "sum_position": _coerce_int(item.get("sum_position")),
                "intersections": _coerce_int(item.get("intersections")),
                "target_overlap_keywords": _coerce_int(
                    target_metrics.get("count")
                ),
                "competitor_overlap_keywords": _coerce_int(
                    competitor_metrics.get("count")
                ),
                "competitor_total_organic_keywords": _coerce_int(
                    full_metrics.get("count")
                ),
                "competitor_estimated_traffic": _money_float(
                    full_metrics.get("etv")
                ),
                "source": PROVIDER,
            }
        )

    return rows


def result_metadata(envelope: dict[str, Any]) -> dict[str, Any]:
    """Extract safe provider metadata and cost information."""

    tasks = envelope.get("tasks") or []
    task = tasks[0] if tasks else {}
    results = task.get("result") or []
    result = results[0] if results else {}

    return {
        "provider": PROVIDER,
        "read_only": True,
        "external_write": False,
        "status_code": envelope.get("status_code"),
        "status_message": envelope.get("status_message"),
        "cost": _money_float(envelope.get("cost")),
        "task_status_code": task.get("status_code"),
        "task_status_message": task.get("status_message"),
        "task_cost": _money_float(task.get("cost")),
        "tasks_count": envelope.get("tasks_count"),
        "tasks_error": envelope.get("tasks_error"),
        "total_count": result.get("total_count"),
        "items_count": result.get("items_count"),
    }


def normalize_ranked_keywords(
    envelope: dict[str, Any],
    *,
    location: str = DEFAULT_LOCATION,
    device: str = "desktop",
) -> list[dict[str, Any]]:
    """Normalize DataForSEO ranked-keyword rows for Search Intelligence."""

    normalized: list[dict[str, Any]] = []

    for item in _result_items(envelope):
        keyword_data = item.get("keyword_data") or {}
        keyword_info = keyword_data.get("keyword_info") or {}
        keyword_properties = keyword_data.get("keyword_properties") or {}
        search_intent = keyword_data.get("search_intent_info") or {}

        ranked = item.get("ranked_serp_element") or {}
        serp_item = ranked.get("serp_item") or {}

        keyword = str(keyword_data.get("keyword") or "").strip()
        if not keyword:
            continue

        intent = (
            search_intent.get("main_intent")
            or search_intent.get("intent")
            or "unknown"
        )

        difficulty = (
            keyword_properties.get("keyword_difficulty")
            if "keyword_difficulty" in keyword_properties
            else keyword_info.get("keyword_difficulty")
        )

        serp_features: list[str] = []

        serp_type = serp_item.get("type")
        if serp_type and serp_type != "organic":
            serp_features.append(str(serp_type))

        extra_features = serp_item.get("serp_features")
        if isinstance(extra_features, list):
            for feature in extra_features:
                text = str(feature).strip().lower()
                if text and text not in serp_features:
                    serp_features.append(text)

        normalized.append(
            {
                "keyword": keyword,
                "normalized_keyword": " ".join(keyword.lower().split()),
                "intent": str(intent).strip().lower() or "unknown",
                "search_volume": _coerce_int(keyword_info.get("search_volume")),
                "keyword_difficulty": _coerce_int(difficulty),
                "cpc": _money_float(keyword_info.get("cpc")),
                "current_rank": _coerce_int(
                    serp_item.get("rank_absolute")
                    or serp_item.get("rank_group")
                ),
                "ranking_url": serp_item.get("url"),
                "serp_features": serp_features,
                "source": PROVIDER,
                "metric_type": "organic_serp_rank",
                "location": location,
                "device": device,
                "is_tracked": False,
            }
        )

    return normalized


class DataForSEOIntegration(MarketingIntegration):
    """Read-only DataForSEO Labs integration."""

    provider = PROVIDER

    def __init__(
        self,
        *,
        client=None,
        client_factory=None,
        base_url: Optional[str] = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self._client = client
        self._client_factory = client_factory
        self._base_url = (
            base_url
            or (os.environ.get(BASE_URL_ENV) or "").strip()
            or DEFAULT_BASE_URL
        ).rstrip("/")
        self._timeout_seconds = float(timeout_seconds)

    async def health(self) -> dict:
        """Local readiness only; performs no provider call."""

        return credential_readiness()

    def _credentials(self) -> tuple[str, str]:
        login = (os.environ.get(LOGIN_ENV) or "").strip()
        password = (os.environ.get(PASSWORD_ENV) or "").strip()

        if not login or not password:
            raise DataForSEOError(
                f"{PROVIDER} not connected: "
                f"{credential_readiness()['status']}"
            )

        return login, password

    def _get_client(self):
        if self._client is not None:
            return self._client

        if self._client_factory is not None:
            self._client = self._client_factory()
            return self._client

        import httpx  # lazy import

        self._client = httpx.Client()
        return self._client

    def _post(
        self,
        endpoint: str,
        task: dict[str, Any],
    ) -> dict[str, Any]:
        login, password = self._credentials()

        client = self._get_client()

        response = client.post(
            f"{self._base_url}/{endpoint.lstrip('/')}",
            json=[task],
            auth=(login, password),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=self._timeout_seconds,
        )

        try:
            response.raise_for_status()
        except Exception as exc:
            status = getattr(response, "status_code", None)
            raise DataForSEOError(
                f"{PROVIDER} HTTP request failed"
                + (f" with status {status}" if status else "")
            ) from exc

        try:
            envelope = response.json()
        except Exception as exc:
            raise DataForSEOError(
                f"{PROVIDER} returned invalid JSON"
            ) from exc

        if not isinstance(envelope, dict):
            raise DataForSEOError(
                f"{PROVIDER} returned an invalid response envelope"
            )

        status_code = envelope.get("status_code")
        if status_code != 20000:
            raise DataForSEOError(
                f"{PROVIDER} request failed: "
                f"status_code={status_code}"
            )

        tasks = envelope.get("tasks") or []

        for provider_task in tasks:
            task_status = provider_task.get("status_code")
            if task_status != 20000:
                raise DataForSEOError(
                    f"{PROVIDER} task failed: "
                    f"status_code={task_status}"
                )

        return envelope

    @staticmethod
    def _validate_limit(limit: int) -> int:
        if not isinstance(limit, int):
            raise ValueError("limit must be an integer")

        if not 1 <= limit <= MAX_RESULTS_LIMIT:
            raise ValueError(
                f"limit must be between 1 and {MAX_RESULTS_LIMIT}"
            )

        return limit

    async def fetch_ranked_keywords(
        self,
        *,
        target: str,
        location_name: str = DEFAULT_LOCATION,
        language_name: str = DEFAULT_LANGUAGE,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        limit = self._validate_limit(limit)

        if offset < 0:
            raise ValueError("offset must be >= 0")

        domain = normalize_target(target)

        task = {
            "target": domain,
            "location_name": location_name,
            "language_name": language_name,
            "limit": limit,
            "offset": offset,
        }

        envelope = self._post(
            "dataforseo_labs/google/ranked_keywords/live",
            task,
        )

        return {
            **result_metadata(envelope),
            "report": REPORT_RANKED_KEYWORDS,
            "target": domain,
            "location": location_name,
            "language": language_name,
            "limit": limit,
            "offset": offset,
            "keywords": normalize_ranked_keywords(
                envelope,
                location=location_name,
            ),
        }

    async def fetch_domain_rank_overview(
        self,
        *,
        target: str,
        location_name: str = DEFAULT_LOCATION,
        language_name: str = DEFAULT_LANGUAGE,
    ) -> dict[str, Any]:
        domain = normalize_target(target)

        task = {
            "target": domain,
            "location_name": location_name,
            "language_name": language_name,
        }

        envelope = self._post(
            "dataforseo_labs/google/domain_rank_overview/live",
            task,
        )

        return {
            **result_metadata(envelope),
            "report": REPORT_DOMAIN_RANK_OVERVIEW,
            "target": domain,
            "location": location_name,
            "language": language_name,
            "overview": normalize_domain_overview(envelope),
        }

    async def fetch_competitors_domain(
        self,
        *,
        target: str,
        location_name: str = DEFAULT_LOCATION,
        language_name: str = DEFAULT_LANGUAGE,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        limit = self._validate_limit(limit)

        if offset < 0:
            raise ValueError("offset must be >= 0")

        domain = normalize_target(target)

        task = {
            "target": domain,
            "location_name": location_name,
            "language_name": language_name,
            "limit": limit,
            "offset": offset,
        }

        envelope = self._post(
            "dataforseo_labs/google/competitors_domain/live",
            task,
        )

        return {
            **result_metadata(envelope),
            "report": REPORT_COMPETITORS_DOMAIN,
            "target": domain,
            "location": location_name,
            "language": language_name,
            "limit": limit,
            "offset": offset,
            "competitors": normalize_competitors(
                envelope,
                target=domain,
            ),
        }

    async def fetch_performance(self, **kwargs) -> dict:
        """Dispatch one supported read-only SEO intelligence report."""

        report = str(
            kwargs.pop("report", REPORT_RANKED_KEYWORDS)
        ).strip().lower()

        if report not in SUPPORTED_REPORTS:
            raise ValueError(
                f"unsupported DataForSEO report: {report}"
            )

        if report == REPORT_RANKED_KEYWORDS:
            return await self.fetch_ranked_keywords(**kwargs)

        if report == REPORT_DOMAIN_RANK_OVERVIEW:
            return await self.fetch_domain_rank_overview(**kwargs)

        return await self.fetch_competitors_domain(**kwargs)


__all__ = [
    "BASE_URL_ENV",
    "DataForSEOError",
    "DataForSEOIntegration",
    "LOGIN_ENV",
    "PASSWORD_ENV",
    "PROVIDER",
    "REPORT_COMPETITORS_DOMAIN",
    "REPORT_DOMAIN_RANK_OVERVIEW",
    "REPORT_RANKED_KEYWORDS",
    "SUPPORTED_REPORTS",
    "credential_readiness",
    "normalize_competitors",
    "normalize_domain_overview",
    "normalize_ranked_keywords",
    "normalize_target",
    "result_metadata",
]
