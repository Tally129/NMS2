"""Phase 3 Search Intelligence services (pure/deterministic where possible).

Competitor normalization, keyword-gap classification, backlink + local
normalization/summaries, and advisory recommendations. Provider-neutral:
unavailable metrics stay None (never fabricated / never treated as zero).
No PHI. No external writes.
"""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlparse

from marketing_os.services.measurement import assert_non_phi_marketing_payload
from .keywords import normalize_keyword_text, normalize_intent

_WS = re.compile(r"\s+")

# Keyword-gap opportunity classifications.
GAP_SHARED = "shared"
GAP_NMS_ONLY = "nms_only"
GAP_MISSING = "missing"          # competitor ranks, NMS does not
GAP_WEAK = "weak"               # both rank, competitor better
GAP_STRONG = "strong"           # both rank, NMS better
GAP_UNKNOWN = "unknown"
GAP_CLASSES = (GAP_SHARED, GAP_NMS_ONLY, GAP_MISSING, GAP_WEAK,
               GAP_STRONG, GAP_UNKNOWN)


def normalize_domain(value: Any) -> str:
    text = _WS.sub("", str(value or "").strip().lower())
    if "://" in text:
        text = urlparse(text).netloc or text
    if text.startswith("www."):
        text = text[4:]
    return text.split("/")[0]


def normalize_competitor(payload: dict) -> dict:
    assert_non_phi_marketing_payload(payload)
    domain = normalize_domain(payload.get("domain"))
    if not domain:
        raise ValueError("competitor domain is required")
    return {
        "domain": str(payload.get("domain")).strip(),
        "normalized_domain": domain,
        "display_name": (payload.get("display_name") or None),
        "is_active": bool(payload.get("is_active", True)),
        "notes": (payload.get("notes") or None),
    }


# --------------------------------------------------------------- keyword gap

def classify_gap(
    nms_position: Optional[int],
    competitor_position: Optional[int],
) -> str:
    """Deterministic gap classification. None means 'unknown/not ranking',
    NEVER zero."""
    if nms_position is None and competitor_position is None:
        return GAP_UNKNOWN
    if nms_position is None and competitor_position is not None:
        return GAP_MISSING
    if nms_position is not None and competitor_position is None:
        return GAP_NMS_ONLY
    if nms_position < competitor_position:
        return GAP_STRONG
    if nms_position > competitor_position:
        return GAP_WEAK
    return GAP_SHARED


def normalize_gap_record(payload: dict) -> dict:
    assert_non_phi_marketing_payload(payload)
    keyword = _WS.sub(" ", str(payload.get("keyword") or "").strip())
    if not keyword:
        raise ValueError("keyword is required")
    nms = payload.get("nms_position")
    comp = payload.get("competitor_position")
    nms = int(nms) if nms not in (None, "") else None
    comp = int(comp) if comp not in (None, "") else None
    return {
        "keyword": keyword,
        "normalized_keyword": normalize_keyword_text(keyword),
        "nms_position": nms,
        "nms_source": payload.get("nms_source") or None,
        "competitor_position": comp,
        "competitor_source": payload.get("competitor_source") or None,
        "search_volume": (
            int(payload["search_volume"])
            if payload.get("search_volume") not in (None, "") else None),
        "keyword_difficulty": (
            int(payload["keyword_difficulty"])
            if payload.get("keyword_difficulty") not in (None, "") else None),
        "intent": normalize_intent(payload.get("intent"), keyword=keyword),
        "opportunity": classify_gap(nms, comp),
        "source": payload.get("source") or "unknown",
    }


def summarize_gap(records: list[dict]) -> dict:
    counts = {c: 0 for c in GAP_CLASSES}
    for r in records:
        counts[r.get("opportunity", GAP_UNKNOWN)] = counts.get(
            r.get("opportunity", GAP_UNKNOWN), 0) + 1
    return {
        "total": len(records),
        "shared": counts[GAP_SHARED],
        "nms_only": counts[GAP_NMS_ONLY],
        "competitor_only": counts[GAP_MISSING],
        "missing": counts[GAP_MISSING],
        "weak": counts[GAP_WEAK],
        "strong": counts[GAP_STRONG],
    }


# ---------------------------------------------------------------- backlinks

def normalize_backlink(payload: dict) -> dict:
    assert_non_phi_marketing_payload(payload)
    source_url = str(payload.get("source_url") or "").strip()
    if not source_url:
        raise ValueError("source_url is required")
    ref = normalize_domain(payload.get("referring_domain") or source_url)
    rel = str(payload.get("rel_type") or "unknown").lower()
    if rel not in ("follow", "nofollow", "unknown"):
        rel = "unknown"
    return {
        "referring_domain": ref,
        "source_url": source_url,
        "target_url": payload.get("target_url") or None,
        "anchor_text": payload.get("anchor_text") or None,
        "first_seen": payload.get("first_seen") or None,
        "last_seen": payload.get("last_seen") or None,
        "status": str(payload.get("status") or "active").lower(),
        "rel_type": rel,
        # authority ONLY when a real provider supplies it; else None.
        "authority": payload.get("authority"),
        "provider": payload.get("provider") or "unknown",
    }


def backlink_deltas(current: list[dict], previous: list[dict]) -> dict:
    def key(b):
        return (b.get("source_url"), b.get("target_url"))
    cur = {key(b) for b in current}
    prev = {key(b) for b in previous}
    new = cur - prev
    lost = prev - cur
    ref_domains = {b.get("referring_domain") for b in current}
    return {
        "backlink_count": len(current),
        "referring_domains": len(ref_domains),
        "new_backlinks": len(new),
        "lost_backlinks": len(lost),
    }


def backlink_overview(
    current: Optional[list[dict]],
    previous: Optional[list[dict]] = None,
    *,
    connected: bool = False,
) -> dict:
    if not connected:
        return {
            "connected": False,
            "not_connected_reason": "no_backlink_provider",
            "backlink_count": None,
            "referring_domains": None,
            "new_backlinks": None,
            "lost_backlinks": None,
        }
    deltas = backlink_deltas(current or [], previous or [])
    return {"connected": True, "provider": (current or [{}])[0].get(
        "provider", "unknown") if current else "unknown", **deltas}


# ---------------------------------------------------------------- local seo

def normalize_local_record(payload: dict) -> dict:
    assert_non_phi_marketing_payload(payload)
    keyword = _WS.sub(" ", str(payload.get("target_keyword") or "").strip())
    if not keyword:
        raise ValueError("target_keyword is required")
    rank = payload.get("local_rank")
    return {
        "location_id": str(payload.get("location_id") or "default"),
        "location_name": payload.get("location_name") or None,
        "city": payload.get("city") or None,
        "state": payload.get("state") or None,
        "postal_code": payload.get("postal_code") or None,
        "target_service": payload.get("target_service") or None,
        "target_keyword": keyword,
        "normalized_keyword": normalize_keyword_text(keyword),
        "local_rank": int(rank) if rank not in (None, "") else None,
        "provider": payload.get("provider") or "unknown",
    }
