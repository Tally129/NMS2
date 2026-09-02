"""Provider-neutral normalization for paid-media read-only performance.

Canonical campaign/performance fields shared by google_ads, meta_ads and
microsoft_ads. Unavailable metrics stay None (never fabricated as zero).
Derived rates (ctr/cpc/cpl/cpa/roas) are computed only when their inputs
exist. No PHI, no writes.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

CANONICAL_FIELDS = (
    "provider", "account_id", "campaign_id", "campaign_name",
    "campaign_type", "status", "objective", "daily_budget", "spend",
    "impressions", "clicks", "ctr", "cpc", "leads", "cpl", "conversions",
    "cpa", "revenue", "roas", "metric_date",
)


def _dec(v: Any) -> Optional[Decimal]:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _rate(num: Optional[Decimal], den: Optional[Decimal]) -> Optional[float]:
    if num is None or den in (None, 0, Decimal(0)):
        return None
    return round(float(num) / float(den), 6)


def normalize_campaign_row(provider: str, row: dict) -> dict:
    """Map a provider row into the canonical, provider-neutral shape."""
    spend = _dec(row.get("spend"))
    impressions = _int(row.get("impressions"))
    clicks = _int(row.get("clicks"))
    leads = _int(row.get("leads"))
    conversions = _int(row.get("conversions"))
    revenue = _dec(row.get("revenue"))

    ctr = row.get("ctr")
    ctr = float(ctr) if ctr is not None else _rate(
        Decimal(clicks) if clicks is not None else None,
        Decimal(impressions) if impressions is not None else None)
    cpc = _rate(spend, Decimal(clicks) if clicks else None)
    cpl = _rate(spend, Decimal(leads) if leads else None)
    cpa = _rate(spend, Decimal(conversions) if conversions else None)
    # ROAS only when real revenue/attribution exists.
    roas = _rate(revenue, spend) if revenue is not None else None

    return {
        "provider": provider,
        "account_id": row.get("account_id"),
        "campaign_id": row.get("campaign_id"),
        "campaign_name": row.get("campaign_name"),
        "campaign_type": row.get("campaign_type"),
        "status": row.get("status"),
        "objective": row.get("objective"),
        "daily_budget": (
            float(_dec(row.get("daily_budget")))
            if row.get("daily_budget") is not None else None),
        "spend": float(spend) if spend is not None else None,
        "impressions": impressions,
        "clicks": clicks,
        "ctr": ctr,
        "cpc": cpc,
        "leads": leads,
        "cpl": cpl,
        "conversions": conversions,
        "cpa": cpa,
        "revenue": float(revenue) if revenue is not None else None,
        "roas": roas,
        "metric_date": row.get("metric_date"),
    }
