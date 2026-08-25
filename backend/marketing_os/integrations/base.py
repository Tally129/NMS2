"""Base contract for Marketing OS external integrations."""

from abc import ABC, abstractmethod


class MarketingIntegration(ABC):
    provider: str = "unknown"

    @abstractmethod
    async def health(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def fetch_performance(self, **kwargs) -> dict:
        raise NotImplementedError

    async def execute_action(self, **kwargs) -> dict:
        raise RuntimeError(
            f"{self.provider} external writes are not enabled"
        )
