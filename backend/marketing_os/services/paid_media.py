"""Provider-neutral, read-only paid-media overview service.

Aggregates locally-stored normalized daily performance for the paid
advertising channels (google_ads, meta_ads, microsoft_ads) and combines
it with each provider's credential readiness.

Safety:
- read-only; performs no external provider calls;
- no campaign, budget, bid, audience, or publishing mutation;
- unavailable metrics stay ``None`` and are never fabricated as zero;
- a channel with no stored performance rows reports ``has_data = False``
  with null metrics (honest empty state), never invented numbers.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Optional

from marketing_os.integrations import google_ads, meta_ads, microsoft_ads

PAID_PROVIDERS: tuple[str, ...] = (
    "google_ads",
    "meta_ads",
    "microsoft_ads",
)

DISPLAY_NAMES: dict[str, str] = {
    "google_ads": "Google Ads",
    "meta_ads": "Meta Ads",
    "microsoft_ads": "Microsoft Advertising",
}

METRIC_FIELDS: tuple[str, ...] = (
    "spend",
    "impressions",
    "clicks",
    "ctr",
    "conversions",
    "cpa",
    "roas",
)


def _dec(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _rate(
    numerator: Optional[Decimal],
    denominator: Optional[Decimal],
) -> Optional[float]:
    if numerator is None or denominator in (None, 0, Decimal(0)):
        return None
    return round(float(numerator) / float(denominator), 6)


def provider_readiness(provider: str) -> dict[str, Any]:
    """Return a provider-neutral readiness shape without any network call."""

    if provider == "google_ads":
        raw = google_ads.credential_readiness()
        missing = raw.get("missing_required") or []
        present = len(google_ads._REQUIRED_ENV) - len(missing)
        if not missing:
            status = "connected"
        elif present <= 0:
            status = "not_connected"
        else:
            status = "configuration_incomplete"
        return {
            "provider": provider,
            "status": status,
            "connected": status == "connected",
            "account_configured": bool(
                raw.get("login_customer_id_configured")
            ),
            "credentials_present": present > 0,
            "read_only": True,
            "external_write": False,
        }

    if provider == "meta_ads":
        raw = meta_ads.credential_readiness()
    elif provider == "microsoft_ads":
        raw = microsoft_ads.credential_readiness()
    else:
        return {
            "provider": provider,
            "status": "unknown_provider",
            "connected": False,
            "account_configured": False,
            "credentials_present": False,
            "read_only": True,
            "external_write": False,
        }

    return {
        "provider": provider,
        "status": raw.get("status", "not_connected"),
        "connected": bool(raw.get("connected")),
        "account_configured": bool(raw.get("account_configured")),
        "credentials_present": bool(raw.get("credentials_present")),
        "read_only": True,
        "external_write": False,
    }


def _aggregate_metrics(
    rows: list[Mapping[str, Any]],
) -> Optional[dict[str, Any]]:
    """Aggregate stored daily rows for one provider.

    Returns ``None`` when there are no rows (honest empty state).
    Derived rates stay ``None`` when their inputs are missing/zero.
    """

    if not rows:
        return None

    spend = Decimal(0)
    impressions = 0
    clicks = 0
    conversions = Decimal(0)
    revenue = Decimal(0)

    for row in rows:
        spend += _dec(row.get("spend")) or Decimal(0)
        conversions += _dec(row.get("conversions")) or Decimal(0)
        revenue += _dec(row.get("conversion_value")) or Decimal(0)
        try:
            impressions += int(row.get("impressions") or 0)
        except (TypeError, ValueError):
            pass
        try:
            clicks += int(row.get("clicks") or 0)
        except (TypeError, ValueError):
            pass

    ctr = _rate(
        Decimal(clicks) if clicks else None,
        Decimal(impressions) if impressions else None,
    )
    cpa = _rate(spend, conversions if conversions else None)
    # ROAS only when real attributed revenue and spend both exist.
    roas = (
        _rate(revenue, spend)
        if (revenue > 0 and spend > 0)
        else None
    )

    return {
        "spend": float(spend),
        "impressions": impressions,
        "clicks": clicks,
        "ctr": ctr,
        "conversions": float(conversions),
        "cpa": cpa,
        "roas": roas,
    }


def build_paid_media_overview(
    rows: Iterable[Mapping[str, Any]] = (),
    *,
    readiness_overrides: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    """Build the read-only cross-channel paid-media overview.

    ``rows`` are locally-stored normalized daily metric rows; each row
    must carry a ``provider`` key. Providers with no rows report honest
    empty metrics (``None``).
    """

    grouped: dict[str, list[Mapping[str, Any]]] = {
        provider: [] for provider in PAID_PROVIDERS
    }

    for row in rows:
        provider = str(row.get("provider") or "").strip().lower()
        if provider in grouped:
            grouped[provider].append(row)

    providers: list[dict[str, Any]] = []

    for provider in PAID_PROVIDERS:
        if readiness_overrides and provider in readiness_overrides:
            readiness = dict(readiness_overrides[provider])
        else:
            readiness = provider_readiness(provider)

        metrics = _aggregate_metrics(grouped[provider])
        has_data = metrics is not None

        if has_data:
            note = "Showing locally stored normalized performance."
        elif readiness.get("connected"):
            note = (
                "Connected. No normalized performance data has been "
                "synced yet."
            )
        else:
            note = (
                "Not connected. No performance data available — metrics "
                "are unknown, not zero."
            )

        providers.append(
            {
                "provider": provider,
                "display_name": DISPLAY_NAMES.get(provider, provider),
                "readiness": readiness,
                "connected": bool(readiness.get("connected")),
                "has_data": has_data,
                "metrics": metrics,
                "note": note,
            }
        )

    return {
        "read_only": True,
        "external_writes_enabled": False,
        "automatic_budget_changes_enabled": False,
        "automatic_campaign_creation_enabled": False,
        "human_approval_required": True,
        "providers": providers,
    }


def paid_performance_signals(
    overview: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Extract channel performance signals ONLY for channels with data.

    Disconnected or empty channels contribute no signal, so the Director
    never generates performance recommendations for them.
    """

    signals: list[dict[str, Any]] = []

    for entry in overview.get("providers", []):
        if not entry.get("has_data"):
            continue

        metrics = entry.get("metrics") or {}
        signals.append(
            {
                "channel": entry.get("provider"),
                "impressions": metrics.get("impressions") or 0,
                "clicks": metrics.get("clicks") or 0,
                "conversions": metrics.get("conversions") or 0,
                "spend": metrics.get("spend") or 0,
                "revenue": (
                    (metrics.get("roas") or 0)
                    * (metrics.get("spend") or 0)
                ),
            }
        )

    return signals
