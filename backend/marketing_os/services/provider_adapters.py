"""Phase 14 controlled provider adapter contracts.

All adapters in Phase 14B are DRY RUN ONLY.

No provider SDKs.
No HTTP calls.
No external mutations.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from marketing_os.services.execution_policy import (
    canonical_provider,
)


class AdapterError(RuntimeError):
    pass


class BaseMarketingProviderAdapter:
    provider = "unknown"
    live_execution_enabled = False

    def dry_run(
        self,
        *,
        action_type: str,
        target_type: str,
        target_id: str | None,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "action_type": str(action_type),
            "target_type": str(target_type),
            "target_id": (
                str(target_id)
                if target_id is not None
                else None
            ),
            "payload": dict(payload or {}),
            "status": "dry_run_validated",
            "dry_run": True,
            "external_write_performed": False,
            "live_execution_enabled": False,
        }

    async def execute(
        self,
        *,
        action_type: str,
        target_type: str,
        target_id: str | None,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        raise AdapterError("live_execution_not_enabled")


class GoogleAdsAdapter(BaseMarketingProviderAdapter):
    provider = "google_ads"


class MetaAdsAdapter(BaseMarketingProviderAdapter):
    provider = "meta_ads"


class MicrosoftAdsAdapter(BaseMarketingProviderAdapter):
    provider = "microsoft_ads"


_ADAPTERS = {
    "google_ads": GoogleAdsAdapter(),
    "meta_ads": MetaAdsAdapter(),
    "microsoft_ads": MicrosoftAdsAdapter(),
}


def get_provider_adapter(
    provider: str,
) -> BaseMarketingProviderAdapter:
    provider = canonical_provider(provider)

    adapter = _ADAPTERS.get(provider)

    if adapter is None:
        raise AdapterError("unsupported_provider")

    return adapter


__all__ = [
    "AdapterError",
    "BaseMarketingProviderAdapter",
    "GoogleAdsAdapter",
    "MetaAdsAdapter",
    "MicrosoftAdsAdapter",
    "get_provider_adapter",
]
