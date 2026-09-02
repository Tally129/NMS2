"""Deterministic keyword normalization + rank math for Search Intelligence.

Pure functions only. No network, no DB, no PHI. Callers must pass
marketing-only data; normalize_keyword enforces the non-PHI boundary.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Optional

from marketing_os.services.measurement import assert_non_phi_marketing_payload

from .contracts import (
    DEVICE_DESKTOP,
    DEVICES,
    INTENT_COMMERCIAL,
    INTENT_INFORMATIONAL,
    INTENT_NAVIGATIONAL,
    INTENT_TRANSACTIONAL,
    INTENT_UNKNOWN,
    NormalizedKeyword,
    SEARCH_INTENTS,
    TOP_10,
    TOP_20,
    TOP_3,
)

_WHITESPACE = re.compile(r"\s+")

# Deterministic intent inference token sets (checked in priority order).
_TRANSACTIONAL_TOKENS = frozenset({
    "buy", "book", "booking", "appointment", "schedule", "order",
    "signup", "sign-up", "subscribe", "apply", "quote", "consultation",
})
_COMMERCIAL_TOKENS = frozenset({
    "best", "top", "review", "reviews", "compare", "comparison", "vs",
    "price", "pricing", "cost", "cheap", "affordable", "near", "deal",
    "deals", "discount",
})
_INFORMATIONAL_TOKENS = frozenset({
    "how", "what", "why", "when", "where", "who", "guide", "tips",
    "symptoms", "causes", "benefits", "treatment", "remedy", "remedies",
    "meaning", "definition", "ideas", "examples",
})


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return _WHITESPACE.sub(" ", str(value).strip())


def normalize_keyword_text(value: Any) -> str:
    """Lowercased, whitespace-collapsed keyword used for dedupe/index."""
    return normalize_text(value).lower()


def infer_intent(keyword: str) -> str:
    """Deterministic, rule-based intent classification."""
    tokens = set(normalize_keyword_text(keyword).replace("/", " ").split())
    if not tokens:
        return INTENT_UNKNOWN
    if tokens & _TRANSACTIONAL_TOKENS:
        return INTENT_TRANSACTIONAL
    # "near me" is a strong commercial-local signal.
    if "near" in tokens and "me" in tokens:
        return INTENT_COMMERCIAL
    if tokens & _COMMERCIAL_TOKENS:
        return INTENT_COMMERCIAL
    if tokens & _INFORMATIONAL_TOKENS:
        return INTENT_INFORMATIONAL
    return INTENT_UNKNOWN


def normalize_intent(value: Any, *, keyword: str = "") -> str:
    candidate = normalize_keyword_text(value)
    if candidate in SEARCH_INTENTS:
        return candidate
    if candidate == INTENT_NAVIGATIONAL:  # explicit passthrough
        return INTENT_NAVIGATIONAL
    # Fall back to deterministic inference when not explicitly provided.
    return infer_intent(keyword)


def normalize_device(value: Any) -> str:
    candidate = normalize_keyword_text(value)
    if candidate in DEVICES:
        return candidate
    return DEVICE_DESKTOP


def _coerce_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_rank(value: Any) -> Optional[int]:
    rank = _coerce_int(value)
    if rank is None:
        return None
    # Ranks are 1-based positions; anything < 1 is treated as unranked.
    return rank if rank >= 1 else None


def _coerce_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def compute_rank_change(
    current_rank: Optional[int],
    previous_rank: Optional[int],
) -> Optional[int]:
    """Positions gained (positive) or lost (negative).

    Lower rank numbers are better, so an improvement from 8 -> 3 yields
    +5. Returns None when either value is missing (e.g. a brand-new term).
    """
    if current_rank is None or previous_rank is None:
        return None
    return previous_rank - current_rank


def normalize_serp_features(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        parts: Iterable[str] = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        parts = value
    else:
        return []
    seen: list[str] = []
    for part in parts:
        feature = normalize_keyword_text(part)
        if feature and feature not in seen:
            seen.append(feature)
    return seen


def normalize_keyword(
    payload: Mapping[str, Any],
    *,
    source_default: str = "manual",
    is_tracked_default: bool = True,
) -> NormalizedKeyword:
    """Normalize a raw keyword payload into a NormalizedKeyword.

    Enforces the marketing non-PHI boundary before doing anything else.
    """
    assert_non_phi_marketing_payload(payload)

    keyword = normalize_text(payload.get("keyword"))
    if not keyword:
        raise ValueError("keyword is required")

    current_rank = _coerce_rank(payload.get("current_rank"))
    previous_rank = _coerce_rank(payload.get("previous_rank"))

    provided_change = payload.get("rank_change")
    rank_change = (
        _coerce_int(provided_change)
        if provided_change is not None
        else compute_rank_change(current_rank, previous_rank)
    )

    difficulty = _coerce_int(payload.get("keyword_difficulty"))
    if difficulty is not None:
        difficulty = max(0, min(100, difficulty))

    ranking_url = normalize_text(payload.get("ranking_url")) or None
    captured = payload.get("captured_date")
    captured_date = str(captured) if captured else None

    tracked = payload.get("is_tracked")
    is_tracked = is_tracked_default if tracked is None else bool(tracked)

    return NormalizedKeyword(
        keyword=keyword,
        normalized_keyword=normalize_keyword_text(keyword),
        intent=normalize_intent(payload.get("intent"), keyword=keyword),
        search_volume=_coerce_int(payload.get("search_volume")),
        keyword_difficulty=difficulty,
        cpc=_coerce_decimal(payload.get("cpc")),
        current_rank=current_rank,
        previous_rank=previous_rank,
        rank_change=rank_change,
        ranking_url=ranking_url,
        serp_features=normalize_serp_features(payload.get("serp_features")),
        source=normalize_text(payload.get("source")) or source_default,
        location=normalize_text(payload.get("location")) or "global",
        device=normalize_device(payload.get("device")),
        captured_date=captured_date,
        is_tracked=is_tracked,
    )


def summarize_keywords(
    keywords: list[NormalizedKeyword],
) -> dict[str, Any]:
    """Aggregate ranking distribution + movement counts.

    Deterministic. Positions in the Top N buckets are cumulative
    (Top 3 keywords are also counted in Top 10 and Top 20).
    """
    ranked = [k for k in keywords if k.current_rank is not None]

    top_3 = sum(1 for k in ranked if k.current_rank <= TOP_3)
    top_10 = sum(1 for k in ranked if k.current_rank <= TOP_10)
    top_20 = sum(1 for k in ranked if k.current_rank <= TOP_20)

    gains = sum(
        1 for k in keywords
        if k.rank_change is not None and k.rank_change > 0
    )
    losses = sum(
        1 for k in keywords
        if k.rank_change is not None and k.rank_change < 0
    )

    average_position = (
        round(sum(k.current_rank for k in ranked) / len(ranked), 2)
        if ranked
        else None
    )

    return {
        "total": len(keywords),
        "ranked": len(ranked),
        "tracked": sum(1 for k in keywords if k.is_tracked),
        "average_position": average_position,
        "keywords_in_top_3": top_3,
        "keywords_in_top_10": top_10,
        "keywords_in_top_20": top_20,
        "ranking_gains": gains,
        "ranking_losses": losses,
    }


def rank_gainers(
    keywords: list[NormalizedKeyword],
) -> list[NormalizedKeyword]:
    gainers = [
        k for k in keywords
        if k.rank_change is not None and k.rank_change > 0
    ]
    return sorted(gainers, key=lambda k: k.rank_change, reverse=True)


def rank_losers(
    keywords: list[NormalizedKeyword],
) -> list[NormalizedKeyword]:
    losers = [
        k for k in keywords
        if k.rank_change is not None and k.rank_change < 0
    ]
    return sorted(losers, key=lambda k: k.rank_change)
