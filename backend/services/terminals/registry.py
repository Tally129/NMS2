from typing import Dict

from .base import TerminalProvider


_PROVIDERS: Dict[str, TerminalProvider] = {}


def register_terminal_provider(
    provider: TerminalProvider,
) -> None:
    if not provider.name:
        raise ValueError(
            "Terminal provider requires a name"
        )

    _PROVIDERS[provider.name] = provider


def get_terminal_provider(
    name: str,
) -> TerminalProvider:
    provider = _PROVIDERS.get(name)

    if provider is None:
        raise RuntimeError(
            f"Terminal provider '{name}' "
            "is not configured"
        )

    return provider


def configured_terminal_providers():
    return sorted(_PROVIDERS.keys())
