"""Marketing OS — unified Lead → Appointment → Revenue attribution API.

Read-only, deterministic, PHI-free. Reads marketing-safe conversion events
and aggregate spend rows; performs no external writes and no clinical reads.
"""
from __future__ import annotations

from fastapi import Depends, Query
from sqlalchemy import text

from deps import api, require_roles
from postgres_db import AsyncSessionLocal
from marketing_os.services.journey import (
    attribute_outcome,
    build_attribution_overview,
    build_journeys,
    compute_channel_economics,
    compute_funnel,
    compute_revenue,
)

MARKETING_ROLES = ("admin", "practitioner")
ATTRIBUTION_MODELS = ("first_touch", "last_touch")


async def _load_events() -> list[dict]:
    async with AsyncSessionLocal() as pg:
        result = await pg.execute(
            text(
                """
                SELECT
                    event_type,
                    occurred_at,
                    marketing_subject_id,
                    source,
                    medium,
                    campaign,
                    value,
                    properties
                FROM marketing_conversion_events
                ORDER BY occurred_at ASC
                """
            )
        )
        return [dict(row._mapping) for row in result]


async def _load_spend_rows() -> list[dict]:
    async with AsyncSessionLocal() as pg:
        result = await pg.execute(
            text(
                """
                SELECT provider, spend
                FROM marketing_daily_metrics
                """
            )
        )
        return [dict(row._mapping) for row in result]


def _model(model: str) -> str:
    return model if model in ATTRIBUTION_MODELS else "last_touch"


@api.get("/marketing-os/attribution/overview")
async def attribution_overview(
    model: str = Query("last_touch"),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    del user
    events = await _load_events()
    spend_rows = await _load_spend_rows()
    return build_attribution_overview(events, spend_rows, model=_model(model))


@api.get("/marketing-os/attribution/funnel")
async def attribution_funnel(
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    del user
    events = await _load_events()
    return compute_funnel(events)


@api.get("/marketing-os/attribution/channels")
async def attribution_channels(
    model: str = Query("last_touch"),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    del user
    events = await _load_events()
    spend_rows = await _load_spend_rows()
    return compute_channel_economics(events, spend_rows, model=_model(model))


@api.get("/marketing-os/attribution/campaigns")
async def attribution_campaigns(
    model: str = Query("last_touch"),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    del user
    events = await _load_events()
    resolved = _model(model)
    return {
        "attribution_model": resolved,
        "booked": attribute_outcome(
            events, outcome_stage="appointment_booked",
            model=resolved, dimension="campaign",
        ),
        "completed": attribute_outcome(
            events, outcome_stage="appointment_completed",
            model=resolved, dimension="campaign",
        ),
        "revenue": compute_revenue(events, model=resolved).get("by_campaign"),
    }


@api.get("/marketing-os/attribution/revenue")
async def attribution_revenue(
    model: str = Query("last_touch"),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    del user
    events = await _load_events()
    return compute_revenue(events, model=_model(model))


@api.get("/marketing-os/attribution/journeys")
async def attribution_journeys(
    limit: int = Query(100, ge=1, le=500),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    del user
    events = await _load_events()
    journeys = build_journeys(events)
    return {
        "count": len(journeys),
        "journeys": journeys[:limit],
        "phi_used": False,
    }
