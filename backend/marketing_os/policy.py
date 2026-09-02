"""Safety policy for Marketing OS external actions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketingActionPolicy:
    external_writes_enabled: bool = False
    automatic_budget_changes_enabled: bool = False
    automatic_campaign_creation_enabled: bool = False
    automatic_publishing_enabled: bool = False
    human_approval_required: bool = True
    # Phase 8: automatic external outreach (email/etc.) is disabled. This flag
    # is advisory/reporting only. It MUST NOT be used to auto-release actions
    # that were already held: enabling real sends in the future requires an
    # explicit recipient-resolution/dispatch boundary and deliberate human
    # authorization, not a configuration toggle.
    automatic_outreach_enabled: bool = False


DEFAULT_POLICY = MarketingActionPolicy()
