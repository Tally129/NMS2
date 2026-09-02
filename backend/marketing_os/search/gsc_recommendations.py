"""Advisory Search-Console-driven recommendations for the Marketing Director.

Deterministic + ADVISORY only. No page changes, no publishing, no external
writes. Dict shape matches the existing director/search recommendations.
"""

from __future__ import annotations

from typing import Any, Optional

_CHANNEL = "seo"

# Thresholds (deterministic).
HIGH_IMPRESSION_MIN = 100
LOW_CTR_MAX = 0.01          # 1%
NEAR_PAGE1_MIN = 10.0       # avg position just off page one
CLICK_DECLINE_MIN = 5       # absolute click drop to flag


def _advisory(*, recommendation_type, priority, title, reason,
              proposed_action, evidence=None) -> dict[str, Any]:
    return {
        "type": recommendation_type,
        "channel": _CHANNEL,
        "priority": priority,
        "title": title,
        "reason": reason,
        "proposed_action": proposed_action,
        "evidence": evidence or {},
        "source": "google_search_console",
        "advisory_only": True,
        "requires_human_approval": True,
        "external_write": False,
    }


def build_gsc_recommendations(
    *,
    query_rows: Optional[list[dict]] = None,
    page_current: Optional[list[dict]] = None,
    page_previous: Optional[list[dict]] = None,
    rank_items: Optional[list[dict]] = None,
) -> list[dict[str, Any]]:
    """Produce advisory SEO recommendations from normalized GSC data.

    - query_rows: latest normalized query metrics (clicks/impressions/ctr/position)
    - page_current / page_previous: page metrics for two periods (by page url)
    - rank_items: rank-history items (with movement + metric_type)
    """
    query_rows = query_rows or []
    recs: list[dict[str, Any]] = []

    # 1. High-impression / low-CTR queries.
    for q in query_rows:
        if (
            q.get("impressions", 0) >= HIGH_IMPRESSION_MIN
            and q.get("ctr", 1) <= LOW_CTR_MAX
        ):
            recs.append(_advisory(
                recommendation_type="meta_description",
                priority=78,
                title="Improve CTR on high-impression query",
                reason=(
                    f"Query '{q.get('query')}' has "
                    f"{q.get('impressions')} impressions but a "
                    f"{round(q.get('ctr', 0) * 100, 2)}% CTR."
                ),
                proposed_action=(
                    "Refine the title/meta description to better match "
                    "this query's intent."
                ),
                evidence={"query": q.get("query"),
                          "impressions": q.get("impressions"),
                          "ctr": q.get("ctr")},
            ))

    # 2. Strong query without a page-one position (content opportunity).
    for q in query_rows:
        pos = q.get("position")
        if (
            pos is not None and pos > NEAR_PAGE1_MIN
            and q.get("impressions", 0) >= HIGH_IMPRESSION_MIN
        ):
            recs.append(_advisory(
                recommendation_type="content",
                priority=66,
                title="Create/optimize content for a strong query",
                reason=(
                    f"Query '{q.get('query')}' draws impressions but "
                    f"averages GSC position {pos} (off page one). "
                    "Note: GSC average position is not a dedicated SERP "
                    "rank."
                ),
                proposed_action=(
                    "Build or optimize a landing page targeting this "
                    "query."
                ),
                evidence={"query": q.get("query"),
                          "gsc_average_position": pos},
            ))

    # 3. Ranking decline (from rank-history items).
    for item in (rank_items or []):
        if item.get("movement") == "loss":
            recs.append(_advisory(
                recommendation_type="seo",
                priority=74,
                title="Investigate ranking decline",
                reason=(
                    f"'{item.get('keyword')}' declined "
                    f"({item.get('metric_type')}, source "
                    f"{item.get('source')}): {item.get('previous_position')}"
                    f" -> {item.get('current_position')}."
                ),
                proposed_action=(
                    "Review recent changes and refresh the affected page."
                ),
                evidence={"keyword": item.get("keyword"),
                          "metric_type": item.get("metric_type")},
            ))

    # 4. Pages with declining clicks (period over period).
    if page_current and page_previous:
        prev_by_page = {p.get("page"): p for p in page_previous}
        for p in page_current:
            prev = prev_by_page.get(p.get("page"))
            if not prev:
                continue
            drop = prev.get("clicks", 0) - p.get("clicks", 0)
            if drop >= CLICK_DECLINE_MIN:
                recs.append(_advisory(
                    recommendation_type="content",
                    priority=70,
                    title="Address page with declining clicks",
                    reason=(
                        f"Page '{p.get('page')}' lost {drop} clicks "
                        "period-over-period."
                    ),
                    proposed_action=(
                        "Refresh the page content and internal linking."
                    ),
                    evidence={"page": p.get("page"),
                              "clicks_now": p.get("clicks"),
                              "clicks_prev": prev.get("clicks")},
                ))

    recs.sort(key=lambda r: (-r["priority"], r["title"]))
    return recs
