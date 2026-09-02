"""Advisory Phase 3 recommendations for the AI Marketing Director.

Deterministic + ADVISORY only. No publishing, outreach, listing updates, or
external writes. Dict shape matches other search recommendations.
"""
from __future__ import annotations
from typing import Any, Optional

_CHANNEL = "seo"


def _advisory(*, recommendation_type, priority, title, reason,
              proposed_action, evidence=None) -> dict[str, Any]:
    return {
        "type": recommendation_type, "channel": _CHANNEL,
        "priority": priority, "title": title, "reason": reason,
        "proposed_action": proposed_action, "evidence": evidence or {},
        "advisory_only": True, "requires_human_approval": True,
        "external_write": False,
    }


def build_phase3_recommendations(
    *,
    gap_records: Optional[list[dict]] = None,
    lost_backlinks: Optional[list[dict]] = None,
    backlink_opportunities: Optional[list[dict]] = None,
    local_gaps: Optional[list[dict]] = None,
) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []
    for r in (gap_records or []):
        opp = r.get("opportunity")
        if opp == "missing":
            recs.append(_advisory(
                recommendation_type="content", priority=80,
                title="Target missing competitor keyword",
                reason=(f"Competitor ranks for '{r.get('keyword')}' where "
                        "NMS does not."),
                proposed_action=("Create or optimize a landing page "
                                 "targeting this keyword."),
                evidence={"keyword": r.get("keyword"),
                          "competitor_source": r.get("competitor_source")}))
        elif opp == "weak":
            recs.append(_advisory(
                recommendation_type="content", priority=68,
                title="Improve weak keyword",
                reason=(f"'{r.get('keyword')}' ranks worse than a "
                        "competitor."),
                proposed_action="Strengthen the ranking page's content.",
                evidence={"keyword": r.get("keyword"),
                          "nms_position": r.get("nms_position"),
                          "competitor_position":
                              r.get("competitor_position")}))
    for b in (lost_backlinks or []):
        recs.append(_advisory(
            recommendation_type="backlink", priority=64,
            title="Investigate lost backlink",
            reason=(f"Referring domain '{b.get('referring_domain')}' "
                    "appears lost."),
            proposed_action=("Review the linking page and consider "
                             "outreach (manual, human-approved)."),
            evidence={"source_url": b.get("source_url")}))
    for b in (backlink_opportunities or []):
        recs.append(_advisory(
            recommendation_type="backlink", priority=58,
            title="Pursue backlink opportunity",
            reason=(f"Potential referring domain "
                    f"'{b.get('referring_domain')}'."),
            proposed_action="Evaluate for a manual, human-approved outreach.",
            evidence={"referring_domain": b.get("referring_domain")}))
    for g in (local_gaps or []):
        recs.append(_advisory(
            recommendation_type="local_seo", priority=62,
            title="Create local service/location content",
            reason=(f"Service+city keyword '{g.get('keyword')}' is not "
                    "tracked/covered."),
            proposed_action=("Create a location/service page and track the "
                             "local keyword."),
            evidence={"keyword": g.get("keyword"),
                      "city": g.get("city")}))
    recs.sort(key=lambda r: (-r["priority"], r["title"]))
    return recs
