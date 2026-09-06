"""Meta (Facebook/Instagram) Marketing API integration — Graph API v21.

Read: ad account, campaigns → ad sets → ads (Meta hierarchy preserved),
insights at campaign/adset/ad level. Governed writes: pause/resume at each
level and controlled daily-budget updates, each followed by a readback.

Transport is injectable (``http``) so tests never hit the network. Credentials
come only from the server environment (never the browser).
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any, Callable, Optional

from .base import MarketingIntegration
from .paid_normalize import normalize_campaign_row

PROVIDER = "meta_ads"
ACCESS_TOKEN_ENV = "META_ADS_ACCESS_TOKEN"
APP_ID_ENV = "META_ADS_APP_ID"
APP_SECRET_ENV = "META_ADS_APP_SECRET"
ACCOUNT_ENV = "META_ADS_ACCOUNT_ID"
GRAPH_VERSION = os.environ.get("META_GRAPH_VERSION", "v21.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

CAMPAIGN_FIELDS = "id,name,status,effective_status,objective,daily_budget,lifetime_budget,start_time,stop_time,buying_type,updated_time"
ADSET_FIELDS = "id,name,campaign_id,status,effective_status,daily_budget,lifetime_budget,optimization_goal,billing_event,start_time,end_time,targeting"
AD_FIELDS = "id,name,adset_id,campaign_id,status,effective_status,creative{id,name}"
INSIGHT_FIELDS = "campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,objective,spend,impressions,reach,frequency,clicks,inline_link_clicks,ctr,cpc,cpm,actions,action_values,cost_per_action_type,purchase_roas,date_start,date_stop"
CONVERSION_ACTION_TYPES = ("lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead",
                           "purchase", "offsite_conversion.fb_pixel_purchase", "omni_purchase",
                           "schedule", "onsite_conversion.messaging_conversation_started_7d", "complete_registration")
SUPPORTED_ACTIONS = {"campaign.pause", "campaign.resume", "adset.pause", "adset.resume", "ad.pause", "ad.resume", "campaign.budget_update", "adset.budget_update"}


class MetaAdsError(RuntimeError):
    pass


REQUIRED_ENV = (ACCESS_TOKEN_ENV, APP_ID_ENV, APP_SECRET_ENV, ACCOUNT_ENV)


def credential_readiness() -> dict:
    """not_connected (nothing configured) / configuration_incomplete /
    connected. Same contract the paid-media readiness layer already expects."""
    present = {n: bool((os.environ.get(n) or "").strip()) for n in REQUIRED_ENV}
    missing = [n for n, ok in present.items() if not ok]
    if not any(present.values()):
        status = "not_connected"
    elif missing:
        status = "configuration_incomplete"
    else:
        status = "connected"
    return {"provider": PROVIDER, "connected": status == "connected", "status": status, "missing": missing,
            "account_configured": present[ACCOUNT_ENV], "credentials_present": present[ACCESS_TOKEN_ENV],
            "read_only": False, "graph_version": GRAPH_VERSION}


def _dec(v: Any) -> Optional[Decimal]:
    try:
        return None if v in (None, "") else Decimal(str(v))
    except Exception:
        return None


def _action_sum(actions: Any, types=CONVERSION_ACTION_TYPES) -> Optional[Decimal]:
    if not isinstance(actions, list):
        return None
    total, seen = Decimal(0), False
    for a in actions:
        if isinstance(a, dict) and a.get("action_type") in types:
            v = _dec(a.get("value"))
            if v is not None:
                total += v; seen = True
    return total if seen else None


def normalize_insight_row(row: dict, *, account_id: str, level: str = "campaign") -> dict:
    """Map one Meta insights row onto the shared canonical schema while
    keeping Meta-specific metrics (reach, frequency, cpm, link clicks,
    results by action type) in ``raw``."""
    conversions = _action_sum(row.get("actions"))
    value = _action_sum(row.get("action_values"), ("purchase", "offsite_conversion.fb_pixel_purchase", "omni_purchase"))
    roas_items = row.get("purchase_roas")
    roas = _dec(roas_items[0].get("value")) if isinstance(roas_items, list) and roas_items and isinstance(roas_items[0], dict) else None
    canonical = normalize_campaign_row(PROVIDER, {
        "account_id": account_id, "campaign_id": row.get("campaign_id"), "campaign_name": row.get("campaign_name"),
        "campaign_type": "meta_" + str(row.get("objective") or "unknown").lower(), "status": row.get("effective_status") or row.get("status"),
        "objective": row.get("objective"), "daily_budget": row.get("daily_budget"),
        "spend": row.get("spend"), "impressions": row.get("impressions"), "clicks": row.get("clicks"), "ctr": row.get("ctr"),
        "conversions": conversions, "leads": _action_sum(row.get("actions"), ("lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead")),
        "revenue": value, "metric_date": row.get("date_start"),
    })
    canonical["level"] = level
    canonical["adset_id"] = row.get("adset_id"); canonical["adset_name"] = row.get("adset_name")
    canonical["ad_id"] = row.get("ad_id"); canonical["ad_name"] = row.get("ad_name")
    canonical["raw"] = {k: row.get(k) for k in ("reach", "frequency", "cpm", "cpc", "inline_link_clicks", "actions", "action_values", "cost_per_action_type", "purchase_roas", "date_start", "date_stop")}
    if roas is not None:
        canonical["roas"] = float(roas)
    return canonical


class MetaAdsIntegration(MarketingIntegration):
    provider = PROVIDER

    def __init__(self, *, account: Optional[dict] = None, http: Optional[Callable[..., dict]] = None, **_legacy):
        self._account = account or {}
        self._http = http  # callable(method, path, params=None, data=None) -> dict

    # ------------------------------------------------------------ transport
    def _request(self, method: str, path: str, params: dict | None = None, data: dict | None = None) -> dict:
        if self._http is not None:
            return self._http(method, path, params=params or {}, data=data or {})
        readiness = credential_readiness()
        if not readiness["connected"]:
            raise MetaAdsError(f"meta_ads not connected: missing {readiness['missing']}")
        import httpx
        params = dict(params or {}); params["access_token"] = os.environ.get(ACCESS_TOKEN_ENV)
        with httpx.Client(timeout=30) as client:
            resp = client.request(method, f"{GRAPH_BASE}/{path.lstrip('/')}", params=params, data=data or None)
        payload = resp.json() if resp.content else {}
        if resp.status_code >= 400 or "error" in payload:
            err = (payload.get("error") or {}) if isinstance(payload, dict) else {}
            raise MetaAdsError(f"meta_ads {resp.status_code}: {err.get('message') or 'request failed'} (code {err.get('code')})")
        return payload

    def _paged(self, path: str, params: dict, max_pages: int = 20) -> list[dict]:
        rows, after, pages = [], None, 0
        while pages < max_pages:
            p = dict(params); p["limit"] = p.get("limit", 200)
            if after:
                p["after"] = after
            payload = self._request("GET", path, params=p)
            rows.extend([r for r in payload.get("data") or [] if isinstance(r, dict)])
            after = ((payload.get("paging") or {}).get("cursors") or {}).get("after")
            pages += 1
            if not after or not (payload.get("paging") or {}).get("next"):
                break
        return rows

    def _account_id(self) -> str:
        acc = str(self._account.get("external_account_id") or os.environ.get(ACCOUNT_ENV) or "").strip()
        if not acc:
            raise MetaAdsError("meta_ads account id missing")
        return acc if acc.startswith("act_") else f"act_{acc}"

    async def health(self) -> dict:
        return {**credential_readiness(), "read_only": False}

    # ---------------------------------------------------------------- reads
    async def fetch_account(self) -> dict:
        return self._request("GET", self._account_id(), params={"fields": "id,name,account_status,currency,timezone_name,amount_spent,balance"})

    async def fetch_campaigns(self) -> list[dict]:
        return self._paged(f"{self._account_id()}/campaigns", {"fields": CAMPAIGN_FIELDS})

    async def fetch_adsets(self, campaign_id: str | None = None) -> list[dict]:
        path = f"{campaign_id}/adsets" if campaign_id else f"{self._account_id()}/adsets"
        return self._paged(path, {"fields": ADSET_FIELDS})

    async def fetch_ads(self, adset_id: str | None = None) -> list[dict]:
        path = f"{adset_id}/ads" if adset_id else f"{self._account_id()}/ads"
        return self._paged(path, {"fields": AD_FIELDS})

    async def fetch_insights(self, *, start_date: str, end_date: str, level: str = "campaign", daily: bool = True) -> list[dict]:
        if level not in {"campaign", "adset", "ad"}:
            raise ValueError("level must be campaign|adset|ad")
        params = {"fields": INSIGHT_FIELDS, "level": level, "time_range": f'{{"since":"{start_date}","until":"{end_date}"}}'}
        if daily:
            params["time_increment"] = "1"
        return self._paged(f"{self._account_id()}/insights", params)

    async def fetch_performance(self, **kwargs) -> dict:
        account_id = self._account_id()
        rows = await self.fetch_insights(start_date=kwargs.get("start_date"), end_date=kwargs.get("end_date"), level=kwargs.get("level", "campaign"))
        status_by_campaign = {}
        if kwargs.get("include_status", True):
            try:
                status_by_campaign = {c["id"]: c for c in await self.fetch_campaigns()}
            except MetaAdsError:
                status_by_campaign = {}
        out = []
        for r in rows:
            meta = status_by_campaign.get(str(r.get("campaign_id")), {})
            out.append(normalize_insight_row({**r, "effective_status": meta.get("effective_status"), "daily_budget": _budget_units(meta.get("daily_budget"))}, account_id=account_id, level=kwargs.get("level", "campaign")))
        return {"provider": PROVIDER, "account_id": account_id, "read_only": False, "external_write": False, "rows": out}

    # ------------------------------------------------------------ mutations
    async def execute_action(self, *, action: str, resource_id: str, params: dict | None = None, dry_run: bool = False, **_ignored) -> dict:
        """Governed mutation. Only called through the Marketing OS execution
        queue (request → approval → dry-run → live). Returns a readback."""
        if action not in SUPPORTED_ACTIONS:
            raise MetaAdsError(f"unsupported meta action: {action}")
        params = dict(params or {})
        level, verb = action.split(".", 1)
        data: dict[str, Any]
        if verb == "pause":
            data = {"status": "PAUSED"}
        elif verb == "resume":
            data = {"status": "ACTIVE"}
        else:
            budget = _dec(params.get("daily_budget"))
            if budget is None or budget <= 0:
                raise MetaAdsError("daily_budget (account currency units) required and > 0")
            data = {"daily_budget": str(int(budget * 100))}  # Meta expects minor units
        before = self._request("GET", resource_id, params={"fields": "id,name,status,effective_status,daily_budget"})
        if dry_run:
            return {"provider": PROVIDER, "action": action, "resource_id": resource_id, "dry_run": True, "before": before, "would_send": data, "external_write": False}
        result = self._request("POST", resource_id, data=data)
        after = self._request("GET", resource_id, params={"fields": "id,name,status,effective_status,daily_budget"})
        expected_ok = (after.get("status") == data.get("status")) if "status" in data else (str(after.get("daily_budget")) == data["daily_budget"])
        return {"provider": PROVIDER, "action": action, "resource_id": resource_id, "dry_run": False, "external_write": True,
                "before": before, "sent": data, "provider_result": result, "after": after, "readback_verified": bool(expected_ok), "level": level}


def _budget_units(minor: Any) -> Optional[float]:
    d = _dec(minor)
    return None if d is None else float(d / 100)


__all__ = ["MetaAdsIntegration", "MetaAdsError", "PROVIDER", "SUPPORTED_ACTIONS", "credential_readiness", "normalize_insight_row"]
