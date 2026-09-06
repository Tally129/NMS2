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
# Phase 2 reports
REPORT_KEYWORD_GAP = "keyword_gap"            # Labs domain_intersection
REPORT_BACKLINKS_SUMMARY = "backlinks_summary"  # Backlinks summary/live
REPORT_BACKLINKS = "backlinks"                  # Backlinks backlinks/live
REPORT_SERP_RANK = "serp_rank"                  # SERP google/organic/live

SUPPORTED_REPORTS = frozenset(
    {
        REPORT_RANKED_KEYWORDS,
        REPORT_DOMAIN_RANK_OVERVIEW,
        REPORT_COMPETITORS_DOMAIN,
        REPORT_KEYWORD_GAP,
        REPORT_BACKLINKS_SUMMARY,
        REPORT_BACKLINKS,
        REPORT_SERP_RANK,
    }
)

# Keyword-gap classification (Semrush-style) derived ONLY from the two
# ranks DataForSEO returns for the same keyword.
GAP_SHARED = "shared"      # both rank
GAP_MISSING = "missing"    # competitor ranks, NMS does not
GAP_UNTAPPED = "untapped"  # NMS ranks, competitor does not
GAP_WEAK = "weak"          # both rank, competitor better
GAP_STRONG = "strong"      # both rank, NMS better


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

        current_rank = _coerce_int(
            serp_item.get("rank_absolute")
            or serp_item.get("rank_group")
        )
        # Provider-reported rank history (never invented): DataForSEO
        # returns rank_changes.previous_rank_absolute when it has a prior
        # observation for this keyword/domain.
        rank_changes = serp_item.get("rank_changes") or {}
        previous_rank = _coerce_int(
            rank_changes.get("previous_rank_absolute")
        )
        rank_change = None
        if current_rank is not None and previous_rank is not None:
            # Positive = improved (moved up the SERP).
            rank_change = previous_rank - current_rank
        estimated_traffic = _coerce_decimal(serp_item.get("etv"))

        normalized.append(
            {
                "keyword": keyword,
                "normalized_keyword": " ".join(keyword.lower().split()),
                "intent": str(intent).strip().lower() or "unknown",
                "search_volume": _coerce_int(keyword_info.get("search_volume")),
                "keyword_difficulty": _coerce_int(difficulty),
                "cpc": _money_float(keyword_info.get("cpc")),
                "current_rank": current_rank,
                "previous_rank": previous_rank,
                "rank_change": rank_change,
                "estimated_traffic": (
                    float(estimated_traffic)
                    if estimated_traffic is not None else None
                ),
                "is_new": bool(rank_changes.get("is_new"))
                if "is_new" in rank_changes else None,
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


def _safe_target(value: Any) -> str:
    """normalize_target that returns '' instead of raising for empty input."""
    try:
        return normalize_target(value)
    except ValueError:
        return ""


def _keyword_core(keyword_data: dict[str, Any]) -> dict[str, Any]:
    keyword_info = keyword_data.get("keyword_info") or {}
    keyword_properties = keyword_data.get("keyword_properties") or {}
    search_intent = keyword_data.get("search_intent_info") or {}
    keyword = str(keyword_data.get("keyword") or "").strip()
    difficulty = (
        keyword_properties.get("keyword_difficulty")
        if "keyword_difficulty" in keyword_properties
        else keyword_info.get("keyword_difficulty")
    )
    intent = (
        search_intent.get("main_intent") or search_intent.get("intent")
        or "unknown"
    )
    return {
        "keyword": keyword,
        "normalized_keyword": " ".join(keyword.lower().split()),
        "search_volume": _coerce_int(keyword_info.get("search_volume")),
        "cpc": _money_float(keyword_info.get("cpc")),
        "keyword_difficulty": _coerce_int(difficulty),
        "intent": str(intent).strip().lower() or "unknown",
    }


def _serp_rank_url_etv(element: Any) -> tuple[Optional[int], Optional[str],
                                            Optional[float]]:
    if not isinstance(element, dict):
        return None, None, None
    serp_item = element.get("serp_item") or element
    rank = _coerce_int(
        serp_item.get("rank_absolute") or serp_item.get("rank_group")
    )
    etv = _coerce_decimal(serp_item.get("etv"))
    return rank, serp_item.get("url"), (float(etv) if etv is not None else None)


def classify_gap(target_rank: Optional[int],
                 competitor_rank: Optional[int]) -> str:
    """Semrush-style gap bucket from the two provider ranks only."""
    if target_rank is None and competitor_rank is None:
        return GAP_MISSING
    if target_rank is None:
        return GAP_MISSING
    if competitor_rank is None:
        return GAP_UNTAPPED
    if target_rank < competitor_rank:
        return GAP_STRONG
    if target_rank > competitor_rank:
        return GAP_WEAK
    return GAP_SHARED


def normalize_domain_intersection(
    envelope: dict[str, Any],
    *,
    target: str,
    competitor: str,
    target_is_first: bool = True,
) -> list[dict[str, Any]]:
    """Normalize Labs ``domain_intersection`` items into keyword-gap rows.

    DataForSEO returns ``first_domain_serp_element`` / ``second_domain_
    serp_element`` per keyword; ``target_is_first`` tells which slot is
    NMS. Rows with no keyword are skipped. Nothing is invented: a missing
    element simply yields a NULL rank for that side.
    """
    rows: list[dict[str, Any]] = []
    for item in _result_items(envelope):
        core = _keyword_core(item.get("keyword_data") or {})
        if not core["keyword"]:
            continue
        first = item.get("first_domain_serp_element")
        second = item.get("second_domain_serp_element")
        t_el, c_el = (first, second) if target_is_first else (second, first)
        t_rank, t_url, t_etv = _serp_rank_url_etv(t_el)
        c_rank, c_url, c_etv = _serp_rank_url_etv(c_el)
        rows.append(
            {
                **core,
                "target_domain": normalize_target(target),
                "competitor_domain": normalize_target(competitor),
                "target_rank": t_rank,
                "competitor_rank": c_rank,
                "target_url": t_url,
                "competitor_url": c_url,
                "target_etv": t_etv,
                "competitor_etv": c_etv,
                "gap_type": classify_gap(t_rank, c_rank),
                "source": PROVIDER,
            }
        )
    return rows


def normalize_backlink_summary(envelope: dict[str, Any],
                               *, target: str) -> dict[str, Any]:
    item = _first_result_item(envelope) or {}
    if not item:
        return {}
    types = item.get("referring_links_types") or {}
    attrs = item.get("referring_links_attributes") or {}
    nofollow = _coerce_int(attrs.get("nofollow")) if isinstance(attrs, dict) else None
    backlinks = _coerce_int(item.get("backlinks"))
    dofollow = (
        backlinks - nofollow
        if backlinks is not None and nofollow is not None else None
    )
    return {
        "target": _safe_target(item.get("target") or target),
        "rank": _coerce_int(item.get("rank")),
        "backlinks": backlinks,
        "referring_domains": _coerce_int(item.get("referring_domains")),
        "referring_main_domains": _coerce_int(item.get("referring_main_domains")),
        "referring_pages": _coerce_int(item.get("referring_pages")),
        "referring_ips": _coerce_int(item.get("referring_ips")),
        "referring_domains_nofollow": _coerce_int(
            item.get("referring_domains_nofollow")
        ),
        "dofollow_links": dofollow,
        "nofollow_links": nofollow,
        "broken_backlinks": _coerce_int(item.get("broken_backlinks")),
        "broken_pages": _coerce_int(item.get("broken_pages")),
        "backlinks_spam_score": _coerce_int(item.get("backlinks_spam_score")),
        "crawled_pages": _coerce_int(item.get("crawled_pages")),
        "first_seen": item.get("first_seen"),
        "lost_date": item.get("lost_date"),
        "referring_links_types": types if isinstance(types, dict) else None,
        "referring_links_attributes": attrs if isinstance(attrs, dict) else None,
        "referring_links_tld": item.get("referring_links_tld"),
        "referring_links_countries": item.get("referring_links_countries"),
        "source": PROVIDER,
    }


def normalize_backlinks(envelope: dict[str, Any],
                        *, target: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _result_items(envelope):
        url_from = str(item.get("url_from") or "").strip()
        if not url_from:
            continue
        attributes = item.get("attributes")
        rows.append(
            {
                "target": normalize_target(target),
                "source_url": url_from,
                "source_domain": item.get("domain_from"),
                "target_url": item.get("url_to"),
                "anchor": item.get("anchor"),
                "item_type": item.get("item_type"),
                "dofollow": item.get("dofollow")
                if isinstance(item.get("dofollow"), bool) else None,
                "attributes": attributes if isinstance(attributes, list) else None,
                "is_new": item.get("is_new")
                if isinstance(item.get("is_new"), bool) else None,
                "is_lost": item.get("is_lost")
                if isinstance(item.get("is_lost"), bool) else None,
                "is_broken": item.get("is_broken")
                if isinstance(item.get("is_broken"), bool) else None,
                "first_seen": item.get("first_seen"),
                "prev_seen": item.get("prev_seen"),
                "last_seen": item.get("last_seen"),
                "domain_from_rank": _coerce_int(item.get("domain_from_rank")),
                "page_from_rank": _coerce_int(item.get("page_from_rank")),
                "backlink_spam_score": _coerce_int(
                    item.get("backlink_spam_score")
                ),
                "domain_from_platform_type": item.get(
                    "domain_from_platform_type"
                ),
                "semantic_location": item.get("semantic_location"),
                "url_to_status_code": _coerce_int(item.get("url_to_status_code")),
                "source": PROVIDER,
            }
        )
    return rows


def normalize_serp_rank(
    envelope: dict[str, Any],
    *,
    keyword: str,
    target_domain: str,
) -> dict[str, Any]:
    """Locate the target domain in one live Google organic SERP.

    Returns the observed position (rank_absolute), rank_group, url and the
    set of non-organic SERP feature types present. ``found`` is False when
    the domain is absent from the requested depth — that is recorded, not
    interpreted as "rank 0".
    """
    tasks = envelope.get("tasks") or []
    result_obj: dict[str, Any] = {}
    if tasks and isinstance(tasks[0], dict):
        result = tasks[0].get("result") or []
        if result and isinstance(result[0], dict):
            result_obj = result[0]
    items = [i for i in (result_obj.get("items") or []) if isinstance(i, dict)]
    wanted = _safe_target(target_domain)
    features: list[str] = []
    match: Optional[dict[str, Any]] = None
    for item in items:
        item_type = str(item.get("type") or "").strip().lower()
        if item_type and item_type != "organic" and item_type not in features:
            features.append(item_type)
        domain = _safe_target(item.get("domain"))
        if match is None and domain and (
            domain == wanted or domain.endswith("." + wanted)
        ):
            match = item
    return {
        "keyword": keyword,
        "target_domain": wanted,
        "found": match is not None,
        "position": _coerce_int(match.get("rank_absolute")) if match else None,
        "rank_group": _coerce_int(match.get("rank_group")) if match else None,
        "ranking_url": match.get("url") if match else None,
        "ranking_domain": match.get("domain") if match else None,
        "serp_item_type": match.get("type") if match else None,
        "serp_features": features,
        "depth": len(items) or None,
        "se_results_count": _coerce_int(result_obj.get("se_results_count")),
        "check_url": result_obj.get("check_url"),
        "provider_datetime": result_obj.get("datetime"),
        "source": PROVIDER,
    }


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

    async def fetch_domain_intersection(
        self,
        *,
        target: str,
        competitor: str,
        location_name: str = DEFAULT_LOCATION,
        language_name: str = DEFAULT_LANGUAGE,
        limit: int = 100,
        offset: int = 0,
        intersections: bool = True,
        target_is_first: bool = True,
    ) -> dict:
        """Labs ``domain_intersection/live`` — one paid request.

        ``intersections=True`` returns keywords BOTH domains rank for;
        ``intersections=False`` returns keywords target1 ranks for and
        target2 does not. Callers swap slots (``target_is_first``) to
        obtain competitor-only ("missing") keywords.
        """
        limit = self._validate_limit(limit)
        if offset < 0:
            raise ValueError("offset must be >= 0")
        domain = normalize_target(target)
        other = normalize_target(competitor)
        first, second = (domain, other) if target_is_first else (other, domain)
        task = {
            "target1": first,
            "target2": second,
            "location_name": location_name,
            "language_name": language_name,
            "intersections": bool(intersections),
            "include_serp_info": True,
            "limit": limit,
            "offset": offset,
        }
        envelope = self._post(
            "dataforseo_labs/google/domain_intersection/live", task
        )
        return {
            **result_metadata(envelope),
            "report": REPORT_KEYWORD_GAP,
            "target": domain,
            "competitor": other,
            "location": location_name,
            "language": language_name,
            "limit": limit,
            "offset": offset,
            "intersections": bool(intersections),
            "gap_rows": normalize_domain_intersection(
                envelope,
                target=domain,
                competitor=other,
                target_is_first=target_is_first,
            ),
        }

    async def fetch_backlinks_summary(self, *, target: str,
                                      **_ignored) -> dict:
        """Backlinks ``summary/live`` — one paid request, no pagination."""
        domain = normalize_target(target)
        task = {
            "target": domain,
            "include_subdomains": True,
            "backlinks_status_type": "live",
            "internal_list_limit": 10,
        }
        envelope = self._post("backlinks/summary/live", task)
        return {
            **result_metadata(envelope),
            "report": REPORT_BACKLINKS_SUMMARY,
            "target": domain,
            "summary": normalize_backlink_summary(envelope, target=domain),
        }

    async def fetch_backlinks(
        self,
        *,
        target: str,
        limit: int = 100,
        offset: int = 0,
        backlinks_status_type: str = "live",
        **_ignored,
    ) -> dict:
        """Backlinks ``backlinks/live`` — paged, one paid request/page."""
        limit = self._validate_limit(limit)
        if offset < 0:
            raise ValueError("offset must be >= 0")
        domain = normalize_target(target)
        task = {
            "target": domain,
            "mode": "as_is",
            "include_subdomains": True,
            "backlinks_status_type": backlinks_status_type,
            "order_by": ["rank,desc"],
            "limit": limit,
            "offset": offset,
        }
        envelope = self._post("backlinks/backlinks/live", task)
        return {
            **result_metadata(envelope),
            "report": REPORT_BACKLINKS,
            "target": domain,
            "limit": limit,
            "offset": offset,
            "backlinks": normalize_backlinks(envelope, target=domain),
        }

    async def fetch_serp_rank(
        self,
        *,
        keyword: str,
        target: str,
        location_name: str = DEFAULT_LOCATION,
        language_name: str = DEFAULT_LANGUAGE,
        device: str = "desktop",
        depth: int = 100,
        **_ignored,
    ) -> dict:
        """SERP ``google/organic/live/regular`` — one paid request/keyword."""
        keyword = " ".join(str(keyword or "").split())
        if not keyword:
            raise ValueError("keyword is required")
        device = (device or "desktop").strip().lower()
        if device not in {"desktop", "mobile"}:
            raise ValueError("device must be desktop or mobile")
        depth = max(10, min(int(depth), 100))
        task = {
            "keyword": keyword,
            "location_name": location_name,
            "language_name": language_name,
            "device": device,
            "os": "windows" if device == "desktop" else "android",
            "depth": depth,
        }
        envelope = self._post("serp/google/organic/live/regular", task)
        return {
            **result_metadata(envelope),
            "report": REPORT_SERP_RANK,
            "target": normalize_target(target),
            "location": location_name,
            "language": language_name,
            "device": device,
            "observation": normalize_serp_rank(
                envelope, keyword=keyword, target_domain=target
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

        if report == REPORT_KEYWORD_GAP:
            return await self.fetch_domain_intersection(**kwargs)

        if report == REPORT_BACKLINKS_SUMMARY:
            return await self.fetch_backlinks_summary(**kwargs)

        if report == REPORT_BACKLINKS:
            return await self.fetch_backlinks(**kwargs)

        if report == REPORT_SERP_RANK:
            return await self.fetch_serp_rank(**kwargs)

        return await self.fetch_competitors_domain(**kwargs)


__all__ = [
    "BASE_URL_ENV",
    "DataForSEOError",
    "DataForSEOIntegration",
    "LOGIN_ENV",
    "PASSWORD_ENV",
    "PROVIDER",
    "REPORT_BACKLINKS",
    "REPORT_BACKLINKS_SUMMARY",
    "REPORT_COMPETITORS_DOMAIN",
    "REPORT_DOMAIN_RANK_OVERVIEW",
    "REPORT_KEYWORD_GAP",
    "REPORT_RANKED_KEYWORDS",
    "REPORT_SERP_RANK",
    "classify_gap",
    "normalize_backlink_summary",
    "normalize_backlinks",
    "normalize_domain_intersection",
    "normalize_serp_rank",
    "SUPPORTED_REPORTS",
    "credential_readiness",
    "normalize_competitors",
    "normalize_domain_overview",
    "normalize_ranked_keywords",
    "normalize_target",
    "result_metadata",
]
