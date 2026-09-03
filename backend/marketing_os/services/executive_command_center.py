"""Phase 13 Executive Marketing Command Center.

Pure aggregation / presentation logic.

This module:
- performs no database access
- performs no network access
- performs no AI calls
- performs no external execution
- consumes only business-safe marketing aggregates
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Optional


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int:
    number = _number(value)
    if number is None:
        return 0
    return int(number)


def _money(value: Any) -> Optional[float]:
    number = _number(value)
    if number is None:
        return None
    return round(number, 2)


def _rate(value: Any) -> Optional[float]:
    number = _number(value)
    if number is None:
        return None
    return round(number, 6)


def _safe_text(value: Any, limit: int = 200) -> str:
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _first_number(
    source: Mapping[str, Any],
    *keys: str,
) -> Optional[float]:
    for key in keys:
        value = _number(source.get(key))
        if value is not None:
            return value
    return None


def _sum_metric(
    rows: Iterable[Mapping[str, Any]],
    *keys: str,
) -> Optional[float]:
    total = 0.0
    seen = False

    for row in rows or []:
        if not isinstance(row, Mapping):
            continue

        value = _first_number(row, *keys)
        if value is not None:
            total += value
            seen = True

    if not seen:
        return None

    return total


def _ratio(
    numerator: Optional[float],
    denominator: Optional[float],
) -> Optional[float]:
    if numerator is None or denominator is None:
        return None
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def build_executive_kpis(
    *,
    paid_media: Iterable[Mapping[str, Any]],
    funnel: Mapping[str, Any],
    revenue: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    paid_rows = [
        row
        for row in paid_media or []
        if isinstance(row, Mapping)
    ]

    revenue = revenue or {}

    spend = _sum_metric(
        paid_rows,
        "spend",
        "cost",
    )

    leads = _first_number(
        funnel,
        "leads",
        "lead_count",
        "total_leads",
    )

    conversions = _first_number(
        funnel,
        "conversions",
        "completed",
        "completed_appointments",
    )

    attributed_revenue = _first_number(
        revenue,
        "revenue",
        "total_revenue",
        "attributed_revenue",
    )

    if attributed_revenue is None:
        attributed_revenue = _sum_metric(
            paid_rows,
            "revenue",
            "attributed_revenue",
        )

    cpl = _ratio(
        spend,
        leads,
    )

    cpa = _ratio(
        spend,
        conversions,
    )

    roas = _ratio(
        attributed_revenue,
        spend,
    )

    return {
        "spend": _money(spend),
        "leads": (
            int(leads)
            if leads is not None
            else None
        ),
        "conversions": (
            int(conversions)
            if conversions is not None
            else None
        ),
        "cpl": _money(cpl),
        "cac_cpa": _money(cpa),
        "revenue": _money(attributed_revenue),
        "roas": (
            round(roas, 4)
            if roas is not None
            else None
        ),
        "data_policy": {
            "unknown_values_are_null": True,
            "synthetic_revenue_used": False,
        },
    }


def build_growth_funnel(
    funnel: Mapping[str, Any],
) -> dict[str, Any]:
    leads = _first_number(
        funnel,
        "leads",
        "lead_count",
        "total_leads",
    )

    requests = _first_number(
        funnel,
        "appointment_requests",
        "requested",
        "requests",
    )

    booked = _first_number(
        funnel,
        "booked",
        "booked_appointments",
    )

    completed = _first_number(
        funnel,
        "completed",
        "completed_appointments",
    )

    no_show = _first_number(
        funnel,
        "no_show",
        "no_shows",
    )

    return {
        "leads": int(leads) if leads is not None else None,
        "appointment_requests": (
            int(requests)
            if requests is not None
            else None
        ),
        "booked": (
            int(booked)
            if booked is not None
            else None
        ),
        "completed": (
            int(completed)
            if completed is not None
            else None
        ),
        "no_show": (
            int(no_show)
            if no_show is not None
            else None
        ),
        "lead_to_request_rate": _rate(
            _ratio(requests, leads)
        ),
        "request_to_booking_rate": _rate(
            _ratio(booked, requests)
        ),
        "booking_to_completion_rate": _rate(
            _ratio(completed, booked)
        ),
    }


def build_channel_health(
    paid_media: Iterable[Mapping[str, Any]],
    director_signals: Mapping[str, Any],
) -> list[dict[str, Any]]:
    signals = director_signals.get("signals") or []

    health = []

    for row in paid_media or []:
        if not isinstance(row, Mapping):
            continue

        provider = _safe_text(
            row.get("provider")
            or row.get("channel")
            or row.get("platform")
            or "unknown",
            64,
        ).lower()

        provider_signals = [
            signal
            for signal in signals
            if isinstance(signal, Mapping)
            and signal.get("category") == "paid_media"
            and str(
                (signal.get("evidence") or {}).get("provider")
                or ""
            ).lower() == provider
        ]

        highest_priority = max(
            (
                _integer(signal.get("priority"))
                for signal in provider_signals
            ),
            default=0,
        )

        status = "healthy"

        if highest_priority >= 80:
            status = "critical"
        elif highest_priority >= 60:
            status = "needs_attention"
        elif provider_signals:
            status = "monitor"

        health.append({
            "channel": provider,
            "status": status,
            "spend": _money(row.get("spend")),
            "ctr": _rate(row.get("ctr")),
            "cpc": _money(row.get("cpc")),
            "cpl": _money(row.get("cpl")),
            "cpa": _money(row.get("cpa")),
            "roas": (
                round(_number(row.get("roas")), 4)
                if _number(row.get("roas")) is not None
                else None
            ),
            "signal_count": len(provider_signals),
            "highest_priority": highest_priority,
        })

    # Add non-paid channel categories from Director signals.
    category_map = {
        "search": "seo_search",
        "local_growth": "local_reputation",
        "content": "content",
    }

    for category, channel_name in category_map.items():
        category_signals = [
            signal
            for signal in signals
            if isinstance(signal, Mapping)
            and signal.get("category") == category
        ]

        highest_priority = max(
            (
                _integer(signal.get("priority"))
                for signal in category_signals
            ),
            default=0,
        )

        if highest_priority >= 80:
            status = "critical"
        elif highest_priority >= 60:
            status = "needs_attention"
        elif category_signals:
            status = "monitor"
        else:
            status = "no_signal"

        health.append({
            "channel": channel_name,
            "status": status,
            "signal_count": len(category_signals),
            "highest_priority": highest_priority,
        })

    return health


def build_pipeline_health(
    lead_operations: Mapping[str, Any],
) -> dict[str, Any]:
    overdue = _integer(
        lead_operations.get("overdue_leads")
    )

    if overdue is None:
        overdue = _integer(
            lead_operations.get("overdue")
        )

    no_show = _integer(
        lead_operations.get("no_show")
    )

    if no_show is None:
        no_show = _integer(
            lead_operations.get("no_shows")
        )

    return {
        "needs_attention": _integer(
            lead_operations.get("needs_attention")
        ),
        "overdue_followups": overdue,
        "no_show_recovery": no_show,
    }


def build_director_snapshot(
    director_signals: Mapping[str, Any],
    director_summary: Mapping[str, Any],
) -> dict[str, Any]:
    signals = director_signals.get("signals") or []
    summary = director_signals.get("summary") or {}

    top = [
        signal
        for signal in signals[:8]
        if isinstance(signal, Mapping)
    ]

    return {
        "signal_count": _integer(
            summary.get("total")
        ),
        "high_priority_count": _integer(
            summary.get("high_priority")
        ),
        "executive_summary": _safe_text(
            director_summary.get("executive_summary"),
            2000,
        ),
        "summary_source": _safe_text(
            director_summary.get("source")
            or "deterministic",
            32,
        ),
        "top_actions": [
            {
                "signal_key": _safe_text(
                    signal.get("signal_key"),
                    200,
                ),
                "title": _safe_text(
                    signal.get("title"),
                    300,
                ),
                "priority": _integer(
                    signal.get("priority")
                ),
                "severity": _safe_text(
                    signal.get("severity"),
                    24,
                ),
                "category": _safe_text(
                    signal.get("category"),
                    64,
                ),
                "recommended_action": _safe_text(
                    signal.get("recommended_action"),
                    1000,
                ),
                "confidence": _safe_text(
                    signal.get("confidence"),
                    32,
                ),
                "data_quality": _safe_text(
                    signal.get("data_quality"),
                    32,
                ),
            }
            for signal in top
        ],
    }


def build_executive_command_center(
    *,
    paid_media: Iterable[Mapping[str, Any]],
    funnel: Mapping[str, Any],
    lead_operations: Mapping[str, Any],
    director_signals: Mapping[str, Any],
    director_summary: Mapping[str, Any],
    revenue: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "executive_kpis": build_executive_kpis(
            paid_media=paid_media,
            funnel=funnel,
            revenue=revenue,
        ),
        "growth_funnel": build_growth_funnel(
            funnel,
        ),
        "channel_health": build_channel_health(
            paid_media,
            director_signals,
        ),
        "pipeline_health": build_pipeline_health(
            lead_operations,
        ),
        "marketing_director": build_director_snapshot(
            director_signals,
            director_summary,
        ),
        "safety": {
            "read_only": True,
            "advisory_only": True,
            "automatic_execution": False,
            "human_approval_required": True,
            "external_execution_allowed": False,
            "phi_used": False,
        },
    }


__all__ = [
    "build_executive_kpis",
    "build_growth_funnel",
    "build_channel_health",
    "build_pipeline_health",
    "build_director_snapshot",
    "build_executive_command_center",
]
