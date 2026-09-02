"""Read-only provider performance synchronization.

This module coordinates aggregate advertising-performance reads and
persists normalized daily metrics.

It does not create campaigns, modify budgets, publish content, or call
``execute_action``.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from sqlalchemy import text

from marketing_os.integrations.registry import (
    create_integration,
    normalize_provider,
)
from marketing_os.services.performance import (
    persist_daily_performance,
)


_ALLOWED_ACCOUNT_STATUSES = frozenset(
    {
        "connected",
        "active",
    }
)


def _account_mapping(row: Any) -> Mapping[str, Any]:
    """Normalize SQLAlchemy/fake account rows."""

    if isinstance(row, Mapping):
        return row

    mapping = getattr(row, "_mapping", None)

    if mapping is not None:
        return mapping

    raise TypeError(
        "channel account row must be mapping-compatible"
    )


async def get_readable_channel_accounts(
    session,
    *,
    provider: str | None = None,
) -> list[dict[str, Any]]:
    """Return connected accounts explicitly enabled for reads."""

    params: dict[str, Any] = {}

    provider_filter = ""

    if provider is not None:
        params["provider"] = normalize_provider(
            provider
        )
        provider_filter = (
            " AND lower(provider) = :provider"
        )

    result = await session.execute(
        text(
            f"""
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
                last_sync_at,
                configuration
            FROM marketing_channel_accounts
            WHERE read_enabled = TRUE
              AND lower(status) IN (
                  'connected',
                  'active'
              )
              {provider_filter}
            ORDER BY provider, external_account_id
            """
        ),
        params,
    )

    rows = result.mappings().all()

    return [
        dict(_account_mapping(row))
        for row in rows
    ]


def _performance_records(
    response: Any,
) -> list[Mapping[str, Any]]:
    """Accept a provider list or {'records': [...]} response."""

    if isinstance(response, Mapping):
        records = response.get("records")

        if records is None:
            raise ValueError(
                "provider performance response "
                "must contain records"
            )

    else:
        records = response

    if not isinstance(records, (list, tuple)):
        raise ValueError(
            "provider performance records "
            "must be a list"
        )

    normalized: list[Mapping[str, Any]] = []

    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError(
                "provider performance record "
                "must be a mapping"
            )

        normalized.append(record)

    return normalized


async def sync_channel_account(
    session,
    account: Mapping[str, Any],
    *,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Read and persist aggregate metrics for one channel account."""

    if start_date > end_date:
        raise ValueError(
            "start_date must not be after end_date"
        )

    account = dict(account)

    provider = normalize_provider(
        account.get("provider", "")
    )

    status = str(
        account.get("status") or ""
    ).strip().lower()

    if status not in _ALLOWED_ACCOUNT_STATUSES:
        raise PermissionError(
            "channel account is not connected"
        )

    if account.get("read_enabled") is not True:
        raise PermissionError(
            "channel account read access is disabled"
        )

    integration = create_integration(
        provider,
        account=account,
    )

    response = await integration.fetch_performance(
        account_id=account["external_account_id"],
        start_date=start_date,
        end_date=end_date,
    )

    records = _performance_records(response)

    persisted: list[dict[str, Any]] = []

    for provider_record in records:

        payload = dict(provider_record)

        record_provider = payload.get("provider")

        if record_provider is not None:
            if (
                normalize_provider(record_provider)
                != provider
            ):
                raise ValueError(
                    "provider performance record "
                    "does not match channel account"
                )

        payload["provider"] = provider
        payload["channel_account_id"] = account["id"]

        persisted.append(
            await persist_daily_performance(
                session,
                payload,
            )
        )

    # Updating our own local sync timestamp is not an external
    # advertising-platform write.
    await session.execute(
        text(
            """
            UPDATE marketing_channel_accounts
            SET
                last_sync_at = now(),
                updated_at = now()
            WHERE id = :account_id
            """
        ),
        {
            "account_id": account["id"],
        },
    )

    return {
        "channel_account_id": account["id"],
        "provider": provider,
        "records_received": len(records),
        "records_persisted": len(persisted),
        "daily_metric_ids": [
            item["daily_metric_id"]
            for item in persisted
        ],
    }


async def sync_readable_accounts(
    session,
    *,
    start_date: date,
    end_date: date,
    provider: str | None = None,
) -> dict[str, Any]:
    """Synchronize all eligible read-enabled accounts."""

    accounts = await get_readable_channel_accounts(
        session,
        provider=provider,
    )

    results: list[dict[str, Any]] = []

    for account in accounts:
        results.append(
            await sync_channel_account(
                session,
                account,
                start_date=start_date,
                end_date=end_date,
            )
        )

    return {
        "status": "read_only",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "accounts_found": len(accounts),
        "accounts_synced": len(results),
        "records_persisted": sum(
            item["records_persisted"]
            for item in results
        ),
        "accounts": results,
    }
