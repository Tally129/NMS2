"""Deterministic, idempotent, LOCAL-ONLY paid-media provider bootstrap.

Registers read-only ad provider adapters into the integration registry.
No network/API calls. Registration grants read-only resolution only — it
enables NO external writes (governed by marketing_os.policy.DEFAULT_POLICY
and the adapter contract).
"""
from __future__ import annotations

from .google_ads import PROVIDER as GOOGLE_ADS_PROVIDER, GoogleAdsIntegration
from .meta_ads import PROVIDER as META_PROVIDER, MetaAdsIntegration
from .microsoft_ads import (
    PROVIDER as MICROSOFT_PROVIDER, MicrosoftAdsIntegration)
from .registry import register_integration, registered_providers

_DEFAULTS = (
    (GOOGLE_ADS_PROVIDER, GoogleAdsIntegration),
    (META_PROVIDER, MetaAdsIntegration),
    (MICROSOFT_PROVIDER, MicrosoftAdsIntegration),
)


def register_default_integrations() -> tuple[str, ...]:
    existing = set(registered_providers())
    for provider, factory in _DEFAULTS:
        if provider not in existing:
            register_integration(provider, factory)
    return registered_providers()
