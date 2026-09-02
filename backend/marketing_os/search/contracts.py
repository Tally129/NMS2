"""Contracts (enums + dataclasses) for Search Intelligence.

Pure data structures with no I/O. These define the normalized shapes used
across the overview, keyword, site-audit, and recommendation services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

# --------------------------------------------------------------------------
# Severity + category taxonomy (site audit)
# --------------------------------------------------------------------------

SEVERITY_CRITICAL = "critical"
SEVERITY_WARNING = "warning"
SEVERITY_OPPORTUNITY = "opportunity"
SEVERITY_INFORMATIONAL = "informational"

SEVERITIES = (
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    SEVERITY_OPPORTUNITY,
    SEVERITY_INFORMATIONAL,
)

# Deterministic ordering (most severe first).
SEVERITY_ORDER = {
    SEVERITY_CRITICAL: 0,
    SEVERITY_WARNING: 1,
    SEVERITY_OPPORTUNITY: 2,
    SEVERITY_INFORMATIONAL: 3,
}

CATEGORY_INDEXABILITY = "indexability"
CATEGORY_METADATA = "metadata"
CATEGORY_CONTENT = "content"
CATEGORY_LINKS = "links"
CATEGORY_PERFORMANCE = "performance"
CATEGORY_CRAWLABILITY = "crawlability"
CATEGORY_ACCESSIBILITY = "accessibility"

# --------------------------------------------------------------------------
# Keyword taxonomy
# --------------------------------------------------------------------------

INTENT_INFORMATIONAL = "informational"
INTENT_NAVIGATIONAL = "navigational"
INTENT_COMMERCIAL = "commercial"
INTENT_TRANSACTIONAL = "transactional"
INTENT_UNKNOWN = "unknown"

SEARCH_INTENTS = (
    INTENT_INFORMATIONAL,
    INTENT_NAVIGATIONAL,
    INTENT_COMMERCIAL,
    INTENT_TRANSACTIONAL,
    INTENT_UNKNOWN,
)

DEVICE_DESKTOP = "desktop"
DEVICE_MOBILE = "mobile"
DEVICE_TABLET = "tablet"
DEVICE_UNKNOWN = "unknown"

DEVICES = (
    DEVICE_DESKTOP,
    DEVICE_MOBILE,
    DEVICE_TABLET,
    DEVICE_UNKNOWN,
)

# Rank buckets
TOP_3 = 3
TOP_10 = 10
TOP_20 = 20


@dataclass(frozen=True)
class AuditIssue:
    severity: str
    category: str
    issue_code: str
    url: str
    description: str
    recommended_action: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "category": self.category,
            "issue_code": self.issue_code,
            "url": self.url,
            "description": self.description,
            "recommended_action": self.recommended_action,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class NormalizedKeyword:
    keyword: str
    normalized_keyword: str
    intent: str
    search_volume: Optional[int]
    keyword_difficulty: Optional[int]
    cpc: Optional[Decimal]
    current_rank: Optional[int]
    previous_rank: Optional[int]
    rank_change: Optional[int]
    ranking_url: Optional[str]
    serp_features: list[str]
    source: str
    location: str
    device: str
    captured_date: Optional[str]
    is_tracked: bool = True

    def movement(self) -> str:
        if self.current_rank is None:
            return "unranked"
        if self.previous_rank is None:
            return "new"
        if self.rank_change is None or self.rank_change == 0:
            return "flat"
        return "gain" if self.rank_change > 0 else "loss"

    def to_dict(self) -> dict[str, Any]:
        return {
            "keyword": self.keyword,
            "normalized_keyword": self.normalized_keyword,
            "intent": self.intent,
            "search_volume": self.search_volume,
            "keyword_difficulty": self.keyword_difficulty,
            "cpc": (float(self.cpc) if self.cpc is not None else None),
            "current_rank": self.current_rank,
            "previous_rank": self.previous_rank,
            "rank_change": self.rank_change,
            "movement": self.movement(),
            "ranking_url": self.ranking_url,
            "serp_features": list(self.serp_features),
            "source": self.source,
            "location": self.location,
            "device": self.device,
            "captured_date": self.captured_date,
            "is_tracked": self.is_tracked,
        }
