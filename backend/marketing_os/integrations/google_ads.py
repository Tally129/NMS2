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


    def _campaign_resource_name(
        self,
        campaign_id: Any,
    ) -> str:
        campaign_id = _clean_customer_id(campaign_id)

        return (
            f"customers/{self.customer_id}/"
            f"campaigns/{campaign_id}"
        )

    def _campaign_budget_resource_name(
        self,
        budget_id: Any,
    ) -> str:
        budget_id = _clean_customer_id(budget_id)

        return (
            f"customers/{self.customer_id}/"
            f"campaignBudgets/{budget_id}"
        )

    def _money_to_micros(
        self,
        value: Any,
    ) -> int:
        amount = Decimal(str(value))

        if not amount.is_finite():
            raise ValueError(
                "budget amount must be finite"
            )

        if amount < 0:
            raise ValueError(
                "budget amount must be nonnegative"
            )

        return int(
            amount * Decimal("1000000")
        )

    def _find_reusable_campaign_budget_sync(
        self,
        *,
        budget_name: str,
        amount_micros: int,
    ) -> str | None:
        """Find one exact unreferenced campaign budget.

        Reuse is allowed only when:
        - name matches exactly;
        - amount matches exactly;
        - reference_count is zero;
        - budget is not removed.

        Multiple matching reusable budgets fail closed.
        """

        client = self._get_client()

        service = client.get_service(
            "GoogleAdsService"
        )

        safe_name = (
            str(budget_name)
            .replace("\\", "\\\\")
            .replace("'", "\\'")
        )

        query = f"""
            SELECT
                campaign_budget.id,
                campaign_budget.name,
                campaign_budget.resource_name,
                campaign_budget.amount_micros,
                campaign_budget.status,
                campaign_budget.reference_count
            FROM campaign_budget
            WHERE campaign_budget.name = '{safe_name}'
        """

        rows = list(
            service.search(
                customer_id=self.customer_id,
                query=query,
            )
        )

        matches: list[str] = []

        for row in rows:
            budget = row.campaign_budget

            if str(
                getattr(budget, "name", "") or ""
            ) != budget_name:
                continue

            if int(
                getattr(
                    budget,
                    "amount_micros",
                    -1,
                )
            ) != int(amount_micros):
                continue

            if int(
                getattr(
                    budget,
                    "reference_count",
                    -1,
                )
            ) != 0:
                continue

            status = getattr(
                getattr(
                    budget,
                    "status",
                    None,
                ),
                "name",
                "",
            )

            if str(status).upper() == "REMOVED":
                continue

            resource_name = str(
                getattr(
                    budget,
                    "resource_name",
                    "",
                )
                or ""
            )

            if not resource_name:
                continue

            matches.append(resource_name)

        if len(matches) > 1:
            raise RuntimeError(
                "multiple_reusable_campaign_budgets"
            )

        if matches:
            return matches[0]

        return None


    def _create_campaign_sync(
        self,
        *,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        client = self._get_client()

        budget_amount = (
            payload.get("daily_budget")
            if payload.get("daily_budget") is not None
            else payload.get("amount")
        )

        if budget_amount is None:
            raise ValueError(
                "daily_budget is required for campaign.create"
            )

        name = str(
            payload.get("name") or ""
        ).strip()

        if not name:
            raise ValueError(
                "name is required for campaign.create"
            )

        budget_name = f"{name} Budget"

        budget_amount_micros = (
            self._money_to_micros(
                budget_amount
            )
        )

        budget_resource = (
            self._find_reusable_campaign_budget_sync(
                budget_name=budget_name,
                amount_micros=budget_amount_micros,
            )
        )

        budget_reused = (
            budget_resource is not None
        )

        if budget_resource is None:
            budget_service = client.get_service(
                "CampaignBudgetService"
            )

            budget_operation = client.get_type(
                "CampaignBudgetOperation"
            )

            budget = budget_operation.create

            budget.name = budget_name
            budget.amount_micros = (
                budget_amount_micros
            )

            budget.delivery_method = (
                client.enums
                .BudgetDeliveryMethodEnum
                .STANDARD
            )

            budget_response = (
                budget_service.mutate_campaign_budgets(
                    customer_id=self.customer_id,
                    operations=[budget_operation],
                )
            )

            budget_resource = (
                budget_response
                .results[0]
                .resource_name
            )

        campaign_service = client.get_service(
            "CampaignService"
        )

        campaign_operation = client.get_type(
            "CampaignOperation"
        )

        campaign = campaign_operation.create

        campaign.name = name
        campaign.campaign_budget = budget_resource

        # New campaigns are intentionally PAUSED.
        campaign.status = (
            client.enums.CampaignStatusEnum.PAUSED
        )

        # Initial live execution supports Search campaigns.
        campaign.advertising_channel_type = (
            client.enums.AdvertisingChannelTypeEnum.SEARCH
        )

        # Google Ads API v25 requires an explicit declaration
        # when creating a campaign. NMS advertising is not
        # EU political advertising.
        campaign.contains_eu_political_advertising = (
            client.enums
            .EuPoliticalAdvertisingStatusEnum
            .DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
        )

        campaign.manual_cpc.enhanced_cpc_enabled = False

        start_date = payload.get("start_date")
        end_date = payload.get("end_date")

        if start_date:
            campaign.start_date = (
                str(start_date).replace("-", "")
            )

        if end_date:
            campaign.end_date = (
                str(end_date).replace("-", "")
            )

        response = campaign_service.mutate_campaigns(
            customer_id=self.customer_id,
            operations=[campaign_operation],
        )

        campaign_resource = (
            response.results[0].resource_name
        )

        return {
            "provider": self.provider,
            "action_type": "campaign.create",
            "customer_id": self.customer_id,
            "campaign_resource_name": campaign_resource,
            "campaign_budget_resource_name": budget_resource,
            "campaign_budget_reused": budget_reused,
            "status": "paused",
            "external_write_performed": True,
        }

    def _set_campaign_status_sync(
        self,
        *,
        campaign_id: Any,
        enabled: bool,
    ) -> dict[str, Any]:
        client = self._get_client()

        service = client.get_service(
            "CampaignService"
        )

        operation = client.get_type(
            "CampaignOperation"
        )

        campaign = operation.update

        campaign.resource_name = (
            self._campaign_resource_name(
                campaign_id
            )
        )

        campaign.status = (
            client.enums.CampaignStatusEnum.ENABLED
            if enabled
            else client.enums.CampaignStatusEnum.PAUSED
        )

        operation.update_mask.paths.append(
            "status"
        )

        response = service.mutate_campaigns(
            customer_id=self.customer_id,
            operations=[operation],
        )

        return {
            "provider": self.provider,
            "action_type": (
                "campaign.resume"
                if enabled
                else "campaign.pause"
            ),
            "customer_id": self.customer_id,
            "campaign_resource_name": (
                response.results[0].resource_name
            ),
            "status": (
                "enabled"
                if enabled
                else "paused"
            ),
            "external_write_performed": True,
        }

    def _resolve_campaign_budget_sync(
        self,
        *,
        campaign_id: Any,
    ) -> str:
        client = self._get_client()

        service = client.get_service(
            "GoogleAdsService"
        )

        campaign_id = _clean_customer_id(
            campaign_id
        )

        query = f"""
            SELECT
                campaign.id,
                campaign.campaign_budget
            FROM campaign
            WHERE campaign.id = {campaign_id}
            LIMIT 1
        """

        rows = service.search(
            customer_id=self.customer_id,
            query=query,
        )

        for row in rows:
            return str(
                row.campaign.campaign_budget
            )

        raise LookupError(
            "campaign_not_found"
        )

    def _update_budget_sync(
        self,
        *,
        campaign_id: Any,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        client = self._get_client()

        amount = (
            payload.get("daily_budget")
            if payload.get("daily_budget") is not None
            else payload.get("amount")
        )

        if amount is None:
            raise ValueError(
                "amount or daily_budget is required"
            )

        budget_resource = (
            self._resolve_campaign_budget_sync(
                campaign_id=campaign_id
            )
        )

        service = client.get_service(
            "CampaignBudgetService"
        )

        operation = client.get_type(
            "CampaignBudgetOperation"
        )

        budget = operation.update

        budget.resource_name = budget_resource
        budget.amount_micros = self._money_to_micros(
            amount
        )

        operation.update_mask.paths.append(
            "amount_micros"
        )

        response = (
            service.mutate_campaign_budgets(
                customer_id=self.customer_id,
                operations=[operation],
            )
        )

        return {
            "provider": self.provider,
            "action_type": "budget.update",
            "customer_id": self.customer_id,
            "campaign_id": str(campaign_id),
            "campaign_budget_resource_name": (
                response.results[0].resource_name
            ),
            "amount": str(amount),
            "external_write_performed": True,
        }

    def _verify_campaign_sync(
        self,
        *,
        campaign_id: Any,
    ) -> dict[str, Any]:
        client = self._get_client()

        service = client.get_service(
            "GoogleAdsService"
        )

        campaign_id = _clean_customer_id(
            campaign_id
        )

        query = f"""
            SELECT
                campaign.id,
                campaign.name,
                campaign.status,
                campaign.campaign_budget,
                campaign_budget.amount_micros
            FROM campaign
            WHERE campaign.id = {campaign_id}
            LIMIT 1
        """

        rows = service.search(
            customer_id=self.customer_id,
            query=query,
        )

        for row in rows:
            return {
                "campaign_id":
                    str(row.campaign.id),
                "campaign_name":
                    str(row.campaign.name or ""),
                "campaign_status":
                    row.campaign.status.name,
                "campaign_budget_resource_name":
                    str(
                        row.campaign.campaign_budget
                    ),
                "daily_budget":
                    str(
                        _micros_to_decimal(
                            row.campaign_budget.amount_micros
                        )
                    ),
            }

        raise LookupError(
            "campaign_not_found"
        )


    # ------------------------------------------------------------------
    # Live Google Ads workspace reads
    # ------------------------------------------------------------------

    @staticmethod
    def _enum_name(value) -> str:
        name = getattr(value, "name", None)
        if name:
            return str(name)

        return str(value or "")

    @staticmethod
    def _safe_ratio(
        numerator,
        denominator,
    ):
        try:
            denominator = float(denominator or 0)
            if denominator == 0:
                return None

            return (
                float(numerator or 0)
                / denominator
            )
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    def _workspace_campaign_inventory_query(
        self,
        *,
        campaign_id: str | None = None,
    ) -> str:
        """Return provider state independent of performance activity.

        This query deliberately contains no metrics or date segmentation so
        paused and zero-traffic campaigns remain visible in the NMS workspace.
        """

        campaign_filter = ""

        if campaign_id:
            campaign_id = _clean_customer_id(
                campaign_id
            )

            campaign_filter = (
                f" AND campaign.id = {campaign_id}"
            )

        return f"""
            SELECT
                campaign.id,
                campaign.name,
                campaign.status,
                campaign.advertising_channel_type,
                campaign.campaign_budget,
                campaign.contains_eu_political_advertising,
                campaign_budget.id,
                campaign_budget.name,
                campaign_budget.amount_micros,
                campaign_budget.reference_count,
                campaign_budget.explicitly_shared
            FROM campaign
            WHERE campaign.status != 'REMOVED'
              {campaign_filter}
            ORDER BY campaign.id
        """

    def _workspace_campaign_metrics_query(
        self,
        *,
        start_date: date,
        end_date: date,
        campaign_id: str | None = None,
    ) -> str:
        """Return date-bounded performance aggregated by campaign."""

        start = start_date.isoformat()
        end = end_date.isoformat()

        campaign_filter = ""

        if campaign_id:
            campaign_id = _clean_customer_id(
                campaign_id
            )

            campaign_filter = (
                f" AND campaign.id = {campaign_id}"
            )

        return f"""
            SELECT
                campaign.id,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions,
                metrics.conversions_value
            FROM campaign
            WHERE campaign.status != 'REMOVED'
              AND segments.date BETWEEN
                  '{start}' AND '{end}'
              {campaign_filter}
            ORDER BY campaign.id
        """

    def _workspace_campaigns_sync(
        self,
        *,
        start_date: date,
        end_date: date,
        campaign_id: str | None = None,
    ) -> list[dict[str, Any]]:
        client = self._get_client()

        service = client.get_service(
            "GoogleAdsService"
        )

        inventory_rows = service.search(
            customer_id=self.customer_id,
            query=self._workspace_campaign_inventory_query(
                campaign_id=campaign_id,
            ),
        )

        metric_rows = service.search(
            customer_id=self.customer_id,
            query=self._workspace_campaign_metrics_query(
                start_date=start_date,
                end_date=end_date,
                campaign_id=campaign_id,
            ),
        )

        metrics_by_campaign: dict[str, dict[str, Any]] = {}

        for row in metric_rows:
            campaign_key = str(
                row.campaign.id
            )

            impressions = int(
                row.metrics.impressions
                or 0
            )

            clicks = int(
                row.metrics.clicks
                or 0
            )

            spend = float(
                _micros_to_decimal(
                    row.metrics.cost_micros
                )
            )

            conversions = float(
                row.metrics.conversions
                or 0
            )

            conversion_value = float(
                row.metrics.conversions_value
                or 0
            )

            metrics_by_campaign[
                campaign_key
            ] = {
                "impressions":
                    impressions,
                "clicks":
                    clicks,
                "ctr":
                    self._safe_ratio(
                        clicks,
                        impressions,
                    ),
                "spend":
                    spend,
                "average_cpc":
                    self._safe_ratio(
                        spend,
                        clicks,
                    ),
                "conversions":
                    conversions,
                "conversion_value":
                    conversion_value,
                "cpa":
                    self._safe_ratio(
                        spend,
                        conversions,
                    ),
                "roas":
                    self._safe_ratio(
                        conversion_value,
                        spend,
                    ),
            }

        campaigns = []

        for row in inventory_rows:
            campaign_key = str(
                row.campaign.id
            )

            metrics = metrics_by_campaign.get(
                campaign_key,
                {
                    "impressions": 0,
                    "clicks": 0,
                    "ctr": None,
                    "spend": 0.0,
                    "average_cpc": None,
                    "conversions": 0.0,
                    "conversion_value": 0.0,
                    "cpa": None,
                    "roas": None,
                },
            )

            campaigns.append(
                {
                    "provider":
                        self.provider,
                    "customer_id":
                        self.customer_id,
                    "campaign_id":
                        campaign_key,
                    "campaign_name":
                        str(
                            row.campaign.name
                            or ""
                        ),
                    "status":
                        self._enum_name(
                            row.campaign.status
                        ),
                    "channel_type":
                        self._enum_name(
                            row.campaign
                            .advertising_channel_type
                        ),
                    "campaign_resource_name":
                        (
                            f"customers/"
                            f"{self.customer_id}/"
                            f"campaigns/"
                            f"{row.campaign.id}"
                        ),
                    "budget": {
                        "budget_id":
                            str(
                                row.campaign_budget.id
                            ),
                        "name":
                            str(
                                row.campaign_budget.name
                                or ""
                            ),
                        "resource_name":
                            str(
                                row.campaign
                                .campaign_budget
                                or ""
                            ),
                        "daily_budget":
                            float(
                                _micros_to_decimal(
                                    row.campaign_budget
                                    .amount_micros
                                )
                            ),
                        "reference_count":
                            int(
                                row.campaign_budget
                                .reference_count
                                or 0
                            ),
                        "explicitly_shared":
                            bool(
                                row.campaign_budget
                                .explicitly_shared
                            ),
                    },
                    "metrics":
                        metrics,
                    "eu_political_advertising":
                        self._enum_name(
                            row.campaign
                            .contains_eu_political_advertising
                        ),
                }
            )

        return campaigns

    async def workspace_campaigns(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._workspace_campaigns_sync,
            start_date=start_date,
            end_date=end_date,
        )

    def _workspace_ad_groups_sync(
        self,
        *,
        campaign_id: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        campaign_id = _clean_customer_id(
            campaign_id
        )

        client = self._get_client()

        service = client.get_service(
            "GoogleAdsService"
        )

        query = f"""
            SELECT
                ad_group.id,
                ad_group.name,
                ad_group.status,
                ad_group.type,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions,
                metrics.conversions_value
            FROM ad_group
            WHERE campaign.id = {campaign_id}
              AND ad_group.status != 'REMOVED'
              AND segments.date BETWEEN
                  '{start_date.isoformat()}'
                  AND
                  '{end_date.isoformat()}'
            ORDER BY ad_group.id
        """

        rows = service.search(
            customer_id=self.customer_id,
            query=query,
        )

        items = []

        for row in rows:
            items.append(
                {
                    "ad_group_id":
                        str(row.ad_group.id),
                    "name":
                        str(
                            row.ad_group.name
                            or ""
                        ),
                    "status":
                        self._enum_name(
                            row.ad_group.status
                        ),
                    "type":
                        self._enum_name(
                            row.ad_group.type
                        ),
                    "impressions":
                        int(
                            row.metrics.impressions
                            or 0
                        ),
                    "clicks":
                        int(
                            row.metrics.clicks
                            or 0
                        ),
                    "spend":
                        float(
                            _micros_to_decimal(
                                row.metrics
                                .cost_micros
                            )
                        ),
                    "conversions":
                        float(
                            row.metrics
                            .conversions
                            or 0
                        ),
                    "conversion_value":
                        float(
                            row.metrics
                            .conversions_value
                            or 0
                        ),
                }
            )

        return items

    def _workspace_ads_sync(
        self,
        *,
        campaign_id: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        campaign_id = _clean_customer_id(
            campaign_id
        )

        client = self._get_client()

        service = client.get_service(
            "GoogleAdsService"
        )

        query = f"""
            SELECT
                ad_group.id,
                ad_group.name,
                ad_group_ad.ad.id,
                ad_group_ad.ad.name,
                ad_group_ad.ad.type,
                ad_group_ad.status,
                ad_group_ad.ad.final_urls,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions,
                metrics.conversions_value
            FROM ad_group_ad
            WHERE campaign.id = {campaign_id}
              AND ad_group_ad.status != 'REMOVED'
              AND segments.date BETWEEN
                  '{start_date.isoformat()}'
                  AND
                  '{end_date.isoformat()}'
            ORDER BY ad_group_ad.ad.id
        """

        rows = service.search(
            customer_id=self.customer_id,
            query=query,
        )

        items = []

        for row in rows:
            items.append(
                {
                    "ad_id":
                        str(
                            row.ad_group_ad
                            .ad.id
                        ),
                    "ad_name":
                        str(
                            row.ad_group_ad
                            .ad.name
                            or ""
                        ),
                    "ad_type":
                        self._enum_name(
                            row.ad_group_ad
                            .ad.type
                        ),
                    "status":
                        self._enum_name(
                            row.ad_group_ad
                            .status
                        ),
                    "ad_group_id":
                        str(
                            row.ad_group.id
                        ),
                    "ad_group_name":
                        str(
                            row.ad_group.name
                            or ""
                        ),
                    "final_urls":
                        [
                            str(url)
                            for url in (
                                row.ad_group_ad
                                .ad.final_urls
                                or []
                            )
                        ],
                    "impressions":
                        int(
                            row.metrics.impressions
                            or 0
                        ),
                    "clicks":
                        int(
                            row.metrics.clicks
                            or 0
                        ),
                    "spend":
                        float(
                            _micros_to_decimal(
                                row.metrics
                                .cost_micros
                            )
                        ),
                    "conversions":
                        float(
                            row.metrics
                            .conversions
                            or 0
                        ),
                    "conversion_value":
                        float(
                            row.metrics
                            .conversions_value
                            or 0
                        ),
                }
            )

        return items

    def _workspace_keywords_sync(
        self,
        *,
        campaign_id: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        campaign_id = _clean_customer_id(
            campaign_id
        )

        client = self._get_client()

        service = client.get_service(
            "GoogleAdsService"
        )

        query = f"""
            SELECT
                ad_group.id,
                ad_group.name,
                ad_group_criterion.criterion_id,
                ad_group_criterion.keyword.text,
                ad_group_criterion.keyword.match_type,
                ad_group_criterion.status,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions,
                metrics.conversions_value
            FROM keyword_view
            WHERE campaign.id = {campaign_id}
              AND ad_group_criterion.status != 'REMOVED'
              AND segments.date BETWEEN
                  '{start_date.isoformat()}'
                  AND
                  '{end_date.isoformat()}'
            ORDER BY
                ad_group_criterion.criterion_id
        """

        rows = service.search(
            customer_id=self.customer_id,
            query=query,
        )

        items = []

        for row in rows:
            items.append(
                {
                    "criterion_id":
                        str(
                            row.ad_group_criterion
                            .criterion_id
                        ),
                    "keyword":
                        str(
                            row.ad_group_criterion
                            .keyword.text
                            or ""
                        ),
                    "match_type":
                        self._enum_name(
                            row.ad_group_criterion
                            .keyword.match_type
                        ),
                    "status":
                        self._enum_name(
                            row.ad_group_criterion
                            .status
                        ),
                    "ad_group_id":
                        str(
                            row.ad_group.id
                        ),
                    "ad_group_name":
                        str(
                            row.ad_group.name
                            or ""
                        ),
                    "impressions":
                        int(
                            row.metrics.impressions
                            or 0
                        ),
                    "clicks":
                        int(
                            row.metrics.clicks
                            or 0
                        ),
                    "spend":
                        float(
                            _micros_to_decimal(
                                row.metrics
                                .cost_micros
                            )
                        ),
                    "conversions":
                        float(
                            row.metrics
                            .conversions
                            or 0
                        ),
                    "conversion_value":
                        float(
                            row.metrics
                            .conversions_value
                            or 0
                        ),
                }
            )

        return items

    def _workspace_conversion_actions_sync(
        self,
    ) -> list[dict[str, Any]]:
        client = self._get_client()

        service = client.get_service(
            "GoogleAdsService"
        )

        query = """
            SELECT
                conversion_action.id,
                conversion_action.name,
                conversion_action.status,
                conversion_action.type,
                conversion_action.category,
                conversion_action.primary_for_goal
            FROM conversion_action
            WHERE conversion_action.status != 'REMOVED'
            ORDER BY conversion_action.id
        """

        rows = service.search(
            customer_id=self.customer_id,
            query=query,
        )

        items = []

        for row in rows:
            action = row.conversion_action

            items.append(
                {
                    "conversion_action_id":
                        str(action.id),
                    "name":
                        str(
                            action.name
                            or ""
                        ),
                    "status":
                        self._enum_name(
                            action.status
                        ),
                    "type":
                        self._enum_name(
                            action.type
                        ),
                    "category":
                        self._enum_name(
                            action.category
                        ),
                    "primary_for_goal":
                        bool(
                            action.primary_for_goal
                        ),
                }
            )

        return items

    async def workspace_overview(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        campaigns = await self.workspace_campaigns(
            start_date=start_date,
            end_date=end_date,
        )

        totals = {
            "impressions": 0,
            "clicks": 0,
            "spend": 0.0,
            "conversions": 0.0,
            "conversion_value": 0.0,
        }

        active = 0
        paused = 0

        for campaign in campaigns:
            metrics = (
                campaign.get("metrics")
                or {}
            )

            totals["impressions"] += int(
                metrics.get("impressions")
                or 0
            )

            totals["clicks"] += int(
                metrics.get("clicks")
                or 0
            )

            totals["spend"] += float(
                metrics.get("spend")
                or 0
            )

            totals["conversions"] += float(
                metrics.get("conversions")
                or 0
            )

            totals["conversion_value"] += float(
                metrics.get(
                    "conversion_value"
                )
                or 0
            )

            status = str(
                campaign.get("status")
                or ""
            ).upper()

            if status == "ENABLED":
                active += 1
            elif status == "PAUSED":
                paused += 1

        totals["ctr"] = self._safe_ratio(
            totals["clicks"],
            totals["impressions"],
        )

        totals["average_cpc"] = (
            self._safe_ratio(
                totals["spend"],
                totals["clicks"],
            )
        )

        totals["cpa"] = self._safe_ratio(
            totals["spend"],
            totals["conversions"],
        )

        totals["roas"] = self._safe_ratio(
            totals["conversion_value"],
            totals["spend"],
        )

        return {
            "provider": self.provider,
            "customer_id": self.customer_id,
            "start_date":
                start_date.isoformat(),
            "end_date":
                end_date.isoformat(),
            "campaign_count":
                len(campaigns),
            "enabled_campaigns":
                active,
            "paused_campaigns":
                paused,
            "metrics": totals,
        }

    async def workspace_campaign_detail(
        self,
        *,
        campaign_id: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        campaigns = await asyncio.to_thread(
            self._workspace_campaigns_sync,
            start_date=start_date,
            end_date=end_date,
            campaign_id=campaign_id,
        )

        if not campaigns:
            raise LookupError(
                "campaign_not_found"
            )

        ad_groups, ads, keywords, conversions = (
            await asyncio.gather(
                asyncio.to_thread(
                    self._workspace_ad_groups_sync,
                    campaign_id=campaign_id,
                    start_date=start_date,
                    end_date=end_date,
                ),
                asyncio.to_thread(
                    self._workspace_ads_sync,
                    campaign_id=campaign_id,
                    start_date=start_date,
                    end_date=end_date,
                ),
                asyncio.to_thread(
                    self._workspace_keywords_sync,
                    campaign_id=campaign_id,
                    start_date=start_date,
                    end_date=end_date,
                ),
                asyncio.to_thread(
                    self._workspace_conversion_actions_sync,
                ),
            )
        )

        return {
            "campaign": campaigns[0],
            "ad_groups": ad_groups,
            "ads": ads,
            "keywords": keywords,
            "conversion_actions":
                conversions,
        }

    async def execute_action(
        self,
        *,
        action_type: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        action: str | None = None,
    ) -> dict[str, Any]:
        """Execute one approved Google Ads mutation.

        This method assumes the caller has already enforced:
        - human approval;
        - provider execution policy;
        - allowed action contract;
        - idempotency;
        - PHI/credential payload restrictions.

        Permanent deletion and billing/payment mutations are not
        implemented.
        """

        if action is not None:
            raise RuntimeError(
                "legacy Google Ads execution action is not enabled"
            )

        payload = dict(payload or {})

        action_type = str(
            action_type or ""
        ).strip().lower()

        if action_type == "campaign.create":
            result = await asyncio.to_thread(
                self._create_campaign_sync,
                payload=payload,
            )

            resource = result[
                "campaign_resource_name"
            ]

            campaign_id = resource.rsplit(
                "/",
                1,
            )[-1]

            verification = await asyncio.to_thread(
                self._verify_campaign_sync,
                campaign_id=campaign_id,
            )

        elif action_type == "campaign.pause":
            if not target_id:
                raise ValueError(
                    "campaign target_id is required"
                )

            result = await asyncio.to_thread(
                self._set_campaign_status_sync,
                campaign_id=target_id,
                enabled=False,
            )

            verification = await asyncio.to_thread(
                self._verify_campaign_sync,
                campaign_id=target_id,
            )

        elif action_type == "campaign.resume":
            if not target_id:
                raise ValueError(
                    "campaign target_id is required"
                )

            result = await asyncio.to_thread(
                self._set_campaign_status_sync,
                campaign_id=target_id,
                enabled=True,
            )

            verification = await asyncio.to_thread(
                self._verify_campaign_sync,
                campaign_id=target_id,
            )

        elif action_type == "budget.update":
            if not target_id:
                raise ValueError(
                    "campaign target_id is required"
                )

            result = await asyncio.to_thread(
                self._update_budget_sync,
                campaign_id=target_id,
                payload=payload,
            )

            verification = await asyncio.to_thread(
                self._verify_campaign_sync,
                campaign_id=target_id,
            )

        else:
            raise ValueError(
                f"unsupported_live_action:{action_type}"
            )

        result["verification"] = verification
        result["verified"] = True

        return result

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
