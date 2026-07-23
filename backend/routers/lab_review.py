"""
Lab Review Queue — thin workflow layer on top of the EXISTING `lab_values`
collection (see `routers/health_track.py`). No new lab module.

Adds `review_status`, `ordering_provider_*`, `reviewed_by`, `review_history`
and a one-click "create task" shortcut. All status transitions audit-logged.

Endpoints
    GET   /api/labs/review-queue
    PATCH /api/labs/{lab_id}/review-status
    POST  /api/labs/{lab_id}/create-task
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from audit import get_client_ip, log_audit
from delegations import has_active_delegation
from deps import _strip_id, api, db, require_roles
from models import new_id

REVIEW_STATUSES = (
    "new", "waiting_for_review", "reviewed",
    "patient_notified", "follow_up_needed",
)


class ReviewPatch(BaseModel):
    review_status: str
    review_notes: Optional[str] = Field(default=None, max_length=1000)
    ordering_provider_id: Optional[str] = None


class LabTaskShortcut(BaseModel):
    title: Optional[str] = None
    priority: str = "normal"
    assigned_staff_id: Optional[str] = None
    assigned_provider_id: Optional[str] = None
    due_date: Optional[datetime] = None
    note: Optional[str] = None


def _default_status(doc: dict) -> str:
    return (doc.get("review_status") or "new")


async def _can_transition(user: dict, lab: dict) -> bool:
    """Providers can always transition their labs. Delegated MA/admin can
    only transition labs for clients they have an active delegation on."""
    role = user.get("role")
    if role == "practitioner":
        return True
    if role in ("admin", "medical_assistant"):
        d = await has_active_delegation(user, lab.get("client_id"))
        return d is not None
    return False


@api.get("/labs/review-queue")
async def review_queue(
    status: Optional[str] = None,
    client_id: Optional[str] = None,
    ordering_provider_id: Optional[str] = None,
    limit: int = Query(200, le=500),
    user=Depends(require_roles("practitioner", "admin", "medical_assistant")),
):
    q: dict = {}
    if status:
        if status not in REVIEW_STATUSES:
            raise HTTPException(status_code=400, detail={
                "code": "invalid_review_status",
                "allowed": list(REVIEW_STATUSES),
            })
        q["review_status"] = status
    else:
        # Default queue view: everything that still needs attention.
        q["review_status"] = {"$ne": "patient_notified"}
    if client_id:
        q["client_id"] = client_id
    if ordering_provider_id:
        q["ordering_provider_id"] = ordering_provider_id

    rows = await db.lab_values.find(q).sort("created_at", -1).to_list(limit)
    out = []
    for r in rows:
        r["review_status"] = _default_status(r)
        client = await db.clients.find_one({"id": r.get("client_id")},
                                            {"full_name": 1, "email": 1})
        out.append({
            **_strip_id(r),
            "client_name": (client or {}).get("full_name") or (client or {}).get("email"),
        })
    return out


@api.patch("/labs/{lab_id}/review-status")
async def patch_review_status(lab_id: str, payload: ReviewPatch, request: Request,
                              user=Depends(require_roles("practitioner", "admin", "medical_assistant"))):
    if payload.review_status not in REVIEW_STATUSES:
        raise HTTPException(status_code=400, detail={
            "code": "invalid_review_status",
            "allowed": list(REVIEW_STATUSES),
        })
    lab = await db.lab_values.find_one({"id": lab_id})
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")

    if not await _can_transition(user, lab):
        raise HTTPException(status_code=403, detail={
            "code": "delegation_required",
            "message": "Provider authorization is required to update this lab's review status.",
        })

    now = datetime.now(timezone.utc)
    prev = _default_status(lab)
    actor_name = user.get("full_name") or user.get("email")
    updates = {
        "review_status": payload.review_status,
        "review_status_updated_at": now,
        "review_status_updated_by": user["id"],
    }
    if payload.review_notes:
        updates["review_notes"] = payload.review_notes.strip()
    if payload.ordering_provider_id and not lab.get("ordering_provider_id"):
        prov = await db.users.find_one({"id": payload.ordering_provider_id},
                                        {"full_name": 1})
        updates["ordering_provider_id"] = payload.ordering_provider_id
        updates["ordering_provider_name"] = (prov or {}).get("full_name")
    if payload.review_status == "reviewed":
        updates["reviewed_by"] = user["id"]
        updates["reviewed_by_name"] = actor_name
        updates["reviewed_at"] = now
    if payload.review_status == "patient_notified":
        updates["notified_by"] = user["id"]
        updates["notified_at"] = now
    history_event = {
        "event": "status_changed", "from": prev, "to": payload.review_status,
        "actor_id": user["id"], "actor_name": actor_name, "ts": now,
        "note": (payload.review_notes or "").strip()[:400] or None,
    }
    await db.lab_values.update_one(
        {"id": lab_id},
        {"$set": updates, "$push": {"review_history": history_event}},
    )
    await log_audit(db, user["id"], user["email"], "lab.review_status",
                    resource_type="lab", resource_id=lab_id,
                    severity="info", outcome="success",
                    metadata={"from": prev, "to": payload.review_status,
                              "client_id": lab.get("client_id")},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    updated = await db.lab_values.find_one({"id": lab_id})
    updated["review_status"] = _default_status(updated)
    return _strip_id(updated)


class LabAttachIn(BaseModel):
    file_id: str


@api.post("/labs/{lab_id}/attachments")
async def attach_file_to_lab(lab_id: str, payload: LabAttachIn, request: Request,
                              user=Depends(require_roles("practitioner", "admin", "medical_assistant", "staff"))):
    """Link an already-uploaded file to a lab result. File must already exist
    in the file vault (upload via `/api/files/upload` first with `category=lab`
    and the same `client_id` as the lab)."""
    lab = await db.lab_values.find_one({"id": lab_id})
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    meta = await db.files.find_one({"id": payload.file_id, "deleted_at": None})
    if not meta:
        raise HTTPException(status_code=404, detail="File not found")
    if meta.get("client_id") and lab.get("client_id") and meta["client_id"] != lab["client_id"]:
        raise HTTPException(status_code=400, detail="File belongs to a different client")
    # Delegated access enforcement mirrors _can_transition.
    if user.get("role") in ("admin", "medical_assistant"):
        d = await has_active_delegation(user, lab.get("client_id"))
        if d is None:
            raise HTTPException(status_code=403, detail={
                "code": "delegation_required",
                "message": "Provider authorization required to attach files to this lab.",
            })
    await db.lab_values.update_one(
        {"id": lab_id},
        {"$addToSet": {"attachment_file_ids": payload.file_id}},
    )
    await log_audit(db, user["id"], user["email"], "lab.attach_file",
                    resource_type="lab", resource_id=lab_id,
                    metadata={"file_id": payload.file_id, "client_id": lab.get("client_id")},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    updated = await db.lab_values.find_one({"id": lab_id})
    return _strip_id(updated)


@api.delete("/labs/{lab_id}/attachments/{file_id}")
async def detach_file_from_lab(lab_id: str, file_id: str, request: Request,
                                user=Depends(require_roles("practitioner", "admin", "medical_assistant", "staff"))):
    lab = await db.lab_values.find_one({"id": lab_id})
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    if user.get("role") in ("admin", "medical_assistant"):
        d = await has_active_delegation(user, lab.get("client_id"))
        if d is None:
            raise HTTPException(status_code=403, detail="Provider authorization required")
    await db.lab_values.update_one(
        {"id": lab_id}, {"$pull": {"attachment_file_ids": file_id}},
    )
    await log_audit(db, user["id"], user["email"], "lab.detach_file",
                    resource_type="lab", resource_id=lab_id,
                    metadata={"file_id": file_id}, ip=get_client_ip(request),
                    user_agent=request.headers.get("user-agent"))
    return {"ok": True}



async def create_task_from_lab(lab_id: str, payload: LabTaskShortcut, request: Request,
                               user=Depends(require_roles("practitioner", "admin", "medical_assistant"))):
    lab = await db.lab_values.find_one({"id": lab_id})
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")

    # Reuse the tasks collection directly — the tasks router owns validation
    # for input payloads, but this is an internal shortcut (fewer inputs) so
    # we create the doc inline with sane defaults.
    from routers.tasks import TASK_PRIORITIES  # local import to avoid cycle
    if payload.priority not in TASK_PRIORITIES:
        raise HTTPException(status_code=400, detail="Invalid priority")

    client = await db.clients.find_one({"id": lab.get("client_id")},
                                        {"full_name": 1, "email": 1})
    now = datetime.now(timezone.utc)
    default_title = (
        payload.title or
        f"Review lab: {lab.get('test_name', 'result')} — {(client or {}).get('full_name', 'patient')}"
    )
    task = {
        "id": new_id(),
        "title": default_title[:200],
        "description": payload.note or "Auto-generated from lab review queue.",
        "client_id": lab.get("client_id"),
        "client_name": (client or {}).get("full_name") or (client or {}).get("email"),
        "assigned_staff_id": payload.assigned_staff_id,
        "assigned_staff_name": None,
        "assigned_provider_id": payload.assigned_provider_id or lab.get("ordering_provider_id"),
        "assigned_provider_name": None,
        "due_date": payload.due_date,
        "priority": payload.priority,
        "category": "review_labs",
        "linked_lab_id": lab_id,
        "linked_appointment_id": None,
        "status": "new",
        "created_by": user["id"],
        "created_by_name": user.get("full_name") or user.get("email"),
        "created_at": now, "updated_at": now,
        "completed_by": None, "completed_by_name": None, "completed_at": None,
        "internal_notes": [],
        "history": [{"event": "created_from_lab", "actor_id": user["id"],
                     "actor_name": user.get("full_name") or user.get("email"),
                     "ts": now, "lab_id": lab_id}],
    }
    # Resolve assignee names if given
    for key, id_key, name_key in [("assigned_staff", "assigned_staff_id", "assigned_staff_name"),
                                    ("assigned_provider", "assigned_provider_id", "assigned_provider_name")]:
        uid = task.get(id_key)
        if uid:
            u = await db.users.find_one({"id": uid}, {"full_name": 1, "email": 1})
            if u:
                task[name_key] = u.get("full_name") or u.get("email")
    await db.internal_tasks.insert_one(task)
    await log_audit(db, user["id"], user["email"], "lab.task_created",
                    resource_type="task", resource_id=task["id"],
                    metadata={"lab_id": lab_id, "client_id": lab.get("client_id")},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(task)
