"""Focused tests for Marketing OS Search Intelligence (Phase 1).

Covers: overview aggregation, keyword normalization, rank-change math,
site-audit classification, duplicate title/meta detection, non-PHI data
structures, marketing-role authorization (source inspection), empty /
not-connected states, advisory recommendations, and unchanged safety
policy. All tests are deterministic and require no network or DB.
"""

from __future__ import annotations

import inspect
from decimal import Decimal

import pytest

from marketing_os.capabilities import CAPABILITIES
from marketing_os.policy import DEFAULT_POLICY
from marketing_os.services.measurement import (
    PROHIBITED_MARKETING_FIELDS,
    MarketingDataPolicyError,
)
from marketing_os.search.contracts import (
    AuditIssue,
    NormalizedKeyword,
    SEVERITY_CRITICAL,
    SEVERITY_OPPORTUNITY,
    SEVERITY_WARNING,
)
from marketing_os.search.keywords import (
    compute_rank_change,
    infer_intent,
    normalize_keyword,
    rank_gainers,
    rank_losers,
    summarize_keywords,
)
from marketing_os.search.overview import build_search_overview
from marketing_os.search.recommendations import build_search_recommendations
from marketing_os.search.site_audit import (
    PageFetchResult,
    classify_page,
    run_audit,
)
from marketing_os.routers import search as search_routes


GOOD_HTML = (
    "<html><head><title>Home</title>"
    "<meta name='description' content='A good description'>"
    "<link rel='canonical' href='https://clinic.example/'>"
    "</head><body><h1>Welcome</h1>"
    "<img src='a.jpg' alt='a'></body></html>"
)


def _page(url="https://clinic.example/", status=200, html=GOOD_HTML,
          elapsed=120, headers=None, chain=(), error=None):
    return PageFetchResult(
        url=url,
        final_url=url,
        status_code=status,
        elapsed_ms=elapsed,
        redirect_chain=chain,
        html=html,
        headers=headers or {},
        fetch_error=error,
    )


# --------------------------------------------------------------------------
# Keyword normalization
# --------------------------------------------------------------------------

def test_normalize_keyword_basic():
    nk = normalize_keyword({
        "keyword": "  Naturopathic   Clinic  ",
        "search_volume": "1200",
        "keyword_difficulty": "45",
        "cpc": "3.50",
        "device": "MOBILE",
        "location": "Austin",
    })
    assert nk.keyword == "Naturopathic Clinic"
    assert nk.normalized_keyword == "naturopathic clinic"
    assert nk.search_volume == 1200
    assert nk.keyword_difficulty == 45
    assert nk.cpc == Decimal("3.50")
    assert nk.device == "mobile"
    assert nk.location == "Austin"


def test_keyword_difficulty_clamped():
    assert normalize_keyword(
        {"keyword": "x", "keyword_difficulty": 250}
    ).keyword_difficulty == 100


def test_intent_inference():
    assert infer_intent("book appointment online") == "transactional"
    assert infer_intent("best clinic near me") == "commercial"
    assert infer_intent("what is naturopathy") == "informational"
    assert infer_intent("clinic brand xyz") == "unknown"


def test_normalize_keyword_requires_keyword():
    with pytest.raises(ValueError):
        normalize_keyword({"keyword": "   "})


def test_normalize_keyword_rejects_phi():
    with pytest.raises(MarketingDataPolicyError):
        normalize_keyword({"keyword": "detox", "email": "a@b.com"})
    with pytest.raises(MarketingDataPolicyError):
        normalize_keyword({"keyword": "detox", "diagnosis": "x"})


# --------------------------------------------------------------------------
# Rank-change math
# --------------------------------------------------------------------------

def test_compute_rank_change():
    assert compute_rank_change(3, 8) == 5      # improved
    assert compute_rank_change(9, 4) == -5     # declined
    assert compute_rank_change(5, 5) == 0
    assert compute_rank_change(5, None) is None
    assert compute_rank_change(None, 5) is None


def test_movement_labels():
    assert normalize_keyword(
        {"keyword": "a", "current_rank": 3, "previous_rank": 8}
    ).movement() == "gain"
    assert normalize_keyword(
        {"keyword": "a", "current_rank": 9, "previous_rank": 4}
    ).movement() == "loss"
    assert normalize_keyword(
        {"keyword": "a", "current_rank": 5}
    ).movement() == "new"
    assert normalize_keyword({"keyword": "a"}).movement() == "unranked"


def _kw(keyword, current=None, previous=None, tracked=True):
    return normalize_keyword({
        "keyword": keyword,
        "current_rank": current,
        "previous_rank": previous,
        "is_tracked": tracked,
    })


def test_summarize_keywords_buckets_and_movement():
    keywords = [
        _kw("a", current=1, previous=5),    # top3, gain
        _kw("b", current=8, previous=6),    # top10, loss
        _kw("c", current=15, previous=15),  # top20, flat
        _kw("d", current=None),             # unranked
    ]
    summary = summarize_keywords(keywords)
    assert summary["total"] == 4
    assert summary["ranked"] == 3
    assert summary["keywords_in_top_3"] == 1
    assert summary["keywords_in_top_10"] == 2
    assert summary["keywords_in_top_20"] == 3
    assert summary["ranking_gains"] == 1
    assert summary["ranking_losses"] == 1
    assert summary["average_position"] == round((1 + 8 + 15) / 3, 2)


def test_rank_gainers_and_losers_sorted():
    keywords = [
        _kw("big-gain", current=2, previous=20),
        _kw("small-gain", current=4, previous=6),
        _kw("big-loss", current=30, previous=3),
    ]
    gainers = rank_gainers(keywords)
    assert [k.keyword for k in gainers] == ["big-gain", "small-gain"]
    losers = rank_losers(keywords)
    assert losers[0].keyword == "big-loss"


# --------------------------------------------------------------------------
# Site-audit classification
# --------------------------------------------------------------------------

def _codes(issues):
    return {i.issue_code for i in issues}


def test_good_page_has_no_issues():
    assert classify_page(_page()) == []


def test_missing_metadata_issues():
    html = "<html><head></head><body><img src='a.jpg'></body></html>"
    codes = _codes(classify_page(_page(html=html)))
    assert "missing_title" in codes
    assert "missing_meta_description" in codes
    assert "missing_canonical" in codes
    assert "missing_h1" in codes
    assert "images_missing_alt" in codes


def test_noindex_directive_is_critical():
    html = (
        "<html><head><title>t</title>"
        "<meta name='robots' content='noindex,follow'>"
        "<meta name='description' content='d'>"
        "<link rel='canonical' href='https://clinic.example/'>"
        "</head><body><h1>h</h1></body></html>"
    )
    issues = classify_page(_page(html=html))
    noindex = [i for i in issues if i.issue_code == "noindex_directive"]
    assert noindex and noindex[0].severity == SEVERITY_CRITICAL


def test_x_robots_header_noindex():
    codes = _codes(classify_page(
        _page(headers={"x-robots-tag": "noindex"})
    ))
    assert "noindex_directive" in codes


def test_multiple_h1_is_opportunity():
    html = (
        "<html><head><title>t</title>"
        "<meta name='description' content='d'>"
        "<link rel='canonical' href='https://clinic.example/'>"
        "</head><body><h1>a</h1><h1>b</h1></body></html>"
    )
    issues = classify_page(_page(html=html))
    m = [i for i in issues if i.issue_code == "multiple_h1"]
    assert m and m[0].severity == SEVERITY_OPPORTUNITY


def test_http_errors_short_circuit():
    assert _codes(classify_page(_page(status=404))) == {"http_4xx"}
    assert _codes(classify_page(_page(status=503))) == {"http_5xx"}
    assert _codes(classify_page(_page(error="timeout", status=None))) == {
        "page_unreachable"
    }


def test_redirect_chain_flagged():
    chain = (
        "https://clinic.example/a",
        "https://clinic.example/b",
        "https://clinic.example/",
    )
    codes = _codes(classify_page(_page(chain=chain)))
    assert "redirect_chain" in codes


def test_slow_response_flagged():
    codes = _codes(classify_page(_page(elapsed=5000)))
    assert "slow_response" in codes


def test_broken_internal_link_detection():
    html = (
        "<html><head><title>t</title>"
        "<meta name='description' content='d'>"
        "<link rel='canonical' href='https://clinic.example/'>"
        "</head><body><h1>h</h1>"
        "<a href='https://clinic.example/broken'>x</a></body></html>"
    )
    issues = classify_page(
        _page(html=html),
        link_status={"https://clinic.example/broken": 404},
    )
    assert "broken_internal_link" in _codes(issues)


# --------------------------------------------------------------------------
# Duplicate title / meta detection (cross-page)
# --------------------------------------------------------------------------

def _dup_page(url, title, meta):
    html = (
        f"<html><head><title>{title}</title>"
        f"<meta name='description' content='{meta}'>"
        "<link rel='canonical' href='https://clinic.example/'>"
        "</head><body><h1>h</h1></body></html>"
    )
    return _page(url=url, html=html)


def test_duplicate_title_and_meta_detection():
    pages = [
        _dup_page("https://clinic.example/1", "Same Title", "Same Meta"),
        _dup_page("https://clinic.example/2", "Same Title", "Same Meta"),
    ]
    result = run_audit(pages)
    codes = {i["issue_code"] for i in result["issues"]}
    assert "duplicate_title" in codes
    assert "duplicate_meta_description" in codes
    dup_title_urls = {
        i["url"] for i in result["issues"]
        if i["issue_code"] == "duplicate_title"
    }
    assert dup_title_urls == {
        "https://clinic.example/1", "https://clinic.example/2"
    }


def test_run_audit_counts_and_sitemap():
    result = run_audit([_page()], sitemap_found=False)
    assert result["pages_scanned"] == 1
    assert "missing_sitemap" in {i["issue_code"] for i in result["issues"]}
    assert result["opportunity_count"] >= 1
    # Deterministic total.
    assert result["issues_total"] == len(result["issues"])


# --------------------------------------------------------------------------
# Overview + empty/not-connected
# --------------------------------------------------------------------------

def test_overview_not_connected_when_no_site():
    overview = build_search_overview(site=None)
    assert overview["connected"] is False
    assert overview["not_connected_reason"] == "no_marketing_site_configured"
    for metric in overview["metrics"].values():
        assert metric["value"] is None
        assert metric["connected"] is False


def test_overview_reports_first_party_but_null_provider_metrics():
    site = {"id": "s1", "site_url": "https://clinic.example"}
    keywords = [_kw("a", current=2, previous=9), _kw("b", current=12)]
    audit = {
        "issues_total": 4, "pages_scanned": 3, "critical_count": 1,
        "warning_count": 2, "opportunity_count": 1,
        "informational_count": 0, "status": "completed",
    }
    overview = build_search_overview(
        site=site, keywords=keywords, latest_audit=audit
    )
    assert overview["connected"] is True
    m = overview["metrics"]
    # Provider-only metrics stay honestly null/not-connected.
    assert m["organic_keywords"]["connected"] is False
    assert m["organic_keywords"]["value"] is None
    assert m["backlink_count"]["connected"] is False
    # First-party metrics are populated truthfully.
    assert m["tracked_keywords"]["value"] == 2
    assert m["keywords_in_top_3"]["value"] == 1
    assert m["technical_issue_count"]["value"] == 4
    assert m["indexed_pages"]["value"] == 3


# --------------------------------------------------------------------------
# Advisory recommendations
# --------------------------------------------------------------------------

def test_recommendations_are_advisory_only():
    issues = [
        {"issue_code": "missing_title", "severity": "critical",
         "category": "metadata", "url": "https://clinic.example/"},
        {"issue_code": "slow_response", "severity": "opportunity",
         "category": "performance", "url": "https://clinic.example/"},
    ]
    keywords = [_kw("declining", current=20, previous=5),
                _kw("page2", current=14)]
    recs = build_search_recommendations(
        overview={"connections": {"rank_provider": False}},
        audit_issues=issues,
        keywords=keywords,
    )
    assert recs, "expected recommendations"
    for rec in recs:
        assert rec["advisory_only"] is True
        assert rec["requires_human_approval"] is True
        assert rec["external_write"] is False
    codes = {r["title"] for r in recs}
    assert "Improve page title" in codes
    assert "Investigate ranking decline" in codes
    # Deterministic ordering: non-increasing priority.
    priorities = [r["priority"] for r in recs]
    assert priorities == sorted(priorities, reverse=True)


def test_recommendations_deterministic():
    issues = [{"issue_code": "missing_meta_description",
               "severity": "warning", "category": "metadata",
               "url": "https://clinic.example/"}]
    first = build_search_recommendations(audit_issues=issues)
    second = build_search_recommendations(audit_issues=issues)
    assert first == second


# --------------------------------------------------------------------------
# Non-PHI data structures
# --------------------------------------------------------------------------

def test_contracts_have_no_phi_fields():
    for dc in (NormalizedKeyword, AuditIssue):
        fields = set(getattr(dc, "__dataclass_fields__", {}).keys())
        assert not (fields & PROHIBITED_MARKETING_FIELDS), dc


def test_search_models_have_no_phi_columns():
    from postgres_models.marketing_search import (
        MarketingKeywordRankSnapshot,
        MarketingSearchKeyword,
        MarketingSearchSite,
        MarketingSiteAuditIssue,
        MarketingSiteAuditRun,
    )
    models = [
        MarketingSearchSite, MarketingSearchKeyword,
        MarketingKeywordRankSnapshot, MarketingSiteAuditRun,
        MarketingSiteAuditIssue,
    ]
    for model in models:
        columns = {c.name for c in model.__table__.columns}
        assert not (columns & PROHIBITED_MARKETING_FIELDS), model


# --------------------------------------------------------------------------
# Marketing-role authorization + read-only (source inspection)
# --------------------------------------------------------------------------

SEARCH_HANDLERS = [
    "list_search_sites",
    "register_search_site",
    "list_search_keywords",
    "list_tracked_keywords",
    "track_keyword",
    "search_overview",
    "run_site_audit",
    "latest_site_audit",
    "site_audit_issues",
    "search_recommendations",
]


def test_all_search_routes_use_marketing_role_gate():
    for name in SEARCH_HANDLERS:
        handler = getattr(search_routes, name)
        source = inspect.getsource(handler)
        assert "require_roles(*MARKETING_ROLES)" in source, name


def test_marketing_roles_are_admin_and_practitioner():
    assert search_routes.MARKETING_ROLES == ("admin", "practitioner")


def test_run_audit_engine_performs_no_provider_writes():
    # The deterministic engine must not touch providers or execute actions.
    src = inspect.getsource(run_audit).lower()
    for token in ("execute_action", "create_integration", "insert into"):
        assert token not in src


def test_live_fetcher_is_read_only():
    from marketing_os.search import site_audit
    src = inspect.getsource(site_audit.fetch_site).lower()
    # Only GET requests are issued to the target site.
    for token in ("client.post", "client.put", "client.delete",
                  "client.patch"):
        assert token not in src
    assert "client.get(" in src


# --------------------------------------------------------------------------
# Safety policy unchanged
# --------------------------------------------------------------------------

def test_default_policy_unchanged():
    assert DEFAULT_POLICY.external_writes_enabled is False
    assert DEFAULT_POLICY.automatic_budget_changes_enabled is False
    assert DEFAULT_POLICY.automatic_campaign_creation_enabled is False
    assert DEFAULT_POLICY.automatic_publishing_enabled is False
    assert DEFAULT_POLICY.human_approval_required is True


def test_search_capability_is_read_only_and_non_phi():
    cap = CAPABILITIES["search_intelligence"]
    assert cap["mode"] == "read_only"
    assert cap["write_enabled"] is False
    assert cap["external_write_enabled"] is False
    assert cap["phi_stored"] is False
    assert cap["recommendations_mode"] == "advisory"
