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

def _parse_lab_report_date(value):
    """Best-effort date parser for AI-extracted report dates."""
    if value in (None, ""):
        return None

    raw = str(value).strip()

    for fmt in (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y/%m/%d",
        "%m-%d-%Y",
        "%m-%d-%y",
    ):
        try:
            parsed = datetime.strptime(raw[:10], fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    try:
        parsed = datetime.fromisoformat(
            raw.replace("Z", "+00:00")
        )
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _lab_report_to_dict(report) -> dict:
    """Serialize a SQLAlchemy LabReport row for API responses."""
    payload = dict(report.payload or {})

    output = {
        "id": report.id,
        "client_id": report.client_id,
        "original_file_id": report.original_file_id,
        "source_filename": report.source_filename,
        "mime_type": report.mime_type,
        "report_title": report.report_title,
        "laboratory_name": report.laboratory_name,
        "patient_name_on_report": report.patient_name_on_report,
        "patient_dob_on_report": report.patient_dob_on_report,
        "ordering_provider": report.ordering_provider,
        "accession_number": report.accession_number,
        "collection_date": report.collection_date,
        "reported_date": report.reported_date,
        "review_status": report.review_status,
        "assigned_provider_id": report.assigned_provider_id,
        "assigned_provider_name": report.assigned_provider_name,
        "review_priority": report.review_priority,
        "review_due_date": report.review_due_date,
        "document_confidence": report.document_confidence,
        "verified": report.verified,
        "released_to_patient": report.released_to_patient,
        "approved_by": report.approved_by,
        "approved_at": report.approved_at,
        "rejected_by": report.rejected_by,
        "rejected_at": report.rejected_at,
        "created_by": report.created_by,
        "created_by_name": report.created_by_name,
        "created_at": report.created_at,
        "updated_at": report.updated_at,
    }

    output.update(payload)
    return output


REVIEW_STATUSES = (
    "new",
    "ai_transcribed",
    "pending_assignment",
    "assigned_for_review",
    "provider_reviewing",
    "needs_correction",
    "approved",
    "rejected",
    "patient_notified",
    "follow_up_needed",
)


class ReviewPatch(BaseModel):
    review_status: str
    review_notes: Optional[str] = Field(default=None, max_length=1000)
    ordering_provider_id: Optional[str] = None


class LabAssignIn(BaseModel):
    client_id: Optional[str] = None
    assigned_provider_id: str
    priority: str = "normal"
    due_date: Optional[datetime] = None
    assignment_note: Optional[str] = Field(default=None, max_length=1000)


class LabProviderReviewIn(BaseModel):
    review_notes: Optional[str] = Field(default=None, max_length=4000)
    patient_summary: Optional[str] = Field(default=None, max_length=4000)
    release_to_patient: bool = True
    notify_patient: bool = True


class LabRejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)
    needs_correction: bool = False


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


@api.post("/labs/process-file/{file_id}")
async def process_lab_report_file(
    file_id: str,
    request: Request,
    user=Depends(
        require_roles(
            "practitioner",
            "admin",
            "medical_assistant",
            "staff",
        )
    ),
):
    """Convert a clean secure-vault file into an unverified LabReport.

    This endpoint never creates patient-visible LabValue rows.
    """
    file_meta = await db.files.find_one({
        "id": file_id,
        "deleted_at": None,
    })

    if not file_meta:
        raise HTTPException(
            status_code=404,
            detail="File not found",
        )

    if file_meta.get("category") != "lab":
        raise HTTPException(
            status_code=400,
            detail={
                "code": "not_a_lab_file",
                "message": (
                    "Upload the document with category=lab before "
                    "processing it as a lab report."
                ),
            },
        )

    scan_status = str(
        file_meta.get("scan_status") or "pending"
    ).lower()

    if scan_status == "pending":
        raise HTTPException(
            status_code=425,
            detail={
                "code": "scan_pending",
                "message": "The file is awaiting malware scanning.",
            },
        )

    if scan_status == "infected":
        raise HTTPException(
            status_code=451,
            detail={
                "code": "file_quarantined",
                "message": "The file is quarantined.",
            },
        )

    if scan_status == "error":
        raise HTTPException(
            status_code=503,
            detail={
                "code": "scan_error",
                "message": "The malware scan did not complete.",
            },
        )

    if scan_status != "clean":
        raise HTTPException(
            status_code=403,
            detail="The file is not available for processing.",
        )

    client_id = file_meta.get("client_id")

    if client_id:
        client = await find_client(client_id=client_id)
        if not client:
            raise HTTPException(
                status_code=404,
                detail="Assigned patient was not found.",
            )

    from sqlalchemy import select
    from postgres_db import AsyncSessionLocal
    from postgres_models import LabReport

    # Idempotency: the same uploaded file creates only one LabReport.
    async with AsyncSessionLocal() as pg:
        existing = (
            await pg.execute(
                select(LabReport).where(
                    LabReport.original_file_id == file_id
                )
            )
        ).scalar_one_or_none()

    if existing:
        return _lab_report_to_dict(existing)

    storage_key = file_meta.get("storage_key")

    if not storage_key:
        raise HTTPException(
            status_code=410,
            detail={
                "code": "storage_not_migrated",
                "message": (
                    "This file does not have a supported secure-storage key."
                ),
            },
        )

    from storage import get_storage

    try:
        content = await get_storage().get_bytes(storage_key)
    except Exception as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "stored_file_missing",
                "message": "The uploaded file could not be retrieved.",
            },
        ) from exc

    from services.document_text import extract_document_text

    extracted_text = extract_document_text(
        file_meta.get("filename") or "lab-report",
        content,
    )

    if len(extracted_text.strip()) < 30:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "ocr_required",
                "message": (
                    "The report contains too little readable text. "
                    "It may be scanned and require OCR."
                ),
            },
        )

    from services.lab_ai import transcribe_lab_report

    extraction = await transcribe_lab_report(
        extracted_text=extracted_text,
        source_filename=(
            file_meta.get("filename") or "lab-report"
        ),
        session_id=f"lab-report-{file_id[:16]}",
    )

    now = datetime.now(timezone.utc)
    report_id = new_id()

    payload = {
        "raw_extracted_text": extraction.get(
            "raw_extracted_text",
            "",
        ),
        "full_report_text": extraction.get(
            "full_report_text",
            "",
        ),
        "report_sections": extraction.get(
            "report_sections",
            [],
        ),
        "results": extraction.get("results", []),
        "critical_or_abnormal_text": extraction.get(
            "critical_or_abnormal_text",
            [],
        ),
        "unparsed_lines": extraction.get(
            "unparsed_lines",
            [],
        ),
        "warnings": extraction.get("warnings", []),
        "provider_review_required": True,
        "extraction_status": "ai_transcribed",
        "extracted_at": extraction.get("extracted_at"),
        "source_file": {
            "id": file_id,
            "filename": file_meta.get("filename"),
            "sha256": file_meta.get("sha256"),
            "size": file_meta.get("size"),
            "mime": file_meta.get("mime"),
        },
        "review_history": [
            {
                "event": "ai_transcribed",
                "actor_id": user["id"],
                "actor_name": (
                    user.get("full_name") or user.get("email")
                ),
                "result_count": len(
                    extraction.get("results") or []
                ),
                "ts": now.isoformat(),
            }
        ],
    }

    report = LabReport(
        id=report_id,
        client_id=client_id,
        original_file_id=file_id,
        source_filename=file_meta.get("filename"),
        mime_type=file_meta.get("mime"),
        report_title=extraction.get("report_title"),
        laboratory_name=extraction.get("laboratory_name"),
        patient_name_on_report=extraction.get(
            "patient_name_on_report"
        ),
        patient_dob_on_report=extraction.get(
            "patient_dob_on_report"
        ),
        ordering_provider=extraction.get("ordering_provider"),
        accession_number=extraction.get("accession_number"),
        collection_date=_parse_lab_report_date(
            extraction.get("collection_date")
        ),
        reported_date=_parse_lab_report_date(
            extraction.get("reported_date")
        ),
        review_status="pending_assignment",
        document_confidence=extraction.get(
            "document_confidence"
        ),
        verified=False,
        released_to_patient=False,
        created_by=user["id"],
        created_by_name=(
            user.get("full_name") or user.get("email")
        ),
        created_at=now,
        updated_at=now,
        payload=payload,
    )

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            pg.add(report)

    await log_audit(
        db,
        user["id"],
        user["email"],
        "lab_report.ai_transcribed",
        resource_type="lab_report",
        resource_id=report_id,
        metadata={
            "file_id": file_id,
            "client_id": client_id,
            "result_count": len(
                extraction.get("results") or []
            ),
            "document_confidence": extraction.get(
                "document_confidence"
            ),
            # Do not store extracted report text in audit metadata.
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return _lab_report_to_dict(report)


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

    # Providers default to their own assigned queue. Admin and delegated
    # clinical support roles may see the broader routing queue.
    if user.get("role") == "practitioner":
        q["$or"] = [
            {"assigned_provider_id": user["id"]},
            {
                "assigned_provider_id": {"$exists": False},
                "ordering_provider_id": user["id"],
            },
        ]

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


@api.put("/labs/{lab_id}/assign")
async def assign_lab_for_review(
    lab_id: str,
    payload: LabAssignIn,
    request: Request,
    user=Depends(
        require_roles(
            "practitioner",
            "admin",
            "medical_assistant",
            "staff",
        )
    ),
):
    """Assign an uploaded or transcribed lab to a provider review queue."""
    lab = await db.lab_values.find_one({"id": lab_id})

    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")

    provider = await find_user_by_id(payload.assigned_provider_id)

    if (
        not provider
        or provider.get("role") != "practitioner"
        or not provider.get("is_active", True)
    ):
        raise HTTPException(
            status_code=400,
            detail="Select an active practitioner.",
        )

    client_id = payload.client_id or lab.get("client_id")

    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="A patient must be assigned before provider review.",
        )

    client = await find_client(client_id=client_id)

    if not client:
        raise HTTPException(status_code=404, detail="Patient not found")

    now = datetime.now(timezone.utc)
    actor_name = user.get("full_name") or user.get("email")

    updates = {
        "client_id": client_id,
        "assigned_provider_id": provider["id"],
        "assigned_provider_name": (
            provider.get("full_name") or provider.get("email")
        ),
        "review_status": "assigned_for_review",
        "review_priority": payload.priority,
        "review_due_date": payload.due_date,
        "assignment_note": (
            payload.assignment_note or ""
        ).strip() or None,
        "assigned_at": now,
        "assigned_by": user["id"],
        "assigned_by_name": actor_name,
        "review_status_updated_at": now,
        "review_status_updated_by": user["id"],
    }

    history_event = {
        "event": "assigned_for_review",
        "actor_id": user["id"],
        "actor_name": actor_name,
        "provider_id": provider["id"],
        "provider_name": updates["assigned_provider_name"],
        "client_id": client_id,
        "priority": payload.priority,
        "ts": now,
    }

    await db.lab_values.update_one(
        {"id": lab_id},
        {
            "$set": updates,
            "$push": {"review_history": history_event},
        },
    )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "lab.assigned_for_review",
        resource_type="lab",
        resource_id=lab_id,
        metadata={
            "client_id": client_id,
            "assigned_provider_id": provider["id"],
            "priority": payload.priority,
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    updated = await db.lab_values.find_one({"id": lab_id})
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


@api.post("/labs/{lab_id}/approve")
async def approve_lab_for_patient(
    lab_id: str,
    payload: LabProviderReviewIn,
    request: Request,
    user=Depends(require_roles("practitioner")),
):
    """Approve a reviewed lab for the patient chart.

    AI transcription remains unverified until this endpoint is completed
    by the assigned practitioner.
    """
    lab = await db.lab_values.find_one({"id": lab_id})

    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")

    assigned_provider_id = (
        lab.get("assigned_provider_id")
        or lab.get("ordering_provider_id")
    )

    if assigned_provider_id and assigned_provider_id != user["id"]:
        raise HTTPException(
            status_code=403,
            detail="Only the assigned provider may approve this lab.",
        )

    client_id = lab.get("client_id")

    if not client_id:
        raise HTTPException(
            status_code=409,
            detail="Assign this report to a patient before approval.",
        )

    client = await find_client(client_id=client_id)

    if not client:
        raise HTTPException(status_code=404, detail="Patient not found")

    now = datetime.now(timezone.utc)
    actor_name = user.get("full_name") or user.get("email")

    updates = {
        "review_status": "approved",
        "verified": True,
        "approved_by": user["id"],
        "approved_by_name": actor_name,
        "approved_at": now,
        "reviewed_by": user["id"],
        "reviewed_by_name": actor_name,
        "reviewed_at": now,
        "provider_review_notes": (
            payload.review_notes or ""
        ).strip() or None,
        "patient_summary": (
            payload.patient_summary or ""
        ).strip() or None,
        "released_to_patient": bool(payload.release_to_patient),
        "released_to_patient_at": (
            now if payload.release_to_patient else None
        ),
        "review_status_updated_at": now,
        "review_status_updated_by": user["id"],
    }

    history_event = {
        "event": "approved",
        "actor_id": user["id"],
        "actor_name": actor_name,
        "client_id": client_id,
        "released_to_patient": bool(payload.release_to_patient),
        "ts": now,
    }

    await db.lab_values.update_one(
        {"id": lab_id},
        {
            "$set": updates,
            "$push": {"review_history": history_event},
        },
    )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "lab.approved",
        resource_type="lab",
        resource_id=lab_id,
        severity="high",
        outcome="success",
        metadata={
            "client_id": client_id,
            "released_to_patient": bool(payload.release_to_patient),
            "attachment_count": len(
                lab.get("attachment_file_ids") or []
            ),
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    # Patient notification must remain generic and contain no lab values.
    if payload.release_to_patient and payload.notify_patient:
        try:
            from notifiers import send_generic_portal_update_email

            patient_user = None
            if client.get("user_id"):
                patient_user = await find_user_by_id(client["user_id"])

            if patient_user and patient_user.get("email"):
                await send_generic_portal_update_email(
                    db,
                    patient_user["email"],
                    first_name=(
                        patient_user.get("full_name") or ""
                    ).split(" ")[0] or None,
                    subject="A new portal update is available",
                    heading="New information is available in your portal",
                    message=(
                        "Your care team has added new information to "
                        "your secure patient portal."
                    ),
                    portal_path="/portal/patient/labs",
                )
        except Exception:
            # Notification failure must not roll back clinical approval.
            pass

    updated = await db.lab_values.find_one({"id": lab_id})
    return _strip_id(updated)


@api.post("/labs/{lab_id}/reject")
async def reject_lab_report(
    lab_id: str,
    payload: LabRejectIn,
    request: Request,
    user=Depends(require_roles("practitioner")),
):
    lab = await db.lab_values.find_one({"id": lab_id})

    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")

    assigned_provider_id = (
        lab.get("assigned_provider_id")
        or lab.get("ordering_provider_id")
    )

    if assigned_provider_id and assigned_provider_id != user["id"]:
        raise HTTPException(
            status_code=403,
            detail="Only the assigned provider may reject this lab.",
        )

    now = datetime.now(timezone.utc)
    actor_name = user.get("full_name") or user.get("email")
    status = (
        "needs_correction"
        if payload.needs_correction
        else "rejected"
    )

    await db.lab_values.update_one(
        {"id": lab_id},
        {
            "$set": {
                "review_status": status,
                "verified": False,
                "rejection_reason": payload.reason.strip(),
                "rejected_by": user["id"],
                "rejected_by_name": actor_name,
                "rejected_at": now,
                "released_to_patient": False,
                "review_status_updated_at": now,
                "review_status_updated_by": user["id"],
            },
            "$push": {
                "review_history": {
                    "event": status,
                    "actor_id": user["id"],
                    "actor_name": actor_name,
                    "reason": payload.reason.strip()[:500],
                    "ts": now,
                }
            },
        },
    )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "lab.rejected",
        resource_type="lab",
        resource_id=lab_id,
        severity="high",
        outcome="success",
        metadata={
            "client_id": lab.get("client_id"),
            "status": status,
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    updated = await db.lab_values.find_one({"id": lab_id})
    return _strip_id(updated)


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
