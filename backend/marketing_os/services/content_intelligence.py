"""Deterministic Marketing OS Phase 11 content + social logic (pure).

No DB/network/PHI. Deterministic scoring + template (advisory) draft scaffolds.
AI/LLM is NOT invoked here; drafts are deterministic scaffolds a human/AI can
refine. Nothing here publishes anything.
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping, Optional

from marketing_os.services.measurement import (
    MarketingDataPolicyError, assert_non_phi_marketing_payload,
)

CHANNELS = ("blog", "tiktok", "instagram", "facebook", "linkedin", "email")
SHORT_FORM = frozenset({"tiktok", "instagram"})
SEARCH_INTENTS = ("informational", "commercial", "transactional",
                  "navigational")
FUNNEL_STAGES = ("awareness", "consideration", "decision", "retention")
TOPIC_STATUSES = ("idea", "planned", "draft", "approved", "ready")
ITEM_STATUSES = ("idea", "planned", "draft", "approved", "ready")

MAX_LEN = 300
MAX_JSON = 20000
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-_]{0,199}$")


class ContentConfigError(ValueError):
    """Malformed content configuration (fail-closed)."""


def req_str(v, field, *, max_len=MAX_LEN, min_len=1):
    if not isinstance(v, str):
        raise ContentConfigError(f"{field} must be a string")
    c = v.strip()
    if len(c) < min_len:
        raise ContentConfigError(f"{field} must not be empty")
    if len(c) > max_len:
        raise ContentConfigError(f"{field} exceeds max length {max_len}")
    return c


def opt_str(v, field, *, max_len=MAX_LEN):
    if v is None:
        return None
    if not isinstance(v, str):
        raise ContentConfigError(f"{field} must be a string")
    c = v.strip()
    return c[:max_len] if c else None


def validate_slug(v):
    c = req_str(v, "slug", max_len=200)
    if not _SLUG_RE.match(c):
        raise ContentConfigError("slug must be lowercase alphanumeric -/_")
    return c


def validate_channel(v):
    if not isinstance(v, str) or v.strip().lower() not in CHANNELS:
        raise ContentConfigError(f"unsupported channel: {v!r}")
    return v.strip().lower()


def bounded_json(v, field):
    if v is None:
        return {}
    if not isinstance(v, Mapping):
        raise ContentConfigError(f"{field} must be an object")
    payload = dict(v)
    assert_non_phi_marketing_payload(payload)
    try:
        s = json.dumps(payload)
    except (TypeError, ValueError) as exc:
        raise ContentConfigError(f"{field} must be JSON-serializable") from exc
    if len(s) > MAX_JSON:
        raise ContentConfigError(f"{field} exceeds max size")
    return payload


# --------------------------------------------------------------------------- #
# Deterministic scoring
# --------------------------------------------------------------------------- #

def _num(v, default=0.0):
    try:
        if v is None or isinstance(v, bool):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def seo_opportunity_priority(metrics: Mapping[str, Any]) -> int:
    """Deterministic 0..100 from GSC-style metrics (impressions/position/ctr).

    High impressions + poor position + low ctr => higher opportunity.
    """
    impressions = _num(metrics.get("impressions"))
    position = _num(metrics.get("avg_position"), 100.0)
    ctr = _num(metrics.get("ctr"))
    gap = _num(metrics.get("competitor_gap"))
    imp_norm = min(impressions / 1000.0, 1.0)
    pos_norm = min(max((position - 3.0) / 27.0, 0.0), 1.0)  # worse pos => 1
    ctr_norm = 1.0 - min(max(ctr, 0.0), 1.0)
    gap_norm = min(max(gap, 0.0), 1.0)
    score = imp_norm * 40 + pos_norm * 25 + ctr_norm * 20 + gap_norm * 15
    return int(round(min(max(score, 0.0), 100.0)))


def funnel_relevance(funnel_stage: Optional[str],
                     has_offer: bool, has_funnel: bool) -> int:
    base = {"decision": 40, "consideration": 30, "retention": 20,
            "awareness": 10}.get((funnel_stage or "").lower(), 10)
    return min(base + (30 if has_offer else 0) + (30 if has_funnel else 0), 100)


def conversion_relevance(metrics: Mapping[str, Any]) -> int:
    leads = _num(metrics.get("attributed_leads"))
    revenue = _num(metrics.get("attributed_revenue"))
    return int(round(min(leads * 5 + min(revenue / 100.0, 50), 100.0)))


def freshness_need(days_since_update: Any) -> str:
    d = _num(days_since_update, -1)
    if d < 0:
        return "unknown"
    if d >= 365:
        return "high"
    if d >= 180:
        return "medium"
    return "low"


def local_content_opportunity(local_opps: Any) -> int:
    """Priority contribution from Phase 10 local opportunities count."""
    try:
        n = len(local_opps or [])
    except TypeError:
        n = 0
    return min(n * 15, 60)


def composite_topic_priority(*, seo: int, funnel: int, conversion: int,
                             freshness: str) -> int:
    fresh = {"high": 20, "medium": 10, "low": 0, "unknown": 0}[freshness]
    score = seo * 0.45 + funnel * 0.2 + conversion * 0.25 + fresh
    return int(round(min(max(score, 0.0), 100.0)))


# --------------------------------------------------------------------------- #
# Deterministic (advisory) draft scaffolds — NOT published, NOT LLM
# --------------------------------------------------------------------------- #

def generate_draft_scaffold(*, channel: str, title: str,
                            target_keyword: Optional[str] = None,
                            cta: Optional[str] = None,
                            audience: Optional[str] = None) -> dict[str, Any]:
    """Deterministic starter scaffold for human/AI refinement. Draft-only."""
    ch = channel.lower()
    kw = target_keyword or title
    cta = cta or "Book a consultation"
    aud = audience or "local patients"
    common = {"generator": "template", "cta": cta}
    if ch == "blog":
        return {**common, "headline": title,
                "body": (f"[DRAFT] Intro addressing '{kw}'. "
                         "H2: What to know. H2: Options. H2: Why it matters. "
                         f"Closing CTA: {cta}."),
                "caption": None, "hook": None, "script": None,
                "on_screen_text": None, "shot_list": {}}
    if ch in SHORT_FORM or ch == "tiktok":
        return {**common, "headline": title,
                "hook": f"Did you know about {kw}?",
                "script": (f"[DRAFT 20-30s] Hook -> problem -> 3 quick points "
                           f"on {kw} -> CTA: {cta}."),
                "on_screen_text": f"{kw} — what to know",
                "caption": f"{title} #wellness",
                "shot_list": {"shots": ["talking head hook", "b-roll",
                                        "on-screen tips", "CTA card"]},
                "body": None}
    # facebook / linkedin / email
    return {**common, "headline": title,
            "caption": f"[DRAFT] {title} — for {aud}. {cta}.",
            "body": f"[DRAFT] Post copy about {kw} tailored to {aud}.",
            "hook": None, "script": None, "on_screen_text": None,
            "shot_list": {}}


# re-export for routers
__all__ = [
    "CHANNELS", "SEARCH_INTENTS", "FUNNEL_STAGES", "TOPIC_STATUSES",
    "ITEM_STATUSES", "ContentConfigError", "MarketingDataPolicyError",
    "req_str", "opt_str", "validate_slug", "validate_channel", "bounded_json",
    "seo_opportunity_priority", "funnel_relevance", "conversion_relevance",
    "freshness_need", "local_content_opportunity", "composite_topic_priority",
    "generate_draft_scaffold",
]
