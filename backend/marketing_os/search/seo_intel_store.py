"""SEO intelligence phase 2 store — keyword gap, backlinks, SERP rank
tracking, governed refresh schedules.

PostgreSQL only. Persistence functions never open transactions (callers
control ``pg.begin()``); read functions are SELECT-only. Nothing here talks
to a provider. Snapshots are keyed by ``captured_date`` so history is kept.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text

from marketing_os.integrations.dataforseo import (
    _safe_target,
    GAP_MISSING, GAP_SHARED, GAP_STRONG, GAP_UNTAPPED, GAP_WEAK,
    REPORT_BACKLINKS, REPORT_BACKLINKS_SUMMARY, REPORT_COMPETITORS_DOMAIN,
    REPORT_DOMAIN_RANK_OVERVIEW, REPORT_KEYWORD_GAP, REPORT_RANKED_KEYWORDS,
    REPORT_SERP_RANK, normalize_target,
)

from .seo_provider_persistence import (
    DEFAULT_DEVICE, DEFAULT_LANGUAGE, DEFAULT_LOCATION, DEFAULT_PROVIDER,
    _captured_date, _new_id, _text_value,
)
from .seo_provider_reads import _serialize_row, _validate_page


class _MappingRow:
    __slots__ = ("_mapping",)

    def __init__(self, mapping):
        self._mapping = mapping


def _ser(row) -> dict:
    """JSON-safe dict from a Row OR a RowMapping (``.mappings()`` result)."""
    if row is None:
        return {}
    if hasattr(row, "_mapping"):
        return _serialize_row(row)
    return _serialize_row(_MappingRow(dict(row)))


def _sers(rows) -> list[dict]:
    return [_ser(r) for r in rows]

GAP_TYPES = (GAP_SHARED, GAP_MISSING, GAP_UNTAPPED, GAP_WEAK, GAP_STRONG)

# Conservative default cadences (hours). All schedules are created DISABLED.
DEFAULT_SCHEDULES: dict[str, dict[str, Any]] = {
    REPORT_DOMAIN_RANK_OVERVIEW: {"cadence_hours": 168, "max_pages": 1, "max_requests": 1, "max_total_cost": 0.05, "limit_per_page": 1},
    REPORT_RANKED_KEYWORDS: {"cadence_hours": 168, "max_pages": 2, "max_requests": 2, "max_total_cost": 0.50, "limit_per_page": 1000},
    REPORT_COMPETITORS_DOMAIN: {"cadence_hours": 336, "max_pages": 1, "max_requests": 1, "max_total_cost": 0.25, "limit_per_page": 1000},
    REPORT_KEYWORD_GAP: {"cadence_hours": 336, "max_pages": 1, "max_requests": 1, "max_total_cost": 0.25, "limit_per_page": 1000},
    REPORT_BACKLINKS_SUMMARY: {"cadence_hours": 168, "max_pages": 1, "max_requests": 1, "max_total_cost": 0.05, "limit_per_page": 1},
    REPORT_BACKLINKS: {"cadence_hours": 336, "max_pages": 1, "max_requests": 1, "max_total_cost": 0.25, "limit_per_page": 500},
    REPORT_SERP_RANK: {"cadence_hours": 168, "max_pages": 1, "max_requests": 25, "max_total_cost": 0.25, "limit_per_page": 100},
}


def _jsonb(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return None


def _ts(value: Any) -> Optional[datetime]:
    """Parse provider timestamps ('2024-05-01 10:11:12 +00:00') safely."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    raw = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(raw.replace(" +", "+"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Keyword gap
# ---------------------------------------------------------------------------


async def persist_keyword_gap_snapshots(
    pg, *, site_id: str, rows: Sequence[Mapping[str, Any]],
    provider_run_id: str | None = None, provider: str = DEFAULT_PROVIDER,
    captured_date: date | None = None, location: str = DEFAULT_LOCATION,
    language: str = DEFAULT_LANGUAGE, device: str = DEFAULT_DEVICE,
) -> int:
    captured = _captured_date(captured_date)
    stored = 0
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        keyword = _text_value(item.get("keyword"), limit=512)
        competitor = _safe_target(item.get("competitor_domain") or "")
        if not keyword or not competitor:
            continue
        gap_type = str(item.get("gap_type") or "").lower()
        if gap_type not in GAP_TYPES:
            continue
        await pg.execute(text("""
            INSERT INTO marketing_seo_keyword_gap_snapshots (
                id, site_id, provider_run_id, provider, captured_date,
                target_domain, competitor_domain, keyword, normalized_keyword,
                gap_type, target_rank, competitor_rank, target_url,
                competitor_url, target_etv, competitor_etv, search_volume,
                cpc, intent, keyword_difficulty, location, language, device)
            VALUES (
                :id, :site_id, :provider_run_id, :provider, :captured_date,
                :target_domain, :competitor_domain, :keyword,
                :normalized_keyword, :gap_type, :target_rank,
                :competitor_rank, :target_url, :competitor_url, :target_etv,
                :competitor_etv, :search_volume, :cpc, :intent,
                :keyword_difficulty, :location, :language, :device)
            ON CONFLICT (site_id, competitor_domain, normalized_keyword,
                         captured_date, provider, location, language, device)
            DO UPDATE SET
                provider_run_id = EXCLUDED.provider_run_id,
                gap_type = EXCLUDED.gap_type,
                target_rank = EXCLUDED.target_rank,
                competitor_rank = EXCLUDED.competitor_rank,
                target_url = EXCLUDED.target_url,
                competitor_url = EXCLUDED.competitor_url,
                target_etv = EXCLUDED.target_etv,
                competitor_etv = EXCLUDED.competitor_etv,
                search_volume = EXCLUDED.search_volume,
                cpc = EXCLUDED.cpc, intent = EXCLUDED.intent,
                keyword_difficulty = EXCLUDED.keyword_difficulty,
                updated_at = now()
        """), {
            "id": _new_id(), "site_id": site_id,
            "provider_run_id": provider_run_id,
            "provider": _text_value(item.get("source") or provider, default=DEFAULT_PROVIDER, limit=64),
            "captured_date": captured,
            "target_domain": _safe_target(item.get("target_domain") or ""),
            "competitor_domain": competitor, "keyword": keyword,
            "normalized_keyword": _text_value(item.get("normalized_keyword") or " ".join(keyword.lower().split()), limit=512),
            "gap_type": gap_type,
            "target_rank": item.get("target_rank"),
            "competitor_rank": item.get("competitor_rank"),
            "target_url": item.get("target_url"),
            "competitor_url": item.get("competitor_url"),
            "target_etv": item.get("target_etv"),
            "competitor_etv": item.get("competitor_etv"),
            "search_volume": item.get("search_volume"), "cpc": item.get("cpc"),
            "intent": _text_value(item.get("intent"), default="unknown", limit=32).lower(),
            "keyword_difficulty": item.get("keyword_difficulty"),
            "location": _text_value(location, default=DEFAULT_LOCATION, limit=128),
            "language": _text_value(language, default=DEFAULT_LANGUAGE, limit=64),
            "device": _text_value(device, default=DEFAULT_DEVICE, limit=32),
        })
        stored += 1
    return stored


async def list_keyword_gap_competitors(pg, *, site_id: str,
                                       provider: str = DEFAULT_PROVIDER) -> list[dict]:
    result = await pg.execute(text("""
        SELECT competitor_domain,
               MAX(captured_date) AS latest_captured_date,
               COUNT(*) FILTER (WHERE captured_date = (
                   SELECT MAX(g2.captured_date) FROM marketing_seo_keyword_gap_snapshots g2
                   WHERE g2.site_id = g.site_id AND g2.competitor_domain = g.competitor_domain
                     AND g2.provider = g.provider)) AS keyword_rows
        FROM marketing_seo_keyword_gap_snapshots g
        WHERE site_id = :site_id AND provider = :provider
        GROUP BY competitor_domain ORDER BY latest_captured_date DESC, competitor_domain
    """), {"site_id": site_id, "provider": provider})
    return _sers(result.mappings().all())


async def list_keyword_gap(
    pg, *, site_id: str, competitor_domain: str, provider: str = DEFAULT_PROVIDER,
    gap_type: str | None = None, search: str | None = None,
    sort: str = "search_volume", direction: str = "desc",
    limit: int = 50, offset: int = 0, captured_date: date | None = None,
) -> dict[str, Any]:
    limit, offset = _validate_page(limit=limit, offset=offset)
    competitor = normalize_target(competitor_domain)
    sort_cols = {"search_volume": "search_volume", "cpc": "cpc", "keyword": "keyword",
                 "target_rank": "target_rank", "competitor_rank": "competitor_rank",
                 "keyword_difficulty": "keyword_difficulty", "competitor_etv": "competitor_etv"}
    order_col = sort_cols.get(sort, "search_volume")
    order_dir = "ASC" if str(direction).lower() == "asc" else "DESC"
    params: dict[str, Any] = {"site_id": site_id, "provider": provider, "competitor": competitor}
    if captured_date is None:
        row = (await pg.execute(text("""
            SELECT MAX(captured_date) AS d FROM marketing_seo_keyword_gap_snapshots
            WHERE site_id = :site_id AND provider = :provider AND competitor_domain = :competitor
        """), params)).first()
        captured_date = row._mapping["d"] if row else None
    if captured_date is None:
        return {"connected": True, "has_snapshot": False, "competitor_domain": competitor,
                "captured_date": None, "items": [], "total": 0, "limit": limit,
                "offset": offset, "has_more": False, "counts": {t: 0 for t in GAP_TYPES}}
    params["captured_date"] = captured_date
    where = ["site_id = :site_id", "provider = :provider", "competitor_domain = :competitor",
             "captured_date = :captured_date"]
    if gap_type and gap_type in GAP_TYPES:
        where.append("gap_type = :gap_type"); params["gap_type"] = gap_type
    if search:
        where.append("keyword ILIKE :search"); params["search"] = f"%{search.strip()}%"
    where_sql = " AND ".join(where)
    total = (await pg.execute(text(
        f"SELECT COUNT(*) FROM marketing_seo_keyword_gap_snapshots WHERE {where_sql}"
    ), params)).scalar() or 0
    counts_rows = (await pg.execute(text("""
        SELECT gap_type, COUNT(*) AS c FROM marketing_seo_keyword_gap_snapshots
        WHERE site_id = :site_id AND provider = :provider AND competitor_domain = :competitor
          AND captured_date = :captured_date GROUP BY gap_type
    """), params)).mappings().all()
    counts = {t: 0 for t in GAP_TYPES}
    for r in counts_rows:
        counts[r["gap_type"]] = int(r["c"])
    rows = (await pg.execute(text(f"""
        SELECT * FROM marketing_seo_keyword_gap_snapshots WHERE {where_sql}
        ORDER BY {order_col} {order_dir} NULLS LAST, keyword ASC LIMIT :limit OFFSET :offset
    """), {**params, "limit": limit, "offset": offset})).mappings().all()
    items = _sers(rows)
    return {"connected": True, "has_snapshot": True, "competitor_domain": competitor,
            "captured_date": captured_date.isoformat(), "items": items, "total": int(total),
            "limit": limit, "offset": offset, "has_more": offset + len(items) < int(total),
            "counts": counts, "provider": provider}


# ---------------------------------------------------------------------------
# Backlinks
# ---------------------------------------------------------------------------


async def persist_backlink_summary_snapshot(
    pg, *, site_id: str, summary: Mapping[str, Any], provider_run_id: str | None = None,
    provider: str = DEFAULT_PROVIDER, captured_date: date | None = None,
) -> dict | None:
    if not summary or not summary.get("target"):
        return None
    captured = _captured_date(captured_date)
    params = {
        "id": _new_id(), "site_id": site_id, "provider_run_id": provider_run_id,
        "provider": _text_value(summary.get("source") or provider, default=DEFAULT_PROVIDER, limit=64),
        "captured_date": captured, "target": normalize_target(summary.get("target")),
        "first_seen": _ts(summary.get("first_seen")), "lost_date": _ts(summary.get("lost_date")),
        "referring_links_types": _jsonb(summary.get("referring_links_types")),
        "referring_links_attributes": _jsonb(summary.get("referring_links_attributes")),
        "referring_links_tld": _jsonb(summary.get("referring_links_tld")),
        "referring_links_countries": _jsonb(summary.get("referring_links_countries")),
    }
    for key in ("rank", "backlinks", "referring_domains", "referring_main_domains",
                "referring_pages", "referring_ips", "referring_domains_nofollow",
                "dofollow_links", "nofollow_links", "broken_backlinks", "broken_pages",
                "backlinks_spam_score", "crawled_pages"):
        params[key] = summary.get(key)
    result = await pg.execute(text("""
        INSERT INTO marketing_seo_backlink_summary_snapshots (
            id, site_id, provider_run_id, provider, captured_date, target, rank, backlinks,
            referring_domains, referring_main_domains, referring_pages, referring_ips,
            referring_domains_nofollow, dofollow_links, nofollow_links, broken_backlinks,
            broken_pages, backlinks_spam_score, crawled_pages, first_seen, lost_date,
            referring_links_types, referring_links_attributes, referring_links_tld,
            referring_links_countries)
        VALUES (:id, :site_id, :provider_run_id, :provider, :captured_date, :target, :rank,
            :backlinks, :referring_domains, :referring_main_domains, :referring_pages,
            :referring_ips, :referring_domains_nofollow, :dofollow_links, :nofollow_links,
            :broken_backlinks, :broken_pages, :backlinks_spam_score, :crawled_pages,
            :first_seen, :lost_date, CAST(:referring_links_types AS jsonb),
            CAST(:referring_links_attributes AS jsonb), CAST(:referring_links_tld AS jsonb),
            CAST(:referring_links_countries AS jsonb))
        ON CONFLICT (site_id, target, captured_date, provider) DO UPDATE SET
            provider_run_id = EXCLUDED.provider_run_id, rank = EXCLUDED.rank,
            backlinks = EXCLUDED.backlinks, referring_domains = EXCLUDED.referring_domains,
            referring_main_domains = EXCLUDED.referring_main_domains,
            referring_pages = EXCLUDED.referring_pages, referring_ips = EXCLUDED.referring_ips,
            referring_domains_nofollow = EXCLUDED.referring_domains_nofollow,
            dofollow_links = EXCLUDED.dofollow_links, nofollow_links = EXCLUDED.nofollow_links,
            broken_backlinks = EXCLUDED.broken_backlinks, broken_pages = EXCLUDED.broken_pages,
            backlinks_spam_score = EXCLUDED.backlinks_spam_score,
            crawled_pages = EXCLUDED.crawled_pages, first_seen = EXCLUDED.first_seen,
            lost_date = EXCLUDED.lost_date,
            referring_links_types = EXCLUDED.referring_links_types,
            referring_links_attributes = EXCLUDED.referring_links_attributes,
            referring_links_tld = EXCLUDED.referring_links_tld,
            referring_links_countries = EXCLUDED.referring_links_countries,
            updated_at = now()
        RETURNING *
    """), params)
    row = result.mappings().first()
    return _ser(row) if row else None


async def persist_backlink_snapshots(
    pg, *, site_id: str, rows: Sequence[Mapping[str, Any]], provider_run_id: str | None = None,
    provider: str = DEFAULT_PROVIDER, captured_date: date | None = None,
) -> int:
    captured = _captured_date(captured_date)
    stored = 0
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        source_url = str(item.get("source_url") or "").strip()
        target = _safe_target(item.get("target") or "")
        if not source_url or not target:
            continue
        key = hashlib.sha256(f"{source_url}|{item.get('target_url') or ''}".encode()).hexdigest()[:64]
        await pg.execute(text("""
            INSERT INTO marketing_seo_backlink_snapshots (
                id, site_id, provider_run_id, provider, captured_date, target, backlink_key,
                source_url, source_domain, target_url, anchor, item_type, dofollow, attributes,
                is_new, is_lost, is_broken, first_seen, prev_seen, last_seen, domain_from_rank,
                page_from_rank, backlink_spam_score, domain_from_platform_type,
                semantic_location, url_to_status_code)
            VALUES (:id, :site_id, :provider_run_id, :provider, :captured_date, :target,
                :backlink_key, :source_url, :source_domain, :target_url, :anchor, :item_type,
                :dofollow, CAST(:attributes AS jsonb), :is_new, :is_lost, :is_broken,
                :first_seen, :prev_seen, :last_seen, :domain_from_rank, :page_from_rank,
                :backlink_spam_score, CAST(:domain_from_platform_type AS jsonb),
                :semantic_location, :url_to_status_code)
            ON CONFLICT (site_id, target, backlink_key, captured_date, provider) DO UPDATE SET
                provider_run_id = EXCLUDED.provider_run_id, anchor = EXCLUDED.anchor,
                dofollow = EXCLUDED.dofollow, attributes = EXCLUDED.attributes,
                is_new = EXCLUDED.is_new, is_lost = EXCLUDED.is_lost, is_broken = EXCLUDED.is_broken,
                last_seen = EXCLUDED.last_seen, prev_seen = EXCLUDED.prev_seen,
                domain_from_rank = EXCLUDED.domain_from_rank, page_from_rank = EXCLUDED.page_from_rank,
                backlink_spam_score = EXCLUDED.backlink_spam_score,
                url_to_status_code = EXCLUDED.url_to_status_code, updated_at = now()
        """), {
            "id": _new_id(), "site_id": site_id, "provider_run_id": provider_run_id,
            "provider": _text_value(item.get("source") or provider, default=DEFAULT_PROVIDER, limit=64),
            "captured_date": captured, "target": target, "backlink_key": key,
            "source_url": source_url, "source_domain": _text_value(item.get("source_domain"), limit=255) or None,
            "target_url": item.get("target_url"), "anchor": item.get("anchor"),
            "item_type": _text_value(item.get("item_type"), limit=32) or None,
            "dofollow": item.get("dofollow"), "attributes": _jsonb(item.get("attributes")),
            "is_new": item.get("is_new"), "is_lost": item.get("is_lost"), "is_broken": item.get("is_broken"),
            "first_seen": _ts(item.get("first_seen")), "prev_seen": _ts(item.get("prev_seen")),
            "last_seen": _ts(item.get("last_seen")),
            "domain_from_rank": item.get("domain_from_rank"), "page_from_rank": item.get("page_from_rank"),
            "backlink_spam_score": item.get("backlink_spam_score"),
            "domain_from_platform_type": _jsonb(item.get("domain_from_platform_type")),
            "semantic_location": _text_value(item.get("semantic_location"), limit=64) or None,
            "url_to_status_code": item.get("url_to_status_code"),
        })
        stored += 1
    return stored


async def latest_backlink_summary(pg, *, site_id: str, provider: str = DEFAULT_PROVIDER) -> dict | None:
    row = (await pg.execute(text("""
        SELECT * FROM marketing_seo_backlink_summary_snapshots
        WHERE site_id = :site_id AND provider = :provider
        ORDER BY captured_date DESC, created_at DESC LIMIT 1
    """), {"site_id": site_id, "provider": provider})).mappings().first()
    if not row:
        return None
    data = _ser(row)
    # Derived counts from the sampled backlink rows of the same snapshot date
    # (labelled as sampled in the UI — never presented as the provider total).
    derived = (await pg.execute(text("""
        SELECT COUNT(*) FILTER (WHERE is_new) AS new_sampled,
               COUNT(*) FILTER (WHERE is_lost) AS lost_sampled,
               COUNT(*) AS sampled_rows
        FROM marketing_seo_backlink_snapshots
        WHERE site_id = :site_id AND provider = :provider AND target = :target
          AND captured_date = (SELECT MAX(captured_date) FROM marketing_seo_backlink_snapshots
                               WHERE site_id = :site_id AND provider = :provider AND target = :target)
    """), {"site_id": site_id, "provider": provider, "target": row["target"]})).mappings().first()
    data["sampled"] = _ser(derived) if derived else None
    return data


async def list_backlinks(
    pg, *, site_id: str, provider: str = DEFAULT_PROVIDER, search: str | None = None,
    dofollow: bool | None = None, status: str | None = None, sort: str = "domain_from_rank",
    direction: str = "desc", limit: int = 50, offset: int = 0,
) -> dict[str, Any]:
    limit, offset = _validate_page(limit=limit, offset=offset)
    params: dict[str, Any] = {"site_id": site_id, "provider": provider}
    latest = (await pg.execute(text("""
        SELECT MAX(captured_date) AS d FROM marketing_seo_backlink_snapshots
        WHERE site_id = :site_id AND provider = :provider"""), params)).first()
    captured = latest._mapping["d"] if latest else None
    if captured is None:
        return {"connected": True, "has_snapshot": False, "captured_date": None, "items": [],
                "total": 0, "limit": limit, "offset": offset, "has_more": False}
    params["captured_date"] = captured
    where = ["site_id = :site_id", "provider = :provider", "captured_date = :captured_date"]
    if search:
        where.append("(source_url ILIKE :search OR anchor ILIKE :search OR source_domain ILIKE :search)")
        params["search"] = f"%{search.strip()}%"
    if dofollow is not None:
        where.append("dofollow = :dofollow"); params["dofollow"] = dofollow
    if status == "new":
        where.append("is_new = true")
    elif status == "lost":
        where.append("is_lost = true")
    elif status == "broken":
        where.append("is_broken = true")
    sort_cols = {"domain_from_rank": "domain_from_rank", "page_from_rank": "page_from_rank",
                 "first_seen": "first_seen", "last_seen": "last_seen", "source_domain": "source_domain",
                 "backlink_spam_score": "backlink_spam_score"}
    order_col = sort_cols.get(sort, "domain_from_rank")
    order_dir = "ASC" if str(direction).lower() == "asc" else "DESC"
    where_sql = " AND ".join(where)
    total = (await pg.execute(text(
        f"SELECT COUNT(*) FROM marketing_seo_backlink_snapshots WHERE {where_sql}"), params)).scalar() or 0
    rows = (await pg.execute(text(f"""
        SELECT * FROM marketing_seo_backlink_snapshots WHERE {where_sql}
        ORDER BY {order_col} {order_dir} NULLS LAST, source_url ASC LIMIT :limit OFFSET :offset
    """), {**params, "limit": limit, "offset": offset})).mappings().all()
    items = _sers(rows)
    return {"connected": True, "has_snapshot": True, "captured_date": captured.isoformat(),
            "items": items, "total": int(total), "limit": limit, "offset": offset,
            "has_more": offset + len(items) < int(total), "provider": provider}


# ---------------------------------------------------------------------------
# Tracked keywords + rank observations
# ---------------------------------------------------------------------------


async def create_tracked_keyword(
    pg, *, site_id: str, keyword: str, target_domain: str, target_url: str | None = None,
    location: str = DEFAULT_LOCATION, language: str = DEFAULT_LANGUAGE,
    device: str = DEFAULT_DEVICE, tags: list[str] | None = None, created_by: str | None = None,
) -> dict:
    keyword = " ".join(str(keyword or "").split())
    if not keyword:
        raise ValueError("keyword is required")
    device = (device or DEFAULT_DEVICE).lower()
    if device not in {"desktop", "mobile"}:
        raise ValueError("device must be desktop or mobile")
    row = (await pg.execute(text("""
        INSERT INTO marketing_seo_tracked_keywords (
            id, site_id, keyword, normalized_keyword, target_domain, target_url, location,
            language, device, is_active, tags, created_by)
        VALUES (:id, :site_id, :keyword, :normalized_keyword, :target_domain, :target_url,
            :location, :language, :device, true, CAST(:tags AS jsonb), :created_by)
        ON CONFLICT (site_id, normalized_keyword, location, language, device) DO UPDATE SET
            is_active = true, target_url = COALESCE(EXCLUDED.target_url,
            marketing_seo_tracked_keywords.target_url), tags = COALESCE(EXCLUDED.tags,
            marketing_seo_tracked_keywords.tags), updated_at = now()
        RETURNING *
    """), {
        "id": _new_id(), "site_id": site_id, "keyword": keyword[:512],
        "normalized_keyword": " ".join(keyword.lower().split())[:512],
        "target_domain": normalize_target(target_domain), "target_url": target_url,
        "location": location[:128], "language": language[:64], "device": device,
        "tags": _jsonb(tags), "created_by": created_by,
    })).mappings().first()
    return _ser(row)


async def set_tracked_keyword_active(pg, *, site_id: str, keyword_id: str, is_active: bool) -> dict | None:
    row = (await pg.execute(text("""
        UPDATE marketing_seo_tracked_keywords SET is_active = :is_active, updated_at = now()
        WHERE id = :id AND site_id = :site_id RETURNING *
    """), {"id": keyword_id, "site_id": site_id, "is_active": is_active})).mappings().first()
    return _ser(row) if row else None


async def list_tracked_keywords(pg, *, site_id: str, include_inactive: bool = False,
                                limit: int = 200, offset: int = 0) -> dict[str, Any]:
    limit, offset = _validate_page(limit=limit, offset=offset)
    params: dict[str, Any] = {"site_id": site_id, "limit": limit, "offset": offset}
    active_sql = "" if include_inactive else "AND k.is_active = true"
    total = (await pg.execute(text(
        f"SELECT COUNT(*) FROM marketing_seo_tracked_keywords k WHERE k.site_id = :site_id {active_sql}"
    ), params)).scalar() or 0
    rows = (await pg.execute(text(f"""
        SELECT k.*,
            latest.position AS latest_position, latest.found AS latest_found,
            latest.ranking_url AS latest_url, latest.observed_at AS latest_observed_at,
            latest.serp_features AS latest_serp_features,
            prev.position AS previous_position, prev.observed_at AS previous_observed_at,
            (SELECT COUNT(*) FROM marketing_seo_rank_observations o
               WHERE o.tracked_keyword_id = k.id) AS observation_count
        FROM marketing_seo_tracked_keywords k
        LEFT JOIN LATERAL (
            SELECT * FROM marketing_seo_rank_observations o
            WHERE o.tracked_keyword_id = k.id ORDER BY o.observed_at DESC LIMIT 1) latest ON true
        LEFT JOIN LATERAL (
            SELECT * FROM marketing_seo_rank_observations o
            WHERE o.tracked_keyword_id = k.id ORDER BY o.observed_at DESC OFFSET 1 LIMIT 1) prev ON true
        WHERE k.site_id = :site_id {active_sql}
        ORDER BY k.created_at DESC LIMIT :limit OFFSET :offset
    """), params)).mappings().all()
    items = _sers(rows)
    for item in items:
        lp, pp = item.get("latest_position"), item.get("previous_position")
        item["position_change"] = (pp - lp) if (lp is not None and pp is not None) else None
    return {"items": items, "total": int(total), "limit": limit, "offset": offset,
            "has_more": offset + len(items) < int(total)}


async def get_tracked_keyword(pg, *, site_id: str, keyword_id: str) -> dict | None:
    row = (await pg.execute(text(
        "SELECT * FROM marketing_seo_tracked_keywords WHERE id = :id AND site_id = :site_id"
    ), {"id": keyword_id, "site_id": site_id})).mappings().first()
    return _ser(row) if row else None


async def persist_rank_observation(
    pg, *, site_id: str, tracked_keyword_id: str, observation: Mapping[str, Any],
    provider_run_id: str | None = None, provider: str = DEFAULT_PROVIDER,
    location: str = DEFAULT_LOCATION, language: str = DEFAULT_LANGUAGE,
    device: str = DEFAULT_DEVICE, observed_at: datetime | None = None,
) -> dict:
    observed = observed_at or datetime.now(timezone.utc)
    row = (await pg.execute(text("""
        INSERT INTO marketing_seo_rank_observations (
            id, site_id, tracked_keyword_id, provider_run_id, provider, observed_at,
            captured_date, keyword, location, language, device, found, position, rank_group,
            ranking_url, ranking_domain, serp_item_type, serp_features, depth,
            se_results_count, check_url, provider_datetime)
        VALUES (:id, :site_id, :tracked_keyword_id, :provider_run_id, :provider, :observed_at,
            :captured_date, :keyword, :location, :language, :device, :found, :position,
            :rank_group, :ranking_url, :ranking_domain, :serp_item_type,
            CAST(:serp_features AS jsonb), :depth, :se_results_count, :check_url,
            :provider_datetime)
        RETURNING *
    """), {
        "id": _new_id(), "site_id": site_id, "tracked_keyword_id": tracked_keyword_id,
        "provider_run_id": provider_run_id,
        "provider": _text_value(observation.get("source") or provider, default=DEFAULT_PROVIDER, limit=64),
        "observed_at": observed, "captured_date": observed.date(),
        "keyword": _text_value(observation.get("keyword"), limit=512),
        "location": location[:128], "language": language[:64], "device": device[:32],
        "found": bool(observation.get("found")), "position": observation.get("position"),
        "rank_group": observation.get("rank_group"), "ranking_url": observation.get("ranking_url"),
        "ranking_domain": _text_value(observation.get("ranking_domain"), limit=255) or None,
        "serp_item_type": _text_value(observation.get("serp_item_type"), limit=64) or None,
        "serp_features": _jsonb(observation.get("serp_features") or []),
        "depth": observation.get("depth"), "se_results_count": observation.get("se_results_count"),
        "check_url": observation.get("check_url"),
        "provider_datetime": _text_value(observation.get("provider_datetime"), limit=64) or None,
    })).mappings().first()
    return _ser(row)


async def list_rank_observations(pg, *, site_id: str, keyword_id: str, limit: int = 90) -> list[dict]:
    limit, _ = _validate_page(limit=limit, offset=0)
    rows = (await pg.execute(text("""
        SELECT * FROM marketing_seo_rank_observations
        WHERE site_id = :site_id AND tracked_keyword_id = :kid
        ORDER BY observed_at DESC LIMIT :limit
    """), {"site_id": site_id, "kid": keyword_id, "limit": limit})).mappings().all()
    return _sers(rows)


async def rank_tracking_summary(pg, *, site_id: str) -> dict[str, Any]:
    """Aggregate latest observation per active tracked keyword (cache only)."""
    row = (await pg.execute(text("""
        WITH latest AS (
            SELECT k.id, o.position, o.observed_at,
                   LAG(o.position) OVER (PARTITION BY k.id ORDER BY o.observed_at) AS prev_position,
                   ROW_NUMBER() OVER (PARTITION BY k.id ORDER BY o.observed_at DESC) AS rn
            FROM marketing_seo_tracked_keywords k
            JOIN marketing_seo_rank_observations o ON o.tracked_keyword_id = k.id
            WHERE k.site_id = :site_id AND k.is_active = true)
        SELECT
            (SELECT COUNT(*) FROM marketing_seo_tracked_keywords WHERE site_id = :site_id AND is_active) AS tracked,
            COUNT(*) FILTER (WHERE rn = 1 AND position IS NOT NULL) AS observed,
            COUNT(*) FILTER (WHERE rn = 1 AND position <= 3) AS top_3,
            COUNT(*) FILTER (WHERE rn = 1 AND position <= 10) AS top_10,
            COUNT(*) FILTER (WHERE rn = 1 AND position <= 20) AS top_20,
            COUNT(*) FILTER (WHERE rn = 1 AND prev_position IS NOT NULL AND position < prev_position) AS improved,
            COUNT(*) FILTER (WHERE rn = 1 AND prev_position IS NOT NULL AND position > prev_position) AS declined,
            AVG(position) FILTER (WHERE rn = 1) AS average_position,
            MAX(observed_at) FILTER (WHERE rn = 1) AS last_observed_at
        FROM latest
    """), {"site_id": site_id})).mappings().first()
    return _ser(row) if row else {}


# ---------------------------------------------------------------------------
# Governed refresh schedules
# ---------------------------------------------------------------------------


async def list_refresh_schedules(pg, *, site_id: str, provider: str = DEFAULT_PROVIDER) -> list[dict]:
    rows = (await pg.execute(text("""
        SELECT * FROM marketing_seo_refresh_schedules
        WHERE site_id = :site_id AND provider = :provider ORDER BY report_type
    """), {"site_id": site_id, "provider": provider})).mappings().all()
    existing = {r["report_type"]: _ser(r) for r in rows}
    # Present every supported report with defaults so admins see the full
    # picture; unsaved defaults are flagged (never enabled).
    out = []
    for report, defaults in DEFAULT_SCHEDULES.items():
        if report in existing:
            out.append({**existing[report], "persisted": True})
        else:
            out.append({"id": None, "site_id": site_id, "provider": provider, "report_type": report,
                        "enabled": False, "retry_ceiling": 2, "options": None, "last_run_at": None,
                        "last_success_at": None, "last_status": None, "last_error": None,
                        "next_run_at": None, "consecutive_failures": 0, "persisted": False, **defaults})
    return out


async def upsert_refresh_schedule(
    pg, *, site_id: str, report_type: str, enabled: bool, cadence_hours: int, max_pages: int,
    max_requests: int, max_total_cost: float, retry_ceiling: int, limit_per_page: int,
    options: Mapping[str, Any] | None = None, updated_by: str | None = None,
    provider: str = DEFAULT_PROVIDER,
) -> dict:
    if report_type not in DEFAULT_SCHEDULES:
        raise ValueError(f"unsupported report_type: {report_type}")
    if cadence_hours < 24:
        raise ValueError("cadence_hours must be >= 24 (SEO intelligence is not hourly)")
    if not 1 <= max_pages <= 20:
        raise ValueError("max_pages must be 1..20")
    if not 1 <= max_requests <= 100:
        raise ValueError("max_requests must be 1..100")
    if not 0 < float(max_total_cost) <= 25:
        raise ValueError("max_total_cost must be in (0, 25]")
    if not 0 <= retry_ceiling <= 5:
        raise ValueError("retry_ceiling must be 0..5")
    if not 1 <= limit_per_page <= 1000:
        raise ValueError("limit_per_page must be 1..1000")
    now = datetime.now(timezone.utc)
    row = (await pg.execute(text("""
        INSERT INTO marketing_seo_refresh_schedules (
            id, site_id, provider, report_type, enabled, cadence_hours, limit_per_page, max_pages,
            max_requests, max_total_cost, retry_ceiling, options, next_run_at, updated_by)
        VALUES (:id, :site_id, :provider, :report_type, :enabled, :cadence_hours, :limit_per_page,
            :max_pages, :max_requests, :max_total_cost, :retry_ceiling, CAST(:options AS jsonb),
            :next_run_at, :updated_by)
        ON CONFLICT (site_id, provider, report_type) DO UPDATE SET
            enabled = EXCLUDED.enabled, cadence_hours = EXCLUDED.cadence_hours,
            limit_per_page = EXCLUDED.limit_per_page, max_pages = EXCLUDED.max_pages,
            max_requests = EXCLUDED.max_requests, max_total_cost = EXCLUDED.max_total_cost,
            retry_ceiling = EXCLUDED.retry_ceiling, options = EXCLUDED.options,
            next_run_at = CASE WHEN EXCLUDED.enabled AND marketing_seo_refresh_schedules.next_run_at IS NULL
                               THEN EXCLUDED.next_run_at ELSE marketing_seo_refresh_schedules.next_run_at END,
            updated_by = EXCLUDED.updated_by, updated_at = now()
        RETURNING *
    """), {
        "id": _new_id(), "site_id": site_id, "provider": provider, "report_type": report_type,
        "enabled": bool(enabled), "cadence_hours": int(cadence_hours), "limit_per_page": int(limit_per_page),
        "max_pages": int(max_pages), "max_requests": int(max_requests),
        "max_total_cost": float(max_total_cost), "retry_ceiling": int(retry_ceiling),
        "options": _jsonb(dict(options) if options else None),
        # First automatic run is never immediate: earliest one cadence from now.
        "next_run_at": (now + timedelta(hours=int(cadence_hours))) if enabled else None,
        "updated_by": updated_by,
    })).mappings().first()
    return _ser(row)


async def due_refresh_schedules(pg, *, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    rows = (await pg.execute(text("""
        SELECT s.*, st.normalized_url AS target
        FROM marketing_seo_refresh_schedules s
        JOIN marketing_search_sites st ON st.id = s.site_id
        WHERE s.enabled = true AND s.next_run_at IS NOT NULL AND s.next_run_at <= :now
          AND s.consecutive_failures <= s.retry_ceiling
        ORDER BY s.next_run_at ASC LIMIT 5
    """), {"now": now})).mappings().all()
    return _sers(rows)


async def record_schedule_run(
    pg, *, schedule_id: str, status: str, error: str | None, provider_run_id: str | None,
    cadence_hours: int, now: datetime | None = None,
) -> None:
    now = now or datetime.now(timezone.utc)
    ok = status == "completed"
    await pg.execute(text("""
        UPDATE marketing_seo_refresh_schedules SET
            last_run_at = :now,
            last_success_at = CASE WHEN :ok THEN :now ELSE last_success_at END,
            last_status = :status, last_error = :error,
            last_provider_run_id = COALESCE(:provider_run_id, last_provider_run_id),
            consecutive_failures = CASE WHEN :ok THEN 0 ELSE consecutive_failures + 1 END,
            next_run_at = :next_run_at, updated_at = now()
        WHERE id = :id
    """), {"id": schedule_id, "now": now, "ok": ok, "status": status[:32],
           "error": (error or None), "provider_run_id": provider_run_id,
           "next_run_at": now + timedelta(hours=int(cadence_hours))})
