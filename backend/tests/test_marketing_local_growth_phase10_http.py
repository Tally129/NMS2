"""HTTP tests for Marketing OS Phase 10 reputation + local growth."""

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


def _location(h, suffix, hours=None):
    r = requests.post(f"{API}/marketing-os/local/locations", headers=h, json={
        "name": f"Clinic {suffix}", "slug": f"clinic-{suffix}",
        "city": "Roswell", "state": "GA", "phone": "770-555-0100",
        "website_url": "https://example.com", "hours": hours or {}},
        timeout=15)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _source(h, loc, provider):
    r = requests.post(f"{API}/marketing-os/local/locations/{loc}/sources",
                      headers=h, json={"provider": provider}, timeout=15)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_phase10_location_source_and_snapshots():
    h = _login()
    sfx = uuid.uuid4().hex[:10]
    loc = _location(h, sfx)  # no hours -> should produce missing_hours opp
    src = _source(h, loc, "google")

    rr = requests.post(
        f"{API}/marketing-os/local/locations/{loc}/reputation-snapshots",
        headers=h, json={"source_id": src, "captured_date": "2026-02-01",
        "rating": 4.6, "review_count": 120, "reviews_last_30d": 1,
        "response_rate": 0.3}, timeout=15)
    assert rr.status_code == 201, rr.text

    lr = requests.post(
        f"{API}/marketing-os/local/locations/{loc}/listing-snapshots",
        headers=h, json={"source_id": src, "captured_date": "2026-02-01",
        "listing_status": "published", "name_matches": True,
        "address_matches": False, "phone_matches": True,
        "fields_present": {"name": True, "address": True}}, timeout=15)
    assert lr.status_code == 201, lr.text

    # health: deterministic scores + opportunities
    hr = requests.get(f"{API}/marketing-os/local/locations/{loc}/health",
                      headers=h, timeout=15)
    assert hr.status_code == 200, hr.text
    j = hr.json()
    assert j["safety"]["read_only_intelligence"] is True
    assert j["safety"]["automatic_listing_edits"] is False
    assert 0 <= j["health_score"] <= 100
    assert j["review_velocity_class"] == "low"
    types = {o["opportunity_type"] for o in j["opportunities"]}
    assert "missing_hours" in types
    assert "low_review_velocity" in types
    assert "weak_response_rate" in types
    assert "nap_inconsistent" in types
    assert "missing_directory" in types  # yelp/bing/apple absent

    # recompute persists opportunities, list returns them
    rc = requests.post(
        f"{API}/marketing-os/local/locations/{loc}/opportunities/recompute",
        headers=h, timeout=15)
    assert rc.status_code == 200 and rc.json()["opportunities_written"] > 0
    # idempotent second recompute
    rc2 = requests.post(
        f"{API}/marketing-os/local/locations/{loc}/opportunities/recompute",
        headers=h, timeout=15)
    assert rc2.status_code == 200
    lst = requests.get(
        f"{API}/marketing-os/local/locations/{loc}/opportunities",
        headers=h, params={"status": "open"}, timeout=15).json()
    assert len(lst["opportunities"]) == rc2.json()["opportunities_written"]


def test_phase10_snapshot_upsert_idempotent():
    h = _login()
    sfx = uuid.uuid4().hex[:10]
    loc = _location(h, sfx)
    src = _source(h, loc, "yelp")
    body = {"source_id": src, "captured_date": "2026-02-02", "rating": 4.0,
            "review_count": 10}
    r1 = requests.post(
        f"{API}/marketing-os/local/locations/{loc}/reputation-snapshots",
        headers=h, json=body, timeout=15)
    body["rating"] = 4.5
    r2 = requests.post(
        f"{API}/marketing-os/local/locations/{loc}/reputation-snapshots",
        headers=h, json=body, timeout=15)
    assert r1.status_code == 201 and r2.status_code == 201
    assert r2.json()["rating"] == 4.5  # upserted same date


def test_phase10_validation_4xx():
    h = _login()
    sfx = uuid.uuid4().hex[:8]
    # bad slug
    assert requests.post(f"{API}/marketing-os/local/locations", headers=h,
        json={"name": "x", "slug": "Bad Slug"}, timeout=15).status_code == 422
    # PHI in config
    assert requests.post(f"{API}/marketing-os/local/locations", headers=h,
        json={"name": "x", "slug": f"ok-{sfx}",
              "config": {"email": "a@b.com"}}, timeout=15).status_code == 422
    loc = _location(h, sfx)
    # bad provider
    assert requests.post(
        f"{API}/marketing-os/local/locations/{loc}/sources", headers=h,
        json={"provider": "myspace"}, timeout=15).status_code == 422
    # duplicate provider
    _source(h, loc, "google")
    assert requests.post(
        f"{API}/marketing-os/local/locations/{loc}/sources", headers=h,
        json={"provider": "google"}, timeout=15).status_code == 409
    # snapshot for unknown source
    assert requests.post(
        f"{API}/marketing-os/local/locations/{loc}/reputation-snapshots",
        headers=h, json={"source_id": "nope", "captured_date": "2026-02-01"},
        timeout=15).status_code == 422


def test_phase10_reputation_overview():
    h = _login()
    r = requests.get(f"{API}/marketing-os/local/reputation-overview",
                     headers=h, timeout=20)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["safety"]["phi_used"] is False
    assert j["safety"]["sms_enabled"] is False
    assert isinstance(j["summaries"], list)
