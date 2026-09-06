"""Governed paid-media synchronization + cached cross-channel reads.

* ``sync_provider_performance`` — ONE controlled provider read (Google /
  Meta / Microsoft) for a date range, normalized onto the shared schema and
  persisted idempotently into ``marketing_daily_metrics`` (provider-specific
  metrics preserved in ``raw_metrics``). Updates ``marketing_channel_accounts
  .last_sync_at`` and audit-logs the run. Never called on dashboard loads.
* ``list_cached_campaigns`` — unified campaign table from the cache.
* ``provider_sync_status`` — freshness / last sync / error per provider.
* ``run_due_paid_syncs`` — scheduler tick, opt-in via
  ``PAID_MEDIA_SYNC_ENABLED`` (default false), daily cadence, advisory lock.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text

from marketing_os.services.performance import persist_daily_performance

logger = logging.getLogger("marketing_os.paid_sync")

PROVIDERS = ("google_ads", "meta_ads", "microsoft_ads")
SYNC_ENABLED_ENV = "PAID_MEDIA_SYNC_ENABLED"
SYNC_LOCK_KEY = 7_420_026_002
MAX_RANGE_DAYS = 93
# Persisted rows exclude provider-specific columns the shared table lacks;
# they live in raw_metrics instead.
_RAW_KEYS = ("campaign_type", "status", "objective", "daily_budget", "ctr", "cpc", "cpl", "cpa", "roas", "level",
             "adset_id", "adset_name", "ad_id", "ad_name", "raw", "account_id")


def build_adapter(provider: str, account: dict | None = None):
    if provider == "google_ads":
        from marketing_os.integrations.google_ads import GoogleAdsIntegration
        return GoogleAdsIntegration(account=account) if account else GoogleAdsIntegration()
    if provider == "meta_ads":
        from marketing_os.integrations.meta_ads import MetaAdsIntegration
        return MetaAdsIntegration(account=account)
    if provider == "microsoft_ads":
        from marketing_os.integrations.microsoft_ads import MicrosoftAdsIntegration
        return MicrosoftAdsIntegration(account=account)
    raise ValueError(f"unsupported provider: {provider}")


def provider_readiness(provider: str) -> dict:
    if provider == "google_ads":
        from marketing_os.integrations.google_ads import credential_readiness
        r = credential_readiness()
        return {"provider": provider, "connected": bool(r.get("required_configured")), "status": "connected" if r.get("required_configured") else "not_connected"}
    if provider == "meta_ads":
        from marketing_os.integrations.meta_ads import credential_readiness
        return credential_readiness()
    if provider == "microsoft_ads":
        from marketing_os.integrations.microsoft_ads import credential_readiness
        return credential_readiness()
    raise ValueError(f"unsupported provider: {provider}")


def validate_range(start_date: str, end_date: str) -> tuple[date, date]:
    s, e = date.fromisoformat(str(start_date)[:10]), date.fromisoformat(str(end_date)[:10])
    if e < s:
        raise ValueError("end_date before start_date")
    if (e - s).days > MAX_RANGE_DAYS:
        raise ValueError(f"date range exceeds {MAX_RANGE_DAYS} days")
    if e > date.today():
        raise ValueError("end_date is in the future")
    return s, e


def plan_sync(*, provider: str, start_date: str, end_date: str) -> dict:
    if provider not in PROVIDERS:
        raise ValueError(f"unsupported provider: {provider}")
    s, e = validate_range(start_date, end_date)
    readiness = provider_readiness(provider)
    return {"provider": provider, "start_date": s.isoformat(), "end_date": e.isoformat(), "days": (e - s).days + 1,
            "writes_postgresql": True, "tables": ["marketing_daily_metrics", "marketing_channel_accounts.last_sync_at"],
            "provider_ready": bool(readiness.get("connected")), "provider_readiness": readiness.get("status"),
            "external_write": False, "estimated_provider_requests": 1 if provider != "microsoft_ads" else "1 submit + polls + 1 download"}


async def _account_row(pg, provider: str) -> Optional[dict]:
    row = (await pg.execute(text("""
        SELECT id, provider, external_account_id, account_name, status, currency, timezone, read_enabled, write_enabled, last_sync_at, configuration
        FROM marketing_channel_accounts WHERE lower(provider) = :p ORDER BY created_at DESC LIMIT 1"""), {"p": provider})).mappings().first()
    return dict(row) if row else None


async def sync_provider_performance(pg, *, plan: dict, adapter=None, actor: dict | None = None, trigger: str = "manual") -> dict:
    provider = plan["provider"]
    started = datetime.now(timezone.utc)
    account = await _account_row(pg, provider)
    status, error, rows_in, rows_stored = "completed", None, 0, 0
    try:
        adapter = adapter or build_adapter(provider, account)
        payload = await adapter.fetch_performance(start_date=plan["start_date"], end_date=plan["end_date"])
        rows = payload.get("rows") or []
        rows_in = len(rows)
        for r in rows:
            if not r.get("campaign_id"):
                continue
            raw = {k: r.get(k) for k in _RAW_KEYS if r.get(k) is not None}
            await persist_daily_performance(pg, {
                "provider": provider, "external_campaign_id": str(r["campaign_id"]),
                "metric_date": r.get("metric_date") or plan["end_date"],
                "channel_account_id": (account or {}).get("id"), "campaign_name": r.get("campaign_name"),
                "impressions": r.get("impressions"), "clicks": r.get("clicks"), "spend": r.get("spend"),
                "leads": r.get("leads"), "conversions": r.get("conversions"), "conversion_value": r.get("revenue"),
                "raw_metrics": raw,
            })
            rows_stored += 1
        if account:
            await pg.execute(text("UPDATE marketing_channel_accounts SET last_sync_at = :now, updated_at = now() WHERE id = :id"),
                             {"now": started, "id": account["id"]})
        await pg.commit()
    except Exception as exc:
        try:
            await pg.rollback()
        except Exception:
            logger.exception("rollback after failed paid sync")
        status, error = "error", f"{type(exc).__name__}: {str(exc)[:300]}"
    finished = datetime.now(timezone.utc)
    try:
        from audit import log_audit
        await log_audit(None, (actor or {}).get("id"), (actor or {}).get("email"), "marketing_os.paid.provider_sync",
                        resource_type="paid_provider_sync", resource_id=provider, severity="info" if status == "completed" else "warning",
                        outcome="success" if status == "completed" else "failure",
                        metadata={"trigger": trigger, "start_date": plan["start_date"], "end_date": plan["end_date"],
                                  "rows_received": rows_in, "rows_stored": rows_stored, "error": error})
    except Exception:
        logger.exception("paid sync audit write failed")
    return {"status": status, "error": error, "trigger": trigger, "plan": plan, "rows_received": rows_in, "rows_stored": rows_stored,
            "external_write": False, "started_at": started.isoformat(), "finished_at": finished.isoformat()}


async def provider_sync_status(pg) -> list[dict]:
    out = []
    for provider in PROVIDERS:
        account = await _account_row(pg, provider)
        fresh = (await pg.execute(text("""
            SELECT MAX(metric_date) AS latest_metric_date, MAX(updated_at) AS last_written_at, COUNT(DISTINCT external_campaign_id) AS campaigns,
                   COUNT(*) AS rows FROM marketing_daily_metrics WHERE provider = :p"""), {"p": provider})).mappings().first()
        readiness = provider_readiness(provider)
        latest = fresh["latest_metric_date"] if fresh else None
        out.append({"provider": provider, "connected": bool(readiness.get("connected")), "readiness": readiness.get("status"),
                    "account": {k: account.get(k) for k in ("external_account_id", "account_name", "currency", "read_enabled", "write_enabled")} if account else None,
                    "last_successful_sync": account.get("last_sync_at").isoformat() if account and account.get("last_sync_at") else None,
                    "latest_metric_date": latest.isoformat() if latest else None,
                    "data_age_days": (date.today() - latest).days if latest else None,
                    "cached_campaigns": int(fresh["campaigns"]) if fresh else 0, "cached_rows": int(fresh["rows"]) if fresh else 0})
    return out


async def list_cached_campaigns(pg, *, start_date: str, end_date: str, providers: list[str] | None = None, status: str | None = None,
                                search: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    s, e = validate_range(start_date, end_date)
    limit = max(1, min(int(limit), 500)); offset = max(0, int(offset))
    params: dict[str, Any] = {"s": s, "e": e, "limit": limit, "offset": offset}
    where = ["metric_date BETWEEN :s AND :e"]
    if providers:
        where.append("provider = ANY(:providers)"); params["providers"] = [p for p in providers if p in PROVIDERS]
    if search:
        where.append("campaign_name ILIKE :q"); params["q"] = f"%{search.strip()}%"
    where_sql = " AND ".join(where)
    sql = f"""
        WITH agg AS (
            SELECT provider, external_campaign_id, MAX(campaign_name) AS campaign_name,
                   SUM(impressions) AS impressions, SUM(clicks) AS clicks, SUM(spend) AS spend, SUM(leads) AS leads,
                   SUM(conversions) AS conversions, SUM(conversion_value) AS conversion_value, MAX(updated_at) AS last_updated,
                   (ARRAY_AGG(raw_metrics ORDER BY metric_date DESC))[1] AS latest_raw
            FROM marketing_daily_metrics WHERE {where_sql}
            GROUP BY provider, external_campaign_id)
        SELECT * FROM agg {"WHERE COALESCE(latest_raw->>'status','') ILIKE :status" if status else ""}
        ORDER BY spend DESC NULLS LAST, campaign_name LIMIT :limit OFFSET :offset"""
    if status:
        params["status"] = f"%{status}%"
    rows = (await pg.execute(text(sql), params)).mappings().all()
    total_sql = f"""SELECT COUNT(*) FROM (SELECT provider, external_campaign_id, (ARRAY_AGG(raw_metrics ORDER BY metric_date DESC))[1] AS latest_raw
                     FROM marketing_daily_metrics WHERE {where_sql} GROUP BY provider, external_campaign_id) t
                     {"WHERE COALESCE(latest_raw->>'status','') ILIKE :status" if status else ""}"""
    total = (await pg.execute(text(total_sql), params)).scalar() or 0
    items = []
    for r in rows:
        d = dict(r); raw = d.pop("latest_raw") or {}
        spend, clicks, imps, conv, value = (float(d.get("spend") or 0), int(d.get("clicks") or 0), int(d.get("impressions") or 0),
                                            float(d.get("conversions") or 0), float(d.get("conversion_value") or 0))
        items.append({"provider": d["provider"], "campaign_id": d["external_campaign_id"], "campaign_name": d["campaign_name"],
                      "status": raw.get("status"), "campaign_type": raw.get("campaign_type"), "objective": raw.get("objective"),
                      "daily_budget": raw.get("daily_budget"), "spend": spend, "impressions": imps, "clicks": clicks,
                      "ctr": (clicks / imps) if imps else None, "cpc": (spend / clicks) if clicks else None,
                      "conversions": conv, "cpa": (spend / conv) if conv else None, "conversion_value": value,
                      "roas": (value / spend) if spend and value else None, "leads": float(d.get("leads") or 0),
                      "last_updated": d["last_updated"].isoformat() if d.get("last_updated") else None,
                      "provider_metrics": raw.get("raw")})
    return {"items": items, "total": int(total), "limit": limit, "offset": offset, "has_more": offset + len(items) < int(total),
            "start_date": s.isoformat(), "end_date": e.isoformat()}


def sync_enabled() -> bool:
    return (os.environ.get(SYNC_ENABLED_ENV) or "false").strip().lower() in {"1", "true", "yes"}


async def run_due_paid_syncs(session_factory=None, *, adapters: dict | None = None, now: datetime | None = None, lookback_days: int = 3) -> dict:
    """Daily tick: for each connected provider whose last sync is older than
    ~20h, sync the trailing ``lookback_days`` window (idempotent upserts)."""
    now = now or datetime.now(timezone.utc)
    summary: dict[str, Any] = {"enabled": sync_enabled(), "ran": [], "skipped": []}
    if not summary["enabled"]:
        summary["reason"] = f"{SYNC_ENABLED_ENV} is not true"; return summary
    if session_factory is None:
        from postgres_db import AsyncSessionLocal as session_factory  # type: ignore
    async with session_factory() as pg:
        if not (await pg.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": SYNC_LOCK_KEY})).scalar():
            summary["reason"] = "another sync tick holds the lock"; return summary
        try:
            for provider in PROVIDERS:
                if not provider_readiness(provider).get("connected"):
                    summary["skipped"].append({"provider": provider, "reason": "not_connected"}); continue
                account = await _account_row(pg, provider)
                last = account.get("last_sync_at") if account else None
                if last and (now - last) < timedelta(hours=20):
                    summary["skipped"].append({"provider": provider, "reason": "fresh"}); continue
                end = (now - timedelta(days=1)).date(); start = end - timedelta(days=lookback_days - 1)
                plan = plan_sync(provider=provider, start_date=start.isoformat(), end_date=end.isoformat())
                out = await sync_provider_performance(pg, plan=plan, adapter=(adapters or {}).get(provider), trigger="scheduled")
                summary["ran"].append({"provider": provider, "status": out["status"], "rows_stored": out["rows_stored"], "error": out["error"]})
        finally:
            await pg.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": SYNC_LOCK_KEY}); await pg.commit()
    return summary
