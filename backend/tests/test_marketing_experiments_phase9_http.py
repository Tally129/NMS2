"""HTTP tests for Marketing OS Phase 9 experimentation. Isolated backend only."""

import os
import uuid

import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = {"email": "admin@natmedsol.local", "password": "Admin!2345"}
_H = None


def _login():
    global _H
    if _H is None:
        r = requests.post(f"{API}/auth/login", json=ADMIN, timeout=15)
        assert r.status_code == 200, r.text
        _H = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return _H


def _make_active_experiment(h, suffix, c_alloc=50, t_alloc=50):
    r = requests.post(f"{API}/marketing-os/experiments", headers=h, json={
        "name": f"EXP {suffix}", "slug": f"exp-{suffix}",
        "experiment_type": "landing_page", "primary_metric": "conversion",
        "exposure_metric": "impression"}, timeout=15)
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    for key, ctrl, alloc in [("control", True, c_alloc),
                             ("treatment", False, t_alloc)]:
        rv = requests.post(
            f"{API}/marketing-os/experiments/{eid}/variants", headers=h,
            json={"variant_key": key, "name": key.title(),
                  "is_control": ctrl, "allocation_pct": alloc}, timeout=15)
        assert rv.status_code == 201, rv.text
    rt = requests.post(f"{API}/marketing-os/experiments/{eid}/transition",
                       headers=h, json={"action": "activate"}, timeout=15)
    assert rt.status_code == 200, rt.text
    return eid


def test_phase9_lifecycle_and_activation_guard():
    h = _login()
    suffix = uuid.uuid4().hex[:10]
    r = requests.post(f"{API}/marketing-os/experiments", headers=h, json={
        "name": "guard", "slug": f"guard-{suffix}",
        "experiment_type": "offer"}, timeout=15)
    eid = r.json()["id"]
    # cannot activate with <2 variants / no control / bad sum
    r = requests.post(f"{API}/marketing-os/experiments/{eid}/transition",
                      headers=h, json={"action": "activate"}, timeout=15)
    assert r.status_code == 409, r.text
    # invalid transition draft->complete
    r = requests.post(f"{API}/marketing-os/experiments/{eid}/transition",
                      headers=h, json={"action": "complete"}, timeout=15)
    assert r.status_code == 409, r.text


def test_phase9_deterministic_assignment_idempotent():
    h = _login()
    eid = _make_active_experiment(h, uuid.uuid4().hex[:10])
    subj = f"subj_{uuid.uuid4().hex[:8]}"
    a1 = requests.post(f"{API}/marketing-os/experiments/{eid}/assign",
                       headers=h, json={"marketing_subject_id": subj},
                       timeout=15)
    assert a1.status_code == 200, a1.text
    v1 = a1.json()["variant_id"]
    assert a1.json()["reused"] is False
    # repeat → same variant, reused
    a2 = requests.post(f"{API}/marketing-os/experiments/{eid}/assign",
                       headers=h, json={"marketing_subject_id": subj},
                       timeout=15)
    assert a2.status_code == 200
    assert a2.json()["variant_id"] == v1
    assert a2.json()["reused"] is True


def test_phase9_assign_requires_active():
    h = _login()
    suffix = uuid.uuid4().hex[:10]
    r = requests.post(f"{API}/marketing-os/experiments", headers=h, json={
        "name": "draftx", "slug": f"draftx-{suffix}",
        "experiment_type": "offer"}, timeout=15)
    eid = r.json()["id"]
    r = requests.post(f"{API}/marketing-os/experiments/{eid}/assign",
                      headers=h, json={"marketing_subject_id": "s1"},
                      timeout=15)
    assert r.status_code == 409, r.text


def test_phase9_outcomes_and_report():
    h = _login()
    eid = _make_active_experiment(h, uuid.uuid4().hex[:10])
    # assign 4 subjects, record impression+conversion outcomes
    subs = [f"s_{uuid.uuid4().hex[:8]}" for _ in range(4)]
    for s in subs:
        requests.post(f"{API}/marketing-os/experiments/{eid}/assign",
                      headers=h, json={"marketing_subject_id": s}, timeout=15)
        for metric in ["impression", "conversion"]:
            body = {"metric_type": metric, "marketing_subject_id": s}
            if metric == "conversion":
                body.update({"value": 100.0, "currency": "USD"})
            body["idempotency_key"] = f"{eid}:{s}:{metric}"
            rr = requests.post(
                f"{API}/marketing-os/experiments/{eid}/outcomes",
                headers=h, json=body, timeout=15)
            assert rr.status_code in (201, 200), rr.text
    # duplicate outcome ignored (idempotency)
    dup = requests.post(f"{API}/marketing-os/experiments/{eid}/outcomes",
                        headers=h, json={"metric_type": "impression",
                        "marketing_subject_id": subs[0],
                        "idempotency_key": f"{eid}:{subs[0]}:impression"},
                        timeout=15)
    assert dup.json().get("status") == "duplicate_ignored"

    rep = requests.get(f"{API}/marketing-os/experiments/{eid}/report",
                       headers=h, timeout=15)
    assert rep.status_code == 200, rep.text
    j = rep.json()
    assert j["safety"]["autonomous_publishing"] is False
    assert j["safety"]["automatic_winner_selection"] is False
    total_conv = sum(r["conversions"] for r in j["variants"])
    assert total_conv == 4
    # recommendation present and advisory-only (small sample → no winner)
    assert j["recommendation"]["advisory_only"] is True
    assert j["recommendation"]["auto_publish"] is False


def test_phase9_malformed_returns_4xx():
    h = _login()
    suffix = uuid.uuid4().hex[:8]
    # bad slug
    assert requests.post(f"{API}/marketing-os/experiments", headers=h, json={
        "name": "x", "slug": "Bad Slug", "experiment_type": "offer"},
        timeout=15).status_code == 422
    # unknown type
    assert requests.post(f"{API}/marketing-os/experiments", headers=h, json={
        "name": "x", "slug": f"okk-{suffix}", "experiment_type": "banner"},
        timeout=15).status_code == 422
    # extra forbidden field
    assert requests.post(f"{API}/marketing-os/experiments", headers=h, json={
        "name": "x", "slug": f"ok2-{suffix}", "experiment_type": "offer",
        "surprise": 1}, timeout=15).status_code == 422
    # valid then bad outcome metric
    r = requests.post(f"{API}/marketing-os/experiments", headers=h, json={
        "name": "x", "slug": f"ok3-{suffix}", "experiment_type": "offer"},
        timeout=15)
    eid = r.json()["id"]
    bad = requests.post(f"{API}/marketing-os/experiments/{eid}/outcomes",
                        headers=h, json={"metric_type": "teleport",
                        "variant_id": "nope"}, timeout=15)
    assert bad.status_code == 422, bad.text
