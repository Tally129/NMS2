"""Deterministic, ADVISORY Search Intelligence recommendations.

These functions expose Search Intelligence signals to the existing AI
Marketing Director as plain internal service calls. Every recommendation
is advisory only:

- advisory_only = True
- requires_human_approval = True
- external_write = False

No page is changed, no content is published, no provider write occurs.
The dict shape matches marketing_os.services.director recommendations.
"""

from __future__ import annotations

from typing import Any, Optional

from .contracts import NormalizedKeyword
from .keywords import rank_losers, summarize_keywords

_CHANNEL = "seo"

# Map audit issue codes -> (recommendation_type, title, action).
_ISSUE_RECOMMENDATIONS = {
    "missing_title": (
        "page_title",
        "Improve page title",
        "Add a unique, descriptive <title> to the affected page.",
    ),
    "multiple_titles": (
        "page_title",
        "Fix duplicate title tags",
        "Keep exactly one <title> element on the page.",
    ),
    "duplicate_title": (
        "page_title",
        "Make page titles unique",
        "Differentiate titles that are shared across multiple pages.",
    ),
    "missing_meta_description": (
        "meta_description",
        "Improve meta description",
        "Write a concise, unique meta description for the page.",
    ),
    "duplicate_meta_description": (
        "meta_description",
        "Make meta descriptions unique",
        "Write a distinct meta description per page.",
    ),
    "missing_h1": (
        "content",
        "Add a primary H1 heading",
        "Add a single descriptive H1 that reflects the page topic.",
    ),
    "noindex_directive": (
        "technical_seo",
        "Investigate indexability",
        "Confirm whether the noindex directive is intentional.",
    ),
    "http_4xx": (
        "technical_seo",
        "Address technical SEO issue",
        "Fix or redirect the URL returning a client error.",
    ),
    "http_5xx": (
        "technical_seo",
        "Address technical SEO issue",
        "Resolve the server error preventing the page from loading.",
    ),
    "page_unreachable": (
        "technical_seo",
        "Address technical SEO issue",
        "Ensure the page is publicly reachable and returns HTTP 200.",
    ),
    "broken_internal_link": (
        "technical_seo",
        "Fix broken internal links",
        "Repair or remove internal links pointing to error pages.",
    ),
    "redirect_chain": (
        "technical_seo",
        "Shorten redirect chains",
        "Point initial URLs directly at their final destinations.",
    ),
    "missing_canonical": (
        "landing_page",
        "Add canonical tags",
        "Add a self-referencing canonical to consolidate signals.",
    ),
    "images_missing_alt": (
        "landing_page",
        "Add image alt text",
        "Add descriptive alt text to images for accessibility and SEO.",
    ),
    "slow_response": (
        "landing_page",
        "Improve landing-page speed",
        "Reduce server/page response time on slow pages.",
    ),
    "missing_sitemap": (
        "technical_seo",
        "Publish an XML sitemap",
        "Publish sitemap.xml and reference it from robots.txt.",
    ),
}

# Priority by severity.
_SEVERITY_PRIORITY = {
    "critical": 90,
    "warning": 70,
    "opportunity": 50,
    "informational": 30,
}


def _advisory(
    *,
    recommendation_type: str,
    priority: int,
    title: str,
    reason: str,
    proposed_action: str,
    evidence: Optional[dict] = None,
) -> dict[str, Any]:
    return {
        "type": recommendation_type,
        "channel": _CHANNEL,
        "priority": priority,
        "title": title,
        "reason": reason,
        "proposed_action": proposed_action,
        "evidence": evidence or {},
        # Safety contract (identical to director recommendations).
        "advisory_only": True,
        "requires_human_approval": True,
        "external_write": False,
    }


def build_search_recommendations(
    *,
    overview: Optional[dict] = None,
    audit_issues: Optional[list[dict]] = None,
    keywords: Optional[list[NormalizedKeyword]] = None,
) -> list[dict[str, Any]]:
    """Return advisory SEO recommendations for the Marketing Director."""
    recommendations: list[dict[str, Any]] = []
    audit_issues = audit_issues or []
    keywords = keywords or []

    # 1. Not-connected measurement guidance (honest).
    connections = (overview or {}).get("connections", {})
    if overview is not None and not connections.get("rank_provider"):
        recommendations.append(_advisory(
            recommendation_type="measurement",
            priority=85,
            title="Connect a rank-tracking data source",
            reason=(
                "No rank provider is connected, so organic ranking "
                "metrics cannot be measured."
            ),
            proposed_action=(
                "Connect Google Search Console or a rank provider in a "
                "future phase to populate organic metrics."
            ),
        ))

    # 2. One recommendation per distinct audit issue code (highest severity).
    best_by_code: dict[str, dict] = {}
    for issue in audit_issues:
        code = issue.get("issue_code")
        if code not in _ISSUE_RECOMMENDATIONS:
            continue
        severity = issue.get("severity", "informational")
        prev = best_by_code.get(code)
        if prev is None or _SEVERITY_PRIORITY.get(
            severity, 0
        ) > _SEVERITY_PRIORITY.get(prev.get("severity", ""), 0):
            best_by_code[code] = issue

    for code, issue in best_by_code.items():
        rec_type, title, action = _ISSUE_RECOMMENDATIONS[code]
        severity = issue.get("severity", "informational")
        count = sum(
            1 for i in audit_issues if i.get("issue_code") == code
        )
        recommendations.append(_advisory(
            recommendation_type=rec_type,
            priority=_SEVERITY_PRIORITY.get(severity, 30),
            title=title,
            reason=(
                f"Technical audit found {count} '{code}' issue(s) "
                f"(severity: {severity})."
            ),
            proposed_action=action,
            evidence={"issue_code": code, "count": count, "example_url":
                      issue.get("url")},
        ))

    # 3. Ranking declines -> investigate.
    losers = rank_losers(keywords)
    if losers:
        worst = losers[0]
        recommendations.append(_advisory(
            recommendation_type="seo",
            priority=75,
            title="Investigate ranking decline",
            reason=(
                f"{len(losers)} tracked keyword(s) lost rank; the largest "
                f"drop is {abs(worst.rank_change)} positions."
            ),
            proposed_action=(
                "Review recent content/technical changes for declining "
                "keywords and refresh the affected pages."
            ),
            evidence={
                "declining_keywords": len(losers),
                "example_keyword": worst.keyword,
            },
        ))

    # 4. Content opportunities: tracked keywords ranking beyond page 1.
    page_two_plus = [
        k for k in keywords
        if k.current_rank is not None and k.current_rank > 10
    ]
    if page_two_plus:
        recommendations.append(_advisory(
            recommendation_type="content",
            priority=60,
            title="Create or update content for near-page-1 keywords",
            reason=(
                f"{len(page_two_plus)} tracked keyword(s) rank beyond the "
                "first page and could be improved with content work."
            ),
            proposed_action=(
                "Expand or refresh content targeting these keywords to "
                "move them onto page one."
            ),
            evidence={"keywords": [k.keyword for k in page_two_plus[:10]]},
        ))

    # Deterministic ordering: highest priority first, then title.
    recommendations.sort(key=lambda r: (-r["priority"], r["title"]))
    return recommendations
