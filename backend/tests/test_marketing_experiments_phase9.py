"""Phase 9 experimentation — pure deterministic unit tests (no DB/network)."""

import pytest

from marketing_os.services import experiments as ex
from marketing_os.services.experiments import ExperimentConfigError
from marketing_os.services.measurement import MarketingDataPolicyError


# --------------------------- validation --------------------------- #

def test_valid_experiment_defaults():
    out = ex.validate_experiment_payload(
        {"name": "LP test", "slug": "lp-test", "experiment_type": "landing_page"}
    )
    assert out["primary_metric"] == "conversion"
    assert out["exposure_metric"] == "impression"


@pytest.mark.parametrize("bad", ["Bad Slug!", "", "A_B"])
def test_bad_slug_rejected(bad):
    with pytest.raises(ExperimentConfigError):
        ex.validate_experiment_payload(
            {"name": "x", "slug": bad, "experiment_type": "offer"})


def test_unknown_type_rejected():
    with pytest.raises(ExperimentConfigError):
        ex.validate_experiment_payload(
            {"name": "x", "slug": "ok", "experiment_type": "banner"})


def test_config_phi_rejected():
    with pytest.raises((MarketingDataPolicyError, ExperimentConfigError)):
        ex.validate_experiment_payload(
            {"name": "x", "slug": "ok", "experiment_type": "offer",
             "config": {"email": "a@b.com"}})


def test_variant_alloc_bounds():
    with pytest.raises(ExperimentConfigError):
        ex.validate_variant_payload(
            {"variant_key": "v1", "name": "V1", "allocation_pct": 150})


def test_activation_requires_two_variants_one_control_sum_100():
    with pytest.raises(ExperimentConfigError):
        ex.validate_activation([{"variant_key": "a", "is_control": True,
                                 "allocation_pct": 100}])
    with pytest.raises(ExperimentConfigError):  # no control
        ex.validate_activation([
            {"variant_key": "a", "is_control": False, "allocation_pct": 50},
            {"variant_key": "b", "is_control": False, "allocation_pct": 50}])
    with pytest.raises(ExperimentConfigError):  # sum != 100
        ex.validate_activation([
            {"variant_key": "a", "is_control": True, "allocation_pct": 40},
            {"variant_key": "b", "is_control": False, "allocation_pct": 40}])
    # valid
    ex.validate_activation([
        {"variant_key": "a", "is_control": True, "allocation_pct": 50},
        {"variant_key": "b", "is_control": False, "allocation_pct": 50}])


@pytest.mark.parametrize("cur,tgt,ok", [
    ("draft", "active", True), ("draft", "completed", False),
    ("active", "paused", True), ("active", "archived", True),
    ("paused", "active", True), ("completed", "active", False),
    ("archived", "active", False),
])
def test_transitions(cur, tgt, ok):
    if ok:
        ex.assert_can_transition(cur, tgt)
    else:
        with pytest.raises(ExperimentConfigError):
            ex.assert_can_transition(cur, tgt)


# --------------------------- assignment --------------------------- #

VARIANTS = [
    {"id": "vA", "variant_key": "control", "is_control": True,
     "allocation_pct": 50},
    {"id": "vB", "variant_key": "treatment", "is_control": False,
     "allocation_pct": 50},
]


def test_assignment_is_deterministic():
    a = ex.assign_variant("exp1", "subject-123", VARIANTS)
    b = ex.assign_variant("exp1", "subject-123", VARIANTS)
    assert a["id"] == b["id"]


def test_assignment_differs_by_experiment():
    # Same subject may map differently across experiments (independent hashing)
    got = {ex.assign_variant(f"exp{i}", "subject-123", VARIANTS)["id"]
           for i in range(50)}
    assert got.issubset({"vA", "vB"})


def test_assignment_respects_allocation_roughly():
    counts = {"vA": 0, "vB": 0}
    for i in range(2000):
        counts[ex.assign_variant("expX", f"subj-{i}", VARIANTS)["id"]] += 1
    # 50/50 allocation → both arms populated, neither trivially empty
    assert counts["vA"] > 700 and counts["vB"] > 700


def test_assignment_100_pct_control():
    v = [
        {"id": "vA", "variant_key": "control", "is_control": True,
         "allocation_pct": 100},
        {"id": "vB", "variant_key": "t", "is_control": False,
         "allocation_pct": 0},
    ]
    got = {ex.assign_variant("e", f"s{i}", v)["id"] for i in range(200)}
    assert got == {"vA"}


# --------------------------- reporting --------------------------- #

def test_aggregate_and_report_rates():
    variants = [
        {"id": "c", "variant_key": "control", "is_control": True,
         "allocation_pct": 50, "name": "Control"},
        {"id": "t", "variant_key": "treatment", "is_control": False,
         "allocation_pct": 50, "name": "Treatment"},
    ]
    per_variant = {
        "c": ex.aggregate_variant([
            {"metric_type": "impression", "cnt": 200, "sum": 0},
            {"metric_type": "conversion", "cnt": 20, "sum": 2000},
            {"metric_type": "spend", "cnt": 1, "sum": 500},
            {"metric_type": "lead", "cnt": 40, "sum": 0},
        ], assignments=200),
        "t": ex.aggregate_variant([
            {"metric_type": "impression", "cnt": 200, "sum": 0},
            {"metric_type": "conversion", "cnt": 40, "sum": 4000},
            {"metric_type": "spend", "cnt": 1, "sum": 500},
            {"metric_type": "lead", "cnt": 50, "sum": 0},
        ], assignments=200),
    }
    report = ex.build_report(
        {"id": "e", "primary_metric": "conversion",
         "exposure_metric": "impression"},
        variants, per_variant)
    rows = {r["variant_key"]: r for r in report["variants"]}
    assert rows["control"]["conversion_rate"] == 0.1
    assert rows["treatment"]["conversion_rate"] == 0.2
    assert rows["treatment"]["lift_vs_control"] == 1.0  # +100%
    assert rows["treatment"]["roas"] == 8.0  # 4000/500
    assert rows["treatment"]["cpa"] == 12.5  # 500/40
    # significant winner (200 exposures each, clear lift)
    rec = report["recommendation"]
    assert rec["advisory_only"] is True and rec["auto_publish"] is False
    assert rec["winner_variant_id"] == "t"


def test_insufficient_sample_flagged_no_winner():
    variants = [
        {"id": "c", "variant_key": "control", "is_control": True,
         "allocation_pct": 50, "name": "C"},
        {"id": "t", "variant_key": "treat", "is_control": False,
         "allocation_pct": 50, "name": "T"},
    ]
    per_variant = {
        "c": ex.aggregate_variant([
            {"metric_type": "impression", "cnt": 10, "sum": 0},
            {"metric_type": "conversion", "cnt": 1, "sum": 0}], 10),
        "t": ex.aggregate_variant([
            {"metric_type": "impression", "cnt": 10, "sum": 0},
            {"metric_type": "conversion", "cnt": 3, "sum": 0}], 10),
    }
    report = ex.build_report(
        {"id": "e", "primary_metric": "conversion",
         "exposure_metric": "impression"}, variants, per_variant)
    t = next(r for r in report["variants"] if r["variant_key"] == "treat")
    assert t["significance"]["insufficient_sample"] is True
    assert report["recommendation"]["winner_variant_id"] is None
    assert report["recommendation"]["reason"] == "insufficient_sample"


def test_safe_ratio_zero_denominator():
    assert ex.safe_ratio(5, 0) is None
    assert ex.safe_ratio(0, 10) == 0.0


def test_two_proportion_z_symmetry():
    r = ex.two_proportion_z(50, 500, 100, 500)
    assert r["insufficient_sample"] is False
    assert r["significant"] is True
    assert r["z"] is not None and r["p_value"] is not None
