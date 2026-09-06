"""Microsoft Advertising (Bing Ads) integration — REST API v13.

Auth: OAuth refresh-token → access token (Microsoft identity platform).
Reads: accounts, campaigns (Campaign Management REST), campaign performance
(Reporting REST: submit → poll → download CSV, aggregated per campaign/day).
Governed writes: pause/resume campaign, controlled daily budget updates, each
followed by a readback. Transport is injectable (``http``) for tests.
"""

from __future__ import annotations

import csv
import io
import os
import time
from decimal import Decimal
from typing import Any, Callable, Optional

from .base import MarketingIntegration
from .paid_normalize import normalize_campaign_row

PROVIDER = "microsoft_ads"
DEV_TOKEN_ENV = "MICROSOFT_ADS_DEVELOPER_TOKEN"
CLIENT_ID_ENV = "MICROSOFT_ADS_CLIENT_ID"
CLIENT_SECRET_ENV = "MICROSOFT_ADS_CLIENT_SECRET"
REFRESH_TOKEN_ENV = "MICROSOFT_ADS_REFRESH_TOKEN"
CUSTOMER_ENV = "MICROSOFT_ADS_CUSTOMER_ID"
ACCOUNT_ENV = "MICROSOFT_ADS_ACCOUNT_ID"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
CM_BASE = "https://campaign.api.bingads.microsoft.com/CampaignManagement/v13"
REPORT_BASE = "https://reporting.api.bingads.microsoft.com/Reporting/v13"
SUPPORTED_ACTIONS = {"campaign.pause", "campaign.resume", "campaign.budget_update"}
REPORT_COLUMNS = ["TimePeriod", "CampaignId", "CampaignName", "CampaignStatus", "CampaignType", "Impressions", "Clicks", "Ctr",
                  "AverageCpc", "Spend", "Conversions", "ConversionRate", "CostPerConversion", "Revenue", "ReturnOnAdSpend", "DeviceType", "Network"]


class MicrosoftAdsError(RuntimeError):
    pass


REQUIRED_ENV = (DEV_TOKEN_ENV, CLIENT_ID_ENV, REFRESH_TOKEN_ENV, ACCOUNT_ENV)
OPTIONAL_ENV = (CLIENT_SECRET_ENV, CUSTOMER_ENV)  # public-client flows have no secret


def credential_readiness() -> dict:
    present = {n: bool((os.environ.get(n) or "").strip()) for n in REQUIRED_ENV}
    missing = [n for n, ok in present.items() if not ok]
    if not any(present.values()):
        status = "not_connected"
    elif missing:
        status = "configuration_incomplete"
    else:
        status = "connected"
    return {"provider": PROVIDER, "connected": status == "connected", "status": status, "missing": missing,
            "account_configured": present[ACCOUNT_ENV], "credentials_present": present[REFRESH_TOKEN_ENV],
            "read_only": False}


def _dec(v: Any) -> Optional[Decimal]:
    try:
        return None if v in (None, "") else Decimal(str(v).replace("%", "").replace(",", ""))
    except Exception:
        return None


def normalize_report_row(row: dict, *, account_id: str) -> dict:
    """One Reporting CSV row → canonical schema; Microsoft-specific values
    (device, network, conversion rate, ROAS as reported) kept in ``raw``."""
    canonical = normalize_campaign_row(PROVIDER, {
        "account_id": account_id, "campaign_id": row.get("CampaignId"), "campaign_name": row.get("CampaignName"),
        "campaign_type": "microsoft_" + str(row.get("CampaignType") or "search").lower().replace(" ", "_"),
        "status": row.get("CampaignStatus"), "spend": row.get("Spend"), "impressions": row.get("Impressions"), "clicks": row.get("Clicks"),
        "ctr": _dec(row.get("Ctr")) / 100 if _dec(row.get("Ctr")) is not None else None, "conversions": row.get("Conversions"),
        "revenue": row.get("Revenue"), "metric_date": row.get("TimePeriod"),
    })
    roas = _dec(row.get("ReturnOnAdSpend"))
    if roas is not None:
        canonical["roas"] = float(roas)
    canonical["raw"] = {k: row.get(k) for k in ("DeviceType", "Network", "ConversionRate", "CostPerConversion", "AverageCpc", "ReturnOnAdSpend")}
    return canonical


class MicrosoftAdsIntegration(MarketingIntegration):
    provider = PROVIDER

    def __init__(self, *, account: Optional[dict] = None, http: Optional[Callable[..., Any]] = None, sleep=time.sleep, **_legacy):
        self._account = account or {}
        self._http = http  # callable(method, url, headers=None, json=None, data=None) -> (status, body)
        self._sleep = sleep
        self._token: Optional[str] = None

    # ------------------------------------------------------------ transport
    def _raw(self, method: str, url: str, headers: dict | None = None, json: Any = None, data: Any = None):
        if self._http is not None:
            return self._http(method, url, headers=headers or {}, json=json, data=data)
        import httpx
        with httpx.Client(timeout=60) as client:
            resp = client.request(method, url, headers=headers, json=json, data=data)
        body: Any
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
        return resp.status_code, body

    def _access_token(self) -> str:
        if self._token:
            return self._token
        readiness = credential_readiness()
        if not readiness["connected"] and self._http is None:
            raise MicrosoftAdsError(f"microsoft_ads not connected: missing {readiness['missing']}")
        status, body = self._raw("POST", TOKEN_URL, data={
            "client_id": os.environ.get(CLIENT_ID_ENV), "client_secret": os.environ.get(CLIENT_SECRET_ENV),
            "refresh_token": os.environ.get(REFRESH_TOKEN_ENV), "grant_type": "refresh_token",
            "scope": "https://ads.microsoft.com/msads.manage offline_access"})
        if status >= 400 or not isinstance(body, dict) or not body.get("access_token"):
            raise MicrosoftAdsError(f"microsoft_ads token refresh failed ({status})")
        self._token = body["access_token"]
        return self._token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token()}", "DeveloperToken": os.environ.get(DEV_TOKEN_ENV, ""),
                "CustomerId": os.environ.get(CUSTOMER_ENV) or self._account_id(), "CustomerAccountId": self._account_id(), "Content-Type": "application/json"}

    def _call(self, base: str, op: str, payload: dict) -> dict:
        status, body = self._raw("POST", f"{base}/{op}", headers=self._headers(), json=payload)
        if status >= 400 or not isinstance(body, dict):
            raise MicrosoftAdsError(f"microsoft_ads {op} failed ({status}): {str(body)[:200]}")
        errors = body.get("PartialErrors") or body.get("OperationErrors") or []
        if errors:
            raise MicrosoftAdsError(f"microsoft_ads {op} errors: {str(errors)[:300]}")
        return body

    def _account_id(self) -> str:
        acc = str(self._account.get("external_account_id") or os.environ.get(ACCOUNT_ENV) or "").strip()
        if not acc:
            raise MicrosoftAdsError("microsoft_ads account id missing")
        return acc

    async def health(self) -> dict:
        return {**credential_readiness(), "read_only": False}

    # ---------------------------------------------------------------- reads
    async def fetch_account(self) -> dict:
        body = self._call("https://clientcenter.api.bingads.microsoft.com/CustomerManagement/v13", "Account/Query", {"AccountId": int(self._account_id())})
        return body.get("Account") or body

    async def fetch_campaigns(self) -> list[dict]:
        body = self._call(CM_BASE, "Campaigns/QueryByAccountId", {"AccountId": self._account_id(), "CampaignType": "Search Shopping DynamicSearchAds Audience PerformanceMax", "ReturnAdditionalFields": "BudgetId"})
        return [c for c in body.get("Campaigns") or [] if isinstance(c, dict)]

    async def fetch_performance(self, **kwargs) -> dict:
        account_id = self._account_id()
        start, end = kwargs.get("start_date"), kwargs.get("end_date")
        req = {"ReportRequest": {"Type": "CampaignPerformanceReportRequest", "ExcludeColumnHeaders": False, "ExcludeReportFooter": True, "ExcludeReportHeader": True,
               "Format": "Csv", "ReportName": "NMS campaign performance", "ReturnOnlyCompleteData": False, "Aggregation": "Daily",
               "Columns": REPORT_COLUMNS if kwargs.get("segment") else [c for c in REPORT_COLUMNS if c not in ("DeviceType", "Network")],
               "Scope": {"AccountIds": [int(account_id)]},
               "Time": {"CustomDateRangeStart": _ymd(start), "CustomDateRangeEnd": _ymd(end), "ReportTimeZone": "PacificTimeUSCanadaTijuana"}}}
        submit = self._call(REPORT_BASE, "GenerateReport/Submit", req)
        request_id = submit.get("ReportRequestId")
        if not request_id:
            raise MicrosoftAdsError("microsoft_ads report submit returned no ReportRequestId")
        download_url = None
        for _ in range(int(kwargs.get("max_polls", 20))):
            poll = self._call(REPORT_BASE, "GenerateReport/Poll", {"ReportRequestId": request_id})
            status_obj = poll.get("ReportRequestStatus") or {}
            state = status_obj.get("Status")
            if state == "Success":
                download_url = status_obj.get("ReportDownloadUrl"); break
            if state == "Error":
                raise MicrosoftAdsError("microsoft_ads report generation failed")
            self._sleep(float(kwargs.get("poll_seconds", 3)))
        rows: list[dict] = []
        if download_url:  # empty report => no URL, zero rows
            status, body = self._raw("GET", download_url)
            if status >= 400:
                raise MicrosoftAdsError(f"microsoft_ads report download failed ({status})")
            text_body = body if isinstance(body, str) else (body.decode() if isinstance(body, bytes) else "")
            rows = [normalize_report_row(r, account_id=account_id) for r in csv.DictReader(io.StringIO(text_body)) if r.get("CampaignId")]
        return {"provider": PROVIDER, "account_id": account_id, "read_only": False, "external_write": False, "rows": rows, "report_request_id": request_id}

    # ------------------------------------------------------------ mutations
    async def execute_action(self, *, action: str, resource_id: str, params: dict | None = None, dry_run: bool = False, **_ignored) -> dict:
        if action not in SUPPORTED_ACTIONS:
            raise MicrosoftAdsError(f"unsupported microsoft action: {action}")
        params = dict(params or {})
        before_body = self._call(CM_BASE, "Campaigns/QueryByIds", {"AccountId": self._account_id(), "CampaignIds": [int(resource_id)]})
        before = (before_body.get("Campaigns") or [None])[0]
        if not before:
            raise MicrosoftAdsError(f"campaign {resource_id} not found")
        update: dict[str, Any] = {"Id": int(resource_id)}
        if action == "campaign.pause":
            update["Status"] = "Paused"
        elif action == "campaign.resume":
            update["Status"] = "Active"
        else:
            budget = _dec(params.get("daily_budget"))
            if budget is None or budget <= 0:
                raise MicrosoftAdsError("daily_budget required and > 0")
            update["DailyBudget"] = float(budget); update["BudgetType"] = "DailyBudgetStandard"
        if dry_run:
            return {"provider": PROVIDER, "action": action, "resource_id": resource_id, "dry_run": True, "before": before, "would_send": update, "external_write": False}
        result = self._call(CM_BASE, "Campaigns", {"AccountId": self._account_id(), "Campaigns": [update]})
        after_body = self._call(CM_BASE, "Campaigns/QueryByIds", {"AccountId": self._account_id(), "CampaignIds": [int(resource_id)]})
        after = (after_body.get("Campaigns") or [{}])[0]
        verified = (after.get("Status") == update["Status"]) if "Status" in update else (_dec(after.get("DailyBudget")) == _dec(update["DailyBudget"]))
        return {"provider": PROVIDER, "action": action, "resource_id": resource_id, "dry_run": False, "external_write": True,
                "before": before, "sent": update, "provider_result": result, "after": after, "readback_verified": bool(verified)}


def _ymd(value: str | None) -> dict:
    if not value:
        raise MicrosoftAdsError("start_date/end_date required (YYYY-MM-DD)")
    y, m, d = str(value)[:10].split("-")
    return {"Year": int(y), "Month": int(m), "Day": int(d)}


__all__ = ["MicrosoftAdsIntegration", "MicrosoftAdsError", "PROVIDER", "SUPPORTED_ACTIONS", "credential_readiness", "normalize_report_row"]
