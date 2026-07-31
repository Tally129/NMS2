"""
Internal Task & Workflow Manager — lightweight EMR-side task tracking.

Not a project-management system. Each `internal_task` document tracks a
small unit of clinic work: review a lab, follow up with a patient, collect
a payment, etc. Reuses the existing audit-log infrastructure; no new
notification channels.

Endpoints
    POST   /api/tasks
    GET    /api/tasks                         (filters: assigned_to, status,
                                               priority, due_before, client_id,
                                               mine, category, search)
    GET    /api/tasks/{id}
    PATCH  /api/tasks/{id}                    (reassign, transition, add note)
    DELETE /api/tasks/{id}
    GET    /api/tasks/dashboard/summary       (widget counts: mine, overdue,
                                               due_today, waiting)
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from audit import get_client_ip, log_audit
from deps import _strip_id, api, db, get_current_user, require_roles
from models import new_id
from pg_shims import find_client, find_user_by_id


TASK_STATUSES = ("new", "in_progress", "waiting", "completed")
TASK_PRIORITIES = ("low", "normal", "high", "urgent")
TASK_CATEGORIES = (
    "review_labs", "call_patient", "follow_up_appointment", "collect_payment",
    "review_intake", "upload_documents", "insurance_followup",
    "telehealth_followup", "other",
)
WORKFORCE = ("practitioner", "admin", "staff", "medical_assistant")


class TaskIn(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    client_id: Optional[str] = None
    assigned_staff_id: Optional[str] = None
    assigned_provider_id: Optional[str] = None
    due_date: Optional[datetime] = None
    priority: str = "normal"
    category: str = "other"
    linked_lab_id: Optional[str] = None
    linked_appointment_id: Optional[str] = None


class TaskPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    assigned_staff_id: Optional[str] = None
    assigned_provider_id: Optional[str] = None
    due_date: Optional[datetime] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    category: Optional[str] = None
    add_note: Optional[str] = None


async def _resolve_name(user_id: Optional[str]) -> Optional[str]:
    if not user_id:
        return None
    u = await find_user_by_id(user_id)
    if not u:
        return None
    return u.get("full_name") or u.get("email")


async def _resolve_client_name(client_id: Optional[str]) -> Optional[str]:
    if not client_id:
        return None
    c = await find_client(client_id=client_id)
    if not c:
        return None
    return c.get("full_name") or c.get("email")


def _validate_enum(value: str, allowed: tuple, label: str) -> None:
    if value not in allowed:
        raise HTTPException(status_code=400, detail={
            "code": f"invalid_{label}",
            "message": f"{label} must be one of {list(allowed)}",
        })


@api.post("/tasks")
async def create_task(payload: TaskIn, request: Request,
                      user=Depends(require_roles(*WORKFORCE))):
    _validate_enum(payload.priority, TASK_PRIORITIES, "priority")
    _validate_enum(payload.category, TASK_CATEGORIES, "category")
    now = datetime.now(timezone.utc)
    doc = payload.dict()
    doc.update({
        "id": new_id(),
        "status": "new",
        "created_by": user["id"],
        "created_by_name": user.get("full_name") or user.get("email"),
        "created_at": now,
        "updated_at": now,
        "completed_by": None,
        "completed_by_name": None,
        "completed_at": None,
        "assigned_staff_name": await _resolve_name(payload.assigned_staff_id),
        "assigned_provider_name": await _resolve_name(payload.assigned_provider_id),
        "client_name": await _resolve_client_name(payload.client_id),
        "internal_notes": [],
        "history": [{
            "event": "created", "actor_id": user["id"],
            "actor_name": user.get("full_name") or user.get("email"),
            "ts": now,
        }],
    })
    await db.internal_tasks.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "task.create",
                    resource_type="task", resource_id=doc["id"],
                    metadata={"category": payload.category,
                              "assigned_staff": payload.assigned_staff_id,
                              "assigned_provider": payload.assigned_provider_id,
                              "client_id": payload.client_id},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(doc)


@api.get("/tasks")
async def list_tasks(
    request: Request,
    assigned_to: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    due_before: Optional[datetime] = None,
    client_id: Optional[str] = None,
    category: Optional[str] = None,
    mine: bool = False,
    search: Optional[str] = None,
    limit: int = Query(200, le=500),
    user=Depends(require_roles(*WORKFORCE)),
):
    q: dict = {}
    if mine:
        q["$or"] = [
            {"assigned_staff_id": user["id"]},
            {"assigned_provider_id": user["id"]},
        ]
    elif assigned_to:
        q["$or"] = [
            {"assigned_staff_id": assigned_to},
            {"assigned_provider_id": assigned_to},
        ]
    if status:
        _validate_enum(status, TASK_STATUSES, "status")
        q["status"] = status
    if priority:
        _validate_enum(priority, TASK_PRIORITIES, "priority")
        q["priority"] = priority
    if due_before:
        q["due_date"] = {"$lte": due_before}
    if client_id:
        q["client_id"] = client_id
    if category:
        _validate_enum(category, TASK_CATEGORIES, "category")
        q["category"] = category
    if search:
        q["title"] = {"$regex": search, "$options": "i"}
    rows = await db.internal_tasks.find(q).sort([
        ("status", 1), ("priority", -1), ("due_date", 1),
    ]).to_list(limit)
    return [_strip_id(r) for r in rows]


@api.get("/tasks/dashboard/summary")
async def tasks_dashboard_summary(user=Depends(require_roles(*WORKFORCE))):
    """Small counts payload for the sidebar/nav badge widget."""
    now = datetime.now(timezone.utc)
    today_end = datetime.combine(now.date(), datetime.max.time(), tzinfo=timezone.utc)
    mine = {"$or": [
        {"assigned_staff_id": user["id"]},
        {"assigned_provider_id": user["id"]},
    ]}
    open_states = {"status": {"$in": ["new", "in_progress", "waiting"]}}
    mine_open = {**mine, **open_states}
    return {
        "my_tasks": await db.internal_tasks.count_documents(mine_open),
        "overdue": await db.internal_tasks.count_documents({
            **mine_open, "due_date": {"$lt": now}
        }),
        "due_today": await db.internal_tasks.count_documents({
            **mine_open, "due_date": {"$gte": now, "$lte": today_end}
        }),
        "waiting": await db.internal_tasks.count_documents({
            **mine, "status": "waiting"
        }),
    }


@api.get("/tasks/{task_id}")
async def get_task(task_id: str, user=Depends(require_roles(*WORKFORCE))):
    t = await db.internal_tasks.find_one({"id": task_id})
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    return _strip_id(t)


@api.patch("/tasks/{task_id}")
async def patch_task(task_id: str, payload: TaskPatch, request: Request,
                     user=Depends(require_roles(*WORKFORCE))):
    t = await db.internal_tasks.find_one({"id": task_id})
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    updates: dict = {}
    events: list = []
    now = datetime.now(timezone.utc)
    actor_name = user.get("full_name") or user.get("email")

    if payload.title is not None:
        updates["title"] = payload.title
    if payload.description is not None:
        updates["description"] = payload.description
    if payload.due_date is not None:
        updates["due_date"] = payload.due_date
    if payload.category is not None:
        _validate_enum(payload.category, TASK_CATEGORIES, "category")
        updates["category"] = payload.category
    if payload.priority is not None:
        _validate_enum(payload.priority, TASK_PRIORITIES, "priority")
        if payload.priority != t.get("priority"):
            events.append({"event": "priority_changed", "from": t.get("priority"),
                           "to": payload.priority, "actor_id": user["id"],
                           "actor_name": actor_name, "ts": now})
        updates["priority"] = payload.priority
    if payload.status is not None:
        _validate_enum(payload.status, TASK_STATUSES, "status")
        if payload.status != t.get("status"):
            events.append({"event": "status_changed", "from": t.get("status"),
                           "to": payload.status, "actor_id": user["id"],
                           "actor_name": actor_name, "ts": now})
            updates["status"] = payload.status
            if payload.status == "completed":
                updates["completed_by"] = user["id"]
                updates["completed_by_name"] = actor_name
                updates["completed_at"] = now
    if payload.assigned_staff_id is not None and payload.assigned_staff_id != t.get("assigned_staff_id"):
        updates["assigned_staff_id"] = payload.assigned_staff_id or None
        updates["assigned_staff_name"] = await _resolve_name(payload.assigned_staff_id)
        events.append({"event": "reassigned_staff", "from": t.get("assigned_staff_id"),
                       "to": payload.assigned_staff_id, "actor_id": user["id"],
                       "actor_name": actor_name, "ts": now})
    if payload.assigned_provider_id is not None and payload.assigned_provider_id != t.get("assigned_provider_id"):
        updates["assigned_provider_id"] = payload.assigned_provider_id or None
        updates["assigned_provider_name"] = await _resolve_name(payload.assigned_provider_id)
        events.append({"event": "reassigned_provider", "from": t.get("assigned_provider_id"),
                       "to": payload.assigned_provider_id, "actor_id": user["id"],
                       "actor_name": actor_name, "ts": now})
    if payload.add_note:
        note = {"body": payload.add_note[:1000].strip(),
                "actor_id": user["id"], "actor_name": actor_name, "ts": now}
        await db.internal_tasks.update_one({"id": task_id},
                                            {"$push": {"internal_notes": note}})
        events.append({"event": "note_added", "actor_id": user["id"],
                       "actor_name": actor_name, "ts": now})

    if updates or events:
        updates["updated_at"] = now
        op = {"$set": updates}
        if events:
            op["$push"] = {"history": {"$each": events}}
        await db.internal_tasks.update_one({"id": task_id}, op)
    await log_audit(db, user["id"], user["email"], "task.update",
                    resource_type="task", resource_id=task_id,
                    metadata={"fields": list(updates.keys())},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    t = await db.internal_tasks.find_one({"id": task_id})
    return _strip_id(t)


@api.delete("/tasks/{task_id}")
async def delete_task(task_id: str, request: Request,
                      user=Depends(require_roles("admin", "practitioner"))):
    t = await db.internal_tasks.find_one({"id": task_id})
    if not t:
        return {"ok": True}
    await db.internal_tasks.delete_one({"id": task_id})
    await log_audit(db, user["id"], user["email"], "task.delete",
                    resource_type="task", resource_id=task_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}
