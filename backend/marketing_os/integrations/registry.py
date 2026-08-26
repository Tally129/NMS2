"""Marketing OS integration registry.

The registry resolves provider-specific read adapters without granting
permission to perform external writes.
"""

from __future__ import annotations

from collections.abc import Callable

from marketing_os.integrations.base import MarketingIntegration


IntegrationFactory = Callable[..., MarketingIntegration]

_REGISTRY: dict[str, IntegrationFactory] = {}


def normalize_provider(provider: str) -> str:
    """Return canonical provider identifier."""

    if not isinstance(provider, str):
        raise ValueError("provider must be a string")

    normalized = provider.strip().lower()

    if not normalized:
        raise ValueError("provider is required")

    if len(normalized) > 64:
        raise ValueError(
            "provider exceeds maximum length 64"
        )

    return normalized


def register_integration(
    provider: str,
    factory: IntegrationFactory,
    *,
    replace: bool = False,
) -> None:
    """Register a provider adapter factory."""

    normalized = normalize_provider(provider)

    if not callable(factory):
        raise TypeError(
            "integration factory must be callable"
        )

    if normalized in _REGISTRY and not replace:
        raise ValueError(
            f"integration already registered: {normalized}"
        )

    _REGISTRY[normalized] = factory


def unregister_integration(provider: str) -> None:
    """Remove a provider registration."""

    _REGISTRY.pop(
        normalize_provider(provider),
        None,
    )


def registered_providers() -> tuple[str, ...]:
    """Return registered providers in stable order."""

    return tuple(sorted(_REGISTRY))


def create_integration(
    provider: str,
    **kwargs,
) -> MarketingIntegration:
    """Instantiate one registered provider adapter."""

    normalized = normalize_provider(provider)

    factory = _REGISTRY.get(normalized)

    if factory is None:
        raise LookupError(
            f"no integration registered for provider: "
            f"{normalized}"
        )

    integration = factory(**kwargs)

    if not isinstance(
        integration,
        MarketingIntegration,
    ):
        raise TypeError(
            "integration factory must return "
            "MarketingIntegration"
        )

    actual_provider = normalize_provider(
        integration.provider
    )

    if actual_provider != normalized:
        raise ValueError(
            "integration provider mismatch: "
            f"registered={normalized}, "
            f"adapter={actual_provider}"
        )

    return integration
