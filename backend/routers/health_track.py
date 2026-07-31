"""
Phase 3: Symptom logs + Lab values + Secure messaging.

Extracted from server.py during Phase 16 refactor.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, Query, Request

from audit import get_client_ip, log_audit
from notifiers import push_to_user, send_email
from deps import (
    _resolve_self_client, _strip_id, api, db, get_current_user, require_roles,
)
from models import (
    LabValueIn, LabValueOut, MessageIn, MessageOut,
    SymptomLogIn, SymptomLogOut, ThreadIn, ThreadOut, new_id,
)
from pg_shims import find_client, find_user_by_id


# =================== PHASE 3: SYMPTOMS / LABS / MESSAGING + TELEHEALTH ===================


# ---------- Symptom logs ----------
TRACKED_SYMPTOMS = [
    "Fatigue", "Pain", "Sleep", "Mood", "Digestion", "Anxiety",
    "Headache", "Brain fog", "Energy", "Stress",
]


@api.get("/symptoms/presets")
async def symptom_presets(user=Depends(get_current_user)):
    return {"symptoms": TRACKED_SYMPTOMS}


@api.post("/symptom-logs", response_model=SymptomLogOut)
async def log_symptom(payload: SymptomLogIn, request: Request, user=Depends(get_current_user)):
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            raise HTTPException(status_code=404, detail="Client record missing")
        client_id = self_client["id"]
    else:
        if not payload.client_id:
            raise HTTPException(status_code=400, detail="client_id required")
        client_id = payload.client_id

    now = datetime.now(timezone.utc)
    doc = {
        "id": new_id(),
        "client_id": client_id,
        "symptom": payload.symptom,
        "severity": payload.severity,
        "note": payload.note,
        "logged_at": payload.logged_at or now,
        "created_at": now,
    }
    await db.symptom_logs.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "symptom.log",
                    resource_type="symptom", resource_id=doc["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(doc)


@api.get("/symptom-logs", response_model=List[SymptomLogOut])
async def list_symptoms(client_id: Optional[str] = None, symptom: Optional[str] = None,
                        user=Depends(get_current_user)):
    q = {}
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            return []
        q["client_id"] = self_client["id"]
    elif client_id:
        q["client_id"] = client_id
    if symptom:
        q["symptom"] = symptom
    items = await db.symptom_logs.find(q).sort("logged_at", 1).to_list(1000)
    return [_strip_id(i) for i in items]


# ---------- Lab values ----------
LAB_PRESETS = [
    {"test_name": "TSH", "unit": "mIU/L", "reference_low": 0.4, "reference_high": 4.0},
    {"test_name": "Free T3", "unit": "pg/mL", "reference_low": 2.3, "reference_high": 4.2},
    {"test_name": "Free T4", "unit": "ng/dL", "reference_low": 0.8, "reference_high": 1.8},
    {"test_name": "Vitamin D", "unit": "ng/mL", "reference_low": 30, "reference_high": 100},
    {"test_name": "Vitamin B12", "unit": "pg/mL", "reference_low": 200, "reference_high": 900},
    {"test_name": "A1C", "unit": "%", "reference_low": 4.0, "reference_high": 5.6},
    {"test_name": "Glucose (fasting)", "unit": "mg/dL", "reference_low": 70, "reference_high": 99},
    {"test_name": "Cortisol (AM)", "unit": "mcg/dL", "reference_low": 6, "reference_high": 23},
    {"test_name": "DHEA-S", "unit": "mcg/dL", "reference_low": 35, "reference_high": 430},
]


@api.get("/labs/presets")
async def lab_presets(user=Depends(get_current_user)):
    return {"presets": LAB_PRESETS}


@api.post("/lab-values", response_model=LabValueOut)
async def create_lab(payload: LabValueIn, request: Request, user=Depends(require_roles("practitioner", "admin", "staff"))):
    c = await find_client(client_id=payload.client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    doc = payload.dict()
    doc["id"] = new_id()
    doc["recorded_by"] = user["id"]
    doc["recorded_by_name"] = user.get("full_name", "")
    doc["created_at"] = datetime.now(timezone.utc)
    await db.lab_values.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "lab.create",
                    resource_type="lab", resource_id=doc["id"],
                    metadata={"client_id": payload.client_id, "test": payload.test_name},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(doc)


@api.get("/lab-values", response_model=List[LabValueOut])
async def list_labs(client_id: Optional[str] = None, test_name: Optional[str] = None,
                    user=Depends(get_current_user)):
    q = {}
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            return []
        q["client_id"] = self_client["id"]
    elif client_id:
        q["client_id"] = client_id
    if test_name:
        q["test_name"] = test_name
    items = await db.lab_values.find(q).sort("measured_at", 1).to_list(1000)
    return [_strip_id(i) for i in items]


@api.delete("/lab-values/{lab_id}")
async def delete_lab(lab_id: str, request: Request, user=Depends(require_roles("practitioner", "admin"))):
    await db.lab_values.delete_one({"id": lab_id})
    await log_audit(db, user["id"], user["email"], "lab.delete",
                    resource_type="lab", resource_id=lab_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


async def _message_recipient(thread: dict, sender: dict) -> Optional[dict]:
    """Resolve the other portal user for a two-party patient/care-team thread."""
    if sender.get("role") == "client":
        u = await find_user_by_id(thread.get("practitioner_id"))
        return u if u and u.get("is_active", True) else None

    client = await find_client(client_id=thread.get("client_id"))
    if not client or not client.get("user_id"):
        return None
    u = await find_user_by_id(client["user_id"])
    return u if u and u.get("is_active", True) else None


def _message_portal_path(recipient: dict) -> str:
    return (
        "/portal/patient/messages"
        if recipient.get("role") == "client"
        else "/portal/provider/messages"
    )


async def _notify_new_secure_message(thread: dict, sender: dict) -> dict:
    """Send privacy-safe push and email alerts; message content stays in the portal."""
    recipient = await _message_recipient(thread, sender)
    if not recipient:
        return {"push": 0, "email": "skipped"}

    portal_path = _message_portal_path(recipient)

    # Never include sender identity, thread subject, message body, attachments,
    # diagnosis, treatment, or other PHI in a lock-screen notification.
    push_count = 0
    try:
        push_count = await push_to_user(
            recipient["id"],
            "Natural Medical Solutions",
            "You have a new secure message.",
            url=portal_path,
            tag="secure-message",
        )
    except Exception:
        # The in-app message must still save if web push is unavailable.
        push_count = 0

    email_status = "skipped"
    if recipient.get("email"):
        app_url = os.environ.get("FRONTEND_ORIGIN", "").rstrip("/")
        portal_url = f"{app_url}{portal_path}" if app_url else portal_path
        sender_label = "your care team" if sender.get("role") != "client" else "a patient"
        try:
            email_status = await send_email(
                db,
                recipient["email"],
                "New secure message available",
                (
                    "<p>You have a new secure message from " + sender_label + ".</p>"
                    "<p>For your privacy, message details are not included in this email.</p>"
                    f'<p><a href="{portal_url}">Sign in to the secure portal</a> to read and respond.</p>'
                    "<p>This inbox is not monitored for emergencies. Call 911 for an emergency.</p>"
                ),
                plain_text=(
                    "You have a new secure message. For your privacy, message details are not "
                    f"included in this email. Sign in to the secure portal: {portal_url}"
                ),
                action="message.secure_alert",
                payload_metadata={"thread_id": thread.get("id")},
                redact_recipient=True,
            )
        except Exception:
            email_status = "failed"

    return {"push": push_count, "email": email_status}


# ---------- Secure Messaging ----------
MESSAGE_TEMPLATES = [
    {"id": "follow_up", "label": "Follow-up reminder", "body": "This is a friendly reminder about your follow-up visit. Please log in to the portal to schedule."},
    {"id": "intake_pending", "label": "Intake pending", "body": "We noticed your intake is not yet complete. Please finish it in the portal before your visit."},
    {"id": "labs_ready", "label": "Results available", "body": "Your latest results are now available in the portal. Please log in to review and message us with any questions."},
    {"id": "schedule_visit", "label": "Schedule your next visit", "body": "It's time to book your next wellness visit. Please use the portal to pick a time that works for you."},
    {"id": "thanks", "label": "Thank you", "body": "Thank you for visiting Natural Medical Solutions. We're here if any questions come up."},
]


@api.get("/messages/templates")
async def message_templates(user=Depends(get_current_user)):
    return {"templates": MESSAGE_TEMPLATES}


async def _thread_other_role(role: str) -> str:
    return "practitioner" if role == "client" else "client"


async def _hydrate_thread(t, user):
    t = _strip_id(t)
    if not t:
        return None
    c = await find_client(client_id=t["client_id"])
    if c:
        t["client_name"] = c.get("full_name")
    p = await find_user_by_id(t["practitioner_id"])
    if p:
        t["practitioner_name"] = p.get("full_name")
    # Count unread for current user
    unread = await db.messages.count_documents({"thread_id": t["id"], "read_by": {"$ne": user["id"]}, "sender_id": {"$ne": user["id"]}})
    t["unread_for_me"] = unread
    return t


@api.get("/messages/threads", response_model=List[ThreadOut])
async def list_threads(user=Depends(get_current_user)):
    q = {}
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            return []
        q["client_id"] = self_client["id"]
    elif user["role"] in ("practitioner",):
        q["practitioner_id"] = user["id"]
    items = await db.message_threads.find(q).sort("last_message_at", -1).to_list(200)
    return [await _hydrate_thread(t, user) for t in items]


@api.post("/messages/threads", response_model=ThreadOut)
async def create_thread(payload: ThreadIn, request: Request, user=Depends(get_current_user)):
    # Resolve client + practitioner
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            raise HTTPException(status_code=404, detail="Client record missing")
        client_id = self_client["id"]
        practitioner_id = payload.participant_id
        p = await find_user_by_id(practitioner_id)
        if not p or p.get("role") not in ("practitioner", "admin", "staff"):
            raise HTTPException(status_code=400, detail="Invalid practitioner")
    else:
        c = await find_client(client_id=payload.participant_id)
        if not c:
            raise HTTPException(status_code=404, detail="Client not found")
        client_id = c["id"]
        practitioner_id = user["id"]

    doc = {
        "id": new_id(),
        "client_id": client_id,
        "practitioner_id": practitioner_id,
        "subject": payload.subject,
        "last_message_at": None,
        "last_message_preview": None,
        "created_at": datetime.now(timezone.utc),
    }
    await db.message_threads.insert_one(doc)

    if payload.first_message:
        msg = {
            "id": new_id(),
            "thread_id": doc["id"],
            "sender_id": user["id"],
            "sender_role": user["role"],
            "sender_name": user.get("full_name", ""),
            "body": payload.first_message,
            "attachment_file_ids": [],
            "read_by": [user["id"]],
            "created_at": datetime.now(timezone.utc),
        }
        await db.messages.insert_one(msg)
        await db.message_threads.update_one({"id": doc["id"]}, {"$set": {
            "last_message_at": msg["created_at"],
            "last_message_preview": payload.first_message[:140],
        }})
        await _notify_new_secure_message(doc, user)

    await log_audit(db, user["id"], user["email"], "message.thread_create",
                    resource_type="thread", resource_id=doc["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    t = await db.message_threads.find_one({"id": doc["id"]})
    return await _hydrate_thread(t, user)


@api.get("/messages/threads/{thread_id}", response_model=List[MessageOut])
async def list_messages(thread_id: str, request: Request, user=Depends(get_current_user)):
    t = await db.message_threads.find_one({"id": thread_id})
    if not t:
        raise HTTPException(status_code=404, detail="Thread not found")
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client or t["client_id"] != self_client["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
    elif user["role"] == "practitioner" and t["practitioner_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    items = await db.messages.find({"thread_id": thread_id}).sort("created_at", 1).to_list(500)
    # Mark read for this user
    await db.messages.update_many({"thread_id": thread_id, "read_by": {"$ne": user["id"]}},
                                  {"$push": {"read_by": user["id"]}})
    await log_audit(db, user["id"], user["email"], "message.thread_read",
                    resource_type="thread", resource_id=thread_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return [_strip_id(i) for i in items]


@api.post("/messages/threads/{thread_id}/messages", response_model=MessageOut)
async def post_message(thread_id: str, payload: MessageIn, request: Request, user=Depends(get_current_user)):
    t = await db.message_threads.find_one({"id": thread_id})
    if not t:
        raise HTTPException(status_code=404, detail="Thread not found")
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client or t["client_id"] != self_client["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
    elif user["role"] == "practitioner" and t["practitioner_id"] != user["id"] and user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    now = datetime.now(timezone.utc)
    msg = {
        "id": new_id(),
        "thread_id": thread_id,
        "sender_id": user["id"],
        "sender_role": user["role"],
        "sender_name": user.get("full_name", ""),
        "body": payload.body,
        "attachment_file_ids": payload.attachment_file_ids or [],
        "read_by": [user["id"]],
        "created_at": now,
    }
    await db.messages.insert_one(msg)
    await db.message_threads.update_one({"id": thread_id}, {"$set": {
        "last_message_at": now,
        "last_message_preview": payload.body[:140],
    }})
    # Privacy-safe push + email alerts. Message details remain inside the portal.
    thread = await db.message_threads.find_one({"id": thread_id})
    await _notify_new_secure_message(thread or t, user)
    await log_audit(db, user["id"], user["email"], "message.send",
                    resource_type="thread", resource_id=thread_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(msg)


@api.get("/messages/unread-count")
async def messages_unread_count(user=Depends(get_current_user)):
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            return {"count": 0}
        threads = await db.message_threads.find({"client_id": self_client["id"]}).to_list(500)
    elif user["role"] == "practitioner":
        threads = await db.message_threads.find({"practitioner_id": user["id"]}).to_list(500)
    else:
        return {"count": 0}
    count = 0
    for t in threads:
        c = await db.messages.count_documents({"thread_id": t["id"], "read_by": {"$ne": user["id"]}, "sender_id": {"$ne": user["id"]}})
        count += c
    return {"count": count}


# ---------- Promote a message thread to a task (handoff #6) ----------
# Assignment, owner, priority, due date, status and escalation live on the
# existing `internal_tasks` collection (see routers/tasks.py). To avoid
# duplicating those fields onto every thread, we promote a thread INTO the
# tasks system with a single call. The thread stores only `linked_task_id`;
# the reverse pointer lives on the task via a `linked_thread_id` field.
class PromoteThreadToTaskIn:
    """Free-form dict validated inline so we don't import Pydantic here."""


@api.post("/messages/threads/{thread_id}/promote-to-task")
async def promote_thread_to_task(thread_id: str, payload: dict, request: Request,
                                 user=Depends(require_roles(
                                     "admin", "practitioner", "staff",
                                     "front_desk", "frontdesk", "medical_assistant",
                                 ))):
    t = await db.message_threads.find_one({"id": thread_id})
    if not t:
        raise HTTPException(status_code=404, detail="Thread not found")
    if t.get("linked_task_id"):
        raise HTTPException(status_code=409, detail={
            "code": "task_already_linked",
            "task_id": t["linked_task_id"],
        })

    # Reuse task priority/category enums so this endpoint never drifts from
    # the existing task authorization system.
    from routers.tasks import TASK_PRIORITIES, TASK_CATEGORIES
    priority = (payload or {}).get("priority") or "normal"
    category = (payload or {}).get("category") or "message_followup"
    if priority not in TASK_PRIORITIES:
        raise HTTPException(status_code=400, detail={
            "code": "invalid_priority", "allowed": list(TASK_PRIORITIES),
        })
    if category not in TASK_CATEGORIES:
        # Fall back to a safe default rather than 400 — front-desk shouldn't
        # need to know the enum list.
        category = "other"

    now = datetime.now(timezone.utc)
    default_title = (payload or {}).get("title") or (
        f"Follow up: {t.get('subject', 'patient message')}"
    )[:200]
    assigned_staff_id = (payload or {}).get("assigned_staff_id")
    assigned_provider_id = (payload or {}).get("assigned_provider_id") \
        or t.get("practitioner_id")

    async def _name_of(uid):
        if not uid:
            return None
        u = await find_user_by_id(uid)
        return (u or {}).get("full_name") or (u or {}).get("email")

    client = await find_client(client_id=t.get("client_id"))

    due_raw = (payload or {}).get("due_date")
    due_date = None
    if isinstance(due_raw, str) and due_raw:
        try:
            due_date = datetime.fromisoformat(due_raw.replace("Z", "+00:00"))
        except ValueError:
            due_date = None

    task = {
        "id": new_id(),
        "title": default_title,
        "description": (payload or {}).get("description")
            or t.get("last_message_preview") or "",
        "client_id": t.get("client_id"),
        "client_name": (client or {}).get("full_name") or (client or {}).get("email"),
        "assigned_staff_id": assigned_staff_id,
        "assigned_staff_name": await _name_of(assigned_staff_id),
        "assigned_provider_id": assigned_provider_id,
        "assigned_provider_name": await _name_of(assigned_provider_id),
        "due_date": due_date,
        "priority": priority,
        "category": category,
        "linked_thread_id": thread_id,
        "linked_lab_id": None,
        "linked_appointment_id": None,
        "status": "new",
        "created_by": user["id"],
        "created_by_name": user.get("full_name") or user.get("email"),
        "created_at": now, "updated_at": now,
        "completed_by": None, "completed_by_name": None, "completed_at": None,
        "internal_notes": [],
        "history": [{
            "event": "created_from_message", "actor_id": user["id"],
            "actor_name": user.get("full_name") or user.get("email"),
            "ts": now, "thread_id": thread_id,
        }],
    }
    await db.internal_tasks.insert_one(task)
    await db.message_threads.update_one(
        {"id": thread_id}, {"$set": {"linked_task_id": task["id"]}},
    )
    await log_audit(
        db, user["id"], user["email"], "message.promote_to_task",
        resource_type="task", resource_id=task["id"],
        metadata={"thread_id": thread_id, "client_id": t.get("client_id")},
        ip=get_client_ip(request), user_agent=request.headers.get("user-agent"),
    )
    return _strip_id(task)





