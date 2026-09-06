"""Persistence helpers for external SEO provider intelligence.

The caller supplies the database session and owns the transaction boundary.

This module:
- creates no engine/session
- begins or commits no transaction
- performs no provider/network call
- stores no credentials
- keeps provider keywords separate from tracked keywords
- keeps discovered competitors separate from curated competitors
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text


DEFAULT_PROVIDER = "dataforseo"
DEFAULT_LOCATION = "United States"
DEFAULT_LANGUAGE = "English"
DEFAULT_DEVICE = "desktop"


def _new_id() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _captured_date(value: date | None) -> date:
    return value or _utcnow().date()


def _text_value(
    value: Any,
    *,
    default: str = "",
    limit: int | None = None,
) -> str:
    result = str(value or default).strip()
    if limit is not None:
        result = result[:limit]
    return result


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _json_array(value: Any) -> str:
    if not isinstance(value, list):
        value = []
    return json.dumps(value, default=str)


def normalize_domain(value: Any) -> str:
    domain = _text_value(value, limit=255).lower()

    for prefix in ("https://", "http://"):
        if domain.startswith(prefix):
            domain = domain[len(prefix):]

    domain = domain.split("/", 1)[0]

    if domain.startswith("www."):
        domain = domain[4:]

    return domain.rstrip(".")


async def persist_provider_run(
    pg,
    *,
    site_id: str,
    report_type: str,
    target: str,
    metadata: Mapping[str, Any] | None = None,
    rows_normalized: int = 0,
    provider: str = DEFAULT_PROVIDER,
    location: str = DEFAULT_LOCATION,
    language: str = DEFAULT_LANGUAGE,
    device: str = DEFAULT_DEVICE,
    requested_limit: int | None = None,
    requested_offset: int | None = None,
    complete: bool = True,
    next_offset: int | None = None,
    status: str = "completed",
    error: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> dict[str, Any]:
    meta = dict(metadata or {})
    run_id = _new_id()

    params = {
        "id": run_id,
        "site_id": _text_value(site_id, limit=64),
        "provider": _text_value(
            provider, default=DEFAULT_PROVIDER, limit=64
        ),
        "report_type": _text_value(report_type, limit=64),
        "status": _text_value(status, default="completed", limit=32),
        "target": _text_value(target, limit=512),
        "location": _text_value(
            location, default=DEFAULT_LOCATION, limit=128
        ),
        "language": _text_value(
            language, default=DEFAULT_LANGUAGE, limit=32
        ),
        "device": _text_value(
            device, default=DEFAULT_DEVICE, limit=32
        ),
        "requested_limit": requested_limit,
        "requested_offset": requested_offset,
        "provider_total_count": _optional_int(
            meta.get("total_count")
        ),
        "provider_items_count": _optional_int(
            meta.get("items_count")
        ),
        "rows_normalized": int(rows_normalized or 0),
        "provider_cost": meta.get("cost"),
        "provider_task_cost": meta.get("task_cost"),
        "complete": bool(complete),
        "next_offset": next_offset,
        "provider_status_code": _optional_int(
            meta.get("status_code")
        ),
        "provider_task_status_code": _optional_int(
            meta.get("task_status_code")
        ),
        "error": _text_value(error, limit=4000) if error else None,
        "started_at": started_at or _utcnow(),
        "finished_at": finished_at or _utcnow(),
    }

    await pg.execute(
        text("""
            INSERT INTO marketing_seo_provider_runs (
                id, site_id, provider, report_type, status, target,
                location, language, device,
                requested_limit, requested_offset,
                provider_total_count, provider_items_count,
                rows_normalized, provider_cost, provider_task_cost,
                complete, next_offset,
                provider_status_code, provider_task_status_code,
                error, started_at, finished_at
            )
            VALUES (
                :id, :site_id, :provider, :report_type, :status, :target,
                :location, :language, :device,
                :requested_limit, :requested_offset,
                :provider_total_count, :provider_items_count,
                :rows_normalized, :provider_cost, :provider_task_cost,
                :complete, :next_offset,
                :provider_status_code, :provider_task_status_code,
                :error, :started_at, :finished_at
            )
        """),
        params,
    )

    return {
        "id": run_id,
        "provider": params["provider"],
        "report_type": params["report_type"],
        "rows_normalized": params["rows_normalized"],
        "complete": params["complete"],
    }


async def persist_domain_snapshot(
    pg,
    *,
    site_id: str,
    overview: Mapping[str, Any],
    provider_run_id: str | None = None,
    provider: str = DEFAULT_PROVIDER,
    captured_date: date | None = None,
    location: str = DEFAULT_LOCATION,
    language: str = DEFAULT_LANGUAGE,
    device: str = DEFAULT_DEVICE,
) -> dict[str, Any]:
    positions = overview.get("positions") or {}
    if not isinstance(positions, Mapping):
        positions = {}

    snapshot_id = _new_id()
    captured = _captured_date(captured_date)

    params = {
        "id": snapshot_id,
        "site_id": _text_value(site_id, limit=64),
        "provider_run_id": provider_run_id,
        "provider": _text_value(
            provider, default=DEFAULT_PROVIDER, limit=64
        ),
        "captured_date": captured,
        "location": _text_value(
            location, default=DEFAULT_LOCATION, limit=128
        ),
        "language": _text_value(
            language, default=DEFAULT_LANGUAGE, limit=32
        ),
        "device": _text_value(
            device, default=DEFAULT_DEVICE, limit=32
        ),
        "organic_keywords": overview.get("organic_keywords"),
        "estimated_organic_traffic": overview.get(
            "estimated_organic_traffic"
        ),
        "estimated_paid_traffic_cost": overview.get(
            "estimated_paid_traffic_cost"
        ),
        "pos_1": positions.get("pos_1"),
        "pos_2_3": positions.get("pos_2_3"),
        "pos_4_10": positions.get("pos_4_10"),
        "pos_11_20": positions.get("pos_11_20"),
        "pos_21_30": positions.get("pos_21_30"),
        "pos_31_40": positions.get("pos_31_40"),
        "pos_41_50": positions.get("pos_41_50"),
        "pos_51_60": positions.get("pos_51_60"),
        "pos_61_70": positions.get("pos_61_70"),
        "pos_71_80": positions.get("pos_71_80"),
        "pos_81_90": positions.get("pos_81_90"),
        "pos_91_100": positions.get("pos_91_100"),
        "new_keywords": overview.get("new"),
        "up_keywords": overview.get("up"),
        "down_keywords": overview.get("down"),
        "lost_keywords": overview.get("lost"),
    }

    await pg.execute(
        text("""
            INSERT INTO marketing_seo_domain_snapshots (
                id, site_id, provider_run_id, provider,
                captured_date, location, language, device,
                organic_keywords,
                estimated_organic_traffic,
                estimated_paid_traffic_cost,
                pos_1, pos_2_3, pos_4_10, pos_11_20,
                pos_21_30, pos_31_40, pos_41_50,
                pos_51_60, pos_61_70, pos_71_80,
                pos_81_90, pos_91_100,
                new_keywords, up_keywords,
                down_keywords, lost_keywords
            )
            VALUES (
                :id, :site_id, :provider_run_id, :provider,
                :captured_date, :location, :language, :device,
                :organic_keywords,
                :estimated_organic_traffic,
                :estimated_paid_traffic_cost,
                :pos_1, :pos_2_3, :pos_4_10, :pos_11_20,
                :pos_21_30, :pos_31_40, :pos_41_50,
                :pos_51_60, :pos_61_70, :pos_71_80,
                :pos_81_90, :pos_91_100,
                :new_keywords, :up_keywords,
                :down_keywords, :lost_keywords
            )
            ON CONFLICT (
                site_id, captured_date, provider,
                location, language, device
            )
            DO UPDATE SET
                provider_run_id = EXCLUDED.provider_run_id,
                organic_keywords = EXCLUDED.organic_keywords,
                estimated_organic_traffic =
                    EXCLUDED.estimated_organic_traffic,
                estimated_paid_traffic_cost =
                    EXCLUDED.estimated_paid_traffic_cost,
                pos_1 = EXCLUDED.pos_1,
                pos_2_3 = EXCLUDED.pos_2_3,
                pos_4_10 = EXCLUDED.pos_4_10,
                pos_11_20 = EXCLUDED.pos_11_20,
                pos_21_30 = EXCLUDED.pos_21_30,
                pos_31_40 = EXCLUDED.pos_31_40,
                pos_41_50 = EXCLUDED.pos_41_50,
                pos_51_60 = EXCLUDED.pos_51_60,
                pos_61_70 = EXCLUDED.pos_61_70,
                pos_71_80 = EXCLUDED.pos_71_80,
                pos_81_90 = EXCLUDED.pos_81_90,
                pos_91_100 = EXCLUDED.pos_91_100,
                new_keywords = EXCLUDED.new_keywords,
                up_keywords = EXCLUDED.up_keywords,
                down_keywords = EXCLUDED.down_keywords,
                lost_keywords = EXCLUDED.lost_keywords,
                updated_at = now()
        """),
        params,
    )

    return {
        "id": snapshot_id,
        "organic_keywords": params["organic_keywords"],
        "captured_date": captured.isoformat(),
    }


async def persist_organic_keyword_snapshots(
    pg,
    *,
    site_id: str,
    keywords: Sequence[Mapping[str, Any]],
    provider_run_id: str | None = None,
    provider: str = DEFAULT_PROVIDER,
    captured_date: date | None = None,
    location: str = DEFAULT_LOCATION,
    language: str = DEFAULT_LANGUAGE,
    device: str = DEFAULT_DEVICE,
) -> int:
    captured = _captured_date(captured_date)
    persisted = 0

    for item in keywords:
        if not isinstance(item, Mapping):
            continue

        keyword = _text_value(item.get("keyword"), limit=512)
        if not keyword:
            continue

        normalized_keyword = _text_value(
            item.get("normalized_keyword")
            or " ".join(keyword.lower().split()),
            limit=512,
        )

        row_location = _text_value(
            item.get("location") or location,
            default=DEFAULT_LOCATION,
            limit=128,
        )

        row_device = _text_value(
            item.get("device") or device,
            default=DEFAULT_DEVICE,
            limit=32,
        )

        params = {
            "id": _new_id(),
            "site_id": _text_value(site_id, limit=64),
            "provider_run_id": provider_run_id,
            "keyword": keyword,
            "normalized_keyword": normalized_keyword,
            "intent": _text_value(
                item.get("intent"),
                default="unknown",
                limit=32,
            ).lower(),
            "search_volume": item.get("search_volume"),
            "keyword_difficulty": item.get("keyword_difficulty"),
            "cpc": item.get("cpc"),
            "current_rank": item.get("current_rank"),
            "previous_rank": item.get("previous_rank"),
            "rank_change": item.get("rank_change"),
            "estimated_traffic": item.get("estimated_traffic"),
            "ranking_url": item.get("ranking_url"),
            "serp_features": _json_array(
                item.get("serp_features")
            ),
            "location": row_location,
            "language": _text_value(
                language,
                default=DEFAULT_LANGUAGE,
                limit=32,
            ),
            "device": row_device,
            "provider": _text_value(
                item.get("source") or provider,
                default=DEFAULT_PROVIDER,
                limit=64,
            ),
            "captured_date": captured,
        }

        await pg.execute(
            text("""
                INSERT INTO marketing_seo_organic_keyword_snapshots (
                    id, site_id, provider_run_id,
                    keyword, normalized_keyword,
                    intent, search_volume,
                    keyword_difficulty, cpc,
                    current_rank, ranking_url,
                    previous_rank, rank_change, estimated_traffic,
                    serp_features,
                    location, language, device,
                    provider, captured_date
                )
                VALUES (
                    :id, :site_id, :provider_run_id,
                    :keyword, :normalized_keyword,
                    :intent, :search_volume,
                    :keyword_difficulty, :cpc,
                    :current_rank, :ranking_url,
                    :previous_rank, :rank_change, :estimated_traffic,
                    CAST(:serp_features AS jsonb),
                    :location, :language, :device,
                    :provider, :captured_date
                )
                ON CONFLICT (
                    site_id, normalized_keyword,
                    location, language, device,
                    captured_date, provider
                )
                DO UPDATE SET
                    provider_run_id = EXCLUDED.provider_run_id,
                    keyword = EXCLUDED.keyword,
                    intent = EXCLUDED.intent,
                    search_volume = EXCLUDED.search_volume,
                    keyword_difficulty =
                        EXCLUDED.keyword_difficulty,
                    cpc = EXCLUDED.cpc,
                    current_rank = EXCLUDED.current_rank,
                    previous_rank = COALESCE(
                        EXCLUDED.previous_rank,
                        marketing_seo_organic_keyword_snapshots.previous_rank
                    ),
                    rank_change = COALESCE(
                        EXCLUDED.rank_change,
                        marketing_seo_organic_keyword_snapshots.rank_change
                    ),
                    estimated_traffic = COALESCE(
                        EXCLUDED.estimated_traffic,
                        marketing_seo_organic_keyword_snapshots.estimated_traffic
                    ),
                    ranking_url = EXCLUDED.ranking_url,
                    serp_features = EXCLUDED.serp_features,
                    updated_at = now()
            """),
            params,
        )

        persisted += 1

    return persisted


async def persist_competitor_snapshots(
    pg,
    *,
    site_id: str,
    competitors: Sequence[Mapping[str, Any]],
    target: str | None = None,
    provider_run_id: str | None = None,
    provider: str = DEFAULT_PROVIDER,
    captured_date: date | None = None,
    location: str = DEFAULT_LOCATION,
    language: str = DEFAULT_LANGUAGE,
    device: str = DEFAULT_DEVICE,
) -> int:
    captured = _captured_date(captured_date)
    persisted = 0
    target_domain = normalize_domain(target) if target else ""

    for item in competitors:
        if not isinstance(item, Mapping):
            continue

        domain = normalize_domain(item.get("domain"))

        if not domain:
            continue

        if target_domain and domain == target_domain:
            continue

        params = {
            "id": _new_id(),
            "site_id": _text_value(site_id, limit=64),
            "provider_run_id": provider_run_id,
            "domain": domain,
            "normalized_domain": domain,
            "avg_position": item.get("avg_position"),
            "sum_position": item.get("sum_position"),
            "intersections": item.get("intersections"),
            "target_overlap_keywords": item.get(
                "target_overlap_keywords"
            ),
            "competitor_overlap_keywords": item.get(
                "competitor_overlap_keywords"
            ),
            "competitor_total_organic_keywords": item.get(
                "competitor_total_organic_keywords"
            ),
            "competitor_estimated_traffic": item.get(
                "competitor_estimated_traffic"
            ),
            "location": _text_value(
                location,
                default=DEFAULT_LOCATION,
                limit=128,
            ),
            "language": _text_value(
                language,
                default=DEFAULT_LANGUAGE,
                limit=32,
            ),
            "device": _text_value(
                device,
                default=DEFAULT_DEVICE,
                limit=32,
            ),
            "provider": _text_value(
                item.get("source") or provider,
                default=DEFAULT_PROVIDER,
                limit=64,
            ),
            "captured_date": captured,
        }

        await pg.execute(
            text("""
                INSERT INTO marketing_seo_competitor_snapshots (
                    id, site_id, provider_run_id,
                    domain, normalized_domain,
                    avg_position, sum_position,
                    intersections,
                    target_overlap_keywords,
                    competitor_overlap_keywords,
                    competitor_total_organic_keywords,
                    competitor_estimated_traffic,
                    location, language, device,
                    provider, captured_date
                )
                VALUES (
                    :id, :site_id, :provider_run_id,
                    :domain, :normalized_domain,
                    :avg_position, :sum_position,
                    :intersections,
                    :target_overlap_keywords,
                    :competitor_overlap_keywords,
                    :competitor_total_organic_keywords,
                    :competitor_estimated_traffic,
                    :location, :language, :device,
                    :provider, :captured_date
                )
                ON CONFLICT (
                    site_id, normalized_domain,
                    captured_date, provider,
                    location, language, device
                )
                DO UPDATE SET
                    provider_run_id = EXCLUDED.provider_run_id,
                    domain = EXCLUDED.domain,
                    avg_position = EXCLUDED.avg_position,
                    sum_position = EXCLUDED.sum_position,
                    intersections = EXCLUDED.intersections,
                    target_overlap_keywords =
                        EXCLUDED.target_overlap_keywords,
                    competitor_overlap_keywords =
                        EXCLUDED.competitor_overlap_keywords,
                    competitor_total_organic_keywords =
                        EXCLUDED.competitor_total_organic_keywords,
                    competitor_estimated_traffic =
                        EXCLUDED.competitor_estimated_traffic,
                    updated_at = now()
            """),
            params,
        )

        persisted += 1

    return persisted
