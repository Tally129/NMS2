"""Scheduled-refresh FOUNDATION for search data (READ-ONLY).

Provides a deterministic, callable refresh that reuses the app's existing
session + the read-only GSC sync. It is intended to be wired into the
existing apscheduler in a future step; it intentionally does NOT register
an autonomous recurring job here and performs NO external writes.

When GSC is not connected, it is a safe no-op that reports an honest
reason (no network call).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import text

from postgres_db import AsyncSessionLocal

from .gsc import GoogleSearchConsoleAdapter, credential_readiness
from .gsc_sync import sync_search_console


async def refresh_tracked_search_data(
    *,
    site_id: Optional[str] = None,
    lookback_days: int = 28,
    adapter=None,
) -> dict:
    """Refresh Search Console data for one site. Deterministic + READ-ONLY.

    - No-op (honest reason) when GSC is not connected.
    - `adapter` is injectable for tests; defaults to the real read-only
      GSC adapter otherwise.
    """
    readiness = credential_readiness()
    if adapter is None and not readiness["connected"]:
        return {"refreshed": False, "reason": readiness["status"]}

    end = date.today()
    start = end - timedelta(days=lookback_days)

    async with AsyncSessionLocal() as pg:
        if site_id:
            res = await pg.execute(
                text(
                    "SELECT id FROM marketing_search_sites WHERE id = :id"
                ),
                {"id": site_id},
            )
        else:
            res = await pg.execute(
                text(
                    "SELECT id FROM marketing_search_sites "
                    "WHERE is_active = true ORDER BY created_at ASC LIMIT 1"
                )
            )
        row = res.first()
        if not row:
            return {"refreshed": False, "reason": "no_site"}
        sid = row._mapping["id"]
        result = await sync_search_console(
            pg,
            site_id=sid,
            adapter=adapter or GoogleSearchConsoleAdapter(),
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )
    return {"refreshed": True, "result": result}
