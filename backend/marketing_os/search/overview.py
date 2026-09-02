"""Search Intelligence overview aggregation.

Produces the SEO overview metrics for the Marketing Command Center.
Metrics that require an external provider that is NOT connected in this
phase (organic keyword universe, estimated organic traffic, indexed
pages, backlinks, referring domains) are returned as honest
not-connected / null states. First-party metrics we actually have
(tracked keywords, ranking distribution, technical audit issues) are
reported truthfully.

Never fabricates SEO metrics.
"""

from __future__ import annotations

from typing import Any, Optional

from .contracts import NormalizedKeyword
from .keywords import summarize_keywords


def _metric(value: Any, connected: bool, source: str) -> dict[str, Any]:
    return {
        "value": value if connected else None,
        "connected": connected,
        "source": source,
    }


def build_search_overview(
    *,
    site: Optional[dict] = None,
    keywords: Optional[list[NormalizedKeyword]] = None,
    latest_audit: Optional[dict] = None,
    backlink_summary: Optional[dict] = None,
    connections: Optional[dict] = None,
) -> dict[str, Any]:
    """Aggregate a deterministic, honest SEO overview.

    - `site`: dict of the configured marketing site (or None).
    - `keywords`: first-party tracked NormalizedKeyword list.
    - `latest_audit`: latest audit run summary (or None).
    - `backlink_summary`: reserved for a future backlink provider.
    - `connections`: which external data sources are connected.
    """
    keywords = keywords or []
    conn = {
        "rank_provider": False,
        "search_console": False,
        "backlink_provider": False,
        "site_audit": bool(latest_audit),
        "tracked_keywords": bool(keywords),
    }
    if connections:
        conn.update(connections)

    if site is None:
        return {
            "connected": False,
            "not_connected_reason": "no_marketing_site_configured",
            "connections": conn,
            "metrics": _empty_metrics(conn),
            "keyword_summary": summarize_keywords([]),
        }

    summary = summarize_keywords(keywords)

    audit = latest_audit or {}
    technical_issue_count = (
        audit.get("issues_total") if latest_audit else None
    )
    indexed_pages_val = (
        audit.get("pages_scanned") if latest_audit else None
    )

    backlinks = backlink_summary or {}

    metrics = {
        # Provider-only (not connected this phase) -> honest nulls.
        "organic_keywords": _metric(
            None, conn["search_console"], "search_console"
        ),
        "estimated_organic_traffic": _metric(
            None, conn["search_console"], "search_console"
        ),
        "backlink_count": _metric(
            backlinks.get("backlink_count"),
            conn["backlink_provider"],
            "backlink_provider",
        ),
        "referring_domain_count": _metric(
            backlinks.get("referring_domain_count"),
            conn["backlink_provider"],
            "backlink_provider",
        ),
        # First-party site audit.
        "indexed_pages": _metric(
            indexed_pages_val, conn["site_audit"], "site_audit"
        ),
        "technical_issue_count": _metric(
            technical_issue_count, conn["site_audit"], "site_audit"
        ),
        # First-party tracked keywords (always "connected" when we have rows).
        "tracked_keywords": _metric(
            summary["tracked"], True, "marketing_search_keywords"
        ),
        "average_tracked_position": _metric(
            summary["average_position"], True, "marketing_search_keywords"
        ),
        "keywords_in_top_3": _metric(
            summary["keywords_in_top_3"], True, "marketing_search_keywords"
        ),
        "keywords_in_top_10": _metric(
            summary["keywords_in_top_10"], True, "marketing_search_keywords"
        ),
        "keywords_in_top_20": _metric(
            summary["keywords_in_top_20"], True, "marketing_search_keywords"
        ),
        "ranking_gains": _metric(
            summary["ranking_gains"], True, "marketing_search_keywords"
        ),
        "ranking_losses": _metric(
            summary["ranking_losses"], True, "marketing_search_keywords"
        ),
    }

    return {
        "connected": True,
        "site": site,
        "connections": conn,
        "metrics": metrics,
        "keyword_summary": summary,
        "audit": {
            "has_run": bool(latest_audit),
            "critical_count": audit.get("critical_count"),
            "warning_count": audit.get("warning_count"),
            "opportunity_count": audit.get("opportunity_count"),
            "informational_count": audit.get("informational_count"),
            "status": audit.get("status"),
            "finished_at": audit.get("finished_at"),
        },
    }


def _empty_metrics(conn: dict) -> dict[str, Any]:
    keys = [
        "organic_keywords",
        "estimated_organic_traffic",
        "backlink_count",
        "referring_domain_count",
        "indexed_pages",
        "technical_issue_count",
        "tracked_keywords",
        "average_tracked_position",
        "keywords_in_top_3",
        "keywords_in_top_10",
        "keywords_in_top_20",
        "ranking_gains",
        "ranking_losses",
    ]
    return {key: _metric(None, False, "not_connected") for key in keys}
