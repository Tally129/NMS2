"""HTTP contract tests for Marketing OS Phase 8A (nurture engine).

Runs against the isolated local backend and disposable PostgreSQL only.
No external outreach is ever performed: email actions must remain held.
"""

import os
import uuid

import requests


BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@natmedsol.local", "password": "Admin!2345"}

_HEADERS = None


def _login():
    global _HEADERS
    if _HEADERS is not None:
        return _HEADERS
    r = requests.post(f"{API}/auth/login", json=ADMIN, timeout=15)
    assert r.status_code == 200, r.text
    _HEADERS = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return _HEADERS


def _create_lead(headers, suffix, **overrides):
    body = {
        "marketing_subject_id": f"subj_{suffix}",
        "source": "google",
        "medium": "cpc",
        "service_interest": "wellness",
        "opportunity_score": 60,
    }
    body.update(overrides)
    r = requests.post(
        f"{API}/marketing-os/leads", headers=headers, json=body, timeout=15
    )
    assert r.status_code == 201, r.text
    return r.json()


def _active_sequence_with_steps(headers, suffix):
    seq = requests.post(
        f"{API}/marketing-os/nurture/sequences",
        headers=headers,
        json={
            "name": f"TEST Nurture {suffix}",
            "slug": f"test-nurture-{suffix}",
            "status": "draft",
            "trigger_type": "manual",
        },
        timeout=15,
    )
    assert seq.status_code == 201, seq.text
    seq_id = seq.json()["id"]

    activate = requests.patch(
        f"{API}/marketing-os/nurture/sequences/{seq_id}",
        headers=headers,
        json={"status": "active"},
        timeout=15,
    )
    assert activate.status_code == 200, activate.text

    steps = [
        {
            "step_key": "task_recover",
            "action_type": "create_task",
            "position": 0,
            "delay_minutes": 0,
            "title": "Recover no-show",
            "config": {"task_type": "recover_no_show", "due_in_minutes": 60},
        },
        {
            "step_key": "email_nudge",
            "action_type": "send_email",
            "position": 1,
            "delay_minutes": 0,
            "subject": "We saved your spot",
            "body_html": "<p>Ready to book your visit?</p>",
        },
        {
            "step_key": "task_followup",
            "action_type": "create_task",
            "position": 2,
            "delay_minutes": 0,
            "config": {"task_type": "follow_up_later"},
        },
    ]
    for step in steps:
        r = requests.post(
            f"{API}/marketing-os/nurture/sequences/{seq_id}/steps",
            headers=headers,
            json=step,
            timeout=15,
        )
        assert r.status_code == 201, r.text
    return seq_id


def test_phase8a_full_flow_email_held_and_task_executed():
    headers = _login()
    suffix = uuid.uuid4().hex[:10]

    seq_id = _active_sequence_with_steps(headers, suffix)
    lead = _create_lead(headers, suffix)
    lead_id = lead["id"]

    # Enroll (manual).
    enroll = requests.post(
        f"{API}/marketing-os/nurture/enroll",
        headers=headers,
        json={"sequence_id": seq_id, "lead_id": lead_id},
        timeout=15,
    )
    assert enroll.status_code == 201, enroll.text
    enrollment_id = enroll.json()["id"]
    assert enroll.json()["status"] == "active"
    assert enroll.json()["next_run_at"] is not None

    # Duplicate active enrollment rejected.
    dup = requests.post(
        f"{API}/marketing-os/nurture/enroll",
        headers=headers,
        json={"sequence_id": seq_id, "lead_id": lead_id},
        timeout=15,
    )
    assert dup.status_code == 409, dup.text

    # Scheduler tick materializes due steps (2 approval actions; wait? none).
    tick = requests.post(
        f"{API}/marketing-os/nurture/scheduler/tick",
        headers=headers,
        json={"limit": 50},
        timeout=30,
    )
    assert tick.status_code == 200, tick.text
    body = tick.json()
    assert body["safety"]["automatic_outreach"] is False
    assert body["actions_created"] >= 3

    # Idempotent: second tick creates no new actions (enrollment completed).
    tick2 = requests.post(
        f"{API}/marketing-os/nurture/scheduler/tick",
        headers=headers,
        json={"limit": 50},
        timeout=30,
    )
    assert tick2.status_code == 200, tick2.text
    assert tick2.json()["actions_created"] == 0

    actions = requests.get(
        f"{API}/marketing-os/nurture/actions",
        headers=headers,
        params={"enrollment_id": enrollment_id},
        timeout=15,
    ).json()["actions"]
    assert len(actions) == 3
    assert all(a["status"] == "pending_approval" for a in actions)

    by_type = {}
    for a in actions:
        by_type.setdefault(a["action_type"], []).append(a)

    # Approve create_task -> executes internally (creates a Lead CRM task).
    task_action = next(
        a for a in by_type["create_task"]
        if a["preview"].get("task_type") == "recover_no_show"
    )
    approve_task = requests.post(
        f"{API}/marketing-os/nurture/actions/{task_action['id']}/approve",
        headers=headers,
        timeout=15,
    )
    assert approve_task.status_code == 200, approve_task.text
    approved = approve_task.json()
    assert approved["status"] == "approved"
    assert approved["delivery_status"] == "task_created"
    assert approved["lead_task_id"]

    # The Lead CRM task exists (reuses marketing_lead_tasks).
    tasks = requests.get(
        f"{API}/marketing-os/leads/tasks",
        headers=headers,
        params={"lead_id": lead_id},
        timeout=15,
    ).json()["tasks"]
    assert any(t["task_type"] == "recover_no_show" for t in tasks)

    # Approve email -> ALWAYS held; no send performed.
    email_action = by_type["send_email"][0]
    approve_email = requests.post(
        f"{API}/marketing-os/nurture/actions/{email_action['id']}/approve",
        headers=headers,
        timeout=15,
    )
    assert approve_email.status_code == 200, approve_email.text
    held = approve_email.json()
    assert held["status"] == "held"
    assert held["delivery_status"] == "outreach_disabled"
    assert held["hold_reason"] == "outreach_disabled"

    # Skip the remaining create_task.
    followup = next(
        a for a in by_type["create_task"]
        if a["preview"].get("task_type") == "follow_up_later"
    )
    skip = requests.post(
        f"{API}/marketing-os/nurture/actions/{followup['id']}/skip",
        headers=headers,
        json={"reason": "not needed"},
        timeout=15,
    )
    assert skip.status_code == 200, skip.text
    assert skip.json()["status"] == "skipped"

    # Approving an already-resolved action is rejected.
    reapprove = requests.post(
        f"{API}/marketing-os/nurture/actions/{email_action['id']}/approve",
        headers=headers,
        timeout=15,
    )
    assert reapprove.status_code == 409, reapprove.text

    # Overview reflects safety + counts.
    overview = requests.get(
        f"{API}/marketing-os/nurture/overview", headers=headers, timeout=15
    ).json()
    assert overview["safety"]["automatic_outreach"] is False
    assert overview["safety"]["sms_enabled"] is False
    assert overview["safety"]["human_approval_required"] is True


def test_phase8a_suppression_stops_nurture_for_booked_lead():
    headers = _login()
    suffix = uuid.uuid4().hex[:10]

    seq_id = _active_sequence_with_steps(headers, suffix)
    lead = _create_lead(headers, suffix)
    lead_id = lead["id"]

    enroll = requests.post(
        f"{API}/marketing-os/nurture/enroll",
        headers=headers,
        json={"sequence_id": seq_id, "lead_id": lead_id},
        timeout=15,
    )
    assert enroll.status_code == 201, enroll.text
    enrollment_id = enroll.json()["id"]

    # Move the lead into a terminal/suppressed status (new -> lost allowed).
    status = requests.patch(
        f"{API}/marketing-os/leads/{lead_id}/status",
        headers=headers,
        json={"lead_status": "lost"},
        timeout=15,
    )
    assert status.status_code == 200, status.text

    tick = requests.post(
        f"{API}/marketing-os/nurture/scheduler/tick",
        headers=headers,
        json={"limit": 50},
        timeout=30,
    )
    assert tick.status_code == 200, tick.text
    assert tick.json()["enrollments_stopped"] >= 1

    enrollment = requests.get(
        f"{API}/marketing-os/nurture/enrollments",
        headers=headers,
        params={"lead_id": lead_id},
        timeout=15,
    ).json()["enrollments"]
    row = next(e for e in enrollment if e["id"] == enrollment_id)
    assert row["status"] == "stopped"
    assert row["stop_reason"].startswith("lead_status:")

    # No approval actions were created for the suppressed lead.
    actions = requests.get(
        f"{API}/marketing-os/nurture/actions",
        headers=headers,
        params={"enrollment_id": enrollment_id},
        timeout=15,
    ).json()["actions"]
    assert actions == []


def test_phase8a_enroll_rejected_for_non_nurturable_lead():
    headers = _login()
    suffix = uuid.uuid4().hex[:10]

    seq_id = _active_sequence_with_steps(headers, suffix)
    lead = _create_lead(headers, suffix)
    lead_id = lead["id"]

    requests.patch(
        f"{API}/marketing-os/leads/{lead_id}/status",
        headers=headers,
        json={"lead_status": "lost"},
        timeout=15,
    )

    enroll = requests.post(
        f"{API}/marketing-os/nurture/enroll",
        headers=headers,
        json={"sequence_id": seq_id, "lead_id": lead_id},
        timeout=15,
    )
    assert enroll.status_code == 409, enroll.text


def test_phase8a_malformed_configs_return_4xx_not_500():
    headers = _login()
    suffix = uuid.uuid4().hex[:8]

    # Bad slug.
    r = requests.post(
        f"{API}/marketing-os/nurture/sequences",
        headers=headers,
        json={"name": "x", "slug": "Bad Slug!!"},
        timeout=15,
    )
    assert r.status_code == 422, r.text

    # Unknown trigger type.
    r = requests.post(
        f"{API}/marketing-os/nurture/sequences",
        headers=headers,
        json={"name": "x", "slug": f"ok-{suffix}", "trigger_type": "magic"},
        timeout=15,
    )
    assert r.status_code == 422, r.text

    # Create a valid sequence, then feed malformed steps.
    seq = requests.post(
        f"{API}/marketing-os/nurture/sequences",
        headers=headers,
        json={"name": "x", "slug": f"seq-{suffix}", "status": "draft"},
        timeout=15,
    )
    assert seq.status_code == 201, seq.text
    seq_id = seq.json()["id"]

    # Email step missing subject/body.
    r = requests.post(
        f"{API}/marketing-os/nurture/sequences/{seq_id}/steps",
        headers=headers,
        json={"step_key": "e1", "action_type": "send_email"},
        timeout=15,
    )
    assert r.status_code == 422, r.text

    # Email body containing an email address (PHI channel guard).
    r = requests.post(
        f"{API}/marketing-os/nurture/sequences/{seq_id}/steps",
        headers=headers,
        json={
            "step_key": "e2",
            "action_type": "send_email",
            "subject": "hi",
            "body_html": "<p>write me at patient@example.com</p>",
        },
        timeout=15,
    )
    assert r.status_code == 422, r.text

    # create_task with an invalid task_type.
    r = requests.post(
        f"{API}/marketing-os/nurture/sequences/{seq_id}/steps",
        headers=headers,
        json={
            "step_key": "t1",
            "action_type": "create_task",
            "config": {"task_type": "teleport_lead"},
        },
        timeout=15,
    )
    assert r.status_code == 422, r.text

    # Extra/forbidden field on the payload (pydantic extra="forbid").
    r = requests.post(
        f"{API}/marketing-os/nurture/sequences",
        headers=headers,
        json={"name": "x", "slug": f"extra-{suffix}", "surprise": 1},
        timeout=15,
    )
    assert r.status_code == 422, r.text


def test_phase8a_inactive_sequence_cannot_enroll():
    headers = _login()
    suffix = uuid.uuid4().hex[:10]

    seq = requests.post(
        f"{API}/marketing-os/nurture/sequences",
        headers=headers,
        json={"name": "draft seq", "slug": f"draft-{suffix}",
              "status": "draft"},
        timeout=15,
    )
    assert seq.status_code == 201, seq.text
    seq_id = seq.json()["id"]

    lead = _create_lead(headers, suffix)
    r = requests.post(
        f"{API}/marketing-os/nurture/enroll",
        headers=headers,
        json={"sequence_id": seq_id, "lead_id": lead["id"]},
        timeout=15,
    )
    assert r.status_code == 409, r.text
