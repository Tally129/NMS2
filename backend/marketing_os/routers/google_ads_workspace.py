"""Live Google Ads operational workspace.

READ-ONLY provider API endpoints for the NMS Marketing OS.

These routes expose live Google Ads state and performance but perform
no provider mutation and no local database mutation.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import Depends, HTTPException, Query
from sqlalchemy import text

from deps import api, require_roles
from postgres_db import AsyncSessionLocal

from marketing_os.integrations.google_ads import (
    GoogleAdsIntegration,
)


MARKETING_ROLES = (
    "admin",
    "practitioner",
)


def _date_window(
    days: int,
) -> tuple[date, date]:
    end_date = date.today()

    start_date = (
        end_date
        - timedelta(
            days=days - 1
        )
    )

    return (
        start_date,
        end_date,
    )


async def _read_google_account():
    async with AsyncSessionLocal() as pg:
        result = await pg.execute(
            text(
                """
                SELECT
                    id,
                    provider,
                    external_account_id,
                    account_name,
                    status,
                    currency,
                    timezone,
                    read_enabled,
                    write_enabled,
                    configuration
                FROM marketing_channel_accounts
                WHERE lower(provider) = 'google_ads'
                  AND read_enabled = TRUE
                  AND lower(
                      COALESCE(status, '')
                  ) NOT IN (
                      'disabled',
                      'removed'
                  )
                ORDER BY
                    write_enabled DESC,
                    created_at ASC
                """
            )
        )

        rows = [
            dict(row._mapping)
            for row in result
        ]

    if not rows:
        raise HTTPException(
            status_code=409,
            detail=(
                "No read-enabled Google Ads "
                "account is registered."
            ),
        )

    if len(rows) > 1:
        write_rows = [
            row
            for row in rows
            if row.get("write_enabled")
        ]

        if len(write_rows) == 1:
            return write_rows[0]

        raise HTTPException(
            status_code=409,
            detail=(
                "Multiple Google Ads accounts "
                "are eligible for live reads."
            ),
        )

    return rows[0]


async def _integration():
    account = await _read_google_account()

    return (
        GoogleAdsIntegration(
            account=account,
        ),
        account,
    )


@api.get(
    "/marketing-os/google-ads/overview"
)
async def google_ads_workspace_overview(
    days: int = Query(
        30,
        ge=1,
        le=365,
    ),
    user=Depends(
        require_roles(
            *MARKETING_ROLES
        )
    ),
):
    del user

    integration, account = (
        await _integration()
    )

    start_date, end_date = (
        _date_window(days)
    )

    try:
        result = (
            await integration
            .workspace_overview(
                start_date=start_date,
                end_date=end_date,
            )
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code":
                    "google_ads_live_read_failed",
                "message":
                    str(exc),
            },
        ) from exc

    result["account"] = {
        "id":
            account.get("id"),
        "external_account_id":
            account.get(
                "external_account_id"
            ),
        "account_name":
            account.get(
                "account_name"
            ),
        "currency":
            account.get("currency"),
        "timezone":
            account.get("timezone"),
        "read_enabled":
            bool(
                account.get(
                    "read_enabled"
                )
            ),
        "write_enabled":
            bool(
                account.get(
                    "write_enabled"
                )
            ),
    }

    result["read_only"] = True

    return result


@api.get(
    "/marketing-os/google-ads/campaigns"
)
async def google_ads_workspace_campaigns(
    days: int = Query(
        30,
        ge=1,
        le=365,
    ),
    user=Depends(
        require_roles(
            *MARKETING_ROLES
        )
    ),
):
    del user

    integration, _account = (
        await _integration()
    )

    start_date, end_date = (
        _date_window(days)
    )

    try:
        campaigns = (
            await integration
            .workspace_campaigns(
                start_date=start_date,
                end_date=end_date,
            )
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code":
                    "google_ads_live_read_failed",
                "message":
                    str(exc),
            },
        ) from exc

    return {
        "provider": "google_ads",
        "customer_id":
            integration.customer_id,
        "start_date":
            start_date.isoformat(),
        "end_date":
            end_date.isoformat(),
        "count":
            len(campaigns),
        "items":
            campaigns,
        "read_only": True,
    }


@api.get(
    "/marketing-os/google-ads/"
    "campaigns/{campaign_id}"
)
async def google_ads_workspace_campaign_detail(
    campaign_id: str,
    days: int = Query(
        30,
        ge=1,
        le=365,
    ),
    user=Depends(
        require_roles(
            *MARKETING_ROLES
        )
    ),
):
    del user

    integration, _account = (
        await _integration()
    )

    start_date, end_date = (
        _date_window(days)
    )

    try:
        result = (
            await integration
            .workspace_campaign_detail(
                campaign_id=campaign_id,
                start_date=start_date,
                end_date=end_date,
            )
        )

    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail="Google Ads campaign not found.",
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code":
                    "google_ads_live_read_failed",
                "message":
                    str(exc),
            },
        ) from exc

    return {
        "provider": "google_ads",
        "customer_id":
            integration.customer_id,
        "start_date":
            start_date.isoformat(),
        "end_date":
            end_date.isoformat(),
        "read_only": True,
        **result,
    }
