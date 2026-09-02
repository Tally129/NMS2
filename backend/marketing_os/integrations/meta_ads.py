"""Meta Ads — READ-ONLY provider adapter (provider key: meta_ads).

Credentials come only from environment. Construction/readiness perform NO
network call. Lazy SDK import. No write operations.
"""
from __future__ import annotations

import os
from typing import Optional

from .base import MarketingIntegration
from .paid_normalize import normalize_campaign_row

PROVIDER = "meta_ads"
ACCESS_TOKEN_ENV = "META_ADS_ACCESS_TOKEN"
ACCOUNT_ENV = "META_ADS_ACCOUNT_ID"
APP_ID_ENV = "META_ADS_APP_ID"
APP_SECRET_ENV = "META_ADS_APP_SECRET"

STATE_NOT_CONNECTED = "not_connected"
STATE_CONFIG_INCOMPLETE = "configuration_incomplete"
STATE_CONNECTED = "connected"


def credential_readiness() -> dict:
    token = (os.environ.get(ACCESS_TOKEN_ENV) or "").strip()
    account = (os.environ.get(ACCOUNT_ENV) or "").strip()
    app_id = (os.environ.get(APP_ID_ENV) or "").strip()
    if not token and not account:
        status = STATE_NOT_CONNECTED
    elif not (token and account and app_id):
        status = STATE_CONFIG_INCOMPLETE
    else:
        status = STATE_CONNECTED
    return {
        "provider": PROVIDER, "status": status,
        "connected": status == STATE_CONNECTED,
        "account_configured": bool(account),
        "credentials_present": bool(token),
        "read_only": True, "external_write": False,
        "env": {"access_token": ACCESS_TOKEN_ENV, "account_id": ACCOUNT_ENV,
                "app_id": APP_ID_ENV, "app_secret": APP_SECRET_ENV},
    }


class MetaAdsIntegration(MarketingIntegration):
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
            raise RuntimeError(f"meta_ads not connected: {readiness['status']}")
        from facebook_business.api import FacebookAdsApi  # lazy
        self._client = FacebookAdsApi.init(
            app_id=os.environ.get(APP_ID_ENV),
            app_secret=os.environ.get(APP_SECRET_ENV),
            access_token=os.environ.get(ACCESS_TOKEN_ENV))
        return self._client

    async def fetch_performance(self, **kwargs) -> dict:
        client = self._get_client()
        account_id = (self._account.get("external_account_id")
                      or os.environ.get(ACCOUNT_ENV))
        raw_rows = client.fetch_campaign_insights(
            account_id=account_id,
            start_date=kwargs.get("start_date"),
            end_date=kwargs.get("end_date"))
        rows = [normalize_campaign_row(PROVIDER, r) for r in (raw_rows or [])]
        return {"provider": PROVIDER, "account_id": account_id,
                "read_only": True, "external_write": False, "rows": rows}
