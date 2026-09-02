"""Safety policy for Marketing OS external actions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketingActionPolicy:
    external_writes_enabled: bool = False
    automatic_budget_changes_enabled: bool = False
    automatic_campaign_creation_enabled: bool = False
    automatic_publishing_enabled: bool = False
    human_approval_required: bool = True


DEFAULT_POLICY = MarketingActionPolicy()
