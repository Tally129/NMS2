"""Marketing OS — provider-neutral paid-media readiness API (read-only).

Exposes readiness + registered providers for google_ads / meta_ads /
microsoft_ads plus a unified read-only performance overview. Reuses
existing auth. No external writes.
"""
from __future__ import annotations

from fastapi import Depends
from sqlalchemy import text

from deps import api, require_roles
from postgres_db import AsyncSessionLocal
from marketing_os.integrations.bootstrap import register_default_integrations
from marketing_os.integrations.registry import registered_providers
from marketing_os.services.paid_media import (
    PAID_PROVIDERS,
    build_paid_media_overview,
    provider_readiness,
)

MARKETING_ROLES = ("admin", "practitioner")


@api.get("/marketing-os/paid/providers")
async def paid_providers(user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    # Idempotent, local-only registration (no network). Kept out of module
    # import time so importing this router never mutates the global registry.
    register_default_integrations()
    return {
        "registered": list(registered_providers()),
        "providers": {p: provider_readiness(p) for p in PAID_PROVIDERS},
        "external_writes_enabled": False,
        "human_approval_required": True,
    }


@api.get("/marketing-os/paid/{provider}/readiness")
async def paid_readiness(provider: str,
                         user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    if provider not in PAID_PROVIDERS:
        return {"provider": provider, "status": "unknown_provider",
                "connected": False, "read_only": True,
                "external_write": False}
    return provider_readiness(provider)


@api.get("/marketing-os/paid/performance")
async def paid_performance(user=Depends(require_roles(*MARKETING_ROLES))):
    """Read-only cross-channel paid-media overview.

    Combines each provider's credential readiness with locally stored
    normalized daily performance. Performs no external provider calls.
    Disconnected channels report honest null metrics (never zero).
    """
    del user

    placeholders = ", ".join(f":p{i}" for i in range(len(PAID_PROVIDERS)))
    params = {f"p{i}": provider for i, provider in enumerate(PAID_PROVIDERS)}

    async with AsyncSessionLocal() as pg:
        result = await pg.execute(
            text(
                f"""
                SELECT
                    provider,
                    impressions,
                    clicks,
                    spend,
                    conversions,
                    conversion_value
                FROM marketing_daily_metrics
                WHERE provider IN ({placeholders})
                """
            ),
            params,
        )
        rows = [dict(row._mapping) for row in result]

    return build_paid_media_overview(rows)
