"""Phase 10 local-growth deterministic unit tests (pure, no DB)."""

import pytest

from marketing_os.services import local_growth as lg
from marketing_os.services.local_growth import LocalConfigError
from marketing_os.services.measurement import MarketingDataPolicyError


def test_completeness_score():
    assert lg.listing_completeness_score({}) == 0.0
    full = {f: True for f in lg._PROFILE_FIELDS}
    assert lg.listing_completeness_score(full) == 1.0
    half = {"name": True, "address": True, "phone": True, "website": True}
    assert 0.0 < lg.listing_completeness_score(half) < 1.0


def test_nap_consistency():
    assert lg.nap_consistency_score({"name_matches": True,
        "address_matches": True, "phone_matches": True}) == 1.0
    assert lg.nap_consistency_score({"name_matches": True,
        "address_matches": False}) == 0.5
    assert lg.nap_consistency_score({}) == 0.0


def test_reputation_trend():
    assert lg.reputation_trend(4.6, 4.2)["direction"] == "up"
    assert lg.reputation_trend(4.0, 4.5)["direction"] == "down"
    assert lg.reputation_trend(4.3, 4.3)["direction"] == "flat"
    assert lg.reputation_trend(4.6, 4.2, 120, 100)["review_delta"] == 20


@pytest.mark.parametrize("n,cls", [
    (0, "low"), (1, "low"), (2, "medium"), (7, "medium"), (12, "high"),
    (None, "unknown"),
])
def test_review_velocity(n, cls):
    assert lg.classify_review_velocity(n) == cls


def test_source_coverage():
    c = lg.source_coverage(["google", "yelp"])
    assert "bing" in c["missing"] and "google" in c["covered"]
    assert 0 < c["coverage"] < 1


def test_health_score_bounds():
    lo = lg.location_health_score(completeness=0, nap=0, rating=None,
        review_velocity_class="unknown", response_rate=None)
    hi = lg.location_health_score(completeness=1.0, nap=1.0, rating=5.0,
        review_velocity_class="high", response_rate=1.0)
    assert lo == 0 and hi == 100
    mid = lg.location_health_score(completeness=0.5, nap=0.5, rating=4.0,
        review_velocity_class="medium", response_rate=0.5)
    assert 0 < mid < 100


def test_build_opportunities_explainable():
    opps = lg.build_opportunities(
        location={"id": "L1", "hours": {}},
        active_providers=["google"],
        latest_reputation={"google": {"reviews_last_30d": 0,
                                      "response_rate": 0.2}},
        latest_listing={"google": {"listing_status": "unclaimed",
                                   "fields_present": {"name": True},
                                   "name_matches": True,
                                   "address_matches": False}},
        best_local_rank=9)
    types = {o["opportunity_type"] for o in opps}
    assert "missing_hours" in types
    assert "missing_directory" in types      # yelp/bing/apple missing
    assert "incomplete_profile" in types     # unclaimed google
    assert "nap_inconsistent" in types
    assert "low_review_velocity" in types
    assert "weak_response_rate" in types
    assert "local_ranking_gap" in types
    # sorted by descending priority + deterministic key
    prios = [o["priority"] for o in opps]
    assert prios == sorted(prios, reverse=True)


def test_no_opportunities_when_healthy():
    opps = lg.build_opportunities(
        location={"id": "L1", "hours": {"mon": "9-5"}},
        active_providers=["google", "yelp", "bing", "apple"],
        latest_reputation={"google": {"reviews_last_30d": 12,
                                      "response_rate": 0.95}},
        latest_listing={"google": {"listing_status": "published",
                        "fields_present": {f: True for f in lg._PROFILE_FIELDS},
                        "name_matches": True, "address_matches": True,
                        "phone_matches": True, "category_matches": True,
                        "website_matches": True}},
        best_local_rank=1)
    assert opps == []


def test_validate_provider_and_slug():
    assert lg.validate_provider("Google") == "google"
    with pytest.raises(LocalConfigError):
        lg.validate_provider("myspace")
    with pytest.raises(LocalConfigError):
        lg.validate_slug("Bad Slug")


def test_bounded_json_rejects_phi():
    with pytest.raises((MarketingDataPolicyError, LocalConfigError)):
        lg.bounded_json({"email": "a@b.com"}, "config")
