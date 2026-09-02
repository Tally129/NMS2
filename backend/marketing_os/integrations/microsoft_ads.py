"""Microsoft Advertising (Bing Ads) — READ-ONLY adapter (microsoft_ads).

Credentials env-only. Construction/readiness perform NO network call.
Lazy SDK import. No write operations.
"""
from __future__ import annotations

import os
from typing import Optional

from .base import MarketingIntegration
from .paid_normalize import normalize_campaign_row

PROVIDER = "microsoft_ads"
DEV_TOKEN_ENV = "MICROSOFT_ADS_DEVELOPER_TOKEN"
ACCOUNT_ENV = "MICROSOFT_ADS_ACCOUNT_ID"
CUSTOMER_ENV = "MICROSOFT_ADS_CUSTOMER_ID"
REFRESH_TOKEN_ENV = "MICROSOFT_ADS_REFRESH_TOKEN"
CLIENT_ID_ENV = "MICROSOFT_ADS_CLIENT_ID"

STATE_NOT_CONNECTED = "not_connected"
STATE_CONFIG_INCOMPLETE = "configuration_incomplete"
STATE_CONNECTED = "connected"


def credential_readiness() -> dict:
    dev = (os.environ.get(DEV_TOKEN_ENV) or "").strip()
    account = (os.environ.get(ACCOUNT_ENV) or "").strip()
    refresh = (os.environ.get(REFRESH_TOKEN_ENV) or "").strip()
    client_id = (os.environ.get(CLIENT_ID_ENV) or "").strip()
    if not dev and not account:
        status = STATE_NOT_CONNECTED
    elif not (dev and account and refresh and client_id):
        status = STATE_CONFIG_INCOMPLETE
    else:
        status = STATE_CONNECTED
    return {
        "provider": PROVIDER, "status": status,
        "connected": status == STATE_CONNECTED,
        "account_configured": bool(account),
        "credentials_present": bool(dev and refresh),
        "read_only": True, "external_write": False,
        "env": {"developer_token": DEV_TOKEN_ENV, "account_id": ACCOUNT_ENV,
                "customer_id": CUSTOMER_ENV,
                "refresh_token": REFRESH_TOKEN_ENV,
                "client_id": CLIENT_ID_ENV},
    }


class MicrosoftAdsIntegration(MarketingIntegration):
    provider = PROVIDER

    def __init__(self, *, account: Optional[dict] = None, client=None,
                 client_factory=None):
        self._account = account or {}
        self._client = client
        self._client_factory = client_factory

    async def health(self) -> dict:
        return {**credential_readiness(), "read_only": True}

    def _get_client(self):
        if self._client is not None:
            return self._client
        if self._client_factory is not None:
            self._client = self._client_factory()
            return self._client
        readiness = credential_readiness()
        if not readiness["connected"]:
            raise RuntimeError(
                f"microsoft_ads not connected: {readiness['status']}")
        from bingads.authorization import AuthorizationData  # lazy
        self._client = AuthorizationData(
            developer_token=os.environ.get(DEV_TOKEN_ENV))
        return self._client

    async def fetch_performance(self, **kwargs) -> dict:
        client = self._get_client()
        account_id = (self._account.get("external_account_id")
                      or os.environ.get(ACCOUNT_ENV))
        raw_rows = client.fetch_campaign_performance(
            account_id=account_id,
            start_date=kwargs.get("start_date"),
            end_date=kwargs.get("end_date"))
        rows = [normalize_campaign_row(PROVIDER, r) for r in (raw_rows or [])]
        return {"provider": PROVIDER, "account_id": account_id,
                "read_only": True, "external_write": False, "rows": rows}
