"""HTTP tests for Marketing OS Phase 11 content + social intelligence."""

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


def _topic(h, sfx, **over):
    body = {"topic": f"IV therapy {sfx}", "slug": f"iv-therapy-{sfx}",
            "target_keyword": "iv therapy", "search_intent": "commercial",
            "funnel_stage": "decision",
            "metrics": {"impressions": 4000, "avg_position": 25, "ctr": 0.01,
                        "has_offer": True, "attributed_leads": 3}}
    body.update(over)
    r = requests.post(f"{API}/marketing-os/content/topics", headers=h,
                      json=body, timeout=15)
    assert r.status_code == 201, r.text
    return r.json()


def test_phase11_topic_scoring_and_safety():
    h = _login()
    sfx = uuid.uuid4().hex[:10]
    t = _topic(h, sfx)
    assert 0 <= t["priority"] <= 100
    # a low-value topic should score lower
    low = _topic(h, uuid.uuid4().hex[:10],
                 metrics={"impressions": 5, "avg_position": 2, "ctr": 0.6},
                 funnel_stage="awareness")
    assert t["priority"] > low["priority"]

    lst = requests.get(f"{API}/marketing-os/content/topics", headers=h,
                       timeout=15).json()
    assert lst["safety"]["automatic_publishing"] is False
    assert lst["safety"]["phi_used"] is False
    assert lst["safety"]["ai_llm_used"] is False


def test_phase11_brief_draft_flow():
    h = _login()
    sfx = uuid.uuid4().hex[:10]
    t = _topic(h, sfx)
    # blog brief
    br = requests.post(f"{API}/marketing-os/content/briefs", headers=h, json={
        "topic_id": t["id"], "channel": "blog", "content_type": "article",
        "title": "What to know about IV therapy", "funnel_stage": "decision",
        "cta": "Book a consultation"}, timeout=15)
    assert br.status_code == 201, br.text
    bid = br.json()["id"]
    # deterministic draft scaffold
    dr = requests.post(f"{API}/marketing-os/content/briefs/{bid}/drafts",
                       headers=h, json={}, timeout=15)
    assert dr.status_code == 201, dr.text
    draft = dr.json()
    assert draft["generator"] == "template"
    assert draft["status"] == "draft"
    assert draft["body"]  # blog draft has body

    # tiktok brief produces hook/script scaffold
    br2 = requests.post(f"{API}/marketing-os/content/briefs", headers=h, json={
        "channel": "tiktok", "content_type": "short_video",
        "title": "IV therapy in 30 seconds"}, timeout=15)
    assert br2.status_code == 201, br2.text
    dr2 = requests.post(
        f"{API}/marketing-os/content/briefs/{br2.json()['id']}/drafts",
        headers=h, json={}, timeout=15).json()
    assert dr2["hook"] and dr2["script"]

    drafts = requests.get(f"{API}/marketing-os/content/briefs/{bid}/drafts",
                          headers=h, timeout=15).json()
    assert len(drafts["drafts"]) >= 1


def test_phase11_social_plan_and_calendar():
    h = _login()
    sfx = uuid.uuid4().hex[:10]
    sp = requests.post(f"{API}/marketing-os/content/social-plans", headers=h,
                       json={"channel": "instagram",
                             "name": f"IG plan {sfx}",
                             "cadence": "weekly"}, timeout=15)
    assert sp.status_code == 201, sp.text

    br = requests.post(f"{API}/marketing-os/content/briefs", headers=h, json={
        "channel": "instagram", "content_type": "reel",
        "title": f"Reel {sfx}"}, timeout=15).json()
    ci = requests.post(f"{API}/marketing-os/content/calendar", headers=h,
                       json={"brief_id": br["id"], "channel": "instagram",
                             "title": f"Reel {sfx}",
                             "planned_publish_at": "2026-06-15",
                             "social_plan_id": sp.json()["id"]}, timeout=15)
    assert ci.status_code == 201, ci.text
    # unique brief on calendar
    dup = requests.post(f"{API}/marketing-os/content/calendar", headers=h,
                        json={"brief_id": br["id"], "channel": "instagram",
                              "title": "dup"}, timeout=15)
    assert dup.status_code == 409

    cal = requests.get(f"{API}/marketing-os/content/calendar", headers=h,
                       timeout=15).json()
    assert isinstance(cal["items"], list)


def test_phase11_validation_4xx():
    h = _login()
    sfx = uuid.uuid4().hex[:8]
    # bad slug
    assert requests.post(f"{API}/marketing-os/content/topics", headers=h,
        json={"topic": "x", "slug": "Bad Slug"}, timeout=15
    ).status_code == 422
    # PHI in metrics
    assert requests.post(f"{API}/marketing-os/content/topics", headers=h,
        json={"topic": "x", "slug": f"ok-{sfx}",
              "metrics": {"email": "a@b.com"}}, timeout=15
    ).status_code == 422
    # duplicate slug
    _topic(h, sfx)
    assert requests.post(f"{API}/marketing-os/content/topics", headers=h,
        json={"topic": "y", "slug": f"iv-therapy-{sfx}"}, timeout=15
    ).status_code == 409
    # bad channel on brief
    assert requests.post(f"{API}/marketing-os/content/briefs", headers=h,
        json={"channel": "myspace", "content_type": "x", "title": "t"},
        timeout=15).status_code == 422
    # unknown topic_id
    assert requests.post(f"{API}/marketing-os/content/briefs", headers=h,
        json={"topic_id": "nope", "channel": "blog", "content_type": "x",
              "title": "t"}, timeout=15).status_code == 422


def test_phase11_overview_and_rbac():
    h = _login()
    r = requests.get(f"{API}/marketing-os/content/overview", headers=h,
                     timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert set(j["counts"]) == {"topics", "briefs", "drafts", "social_plans",
                                "calendar_items"}
    assert j["safety"]["human_approval_required"] is True
    # unauthenticated -> 401/403
    assert requests.get(f"{API}/marketing-os/content/overview",
                        timeout=15).status_code in (401, 403)
