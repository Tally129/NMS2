"""Marketing OS — cross-channel paid media routes (cached reads + governed sync).

GET  /marketing-os/paid/sync-status              connection/freshness per provider
GET  /marketing-os/paid/campaigns                unified cached campaign table
GET  /marketing-os/paid/{provider}/hierarchy      Meta campaign→adset→ad (cached-through, admin, explicit)
POST /marketing-os/paid/{provider}/sync           admin; dry_run default → plan; confirm → one provider read
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

from deps import api, require_roles
from postgres_db import AsyncSessionLocal

from marketing_os.routers.search import MARKETING_ROLES
from marketing_os.services.paid_sync import (
    PROVIDERS, list_cached_campaigns, plan_sync, provider_sync_status, sync_enabled, sync_provider_performance,
)

ADMIN_ROLES = ("admin",)


def _default_range() -> tuple[str, str]:
    end = date.today() - timedelta(days=1)
    return (end - timedelta(days=29)).isoformat(), end.isoformat()


@api.get("/marketing-os/paid/sync-status")
async def paid_sync_status(user=Depends(require_roles(*MARKETING_ROLES))):
    async with AsyncSessionLocal() as pg:
        items = await provider_sync_status(pg)
    return {"scheduler_enabled": sync_enabled(), "items": items}


@api.get("/marketing-os/paid/campaigns")
async def paid_campaigns(
    start_date: Optional[str] = Query(default=None), end_date: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None, description="comma-separated providers"),
    status: Optional[str] = Query(default=None), search: Optional[str] = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=500), offset: int = Query(default=0, ge=0),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    ds, de = _default_range()
    providers = [p.strip() for p in provider.split(",")] if provider else None
    if providers and any(p not in PROVIDERS for p in providers):
        raise HTTPException(status_code=422, detail=f"provider must be in {list(PROVIDERS)}")
    try:
        async with AsyncSessionLocal() as pg:
            return await list_cached_campaigns(pg, start_date=start_date or ds, end_date=end_date or de, providers=providers,
                                               status=status, search=search, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


class SyncRequest(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    dry_run: bool = True
    confirm: bool = False


@api.post("/marketing-os/paid/{provider}/sync")
async def paid_provider_sync(provider: str, body: SyncRequest, user=Depends(require_roles(*ADMIN_ROLES))):
    if provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail="unknown provider")
    ds, de = _default_range()
    try:
        plan = plan_sync(provider=provider, start_date=body.start_date or ds, end_date=body.end_date or de)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if body.dry_run or not body.confirm:
        return {"status": "dry_run", "live": False, "plan": plan, "note": "No provider call made. Send dry_run=false and confirm=true to sync."}
    if not plan["provider_ready"]:
        raise HTTPException(status_code=409, detail=f"{provider} not ready: {plan['provider_readiness']}")
    async with AsyncSessionLocal() as pg:
        result = await sync_provider_performance(pg, plan=plan, actor={"id": (user or {}).get("id"), "email": (user or {}).get("email")})
    return {**result, "live": True}


@api.get("/marketing-os/paid/meta_ads/hierarchy")
async def meta_hierarchy(user=Depends(require_roles(*ADMIN_ROLES))):
    """Explicit admin read of the live Meta hierarchy (3 provider requests).
    Not used by dashboard loads."""
    from marketing_os.integrations.meta_ads import MetaAdsError, MetaAdsIntegration, credential_readiness
    if not credential_readiness().get("connected"):
        raise HTTPException(status_code=409, detail="meta_ads not connected")
    adapter = MetaAdsIntegration()
    try:
        campaigns, adsets, ads = await adapter.fetch_campaigns(), await adapter.fetch_adsets(), await adapter.fetch_ads()
    except MetaAdsError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    by_campaign = {c["id"]: {**c, "adsets": []} for c in campaigns}
    by_adset = {}
    for a in adsets:
        node = {**a, "ads": []}; by_adset[a["id"]] = node
        by_campaign.get(str(a.get("campaign_id")), {}).setdefault("adsets", []).append(node)
    for ad in ads:
        by_adset.get(str(ad.get("adset_id")), {}).setdefault("ads", []).append(ad)
    return {"provider": "meta_ads", "campaigns": list(by_campaign.values()), "counts": {"campaigns": len(campaigns), "adsets": len(adsets), "ads": len(ads)}}
