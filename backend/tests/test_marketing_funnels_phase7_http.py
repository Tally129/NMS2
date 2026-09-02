"""HTTP contract tests for Marketing OS Phase 7.

Runs against the isolated local backend and disposable PostgreSQL only.
"""

import os
import uuid

import requests


BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {
    "email": "admin@natmedsol.local",
    "password": "Admin!2345",
}


_ADMIN_HEADERS = None


def _login():
    global _ADMIN_HEADERS

    if _ADMIN_HEADERS is not None:
        return _ADMIN_HEADERS

    r = requests.post(
        f"{API}/auth/login",
        json=ADMIN,
        timeout=15,
    )
    assert r.status_code == 200, r.text

    _ADMIN_HEADERS = {
        "Authorization": f"Bearer {r.json()['access_token']}"
    }
    return _ADMIN_HEADERS


def test_phase7_full_funnel_flow():
    headers = _login()
    suffix = uuid.uuid4().hex[:10]
    service_interest = f"wellness_{suffix}"

    offer = requests.post(
        f"{API}/marketing-os/offers",
        headers=headers,
        json={
            "name": f"TEST Wellness Offer {suffix}",
            "slug": f"test-wellness-offer-{suffix}",
            "status": "active",
            "service_interest": service_interest,
            "min_qualification_score": 80,
            "eligible_locations": ["Roswell"],
            "match_config": {},
        },
        timeout=15,
    )
    assert offer.status_code == 201, offer.text
    offer_id = offer.json()["id"]

    form = requests.post(
        f"{API}/marketing-os/qualification-forms",
        headers=headers,
        json={
            "name": f"TEST Qualification {suffix}",
            "slug": f"test-qualification-{suffix}",
            "status": "active",
            "schema": {
                "fields": [
                    "service_interest",
                    "preferred_location",
                    "appointment_readiness",
                    "contact_consent",
                ]
            },
            "scoring_rules": [
                {
                    "field": "appointment_readiness",
                    "operator": "equals",
                    "value": "ready_now",
                    "points": 40,
                },
                {
                    "field": "service_interest",
                    "operator": "equals",
                    "value": service_interest,
                    "points": 30,
                },
                {
                    "field": "preferred_location",
                    "operator": "equals",
                    "value": "Roswell",
                    "points": 20,
                },
                {
                    "field": "contact_consent",
                    "operator": "truthy",
                    "points": 10,
                },
            ],
            "qualification_config": {
                "qualify_at": 70,
                "review_at": 40,
            },
        },
        timeout=15,
    )
    assert form.status_code == 201, form.text
    form_id = form.json()["id"]

    funnel = requests.post(
        f"{API}/marketing-os/funnels",
        headers=headers,
        json={
            "name": f"TEST Wellness Funnel {suffix}",
            "slug": f"test-wellness-funnel-{suffix}",
            "status": "active",
            "landing_page": "/wellness",
            "qualification_form_id": form_id,
            "default_offer_id": offer_id,
            "config": {},
        },
        timeout=15,
    )
    assert funnel.status_code == 201, funnel.text
    funnel_id = funnel.json()["id"]

    step = requests.post(
        f"{API}/marketing-os/funnels/{funnel_id}/steps",
        headers=headers,
        json={
            "step_key": "qualify",
            "step_type": "qualification",
            "position": 1,
            "title": "Qualification",
            "config": {},
        },
        timeout=15,
    )
    assert step.status_code == 201, step.text

    subject = f"phase7_subject_{suffix}"

    lead = requests.post(
        f"{API}/marketing-os/leads",
        headers=headers,
        json={
            "marketing_subject_id": subject,
            "source": "google",
            "medium": "cpc",
            "campaign_name": "phase7-test",
            "service_interest": service_interest,
        },
        timeout=15,
    )
    assert lead.status_code == 201, lead.text
    lead_id = lead.json()["id"]

    qualification = requests.post(
        f"{API}/marketing-os/funnels/{funnel_id}/qualify",
        headers=headers,
        json={
            "marketing_subject_id": subject,
            "answers": {
                "service_interest": service_interest,
                "preferred_location": "Roswell",
                "appointment_readiness": "ready_now",
                "contact_consent": True,
            },
        },
        timeout=15,
    )

    assert qualification.status_code == 201, qualification.text

    body = qualification.json()

    assert body["qualification_score"] == 100
    assert body["qualification_status"] == "qualified"
    assert body["matched_offer_id"] == offer_id
    assert body["lead_updated"] is True
    assert body["lead_id"] == lead_id

    fetched = requests.get(
        f"{API}/marketing-os/leads/{lead_id}",
        headers=headers,
        timeout=15,
    )

    assert fetched.status_code == 200, fetched.text

    detail = fetched.json()

    # Phase 6 lead-detail contract is {"lead": {...}, "tasks": [...]}.
    assert "lead" in detail
    assert isinstance(detail.get("tasks"), list)

    updated = detail["lead"]

    assert updated["qualification_score"] == 100
    assert updated["qualification_status"] == "qualified"
    assert updated["priority"] == "high"
    assert updated["offer_id"] == offer_id
    assert updated["preferred_location"] == "Roswell"
    assert updated["appointment_readiness"] == "ready_now"
    assert updated["landing_page"] == "/wellness"

    funnels = requests.get(
        f"{API}/marketing-os/funnels",
        headers=headers,
        timeout=15,
    )

    assert funnels.status_code == 200, funnels.text

    selected = next(
        item for item in funnels.json()
        if item["id"] == funnel_id
    )

    assert len(selected["steps"]) == 1
    assert selected["steps"][0]["step_key"] == "qualify"


def test_phase7_rejects_phi_answers():
    headers = _login()
    suffix = uuid.uuid4().hex[:10]

    form = requests.post(
        f"{API}/marketing-os/qualification-forms",
        headers=headers,
        json={
            "name": f"TEST PHI Guard {suffix}",
            "slug": f"test-phi-guard-{suffix}",
            "status": "active",
            "schema": {},
            "scoring_rules": [],
            "qualification_config": {},
        },
        timeout=15,
    )
    assert form.status_code == 201, form.text

    funnel = requests.post(
        f"{API}/marketing-os/funnels",
        headers=headers,
        json={
            "name": f"TEST PHI Funnel {suffix}",
            "slug": f"test-phi-funnel-{suffix}",
            "status": "active",
            "qualification_form_id": form.json()["id"],
            "config": {},
        },
        timeout=15,
    )
    assert funnel.status_code == 201, funnel.text

    r = requests.post(
        f"{API}/marketing-os/funnels/{funnel.json()['id']}/qualify",
        headers=headers,
        json={
            "marketing_subject_id": f"subject_{suffix}",
            "answers": {
                "email": "patient@example.com",
            },
        },
        timeout=15,
    )

    assert r.status_code == 422, r.text


def test_phase7_requires_marketing_role():
    suffix = uuid.uuid4().hex[:10]

    r = requests.post(
        f"{API}/marketing-os/offers",
        json={
            "name": f"Unauthorized {suffix}",
            "slug": f"unauthorized-{suffix}",
        },
        timeout=15,
    )

    assert r.status_code in (401, 403)


def test_phase7_rejects_unsafe_form_configuration():
    headers = _login()
    suffix = uuid.uuid4().hex[:10]

    unsafe_schema = requests.post(
        f"{API}/marketing-os/qualification-forms",
        headers=headers,
        json={
            "name": f"TEST Unsafe Schema {suffix}",
            "slug": f"test-unsafe-schema-{suffix}",
            "status": "draft",
            "schema": {
                "fields": [
                    "service_interest",
                    "patient_id",
                ]
            },
            "scoring_rules": [],
            "qualification_config": {},
        },
        timeout=15,
    )

    assert unsafe_schema.status_code == 422, unsafe_schema.text

    unsafe_rule = requests.post(
        f"{API}/marketing-os/qualification-forms",
        headers=headers,
        json={
            "name": f"TEST Unsafe Rule {suffix}",
            "slug": f"test-unsafe-rule-{suffix}",
            "status": "draft",
            "schema": {
                "fields": [
                    "service_interest",
                ]
            },
            "scoring_rules": [
                {
                    "field": "diagnosis",
                    "operator": "equals",
                    "value": "anything",
                    "points": 10,
                }
            ],
            "qualification_config": {},
        },
        timeout=15,
    )

    assert unsafe_rule.status_code == 422, unsafe_rule.text


def test_phase7_rejects_bad_scoring_operator_and_shape():
    headers = _login()
    suffix = uuid.uuid4().hex[:10]

    unsupported_operator = requests.post(
        f"{API}/marketing-os/qualification-forms",
        headers=headers,
        json={
            "name": f"TEST Bad Operator {suffix}",
            "slug": f"test-bad-operator-{suffix}",
            "status": "draft",
            "schema": {
                "fields": [
                    "urgency",
                ]
            },
            "scoring_rules": [
                {
                    "field": "urgency",
                    "operator": "contains",
                    "value": "high",
                    "points": 10,
                }
            ],
            "qualification_config": {},
        },
        timeout=15,
    )

    assert unsupported_operator.status_code == 422, unsupported_operator.text

    bad_in_shape = requests.post(
        f"{API}/marketing-os/qualification-forms",
        headers=headers,
        json={
            "name": f"TEST Bad In Shape {suffix}",
            "slug": f"test-bad-in-shape-{suffix}",
            "status": "draft",
            "schema": {
                "fields": [
                    "urgency",
                ]
            },
            "scoring_rules": [
                {
                    "field": "urgency",
                    "operator": "in",
                    "value": ["high", "urgent"],
                    "points": 10,
                }
            ],
            "qualification_config": {},
        },
        timeout=15,
    )

    assert bad_in_shape.status_code == 422, bad_in_shape.text


def test_phase7_rejects_invalid_threshold_configuration():
    headers = _login()
    suffix = uuid.uuid4().hex[:10]

    invalid = requests.post(
        f"{API}/marketing-os/qualification-forms",
        headers=headers,
        json={
            "name": f"TEST Bad Thresholds {suffix}",
            "slug": f"test-bad-thresholds-{suffix}",
            "status": "draft",
            "schema": {},
            "scoring_rules": [],
            "qualification_config": {
                "qualify_at": 40,
                "review_at": 70,
            },
        },
        timeout=15,
    )

    assert invalid.status_code == 422, invalid.text


def test_phase7_form_patch_rejects_unsafe_configuration():
    headers = _login()
    suffix = uuid.uuid4().hex[:10]

    created = requests.post(
        f"{API}/marketing-os/qualification-forms",
        headers=headers,
        json={
            "name": f"TEST Patch Guard {suffix}",
            "slug": f"test-patch-guard-{suffix}",
            "status": "draft",
            "schema": {
                "fields": [
                    "service_interest",
                ]
            },
            "scoring_rules": [
                {
                    "field": "service_interest",
                    "operator": "equals",
                    "value": f"service_{suffix}",
                    "points": 20,
                }
            ],
            "qualification_config": {
                "qualify_at": 70,
                "review_at": 40,
            },
        },
        timeout=15,
    )

    assert created.status_code == 201, created.text

    form_id = created.json()["id"]

    bad_schema = requests.patch(
        f"{API}/marketing-os/qualification-forms/{form_id}",
        headers=headers,
        json={
            "schema": {
                "fields": [
                    "diagnosis",
                ]
            }
        },
        timeout=15,
    )

    assert bad_schema.status_code == 422, bad_schema.text

    bad_thresholds = requests.patch(
        f"{API}/marketing-os/qualification-forms/{form_id}",
        headers=headers,
        json={
            "qualification_config": {
                "qualify_at": 20,
                "review_at": 80,
            }
        },
        timeout=15,
    )

    assert bad_thresholds.status_code == 422, bad_thresholds.text


def test_phase7_offer_match_config_fails_closed_create_and_patch():
    headers = _login()
    suffix = uuid.uuid4().hex[:10]

    rejected_create = requests.post(
        f"{API}/marketing-os/offers",
        headers=headers,
        json={
            "name": f"TEST Unsafe Match Config {suffix}",
            "slug": f"test-unsafe-match-config-{suffix}",
            "status": "draft",
            "match_config": {
                "diagnosis": "anything"
            },
        },
        timeout=15,
    )

    assert rejected_create.status_code == 422, rejected_create.text

    created = requests.post(
        f"{API}/marketing-os/offers",
        headers=headers,
        json={
            "name": f"TEST Match Guard {suffix}",
            "slug": f"test-match-guard-{suffix}",
            "status": "draft",
            "match_config": {},
        },
        timeout=15,
    )

    assert created.status_code == 201, created.text

    rejected_patch = requests.patch(
        f"{API}/marketing-os/offers/{created.json()['id']}",
        headers=headers,
        json={
            "match_config": {
                "patient_id": "anything"
            }
        },
        timeout=15,
    )

    assert rejected_patch.status_code == 422, rejected_patch.text


def test_phase7_form_patch_validates_merged_configuration():
    headers = _login()
    suffix = uuid.uuid4().hex[:10]

    created = requests.post(
        f"{API}/marketing-os/qualification-forms",
        headers=headers,
        json={
            "name": f"TEST Merged Patch Guard {suffix}",
            "slug": f"test-merged-patch-guard-{suffix}",
            "status": "draft",
            "schema": {
                "fields": [
                    "service_interest",
                    "urgency",
                ]
            },
            "scoring_rules": [
                {
                    "field": "urgency",
                    "operator": "equals",
                    "value": "high",
                    "points": 20,
                }
            ],
            "qualification_config": {
                "qualify_at": 70,
                "review_at": 40,
            },
        },
        timeout=15,
    )

    assert created.status_code == 201, created.text
    form_id = created.json()["id"]

    # Changing only the schema must still be checked against
    # the scoring rules already stored on the form.
    schema_only = requests.patch(
        f"{API}/marketing-os/qualification-forms/{form_id}",
        headers=headers,
        json={
            "schema": {
                "fields": [
                    "service_interest",
                ]
            }
        },
        timeout=15,
    )

    assert schema_only.status_code == 422, schema_only.text

    # Changing only scoring rules must still be checked against
    # the schema already stored on the form.
    rules_only = requests.patch(
        f"{API}/marketing-os/qualification-forms/{form_id}",
        headers=headers,
        json={
            "scoring_rules": [
                {
                    "field": "timeline",
                    "operator": "equals",
                    "value": "now",
                    "points": 20,
                }
            ]
        },
        timeout=15,
    )

    assert rules_only.status_code == 422, rules_only.text

    # A consistent paired update remains valid.
    valid_pair = requests.patch(
        f"{API}/marketing-os/qualification-forms/{form_id}",
        headers=headers,
        json={
            "schema": {
                "fields": [
                    "service_interest",
                    "timeline",
                ]
            },
            "scoring_rules": [
                {
                    "field": "timeline",
                    "operator": "equals",
                    "value": "now",
                    "points": 20,
                }
            ],
        },
        timeout=15,
    )

    assert valid_pair.status_code == 200, valid_pair.text
