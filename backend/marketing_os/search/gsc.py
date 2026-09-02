"""Google Search Console — READ-ONLY provider adapter + normalization.

Implements the minimal safe read-only pattern (service-account auth,
`webmasters.readonly` scope, `searchconsole v1`, `searchanalytics().query`).

Safety:
- READ-ONLY. Only searchanalytics().query() is ever called. No write /
  sitemap / property-mutation methods are used.
- Credentials come only from environment (or a mounted secret file). They
  are never logged, returned, or persisted.
- Lazy import: the app boots without the Google client installed/configured.
- readiness() is a pure environment/format check and performs NO network
  call (safe to run during provider registration / health).
- An injectable client_factory is the seam used by tests (no live calls).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

PROVIDER = "google_search_console"
READONLY_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"

PROPERTY_ENV = "GOOGLE_SEARCH_CONSOLE_PROPERTY"
SA_JSON_ENV = "GOOGLE_SERVICE_ACCOUNT_JSON"
SA_FILE_ENV = "GOOGLE_SERVICE_ACCOUNT_JSON_FILE"

_ALLOWED_DIMENSIONS = frozenset(
    {"date", "query", "page", "device", "country"}
)
_WS = re.compile(r"\s+")

# Readiness state machine values (deterministic, UI-facing).
STATE_NOT_CONNECTED = "not_connected"
STATE_CONFIG_INCOMPLETE = "configuration_incomplete"
STATE_CONNECTED = "connected"
STATE_READ_ERROR = "read_error"


def normalize_query_text(value: Any) -> str:
    if value is None:
        return ""
    return _WS.sub(" ", str(value).strip()).lower()


def _read_credentials_raw() -> Optional[str]:
    sa_json = (os.environ.get(SA_JSON_ENV) or "").strip()
    if sa_json:
        return sa_json
    sa_file = (os.environ.get(SA_FILE_ENV) or "").strip()
    if sa_file:
        return Path(sa_file).read_text()
    return None


def credential_readiness() -> dict:
    """Pure environment/format check. NEVER performs a network call and
    NEVER exposes credential values."""
    property_ = (os.environ.get(PROPERTY_ENV) or "").strip()
    sa_json = (os.environ.get(SA_JSON_ENV) or "").strip()
    sa_file = (os.environ.get(SA_FILE_ENV) or "").strip()
    creds_present = bool(sa_json or sa_file)

    creds_valid: Optional[bool] = None
    missing_fields: list[str] = []
    if creds_present:
        try:
            raw = sa_json or Path(sa_file).read_text()
            obj = json.loads(raw)
            required = {"client_email", "private_key", "token_uri"}
            missing_fields = sorted(required - set(obj))
            creds_valid = not missing_fields
        except Exception:  # noqa: BLE001 - never leak details
            creds_valid = False

    if not property_ and not creds_present:
        status = STATE_NOT_CONNECTED
    elif not property_ or not creds_present or creds_valid is False:
        status = STATE_CONFIG_INCOMPLETE
    else:
        status = STATE_CONNECTED

    return {
        "provider": PROVIDER,
        "status": status,
        "connected": status == STATE_CONNECTED,
        "property_configured": bool(property_),
        "credentials_present": creds_present,
        "credentials_valid_format": creds_valid,
        "missing_credential_fields": missing_fields,
        "read_only": True,
        "external_write": False,
        "scope": READONLY_SCOPE,
        "env": {
            "property": PROPERTY_ENV,
            "service_account_json": SA_JSON_ENV,
            "service_account_json_file": SA_FILE_ENV,
        },
    }


def build_client(*, client_factory=None):
    """Construct a Search Console client. Lazy-imports Google libs.

    Tests inject `client_factory` to avoid any live/network call.
    """
    readiness = credential_readiness()
    if not readiness["connected"]:
        raise RuntimeError(
            f"google_search_console not connected: {readiness['status']}"
        )
    if client_factory is not None:
        return client_factory()

    from google.oauth2 import service_account  # lazy
    from googleapiclient.discovery import build  # lazy

    raw = _read_credentials_raw()
    info = json.loads(raw)
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=[READONLY_SCOPE]
    )
    return build(
        "searchconsole", "v1", credentials=credentials,
        cache_discovery=False,
    )


def query_search_analytics(
    client,
    *,
    property_id: str,
    start_date: str,
    end_date: str,
    dimensions: list[str],
    row_limit: int = 1000,
    start_row: int = 0,
    data_state: str = "final",
) -> dict:
    """Issue a single READ-ONLY searchanalytics().query() call."""
    invalid = [d for d in dimensions if d not in _ALLOWED_DIMENSIONS]
    if invalid:
        raise ValueError(f"unsupported dimensions: {invalid}")
    if not 1 <= row_limit <= 25000:
        raise ValueError("row_limit must be between 1 and 25000")

    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": dimensions,
        "type": "web",
        "rowLimit": row_limit,
        "startRow": start_row,
        "dataState": data_state,
    }
    return (
        client.searchanalytics()
        .query(siteUrl=property_id, body=body)
        .execute()
    )


class GoogleSearchConsoleAdapter:
    """Read-only GSC adapter. Constructing it performs NO network call."""

    provider = PROVIDER

    def __init__(self, *, property_id: Optional[str] = None, client=None,
                 client_factory=None):
        self._property = (
            property_id
            or (os.environ.get(PROPERTY_ENV) or "").strip()
            or None
        )
        self._client = client
        self._client_factory = client_factory

    def readiness(self) -> dict:
        return credential_readiness()

    @property
    def property_id(self) -> Optional[str]:
        return self._property

    def _get_client(self):
        if self._client is None:
            self._client = build_client(client_factory=self._client_factory)
        return self._client

    def fetch_search_analytics(
        self,
        *,
        start_date: str,
        end_date: str,
        dimensions: list[str],
        row_limit: int = 1000,
        start_row: int = 0,
        data_state: str = "final",
    ) -> dict:
        prop = self._property or (os.environ.get(PROPERTY_ENV) or "").strip()
        if not prop:
            raise RuntimeError("no Search Console property configured")
        return query_search_analytics(
            self._get_client(),
            property_id=prop,
            start_date=start_date,
            end_date=end_date,
            dimensions=dimensions,
            row_limit=row_limit,
            start_row=start_row,
            data_state=data_state,
        )

    # Read-only contract: no external writes are ever possible.
    def execute_action(self, *args, **kwargs):
        raise RuntimeError(
            "google_search_console is read-only; external writes are "
            "not enabled"
        )


# --------------------------------------------------------------------------
# Normalization (pure)
# --------------------------------------------------------------------------

def normalize_rows(response: Any, dimensions: list[str]) -> list[dict]:
    """Map a GSC query response into flat, typed rows."""
    rows = []
    if isinstance(response, dict):
        rows = response.get("rows", []) or []
    out: list[dict] = []
    for row in rows:
        keys = row.get("keys", []) or []
        entry: dict[str, Any] = {}
        for i, dim in enumerate(dimensions):
            entry[dim] = keys[i] if i < len(keys) else None
        entry["clicks"] = int(row.get("clicks", 0) or 0)
        entry["impressions"] = int(row.get("impressions", 0) or 0)
        entry["ctr"] = round(float(row.get("ctr", 0) or 0.0), 6)
        pos = row.get("position")
        entry["position"] = round(float(pos), 3) if pos is not None else None
        entry["source"] = PROVIDER
        out.append(entry)
    return out


def aggregate_totals(rows: list[dict]) -> dict:
    """Aggregate normalized rows. Position is impression-weighted (an
    approximation) and is explicitly a GSC average position, NOT a SERP
    rank."""
    clicks = sum(r.get("clicks", 0) for r in rows)
    impressions = sum(r.get("impressions", 0) for r in rows)
    ctr = (clicks / impressions) if impressions else 0.0
    weighted = sum(
        (r["position"] or 0) * r.get("impressions", 0)
        for r in rows
        if r.get("position") is not None
    )
    denom = sum(
        r.get("impressions", 0)
        for r in rows
        if r.get("position") is not None
    )
    avg_pos = (weighted / denom) if denom else None
    return {
        "clicks": clicks,
        "impressions": impressions,
        "ctr": round(ctr, 6),
        "average_position": round(avg_pos, 2) if avg_pos is not None else None,
        "source": PROVIDER,
        "metric_type": "gsc_average_position",
    }


def top_by_clicks(rows: list[dict], key: str, limit: int = 10) -> list[dict]:
    ranked = [r for r in rows if r.get(key)]
    ranked.sort(
        key=lambda r: (r.get("clicks", 0), r.get("impressions", 0)),
        reverse=True,
    )
    return ranked[:limit]
