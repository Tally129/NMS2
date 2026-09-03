"""HTTP tests for Marketing OS Phase 8B — appointment-recovery /events adapter.

Isolated local backend + disposable PostgreSQL only. No external outreach; the
scheduler never sends and email actions remain held. No PHI enters Marketing OS.
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


def _active_recovery_sequence(headers, suffix, trigger_type,
                              second_delayed_step=False):
    seq = requests.post(
        f"{API}/marketing-os/nurture/sequences",
        headers=headers,
        json={
            "name": f"TEST Recovery {suffix}",
            "slug": f"test-recovery-{suffix}",
            "status": "draft",
            "trigger_type": trigger_type,
        },
        timeout=15,
    )
    assert seq.status_code == 201, seq.text
    seq_id = seq.json()["id"]

    r = requests.post(
        f"{API}/marketing-os/nurture/sequences/{seq_id}/steps",
        headers=headers,
        json={
            "step_key": "recover_task",
            "action_type": "create_task",
            "position": 0,
            "delay_minutes": 0,
            "config": {"task_type": "recover_no_show"},
        },
        timeout=15,
    )
    assert r.status_code == 201, r.text

    if second_delayed_step:
        # A delayed 2nd step keeps the enrollment active after the first tick.
        r = requests.post(
            f"{API}/marketing-os/nurture/sequences/{seq_id}/steps",
            headers=headers,
            json={
                "step_key": "followup_task",
                "action_type": "create_task",
                "position": 1,
                "delay_minutes": 1440,
                "config": {"task_type": "follow_up_later"},
            },
            timeout=15,
        )
        assert r.status_code == 201, r.text

    r = requests.patch(
        f"{API}/marketing-os/nurture/sequences/{seq_id}",
        headers=headers,
        json={"status": "active"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return seq_id


def _event(headers, **body):
    return requests.post(
        f"{API}/marketing-os/nurture/events",
        headers=headers,
        json=body,
        timeout=20,
    )


def test_phase8b_no_show_event_enrolls_and_is_idempotent():
    headers = _login()
    suffix = uuid.uuid4().hex[:10]
    subject = f"subj_ns_{suffix}"

    seq_id = _active_recovery_sequence(headers, suffix, "no_show")

    # First no-show event: creates a lead + recovery enrollment.
    r1 = _event(headers, marketing_subject_id=subject, status="no_show",
                source="google", medium="cpc", service_category="wellness")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["decision"] == "enroll"
    assert body1["event_type"] == "appointment_no_show"
    # Enrolled into the sequence created by this test (fresh subject).
    mine = [e for e in body1["enrollments"] if e["sequence_id"] == seq_id]
    assert len(mine) == 1
    lead_id = body1["lead_id"]
    assert body1["safety"]["automatic_outreach"] is False

    # Duplicate delivery: no new active enrollment for this sequence.
    r2 = _event(headers, marketing_subject_id=subject, status="no_show")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert all(e["sequence_id"] != seq_id for e in body2["enrollments"])
    assert any(
        s.get("sequence_id") == seq_id and s["reason"] == "already_active"
        for s in body2["skipped"]
    )

    active = requests.get(
        f"{API}/marketing-os/nurture/enrollments",
        headers=headers,
        params={"lead_id": lead_id, "sequence_id": seq_id, "status": "active"},
        timeout=15,
    ).json()["enrollments"]
    assert len(active) == 1

    # Scheduler materializes the recovery task idempotently (scoped to lead).
    t1 = requests.post(f"{API}/marketing-os/nurture/scheduler/tick",
                       headers=headers, json={"limit": 100}, timeout=30)
    assert t1.status_code == 200, t1.text

    actions_after_t1 = requests.get(
        f"{API}/marketing-os/nurture/actions",
        headers=headers,
        params={"lead_id": lead_id},
        timeout=15,
    ).json()["actions"]
    assert len(actions_after_t1) >= 1
    assert all(a["action_type"] == "create_task" for a in actions_after_t1)

    # Re-tick: this lead's action count does not change (idempotent).
    requests.post(f"{API}/marketing-os/nurture/scheduler/tick",
                  headers=headers, json={"limit": 100}, timeout=30)

    actions = requests.get(
        f"{API}/marketing-os/nurture/actions",
        headers=headers,
        params={"lead_id": lead_id},
        timeout=15,
    ).json()["actions"]
    assert len(actions) == len(actions_after_t1)
    assert all(a["action_type"] == "create_task" for a in actions)


def test_phase8b_booked_event_suppresses_active_recovery():
    headers = _login()
    suffix = uuid.uuid4().hex[:10]
    subject = f"subj_sup_{suffix}"

    _active_recovery_sequence(headers, suffix, "no_show",
                              second_delayed_step=True)

    r1 = _event(headers, marketing_subject_id=subject, status="no_show")
    assert r1.status_code == 200, r1.text
    lead_id = r1.json()["lead_id"]

    # Queue an action; enrollment stays active (2nd step is delayed).
    requests.post(f"{API}/marketing-os/nurture/scheduler/tick",
                  headers=headers, json={"limit": 50}, timeout=30)

    active_before = requests.get(
        f"{API}/marketing-os/nurture/enrollments",
        headers=headers,
        params={"lead_id": lead_id, "status": "active"},
        timeout=15,
    ).json()["enrollments"]
    assert len(active_before) >= 1

    # Booked event suppresses active recovery.
    r2 = _event(headers, marketing_subject_id=subject, status="booked")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["decision"] == "suppress"
    assert body2["stopped_enrollments"] >= 1

    enrollments = requests.get(
        f"{API}/marketing-os/nurture/enrollments",
        headers=headers,
        params={"lead_id": lead_id},
        timeout=15,
    ).json()["enrollments"]
    assert all(e["status"] != "active" for e in enrollments)
    assert any(
        (e["stop_reason"] or "").startswith("event:appointment_booked")
        for e in enrollments
    )

    # Pending actions were cancelled (no active/pending remain).
    actions = requests.get(
        f"{API}/marketing-os/nurture/actions",
        headers=headers,
        params={"lead_id": lead_id},
        timeout=15,
    ).json()["actions"]
    assert all(
        a["status"] not in ("pending_approval", "scheduled") for a in actions
    )


def test_phase8b_cancelled_event_enrolls_into_cancel_sequence():
    headers = _login()
    suffix = uuid.uuid4().hex[:10]
    subject = f"subj_cx_{suffix}"

    seq_id = _active_recovery_sequence(
        headers, suffix, "appointment_cancelled"
    )

    r = _event(headers, marketing_subject_id=subject, status="cancelled")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "enroll"
    assert body["event_type"] == "appointment_cancelled"
    mine = [e for e in body["enrollments"] if e["sequence_id"] == seq_id]
    assert len(mine) == 1


def test_phase8b_rejects_phi_and_bad_signals():
    headers = _login()
    suffix = uuid.uuid4().hex[:8]

    # Unknown status -> normalized rejection -> 422 (not 500).
    r = _event(headers, marketing_subject_id=f"subj_{suffix}",
               status="teleported")
    assert r.status_code == 422, r.text

    # Missing subject -> pydantic 422.
    r = requests.post(
        f"{API}/marketing-os/nurture/events",
        headers=headers,
        json={"status": "no_show"},
        timeout=15,
    )
    assert r.status_code == 422, r.text

    # PHI/contact field is not an accepted input field (extra=forbid) -> 422.
    r = requests.post(
        f"{API}/marketing-os/nurture/events",
        headers=headers,
        json={
            "marketing_subject_id": f"subj_{suffix}",
            "status": "no_show",
            "email": "patient@example.com",
        },
        timeout=15,
    )
    assert r.status_code == 422, r.text


def test_phase8b_non_nurturable_lead_is_skipped():
    headers = _login()
    suffix = uuid.uuid4().hex[:10]
    subject = f"subj_lost_{suffix}"

    _active_recovery_sequence(headers, suffix, "no_show")

    # Pre-create the lead and move it to a suppressed status.
    lead = requests.post(
        f"{API}/marketing-os/leads",
        headers=headers,
        json={"marketing_subject_id": subject, "source": "google"},
        timeout=15,
    )
    assert lead.status_code == 201, lead.text
    lead_id = lead.json()["id"]
    requests.patch(
        f"{API}/marketing-os/leads/{lead_id}/status",
        headers=headers,
        json={"lead_status": "lost"},
        timeout=15,
    )

    r = _event(headers, marketing_subject_id=subject, status="no_show")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "enroll"
    assert body["enrollments"] == []
    assert any(s["reason"] == "lead_non_nurturable" for s in body["skipped"])


def test_phase8b_no_active_sequence_is_skipped_cleanly():
    headers = _login()
    suffix = uuid.uuid4().hex[:10]
    subject = f"subj_req_{suffix}"

    # No active 'appointment_requested' sequence exists in this suite.
    r = _event(headers, marketing_subject_id=subject, status="requested")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "enroll"
    assert body["enrollments"] == []
    assert any(
        s.get("reason") == "no_active_sequence_for_trigger"
        for s in body["skipped"]
    )
