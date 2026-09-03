"""Unit tests for Marketing OS Phase 11 deterministic content intelligence."""

import pytest

from marketing_os.services import content_intelligence as ci
from marketing_os.services.measurement import MarketingDataPolicyError


def test_seo_opportunity_priority_bounds_and_ordering():
    low = ci.seo_opportunity_priority(
        {"impressions": 10, "avg_position": 2, "ctr": 0.5})
    high = ci.seo_opportunity_priority(
        {"impressions": 5000, "avg_position": 28, "ctr": 0.0,
         "competitor_gap": 1.0})
    assert 0 <= low <= 100
    assert 0 <= high <= 100
    assert high > low


def test_funnel_relevance_offer_and_funnel_boost():
    base = ci.funnel_relevance("awareness", has_offer=False, has_funnel=False)
    boosted = ci.funnel_relevance("decision", has_offer=True, has_funnel=True)
    assert base == 10
    assert boosted == 100  # 40 + 30 + 30 capped at 100


def test_freshness_need_thresholds():
    assert ci.freshness_need(400) == "high"
    assert ci.freshness_need(200) == "medium"
    assert ci.freshness_need(30) == "low"
    assert ci.freshness_need(None) == "unknown"


def test_composite_priority_is_bounded():
    p = ci.composite_topic_priority(seo=100, funnel=100, conversion=100,
                                    freshness="high")
    assert 0 <= p <= 100


def test_generate_draft_scaffold_blog_vs_tiktok():
    blog = ci.generate_draft_scaffold(channel="blog", title="IV Therapy 101")
    tik = ci.generate_draft_scaffold(channel="tiktok", title="IV Therapy 101",
                                     target_keyword="iv therapy")
    assert blog["body"] and blog["hook"] is None
    assert tik["hook"] and tik["script"] and tik["shot_list"]["shots"]


def test_validate_slug_and_channel_reject_bad_input():
    with pytest.raises(ci.ContentConfigError):
        ci.validate_slug("Bad Slug")
    with pytest.raises(ci.ContentConfigError):
        ci.validate_channel("myspace")
    assert ci.validate_channel("Blog") == "blog"


def test_bounded_json_rejects_phi():
    with pytest.raises(MarketingDataPolicyError):
        ci.bounded_json({"email": "a@b.com"}, "metrics")
    assert ci.bounded_json({"impressions": 10}, "metrics") == {
        "impressions": 10}
