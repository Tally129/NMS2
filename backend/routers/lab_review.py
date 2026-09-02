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
from pg_shims import find_client, find_user_by_id

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
        client = await find_client(client_id=r.get("client_id"))
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
        prov = await find_user_by_id(payload.ordering_provider_id)
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

    client = await find_client(client_id=lab.get("client_id"))
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
            u = await find_user_by_id(uid)
            if u:
                task[name_key] = u.get("full_name") or u.get("email")
    await db.internal_tasks.insert_one(task)
    await log_audit(db, user["id"], user["email"], "lab.task_created",
                    resource_type="task", resource_id=task["id"],
                    metadata={"lab_id": lab_id, "client_id": lab.get("client_id")},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(task)



# =============================================================================
#  AI Lab Review — draft only. NEVER saves, notifies, or changes lab status.
# =============================================================================
#
# Design goals:
#   * One Bedrock call per request, routed through `llm_client.complete_text`.
#     No provider fallback, no per-feature Bedrock client.
#   * Central authorization function `_ai_lab_reviewer` so future role-based
#     restrictions or delegation checks can be added in ONE place without
#     touching the endpoint body.
#   * Minimum-necessary context: this lab + up to five prior values of the
#     same test + the client's allergies / supplements / age / sex only.
#     Names, addresses, phone numbers, insurance, billing, unrelated notes
#     are never sent to Bedrock.
#   * Strict JSON output envelope with the mandatory disclaimer and
#     `provider_review_required=True`. Existing review-note workflow performs
#     any save; this endpoint returns a draft.

from llm_client import PromptTemplate, run_template, safe_extract_json  # noqa: E402


_LAB_AI_REVIEWER_ROLES = tuple(sorted({
    "practitioner", "admin", "medical_assistant",
    "staff", "front_desk", "frontdesk", "auditor",
}))


def _ai_lab_reviewer():
    """Central dependency for AI lab-review access.

    Sprint 9 allows every authenticated workforce role. Tightening the
    permission (e.g. clinical-only, delegation-required) later means editing
    this single function — no endpoint body changes.
    """
    return require_roles(*_LAB_AI_REVIEWER_ROLES)


LAB_AI_TEMPLATE = PromptTemplate(
    feature="lab_review",
    system=(
        "You are a clinical documentation assistant helping a licensed "
        "provider draft a lab review note in a wellness / functional "
        "medicine setting. You never diagnose, prescribe, discontinue, or "
        "change treatment. Every draft is provisional and must be reviewed "
        "by the provider.\n\n"
        "Return STRICT JSON only — no prose, no markdown fences — matching "
        "this schema exactly:\n"
        "{\n"
        '  "summary": "",\n'
        '  "abnormal_findings": [\n'
        '    {"test":"","value":"","reference_range":"","interpretation":""}\n'
        "  ],\n"
        '  "trends": [\n'
        '    {"test":"","direction":"increasing|decreasing|stable|insufficient_data","explanation":""}\n'
        "  ],\n"
        '  "clinical_considerations": [],\n'
        '  "patient_friendly_explanation": "",\n'
        '  "suggested_follow_up_questions": [],\n'
        '  "limitations": [],\n'
        '  "provider_review_required": true\n'
        "}\n\n"
        "Frame every item in `clinical_considerations` as a question or "
        "topic for the provider to consider — never as instructions, "
        "orders, or definitive recommendations. Do not invent lab values "
        "you were not given."
    ),
    max_tokens=2048,
    temperature=0.1,
)


LAB_AI_DISCLAIMER = (
    "AI-generated draft. Provider review and clinical judgment are required."
)


def _compute_age_years(dob: Optional[str]) -> Optional[int]:
    """Best-effort age from YYYY-MM-DD string. Returns None on any parse
    failure so the AI never receives a bogus number."""
    if not dob or not isinstance(dob, str):
        return None
    try:
        birth = datetime.strptime(dob[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    today = datetime.now(timezone.utc).date()
    years = today.year - birth.year - (
        (today.month, today.day) < (birth.month, birth.day)
    )
    return years if 0 < years < 130 else None


def _format_reference_range(lab: dict) -> str:
    lo = lab.get("reference_low")
    hi = lab.get("reference_high")
    if lo is None and hi is None:
        return "not specified"
    return f"{lo if lo is not None else '?'} – {hi if hi is not None else '?'}"


def _abnormal_flag(lab: dict) -> str:
    """Derive high/low/normal without depending on a stored flag."""
    try:
        v = float(lab.get("value"))
    except (TypeError, ValueError):
        return "unknown"
    lo = lab.get("reference_low")
    hi = lab.get("reference_high")
    if lo is not None and v < float(lo):
        return "low"
    if hi is not None and v > float(hi):
        return "high"
    return "normal"


def _build_lab_ai_prompt(lab: dict, client: dict, history: list[dict]) -> str:
    """Assemble the minimum-necessary user prompt sent to Bedrock.

    Pseudonymises the patient with the internal `client_id`. Never includes
    names, contact info, address, insurance, billing, or unrelated chart
    entries. Callers that add fields here MUST review this rule."""
    parts: list[str] = []
    parts.append(
        f"Patient reference: {client.get('id', 'unknown')} (internal id "
        "— do not attempt to identify the patient)."
    )
    age = _compute_age_years(client.get("dob"))
    if age is not None:
        parts.append(f"Age: {age}")
    if client.get("sex"):
        parts.append(f"Sex: {client['sex']}")
    if client.get("allergies"):
        parts.append(f"Allergies: {client['allergies']}")
    if client.get("current_supplements"):
        parts.append(f"Current supplements: {client['current_supplements']}")

    parts.append("")
    parts.append("Selected lab result:")
    parts.append(f"- Test: {lab.get('test_name', 'unknown')}")
    parts.append(
        f"- Value: {lab.get('value')} "
        f"{(lab.get('unit') or '').strip()}".rstrip()
    )
    parts.append(f"- Reference range: {_format_reference_range(lab)}")
    parts.append(f"- Abnormal flag: {_abnormal_flag(lab)}")
    parts.append(
        f"- Collection date: {(lab.get('measured_at') or '').isoformat() if hasattr(lab.get('measured_at'), 'isoformat') else lab.get('measured_at') or 'unknown'}"
    )

    if history:
        parts.append("")
        parts.append(
            "Previous values for the same test (most recent first, "
            f"up to {len(history)}):"
        )
        for h in history:
            when = h.get("measured_at")
            when_s = when.isoformat() if hasattr(when, "isoformat") else str(when or "")
            parts.append(
                f"- {when_s[:10]}: {h.get('value')} "
                f"{(h.get('unit') or '').strip()}".rstrip()
            )

    parts.append("")
    parts.append("Return the JSON draft now.")
    return "\n".join(parts)


def _validate_lab_ai_response(data: Optional[dict]) -> dict:
    """Coerce Bedrock output onto the strict envelope. Missing fields are
    replaced with safe defaults; extraneous top-level keys are dropped so no
    unexpected content is echoed back to the frontend."""
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail={
            "code": "invalid_model_response",
            "message": "AI draft could not be parsed.",
        })

    def _str_list(val) -> list[str]:
        if not isinstance(val, list):
            return []
        return [str(x).strip()[:500] for x in val if isinstance(x, (str, int, float))]

    findings = []
    for row in (data.get("abnormal_findings") or []):
        if not isinstance(row, dict):
            continue
        findings.append({
            "test": str(row.get("test") or "")[:200],
            "value": str(row.get("value") or "")[:120],
            "reference_range": str(row.get("reference_range") or "")[:120],
            "interpretation": str(row.get("interpretation") or "")[:800],
        })

    trends = []
    for row in (data.get("trends") or []):
        if not isinstance(row, dict):
            continue
        direction = str(row.get("direction") or "").lower().strip()
        if direction not in {"increasing", "decreasing", "stable", "insufficient_data"}:
            direction = "insufficient_data"
        trends.append({
            "test": str(row.get("test") or "")[:200],
            "direction": direction,
            "explanation": str(row.get("explanation") or "")[:800],
        })

    return {
        "summary": str(data.get("summary") or "")[:2000],
        "abnormal_findings": findings,
        "trends": trends,
        "clinical_considerations": _str_list(data.get("clinical_considerations")),
        "patient_friendly_explanation": str(
            data.get("patient_friendly_explanation") or ""
        )[:2000],
        "suggested_follow_up_questions": _str_list(
            data.get("suggested_follow_up_questions")
        ),
        "limitations": _str_list(data.get("limitations")),
        # Always true regardless of what the model says. Guardrail.
        "provider_review_required": True,
    }


@api.post("/labs/{lab_id}/ai-review")
async def ai_lab_review_draft(lab_id: str, request: Request,
                              user=Depends(_ai_lab_reviewer())):
    """Generate an AI draft note for a single lab result.

    Draft-only. Never modifies the lab record, review status, chart, or
    patient. The existing review-note workflow performs any save.
    """
    lab = await db.lab_values.find_one({"id": lab_id})
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")

    client = await find_client(client_id=lab.get("client_id"))
    if client:
        # Minimum-necessary projection — no name, phone, email, address,
        # insurance, notes, or unrelated chart data.
        client = {k: v for k, v in client.items() if k in
                  {"id", "dob", "sex", "allergies", "current_supplements"}}
    else:
        client = {"id": lab.get("client_id")}

    # Up to five prior values for the SAME test only.
    history_cursor = db.lab_values.find(
        {
            "client_id": lab.get("client_id"),
            "test_name": lab.get("test_name"),
            "id": {"$ne": lab_id},
        },
        {"value": 1, "unit": 1, "measured_at": 1},
    ).sort("measured_at", -1).limit(5)
    history = await history_cursor.to_list(5)

    user_prompt = _build_lab_ai_prompt(lab, client, history)

    started = datetime.now(timezone.utc)
    try:
        raw = await run_template(LAB_AI_TEMPLATE, user_prompt,
                                 session_id=f"lab_review.{lab_id}")
    except RuntimeError as exc:
        # Safe categories from llm_client — never expose AWS internals.
        code = str(exc)
        status = 503 if code in {
            "ai_disabled", "bedrock_misconfigured", "bedrock_unavailable",
            "model_access_denied", "request_timeout",
        } else 502
        raise HTTPException(status_code=status, detail={"code": code})

    payload = _validate_lab_ai_response(safe_extract_json(raw))
    payload["disclaimer"] = LAB_AI_DISCLAIMER
    payload["provider_review_required"] = True
    latency_ms = int(
        (datetime.now(timezone.utc) - started).total_seconds() * 1000
    )

    # Safe audit metadata: never store the prompt, response, or PHI.
    await log_audit(
        db, user["id"], user["email"], "lab.ai_draft_generated",
        resource_type="lab", resource_id=lab_id,
        metadata={
            "feature": "lab_review",
            "client_id": lab.get("client_id"),
            "test_name": lab.get("test_name"),
            "latency_ms": latency_ms,
            "history_size": len(history),
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return payload
