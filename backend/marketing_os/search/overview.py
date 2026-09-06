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


# Rank-provider (DataForSEO Labs) dataset completeness states.
PROVIDER_DATASET_NOT_CONNECTED = "not_connected"
PROVIDER_DATASET_COMPLETE = "complete"
PROVIDER_DATASET_INCOMPLETE = "incomplete"
PROVIDER_DATASET_UNKNOWN = "unknown"

PROVIDER_RANKED_KEYWORDS_REPORT = "ranked_keywords"

_PROVIDER_INCOMPLETE_MESSAGE = (
    "Provider dataset incomplete — additional ranking keywords are "
    "available to sync. This does not indicate lost rankings."
)
_PROVIDER_COMPLETE_MESSAGE = (
    "Provider dataset complete for the latest cached snapshot."
)
_PROVIDER_UNKNOWN_MESSAGE = (
    "Provider completeness unknown — no completed ranked-keyword "
    "provider run has been recorded for this snapshot."
)
_PROVIDER_NOT_CONNECTED_MESSAGE = (
    "No cached rank-provider data. Organic ranking intelligence has not "
    "been synced yet."
)


def _as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _run_summary(run: Optional[dict]) -> Optional[dict[str, Any]]:
    if not run:
        return None
    return {
        "id": run.get("id"),
        "report_type": run.get("report_type"),
        "status": run.get("status"),
        "requested_limit": _as_int(run.get("requested_limit")),
        "requested_offset": _as_int(run.get("requested_offset")),
        "provider_items_count": _as_int(run.get("provider_items_count")),
        "provider_total_count": _as_int(run.get("provider_total_count")),
        "rows_normalized": _as_int(run.get("rows_normalized")),
        "complete": run.get("complete"),
        "next_offset": _as_int(run.get("next_offset")),
        "error": run.get("error"),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "created_at": run.get("created_at"),
    }


def summarize_provider_dataset(
    *,
    provider: str = "dataforseo",
    snapshot: Optional[dict] = None,
    runs: Optional[list[dict]] = None,
    keyword_rows_stored: Optional[int] = None,
    keyword_captured_date: Optional[str] = None,
) -> dict[str, Any]:
    """Describe whether the cached rank-provider keyword dataset is complete.

    Deterministic and honest:

    * ``runs`` are cached ``marketing_seo_provider_runs`` rows for the
      ranked-keyword report, newest first. Completeness is read from the
      newest *completed* run (``complete`` / ``next_offset`` /
      ``provider_total_count``) — values NMS actually persisted from the
      provider. Nothing is invented.
    * ``percent_complete`` is only reported when the stored provider total
      makes it mathematically valid (total > 0 and total >= rows stored).
    * An incomplete dataset is described as "more keywords available to
      sync" — never as lost rankings.
    """
    runs = [r for r in (runs or []) if isinstance(r, dict)]
    ranked_runs = [
        r for r in runs
        if (r.get("report_type") or PROVIDER_RANKED_KEYWORDS_REPORT)
        == PROVIDER_RANKED_KEYWORDS_REPORT
    ]
    latest_run = ranked_runs[0] if ranked_runs else None
    latest_completed = next(
        (r for r in ranked_runs if (r.get("status") or "completed")
         == "completed"),
        None,
    )

    rows_stored = _as_int(keyword_rows_stored)
    has_snapshot = bool(snapshot)
    has_keywords = bool(rows_stored)
    connected = has_snapshot or has_keywords or bool(latest_run)

    provider_total = None
    complete: Optional[bool] = None
    next_offset = None
    if latest_completed is not None:
        provider_total = _as_int(latest_completed.get("provider_total_count"))
        raw_complete = latest_completed.get("complete")
        complete = bool(raw_complete) if raw_complete is not None else None
        next_offset = _as_int(latest_completed.get("next_offset"))

    if not connected:
        status = PROVIDER_DATASET_NOT_CONNECTED
        message = _PROVIDER_NOT_CONNECTED_MESSAGE
    elif complete is True:
        status = PROVIDER_DATASET_COMPLETE
        message = _PROVIDER_COMPLETE_MESSAGE
    elif complete is False:
        status = PROVIDER_DATASET_INCOMPLETE
        message = _PROVIDER_INCOMPLETE_MESSAGE
    else:
        status = PROVIDER_DATASET_UNKNOWN
        message = _PROVIDER_UNKNOWN_MESSAGE

    percent_complete = None
    if (
        provider_total is not None
        and provider_total > 0
        and rows_stored is not None
        and rows_stored <= provider_total
    ):
        percent_complete = round(rows_stored * 100.0 / provider_total, 1)

    remaining = None
    if (
        provider_total is not None
        and rows_stored is not None
        and provider_total >= rows_stored
    ):
        remaining = provider_total - rows_stored

    last_error = None
    if latest_run is not None and (
        (latest_run.get("status") or "completed") != "completed"
    ):
        last_error = latest_run.get("error") or latest_run.get("status")

    return {
        "provider": provider,
        "report_type": PROVIDER_RANKED_KEYWORDS_REPORT,
        "connected": connected,
        "status": status,
        "message": message,
        "complete": complete,
        "next_offset": next_offset,
        "provider_total_count": provider_total,
        "keyword_rows_stored": rows_stored,
        "keywords_remaining": remaining,
        "percent_complete": percent_complete,
        "keyword_captured_date": keyword_captured_date,
        "snapshot_captured_date": (
            snapshot.get("captured_date") if snapshot else None
        ),
        "latest_run": _run_summary(latest_run),
        "latest_completed_run": _run_summary(latest_completed),
        "last_error": last_error,
    }


def build_search_overview(
    *,
    site: Optional[dict] = None,
    keywords: Optional[list[NormalizedKeyword]] = None,
    latest_audit: Optional[dict] = None,
    backlink_summary: Optional[dict] = None,
    gsc_summary: Optional[dict] = None,
    connections: Optional[dict] = None,
    seo_provider: Optional[dict] = None,
) -> dict[str, Any]:
    """Aggregate a deterministic, honest SEO overview.

    - `site`: dict of the configured marketing site (or None).
    - `keywords`: first-party tracked NormalizedKeyword list.
    - `latest_audit`: latest audit run summary (or None).
    - `backlink_summary`: reserved for a future backlink provider.
    - `gsc_summary`: normalized Google Search Console totals (or None).
    - `connections`: which external data sources are connected.
    - `seo_provider`: CACHED rank-provider (DataForSEO Labs) state read from
      PostgreSQL only — ``{"provider", "snapshot", "runs",
      "keyword_rows_stored", "keyword_captured_date"}``. Never triggers a
      provider call. Snapshot metrics are reported under their own
      provider source and are NEVER derived from Search Console.
    """
    keywords = keywords or []
    gsc = gsc_summary or {}
    gsc_connected = bool(gsc.get("connected"))

    provider_state = seo_provider or {}
    provider_name = str(provider_state.get("provider") or "dataforseo")
    provider_snapshot = provider_state.get("snapshot") or None
    provider_dataset = summarize_provider_dataset(
        provider=provider_name,
        snapshot=provider_snapshot,
        runs=provider_state.get("runs"),
        keyword_rows_stored=provider_state.get("keyword_rows_stored"),
        keyword_captured_date=provider_state.get("keyword_captured_date"),
    )
    rank_provider_connected = bool(provider_snapshot)

    backlinks_state = backlink_summary or {}
    conn = {
        "rank_provider": rank_provider_connected,
        "search_console": gsc_connected,
        "backlink_provider": bool(backlinks_state.get("connected")),
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
            "provider_dataset": summarize_provider_dataset(
                provider=provider_name
            ),
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
    backlink_source = (
        str(backlinks.get("provider") or provider_name)
        if conn["backlink_provider"] else "backlink_provider"
    )
    competitors = provider_state.get("competitors") or {}
    competitors_connected = bool(competitors.get("connected"))
    rank_tracking = provider_state.get("rank_tracking") or {}
    rt_connected = bool(rank_tracking.get("connected"))
    rt_source = (
        f"{provider_name}_serp" if rt_connected else "rank_tracking"
    )

    snap = provider_snapshot or {}
    provider_source = (
        str(snap.get("provider") or provider_name)
        if conn["rank_provider"]
        else "rank_provider"
    )

    metrics = {
        # Search Console first-party observations.
        #
        # GSC query count is NOT a Semrush-style organic ranking-keyword
        # universe, and GSC clicks are NOT estimated organic traffic.
        "gsc_search_queries": _metric(
            gsc.get("search_queries"), conn["search_console"],
            "google_search_console"
        ),
        "organic_clicks": _metric(
            gsc.get("clicks"), conn["search_console"],
            "google_search_console"
        ),
        "organic_impressions": _metric(
            gsc.get("impressions"), conn["search_console"],
            "google_search_console"
        ),
        "organic_ctr": _metric(
            gsc.get("ctr"), conn["search_console"],
            "google_search_console"
        ),
        "average_organic_position": _metric(
            gsc.get("average_position"), conn["search_console"],
            "google_search_console"
        ),

        # Market-ranking metrics come from the CACHED rank provider
        # (DataForSEO Labs domain snapshot). They are a third-party
        # organic-keyword universe estimate — NOT Search Console data.
        "organic_keywords": _metric(
            _as_int(snap.get("organic_keywords")),
            conn["rank_provider"],
            provider_source,
        ),
        "estimated_organic_traffic": _metric(
            _as_float(snap.get("estimated_organic_traffic")),
            conn["rank_provider"],
            provider_source,
        ),
        "provider_new_keywords": _metric(
            _as_int(snap.get("new_keywords")),
            conn["rank_provider"],
            provider_source,
        ),
        "provider_up_keywords": _metric(
            _as_int(snap.get("up_keywords")),
            conn["rank_provider"],
            provider_source,
        ),
        "provider_down_keywords": _metric(
            _as_int(snap.get("down_keywords")),
            conn["rank_provider"],
            provider_source,
        ),
        "provider_lost_keywords": _metric(
            _as_int(snap.get("lost_keywords")),
            conn["rank_provider"],
            provider_source,
        ),
        "backlink_count": _metric(
            _as_int(backlinks.get("backlink_count")),
            conn["backlink_provider"],
            backlink_source,
        ),
        "referring_domain_count": _metric(
            _as_int(backlinks.get("referring_domain_count")),
            conn["backlink_provider"],
            backlink_source,
        ),
        # Sampled from the cached backlink rows of the latest snapshot (the
        # provider summary does not return new/lost totals) — labelled so.
        "backlink_new_links_sampled": _metric(
            _as_int(backlinks.get("new_links_sampled")),
            conn["backlink_provider"],
            backlink_source,
        ),
        "backlink_lost_links_sampled": _metric(
            _as_int(backlinks.get("lost_links_sampled")),
            conn["backlink_provider"],
            backlink_source,
        ),
        # Competitor intelligence (cached DataForSEO competitors_domain).
        "organic_competitors": _metric(
            _as_int(competitors.get("count")),
            competitors_connected,
            provider_name if competitors_connected else "rank_provider",
        ),
        "competitor_common_keywords": _metric(
            _as_int(competitors.get("common_keywords")),
            competitors_connected,
            provider_name if competitors_connected else "rank_provider",
        ),
        "keyword_opportunities": _metric(
            _as_int(competitors.get("keyword_opportunities")),
            competitors_connected,
            provider_name if competitors_connected else "rank_provider",
        ),
        # Live SERP rank tracking (cached observations).
        "rt_tracked_keywords": _metric(
            _as_int(rank_tracking.get("tracked")), rt_connected, rt_source
        ),
        "rt_top_3": _metric(_as_int(rank_tracking.get("top_3")), rt_connected, rt_source),
        "rt_top_10": _metric(_as_int(rank_tracking.get("top_10")), rt_connected, rt_source),
        "rt_top_20": _metric(_as_int(rank_tracking.get("top_20")), rt_connected, rt_source),
        "rt_improved": _metric(_as_int(rank_tracking.get("improved")), rt_connected, rt_source),
        "rt_declined": _metric(_as_int(rank_tracking.get("declined")), rt_connected, rt_source),
        "rt_average_position": _metric(
            _as_float(rank_tracking.get("average_position")), rt_connected, rt_source
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
        "provider_dataset": provider_dataset,
        "provider_snapshot": (
            {
                "provider": provider_source,
                "captured_date": snap.get("captured_date"),
                "location": snap.get("location"),
                "language": snap.get("language"),
                "device": snap.get("device"),
            }
            if conn["rank_provider"]
            else None
        ),
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
        "gsc_search_queries",
        "organic_keywords",
        "estimated_organic_traffic",
        "provider_new_keywords",
        "provider_up_keywords",
        "provider_down_keywords",
        "provider_lost_keywords",
        "organic_clicks",
        "organic_impressions",
        "organic_ctr",
        "average_organic_position",
        "backlink_count",
        "referring_domain_count",
        "backlink_new_links_sampled",
        "backlink_lost_links_sampled",
        "organic_competitors",
        "competitor_common_keywords",
        "keyword_opportunities",
        "rt_tracked_keywords",
        "rt_top_3",
        "rt_top_10",
        "rt_top_20",
        "rt_improved",
        "rt_declined",
        "rt_average_position",
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
