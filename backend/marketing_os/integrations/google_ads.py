"""Read-only Google Ads Marketing OS integration.

This adapter reads aggregate campaign/day performance only.

It does not:
- create or modify campaigns;
- change budgets or bids;
- publish ads;
- upload conversions;
- handle patient/contact/clinical data.

The Google Ads SDK import is intentionally lazy so the adapter can be
unit-tested before the production dependency or credentials are added.
"""

from __future__ import annotations

import asyncio
import os

from datetime import date
from decimal import Decimal
from typing import Any, Callable, Mapping

from marketing_os.integrations.base import MarketingIntegration


PROVIDER = "google_ads"

_REQUIRED_ENV = (
    "GOOGLE_ADS_DEVELOPER_TOKEN",
    "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
)



def credential_readiness() -> dict[str, Any]:
    """Return Google Ads credential presence without exposing values."""

    required = {
        name: bool(
            os.environ.get(name, "").strip()
        )
        for name in _REQUIRED_ENV
    }

    login_customer_id_present = bool(
        os.environ.get(
            "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
            "",
        ).strip()
    )

    missing = [
        name
        for name, present in required.items()
        if not present
    ]

    return {
        "required_configured": not missing,
        "missing_required": missing,
        "login_customer_id_configured":
            login_customer_id_present,
    }


def _clean_customer_id(value: Any) -> str:
    """Return digits-only Google Ads customer ID."""

    cleaned = str(value or "").strip().replace("-", "")

    if not cleaned:
        raise ValueError("Google Ads customer ID is required")

    if not cleaned.isdigit():
        raise ValueError(
            "Google Ads customer ID must contain digits only"
        )

    return cleaned


def _configuration(account: Mapping[str, Any]) -> dict[str, Any]:
    value = account.get("configuration") or {}

    if not isinstance(value, Mapping):
        raise ValueError(
            "Google Ads account configuration must be a mapping"
        )

    return dict(value)


def _optional_customer_id(value: Any) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()

    if not cleaned:
        return None

    return _clean_customer_id(cleaned)


def _load_sdk_client():
    """Construct the official Google Ads SDK client from environment.

    No credential values are accepted from browser/client payloads.
    """

    missing = [
        name
        for name in _REQUIRED_ENV
        if not os.environ.get(name, "").strip()
    ]

    if missing:
        raise RuntimeError(
            "Google Ads credentials are not configured: "
            + ", ".join(missing)
        )

    try:
        from google.ads.googleads.client import GoogleAdsClient
    except ImportError as exc:
        raise RuntimeError(
            "google-ads Python package is not installed"
        ) from exc

    config: dict[str, Any] = {
        "developer_token":
            os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"].strip(),
        "client_id":
            os.environ["GOOGLE_ADS_CLIENT_ID"].strip(),
        "client_secret":
            os.environ["GOOGLE_ADS_CLIENT_SECRET"].strip(),
        "refresh_token":
            os.environ["GOOGLE_ADS_REFRESH_TOKEN"].strip(),
        "use_proto_plus": True,
    }

    login_customer_id = os.environ.get(
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
        "",
    ).strip()

    if login_customer_id:
        config["login_customer_id"] = _clean_customer_id(
            login_customer_id
        )

    return GoogleAdsClient.load_from_dict(config)


def _micros_to_decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0)) / Decimal("1000000")


def _row_to_record(row: Any) -> dict[str, Any]:
    """Normalize one Google Ads campaign/date result."""

    return {
        "metric_date": str(row.segments.date),
        "external_campaign_id": str(row.campaign.id),
        "campaign_name": str(row.campaign.name or ""),
        "impressions": int(row.metrics.impressions or 0),
        "clicks": int(row.metrics.clicks or 0),
        "spend": str(
            _micros_to_decimal(
                row.metrics.cost_micros
            )
        ),
        # Google Ads conversions can be fractional because of
        # attribution models. Preserve the provider value exactly
        # through the provider-neutral Decimal persistence contract.
        "conversions": str(
            Decimal(
                str(row.metrics.conversions or 0)
            )
        ),
        "conversion_value": str(
            Decimal(
                str(
                    row.metrics.conversions_value
                    or 0
                )
            )
        ),
        "leads": 0,
        "raw_metrics": {
            "google_ads_conversions":
                str(row.metrics.conversions or 0),
            "google_ads_conversions_value":
                str(
                    row.metrics.conversions_value
                    or 0
                ),
            "cost_micros":
                int(row.metrics.cost_micros or 0),
        },
    }


class GoogleAdsIntegration(MarketingIntegration):
    """Read-only Google Ads aggregate-performance adapter."""

    provider = PROVIDER

    def __init__(
        self,
        *,
        account: Mapping[str, Any],
        client: Any | None = None,
        client_factory: Callable[[], Any] | None = None,
    ):
        self.account = dict(account)

        self.configuration = _configuration(
            self.account
        )

        self.customer_id = _clean_customer_id(
            self.account.get("external_account_id")
        )

        self._client = client
        self._client_factory = (
            client_factory or _load_sdk_client
        )

    def _get_client(self):
        if self._client is None:
            self._client = self._client_factory()

        return self._client

    def _query(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> str:
        start = start_date.isoformat()
        end = end_date.isoformat()

        return f"""
            SELECT
                segments.date,
                campaign.id,
                campaign.name,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions,
                metrics.conversions_value
            FROM campaign
            WHERE segments.date BETWEEN '{start}' AND '{end}'
              AND campaign.status != 'REMOVED'
            ORDER BY segments.date, campaign.id
        """

    def _search(
        self,
        *,
        start_date: date,
        end_date: date,
    ):
        client = self._get_client()

        service = client.get_service(
            "GoogleAdsService"
        )

        return service.search(
            customer_id=self.customer_id,
            query=self._query(
                start_date=start_date,
                end_date=end_date,
            ),
        )

    async def health(self) -> dict:
        """Return local adapter readiness without mutating Google Ads."""

        try:
            self._get_client()
        except Exception as exc:
            return {
                "status": "unavailable",
                "provider": self.provider,
                "customer_id": self.customer_id,
                "read_only": True,
                "reason": str(exc),
            }

        return {
            "status": "ready",
            "provider": self.provider,
            "customer_id": self.customer_id,
            "read_only": True,
        }

    async def verify_access(self) -> dict:
        """Verify read access to the configured Google Ads customer.

        This performs one minimal Google Ads API read and never
        mutates campaigns, budgets, bids, ads, or account settings.
        """

        def _verify():
            client = self._get_client()

            service = client.get_service(
                "GoogleAdsService"
            )

            query = """
                SELECT
                    customer.id
                FROM customer
                LIMIT 1
            """

            rows = service.search(
                customer_id=self.customer_id,
                query=query,
            )

            # Force evaluation so authentication/authorization
            # failures surface during verification.
            iterator = iter(rows)

            try:
                next(iterator)
            except StopIteration:
                pass

        try:
            await asyncio.to_thread(_verify)
        except Exception as exc:
            return {
                "status": "unavailable",
                "provider": self.provider,
                "customer_id": self.customer_id,
                "read_only": True,
                "verified": False,
                "reason": str(exc),
            }

        return {
            "status": "verified",
            "provider": self.provider,
            "customer_id": self.customer_id,
            "read_only": True,
            "verified": True,
        }

    async def fetch_performance(
        self,
        *,
        account_id,
        start_date,
        end_date,
    ) -> dict:
        """Fetch campaign/day aggregate performance from Google Ads."""

        requested_customer_id = _clean_customer_id(
            account_id
        )

        if requested_customer_id != self.customer_id:
            raise PermissionError(
                "requested Google Ads customer does not "
                "match channel account"
            )

        if not isinstance(start_date, date):
            raise ValueError("start_date must be a date")

        if not isinstance(end_date, date):
            raise ValueError("end_date must be a date")

        if start_date > end_date:
            raise ValueError(
                "start_date must not be after end_date"
            )

        rows = await asyncio.to_thread(
            self._search,
            start_date=start_date,
            end_date=end_date,
        )

        records = [
            _row_to_record(row)
            for row in rows
        ]

        return {
            "provider": self.provider,
            "customer_id": self.customer_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "records": records,
        }
