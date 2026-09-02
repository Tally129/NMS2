"""Focused tests for Phase 3 (competitors / keyword gap / backlinks / local).

Deterministic; no network, no PHI, no production creds.
"""
from __future__ import annotations

import inspect

import pytest

from marketing_os.policy import DEFAULT_POLICY
from marketing_os.services.measurement import (
    PROHIBITED_MARKETING_FIELDS, MarketingDataPolicyError)
from marketing_os.search import phase3
from marketing_os.search.phase3 import (
    backlink_deltas, backlink_overview, classify_gap, normalize_backlink,
    normalize_competitor, normalize_domain, normalize_gap_record,
    normalize_local_record, summarize_gap)
from marketing_os.search.phase3_recommendations import (
    build_phase3_recommendations)
from marketing_os.routers import search_phase3 as routes


# ------------------------------------------------------------- competitors
def test_normalize_domain_variants():
    assert normalize_domain("https://www.Example.com/path") == "example.com"
    assert normalize_domain("Example.com") == "example.com"


def test_normalize_competitor_and_phi():
    c = normalize_competitor({"domain": "https://www.rival.com",
                              "display_name": "Rival"})
    assert c["normalized_domain"] == "rival.com"
    assert c["is_active"] is True
    with pytest.raises(ValueError):
        normalize_competitor({"domain": ""})
    with pytest.raises(MarketingDataPolicyError):
        normalize_competitor({"domain": "rival.com", "email": "a@b.com"})


# ------------------------------------------------------------- keyword gap
def test_classify_gap_all_paths():
    assert classify_gap(None, None) == "unknown"
    assert classify_gap(None, 5) == "missing"        # competitor-only
    assert classify_gap(4, None) == "nms_only"
    assert classify_gap(3, 8) == "strong"            # NMS better
    assert classify_gap(9, 4) == "weak"              # competitor better
    assert classify_gap(5, 5) == "shared"


def test_gap_unavailable_metrics_stay_null_not_zero():
    r = normalize_gap_record({"keyword": "detox clinic"})
    assert r["nms_position"] is None
    assert r["competitor_position"] is None
    assert r["search_volume"] is None
    assert r["keyword_difficulty"] is None
    assert r["opportunity"] == "unknown"
    assert r["source"] == "unknown"


def test_summarize_gap_counts():
    recs = [
        normalize_gap_record({"keyword": "a", "competitor_position": 3}),
        normalize_gap_record({"keyword": "b", "nms_position": 2}),
        normalize_gap_record({"keyword": "c", "nms_position": 3,
                              "competitor_position": 8}),
        normalize_gap_record({"keyword": "d", "nms_position": 9,
                              "competitor_position": 4}),
    ]
    s = summarize_gap(recs)
    assert s["missing"] == 1 and s["competitor_only"] == 1
    assert s["nms_only"] == 1 and s["strong"] == 1 and s["weak"] == 1


def test_gap_record_rejects_phi():
    with pytest.raises(MarketingDataPolicyError):
        normalize_gap_record({"keyword": "x", "phone": "555"})


# --------------------------------------------------------------- backlinks
def test_normalize_backlink_and_authority_null_without_provider():
    b = normalize_backlink({"source_url": "https://ref.com/post",
                            "rel_type": "FOLLOW"})
    assert b["referring_domain"] == "ref.com"
    assert b["rel_type"] == "follow"
    assert b["authority"] is None       # no provider -> not fabricated
    with pytest.raises(ValueError):
        normalize_backlink({"source_url": ""})


def test_backlink_new_lost_calculations():
    prev = [{"source_url": "a", "target_url": "t", "referring_domain": "a"},
            {"source_url": "b", "target_url": "t", "referring_domain": "b"}]
    cur = [{"source_url": "b", "target_url": "t", "referring_domain": "b"},
           {"source_url": "c", "target_url": "t", "referring_domain": "c"}]
    d = backlink_deltas(cur, prev)
    assert d["new_backlinks"] == 1 and d["lost_backlinks"] == 1
    assert d["backlink_count"] == 2 and d["referring_domains"] == 2


def test_backlink_overview_not_connected():
    ov = backlink_overview(None, connected=False)
    assert ov["connected"] is False
    assert ov["backlink_count"] is None
    assert ov["referring_domains"] is None


# ---------------------------------------------------------------- local seo
def test_normalize_local_record():
    r = normalize_local_record({"target_keyword": "Naturopath Austin",
                                "city": "Austin", "state": "TX"})
    assert r["normalized_keyword"] == "naturopath austin"
    assert r["local_rank"] is None     # unknown, not zero
    assert r["provider"] == "unknown"
    with pytest.raises(ValueError):
        normalize_local_record({"target_keyword": ""})


# ------------------------------------------------------ advisory recs / director
def test_recommendations_are_advisory_only():
    gap = [normalize_gap_record({"keyword": "missing kw",
                                 "competitor_position": 3}),
           normalize_gap_record({"keyword": "weak kw", "nms_position": 9,
                                 "competitor_position": 4})]
    recs = build_phase3_recommendations(
        gap_records=gap,
        lost_backlinks=[{"referring_domain": "x.com", "source_url": "u"}],
        backlink_opportunities=[{"referring_domain": "y.com"}],
        local_gaps=[{"keyword": "pt in austin", "city": "Austin"}])
    assert recs
    for r in recs:
        assert r["advisory_only"] is True
        assert r["requires_human_approval"] is True
        assert r["external_write"] is False
    titles = {r["title"] for r in recs}
    assert "Target missing competitor keyword" in titles
    assert "Investigate lost backlink" in titles
    assert "Create local service/location content" in titles
    priorities = [r["priority"] for r in recs]
    assert priorities == sorted(priorities, reverse=True)


# -------------------------------------------------------------- no-PHI models
def test_phase3_models_have_no_phi_columns():
    from postgres_models.marketing_phase3 import (
        MarketingBacklinkSnapshot, MarketingKeywordGapSnapshot,
        MarketingLocalRankSnapshot, MarketingSearchCompetitor)
    for model in (MarketingSearchCompetitor, MarketingKeywordGapSnapshot,
                  MarketingBacklinkSnapshot, MarketingLocalRankSnapshot):
        cols = {c.name for c in model.__table__.columns}
        assert not (cols & PROHIBITED_MARKETING_FIELDS), model


# ------------------------------------------------- role auth + no external write
PHASE3_HANDLERS = [
    "list_competitors", "add_competitor", "get_competitor", "keyword_gap",
    "content_opportunities", "backlinks_overview", "backlinks_list",
    "local_seo", "local_opportunities",
]


def test_all_phase3_routes_use_marketing_role_gate():
    for name in PHASE3_HANDLERS:
        src = inspect.getsource(getattr(routes, name))
        assert "require_roles(*MARKETING_ROLES)" in src, name


def test_no_external_write_paths_in_services():
    for fn in (phase3.normalize_competitor, phase3.normalize_gap_record,
               phase3.normalize_backlink, phase3.normalize_local_record):
        src = inspect.getsource(fn).lower()
        for token in ("requests.", "httpx.", "execute_action", "publish"):
            assert token not in src


def test_safety_policy_unchanged():
    assert DEFAULT_POLICY.external_writes_enabled is False
    assert DEFAULT_POLICY.automatic_budget_changes_enabled is False
    assert DEFAULT_POLICY.automatic_campaign_creation_enabled is False
    assert DEFAULT_POLICY.automatic_publishing_enabled is False
    assert DEFAULT_POLICY.human_approval_required is True
