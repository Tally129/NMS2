"""
Clients + Intake + SOAP Notes + Files + Supplement assignments.

Extracted from server.py during Phase 16 refactor.
"""
from __future__ import annotations

import io
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from fastapi import Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from audit import get_client_ip, log_audit
from delegations import has_active_delegation
from notifiers import push_to_user
from deps import (
    _resolve_self_client, _strip_id, api, db,
    get_current_user, require_roles,
)
from storage import NotFound as StorageNotFound, get_storage
from models import (
    AmendIn, ClientIn, ClientOut, FileMetaOut, IntakeIn, IntakeOut,
    NoteIn, NoteOut, VitalIn, VitalOut, VitalUpdate, new_id,
)
from pg_shims import (
    delete_client as _pg_delete_client, find_active_assignment,
    find_assignment, find_client, find_intake_by_client,
    find_supplement_sheet, find_user_by_id, find_clients_by_ids,
    insert_assignment, insert_client, list_active_assignments_for_client,
    list_active_supplement_sheets, list_clients, list_clients_paginated, touch_assignment_reference,
    update_client as _pg_update_client, upsert_intake, deactivate_assignment,
)
from postgres_db import AsyncSessionLocal
from repositories import clinical_and_messaging as cm_repo
from repositories import scheduling as sched_repo
from repositories import vitals as vitals_repo

logger = logging.getLogger("nms.clients")


async def _fetch_note(note_id: str):
    async with AsyncSessionLocal() as pg:
        return await cm_repo.get_note(pg, note_id)


async def _fetch_notes_for_client(client_id: str):
    async with AsyncSessionLocal() as pg:
        return await cm_repo.list_notes_for_client(pg, client_id, limit=500)


# =================== CLIENTS ===================
@api.get("/clients")
async def list_clients_endpoint(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    q: Optional[str] = Query(default=None, max_length=120),
    sort_by: str = Query(
        default="created_at",
        pattern="^(created_at|full_name|mrn|dob)$",
    ),
    sort_dir: str = Query(
        default="desc",
        pattern="^(asc|desc)$",
    ),
    user=Depends(
        require_roles(
            "admin",
            "practitioner",
            "staff",
            "medical_assistant",
            "front_desk",
            "frontdesk",
        )
    ),
):
    result = await list_clients_paginated(
        page=page,
        page_size=page_size,
        q=q,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )

    return {
        **result,
        "items": [
            _strip_id(item)
            for item in result["items"]
        ],
    }


@api.get("/clients/me", response_model=ClientOut)
async def my_client_record(user=Depends(get_current_user)):
    c = await _resolve_self_client(user)
    if not c:
        raise HTTPException(status_code=404, detail="No client record")
    return _strip_id(c)


@api.get("/clients/{client_id}", response_model=ClientOut)
async def get_client(client_id: str, request: Request, user=Depends(get_current_user)):
    c = await find_client(client_id=client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Patient not found")
    role = user.get("role") or ""

    # Patients may only view their own client record. Authorized workforce
    # roles may view all patient charts as part of clinic operations.
    if role == "client":
        if c.get("user_id") != user["id"]:
            raise HTTPException(
                status_code=403,
                detail="Forbidden",
            )
    elif role not in {
        "admin",
        "practitioner",
        "medical_assistant",
        "staff",
    }:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "scope_denied",
                "resource": "client",
                "id": client_id,
            },
        )

    # admin / auditor / staff pass through (admin=full, auditor=break-glass GET
    # already gated by require_roles elsewhere; staff have client:list not read_any
    # but need patient demographics for scheduling — allowed here).
    await log_audit(db, user["id"], user["email"], "client.read",
                    resource_type="client", resource_id=client_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(c)


@api.post("/clients", response_model=ClientOut)
async def create_client(payload: ClientIn, request: Request,
                        user=Depends(require_roles("admin", "staff", "practitioner"))):
    doc = payload.dict()
    doc["id"] = new_id()
    doc["intake_completed"] = False
    doc["created_at"] = datetime.now(timezone.utc)
    # Auto-generate MRN if not provided: NMS- + 6-char hex
    if not doc.get("mrn"):
        doc["mrn"] = f"NMS-{doc['id'][:6].upper()}"
    await insert_client(doc)
    await log_audit(db, user["id"], user["email"], "client.create",
                    resource_type="client", resource_id=doc["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(doc)


@api.put("/clients/{client_id}", response_model=ClientOut)
async def update_client(client_id: str, payload: ClientIn, request: Request,
                        user=Depends(require_roles("admin", "staff", "practitioner"))):
    c = await find_client(client_id=client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Patient not found")
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    await _pg_update_client(client_id, updates)
    await log_audit(db, user["id"], user["email"], "client.update",
                    resource_type="client", resource_id=client_id,
                    metadata={"fields": list(updates.keys())},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    c = await find_client(client_id=client_id)
    return _strip_id(c)


# =================== INTAKE ===================
@api.post("/intake", response_model=IntakeOut)
async def save_intake(payload: IntakeIn, request: Request, user=Depends(get_current_user)):
    if user["role"] == "client":
        target_client = await _resolve_self_client(user)
        if not target_client:
            raise HTTPException(status_code=404, detail="Patient record missing")
        client_id = target_client["id"]
    else:
        if not payload.client_id:
            raise HTTPException(status_code=400, detail="client_id required")
        target_client = await find_client(client_id=payload.client_id)
        if not target_client:
            raise HTTPException(status_code=404, detail="Patient not found")
        client_id = payload.client_id

    existing = await find_intake_by_client(client_id)
    data = payload.dict()
    data["client_id"] = client_id
    now = datetime.now(timezone.utc)
    data["signed_at"] = now if data.get("consent", {}).get("signed") else None

    if existing:
        data["id"] = existing["id"]
        data["created_at"] = existing.get("created_at", now)
        if payload.completed:
            data["completed_at"] = now
        await upsert_intake(intake_id=existing["id"], client_id=client_id, fields=data)
    else:
        data["id"] = new_id()
        data["created_at"] = now
        if payload.completed:
            data["completed_at"] = now
        await upsert_intake(intake_id=data["id"], client_id=client_id, fields=data)

    if payload.completed:
        await _pg_update_client(client_id, {"intake_completed": True})

    await log_audit(db, user["id"], user["email"], "intake.save",
                    resource_type="intake", resource_id=data["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(data)


@api.get("/intake/{client_id}")
async def get_intake(client_id: str, request: Request, user=Depends(get_current_user)):
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client or self_client["id"] != client_id:
            raise HTTPException(status_code=403, detail="Forbidden")
    intake = await find_intake_by_client(client_id)
    if not intake:
        return None
    await log_audit(db, user["id"], user["email"], "intake.read",
                    resource_type="intake", resource_id=intake["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(intake)


# =================== VITALS ===================
def _calculate_bmi(
    height_in: Optional[float],
    weight_lb: Optional[float],
) -> Optional[float]:
    if not height_in or not weight_lb:
        return None

    if height_in <= 0 or weight_lb <= 0:
        return None

    return round(
        (weight_lb / (height_in * height_in)) * 703,
        1,
    )


@api.get("/vitals", response_model=List[VitalOut])
async def list_vitals(
    request: Request,
    client_id: str = Query(...),
    appointment_id: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    user=Depends(
        require_roles(
            "admin",
            "practitioner",
            "medical_assistant",
        )
    ),
):
    client = await find_client(client_id=client_id)

    if not client:
        raise HTTPException(
            status_code=404,
            detail="Patient not found",
        )

    async with AsyncSessionLocal() as pg:
        rows = await vitals_repo.list_for_client(
            pg,
            client_id,
            appointment_id=appointment_id,
            limit=limit,
        )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "vitals.list",
        resource_type="client",
        resource_id=client_id,
        metadata={
            "appointment_id": appointment_id,
            "count": len(rows),
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return rows


@api.post("/vitals", response_model=VitalOut)
async def create_vitals(
    payload: VitalIn,
    request: Request,
    user=Depends(
        require_roles(
            "admin",
            "practitioner",
            "medical_assistant",
        )
    ),
):
    client = await find_client(
        client_id=payload.client_id
    )

    if not client:
        raise HTTPException(
            status_code=404,
            detail="Patient not found",
        )

    document = payload.dict()
    document["id"] = new_id()
    document["recorded_by_id"] = user["id"]
    document["recorded_by_name"] = (
        user.get("full_name") or user.get("email")
    )
    document["recorded_at"] = (
        payload.recorded_at
        or datetime.now(timezone.utc)
    )
    document["created_at"] = datetime.now(timezone.utc)
    document["bmi"] = _calculate_bmi(
        payload.height_in,
        payload.weight_lb,
    )
    document["prior_values"] = []

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            created = await vitals_repo.create(
                pg,
                document,
            )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "vitals.create",
        resource_type="vital_record",
        resource_id=created["id"],
        metadata={
            "client_id": payload.client_id,
            "appointment_id": payload.appointment_id,
            "source": payload.source,
            "visit_mode": payload.visit_mode,
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return created


@api.put("/vitals/{vital_id}", response_model=VitalOut)
async def amend_vitals(
    vital_id: str,
    payload: VitalUpdate,
    request: Request,
    user=Depends(
        require_roles(
            "admin",
            "practitioner",
            "medical_assistant",
        )
    ),
):
    async with AsyncSessionLocal() as pg:
        existing = await vitals_repo.get_by_id(
            pg,
            vital_id,
        )

    if not existing:
        raise HTTPException(
            status_code=404,
            detail="Vitals record not found",
        )

    updates = payload.dict(
        exclude={
            "amendment_reason",
        },
        exclude_unset=True,
    )

    height = updates.get(
        "height_in",
        existing.get("height_in"),
    )
    weight = updates.get(
        "weight_lb",
        existing.get("weight_lb"),
    )
    updates["bmi"] = _calculate_bmi(
        height,
        weight,
    )

    amended_by_name = (
        user.get("full_name") or user.get("email")
    )

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            amended = await vitals_repo.amend(
                pg,
                vital_id,
                fields=updates,
                amended_by_id=user["id"],
                amended_by_name=amended_by_name,
                amendment_reason=(
                    payload.amendment_reason.strip()
                ),
            )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "vitals.amend",
        resource_type="vital_record",
        resource_id=vital_id,
        severity="high",
        metadata={
            "client_id": existing["client_id"],
            "appointment_id": (
                existing.get("appointment_id")
            ),
            "fields": sorted(updates.keys()),
            "reason": payload.amendment_reason,
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return amended


# =================== SOAP NOTES ===================
@api.get("/notes", response_model=List[NoteOut])
async def list_notes(request: Request, client_id: str = Query(...),
                     user=Depends(get_current_user)):
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client or self_client["id"] != client_id:
            raise HTTPException(status_code=403, detail="Forbidden")
    items = await _fetch_notes_for_client(client_id)
    await log_audit(db, user["id"], user["email"], "note.list",
                    resource_type="client", resource_id=client_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return [_strip_id(i) for i in items]


@api.get("/notes/all", response_model=List[NoteOut])
async def list_all_notes(request: Request,
                         practitioner_id: Optional[str] = None,
                         search: Optional[str] = None,
                         limit: int = 200,
                         user=Depends(require_roles("admin", "practitioner", "staff", "medical_assistant"))):
    """Clinic-wide notes index for admin/practitioner/staff drill-down screens.
    Optional filters: practitioner_id (author), search (matches client_name)."""
    async with AsyncSessionLocal() as pg:
        if practitioner_id:
            rows = await cm_repo.list_notes_by_practitioner(pg, practitioner_id, limit=limit)
        else:
            from sqlalchemy import select
            from postgres_models.clinical_and_messaging import VisitNote
            stmt = select(VisitNote).order_by(VisitNote.created_at.desc()).limit(limit)
            rows = [cm_repo.note_to_dict(n)
                    for n in (await pg.execute(stmt)).scalars().all()]
    # Hydrate with client_name
    client_ids = list({r.get("client_id") for r in rows if r.get("client_id")})
    clients = {c["id"]: c for c in await find_clients_by_ids(client_ids)}
    out = []
    for r in rows:
        c = clients.get(r.get("client_id")) or {}
        cname = c.get("full_name") or c.get("email") or ""
        if search and search.lower() not in cname.lower():
            continue
        d = _strip_id(r)
        d["client_name"] = cname
        out.append(d)
    await log_audit(db, user["id"], user["email"], "note.list_all",
                    resource_type="notes",
                    metadata={"count": len(out)},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return out


@api.post("/notes/ai-draft")
async def create_ai_note_draft(
    payload: dict,
    request: Request,
    user=Depends(
        require_roles(
            "practitioner",
            "admin",
            "medical_assistant",
        )
    ),
):
    """Generate an editable SOAP draft without saving a clinical note."""
    client_id = str(payload.get("client_id") or "").strip()
    encounter_text = str(
        payload.get("encounter_text")
        or payload.get("encounter")
        or ""
    ).strip()
    template_id = str(payload.get("template_id") or "").strip() or None

    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="Patient is required",
        )

    if len(encounter_text) < 10:
        raise HTTPException(
            status_code=400,
            detail=(
                "Enter encounter notes or a transcript before "
                "generating a SOAP draft."
            ),
        )

    if len(encounter_text) > 12000:
        raise HTTPException(
            status_code=413,
            detail="Encounter notes are too long (12,000 characters max).",
        )

    client = await find_client(client_id=client_id)

    if not client:
        raise HTTPException(
            status_code=404,
            detail="Patient not found",
        )

    authorizing_provider_id = None

    # Keep the same delegation rules already used for clinical-note creation.
    if user.get("role") != "practitioner":
        delegation = await has_active_delegation(
            user,
            client_id,
        )

        if not delegation:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "delegation_required",
                    "message": (
                        "Provider authorization is required to use AI "
                        "for clinical documentation."
                    ),
                },
            )

        authorizing_provider_id = delegation.get("provider_id")

    intake = await find_intake_by_client(client_id) or {}

    async with AsyncSessionLocal() as pg:
        previous_notes = await cm_repo.list_notes_for_client(
            pg,
            client_id,
            limit=1,
        )

    last_note = previous_notes[0] if previous_notes else None

    template = None

    if template_id:
        template = await db.soap_templates.find_one({
            "id": template_id,
            "active": True,
        })

        if not template:
            raise HTTPException(
                status_code=404,
                detail="SOAP template not found",
            )

    from services.soap_ai import generate_soap_draft

    try:
        result = await generate_soap_draft(
            client=client,
            intake=intake,
            last_note=last_note,
            encounter_text=encounter_text,
            template=template,
            session_id=f"clinic-soap-{new_id()[:12]}",
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ai_unavailable",
                "message": str(exc),
            },
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "invalid_ai_response",
                "message": str(exc),
            },
        )
    except Exception as exc:
        logger.warning("Clinic SOAP AI draft failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "soap_ai_failed",
                "message": "SOAP drafting failed.",
            },
        )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "note.ai_draft_generated",
        resource_type="client",
        resource_id=client_id,
        metadata={
            "template_id": template_id,
            "actor_role": user.get("role"),
            "authorizing_provider_id": authorizing_provider_id,
            "source": result.get("source"),
            "model": result.get("model"),
            "encounter_character_count": len(encounter_text),
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return result


# =================== IN-PERSON CLINICAL SCRIBE ===================

@api.post("/notes/clinical-scribe/recording")
async def upload_clinical_scribe_recording(
    request: Request,
    file: UploadFile = File(...),
    client_id: str = Form(...),
    recording_consent: bool = Form(...),
    user=Depends(
        require_roles(
            "practitioner",
            "admin",
            "medical_assistant",
        )
    ),
):
    """Upload an in-person clinical recording and start HealthScribe.

    Patient identity remains inside NMS. HealthScribe receives only the
    clinical audio and an opaque internal job identifier.
    """
    if not recording_consent:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "recording_consent_required",
                "message": (
                    "Patient recording consent must be confirmed "
                    "before clinical audio is processed."
                ),
            },
        )

    client = await find_client(client_id=client_id)

    if not client:
        raise HTTPException(
            status_code=404,
            detail="Patient not found",
        )

    # Apply the same delegation rule used for clinical note creation.
    if user["role"] != "practitioner":
        delegation = await has_active_delegation(
            user,
            client_id,
        )

        if not delegation:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "delegation_required",
                    "message": (
                        "Provider authorization is required "
                        "to create clinical documentation."
                    ),
                },
            )

    contents = await file.read()

    if not contents:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "empty_recording",
            },
        )

    # Keep a reasonable hard ceiling on browser uploads.
    if len(contents) > 100 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "recording_too_large",
            },
        )

    from services.telehealth_transcription import (
        normalize_recording_to_flac,
        start_job,
    )

    from storage import get_storage

    recording_id = new_id()

    try:
        flac_contents = await normalize_recording_to_flac(
            contents
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "recording_normalization_failed",
                "message": str(exc),
            },
        )

    storage = get_storage()

    if getattr(storage, "backend_name", "") != "s3":
        raise HTTPException(
            status_code=503,
            detail={
                "code": "healthscribe_requires_s3",
            },
        )

    bucket = getattr(storage, "bucket", None)

    if not bucket:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "storage_bucket_unavailable",
            },
        )

    # Do not put patient names, email addresses, DOBs, etc.
    # into object keys or HealthScribe job names.
    storage_key = (
        f"visits/inperson-{client_id}/"
        f"{recording_id}.healthscribe.flac"
    )

    obj_meta = await storage.put_bytes(
        storage_key,
        flac_contents,
        content_type="audio/flac",
        metadata={
            "client_id": client_id,
            "uploader_id": user["id"],
            "kind": "in_person_clinical_scribe",
        },
    )

    media_uri = f"s3://{bucket}/{storage_key}"

    try:
        job = await start_job(
            appointment_id=f"inperson-{client_id}",
            recording_id=recording_id,
            media_s3_uri=media_uri,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": str(exc),
            },
        )
    except Exception as exc:
        logger.exception(
            "In-person HealthScribe start failed "
            "client=%s recording=%s: %s",
            client_id,
            recording_id,
            exc,
        )

        raise HTTPException(
            status_code=502,
            detail={
                "code": "healthscribe_start_failed",
            },
        )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "note.clinical_scribe_start",
        resource_type="client",
        resource_id=client_id,
        metadata={
            "recording_id": recording_id,
            "job_name": job.get("job_name"),
            "size": len(contents),
            "normalized_size": len(flac_contents),
            "storage_backend": getattr(
                obj_meta,
                "backend",
                "s3",
            ),
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get(
            "user-agent"
        ),
    )

    return {
        "client_id": client_id,
        "recording_id": recording_id,
        **job,
    }


@api.get("/notes/clinical-scribe/transcription")
async def get_clinical_scribe_transcription(
    client_id: str,
    job_name: str,
    user=Depends(
        require_roles(
            "practitioner",
            "admin",
            "medical_assistant",
        )
    ),
):
    """Poll an in-person HealthScribe job."""

    client = await find_client(
        client_id=client_id
    )

    if not client:
        raise HTTPException(
            status_code=404,
            detail="Patient not found",
        )

    if user["role"] != "practitioner":
        delegation = await has_active_delegation(
            user,
            client_id,
        )

        if not delegation:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "delegation_required",
                },
            )

    expected_prefix = (
        f"nms-inperson-{client_id}-"
    )

    if not job_name.startswith(expected_prefix):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "transcription_scope_denied",
            },
        )

    from services.telehealth_transcription import (
        get_completed_outputs,
    )

    try:
        result = await get_completed_outputs(
            job_name
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": str(exc),
            },
        )
    except Exception as exc:
        logger.warning(
            "In-person HealthScribe status failed "
            "client=%s job=%s: %s",
            client_id,
            job_name,
            exc,
        )

        raise HTTPException(
            status_code=502,
            detail={
                "code": "healthscribe_status_failed",
            },
        )

    return {
        "client_id": client_id,
        **result,
    }



@api.post("/notes", response_model=NoteOut)
async def create_note(payload: NoteIn, request: Request,
                      user=Depends(require_roles("practitioner", "admin", "medical_assistant"))):
    c = await find_client(client_id=payload.client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Patient not found")

    # A SOAP note linked to an encounter must belong to the
    # same patient as that appointment.
    if payload.appointment_id:
        async with AsyncSessionLocal() as pg:
            linked_appointment = (
                await sched_repo.get_appointment(
                    pg,
                    payload.appointment_id,
                )
            )

        if not linked_appointment:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "appointment_not_found",
                    "message":
                        "The linked appointment was not found.",
                },
            )

        if (
            str(linked_appointment.get("client_id"))
            != str(payload.client_id)
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code":
                        "appointment_client_mismatch",
                    "message":
                        "The SOAP note patient does not match "
                        "the linked appointment.",
                },
            )
    # Delegated draft editing gate — admin / medical_assistant need an active delegation.
    authorizing_provider_id = None
    if user["role"] != "practitioner":
        deleg = await has_active_delegation(user, payload.client_id)
        if not deleg:
            raise HTTPException(status_code=403, detail={
                "code": "delegation_required",
                "message": "Provider authorization is required to draft clinical documentation.",
            })
        authorizing_provider_id = deleg.get("provider_id")
    doc = payload.dict()
    doc["id"] = new_id()
    # Preserve provider ownership even when drafted by a delegate; if a delegate
    # creates the note, the note is authored on behalf of the authorizing provider
    # (they remain the responsible clinician for eventual finalization).
    if user["role"] == "practitioner":
        doc["practitioner_id"] = user["id"]
        doc["practitioner_name"] = user.get("full_name", "")
    else:
        provider = await find_user_by_id(authorizing_provider_id) if authorizing_provider_id else None
        doc["practitioner_id"] = authorizing_provider_id
        doc["practitioner_name"] = (provider or {}).get("full_name", "")
        doc["drafted_by_id"] = user["id"]
        doc["drafted_by_name"] = user.get("full_name", "")
        doc["drafted_by_role"] = user.get("role")
    doc["amendments"] = []
    doc["status"] = "draft"
    doc["created_at"] = datetime.now(timezone.utc)
    doc["updated_at"] = doc["created_at"]
    doc["finalized_at"] = None
    doc["finalized_by"] = None
    doc["prior_versions"] = []
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            doc = await cm_repo.create_note(pg, doc)

    # ---- Phase 14: auto-attach referenced supplement directions to the patient chart ----
    matched = await _fan_out_supplements_for_note(doc, user)
    if matched:
        doc["auto_attached_supplements"] = matched
    await log_audit(db, user["id"], user["email"], "note.create",
                    resource_type="note", resource_id=doc["id"],
                    metadata={"client_id": payload.client_id,
                              "auto_attached": [m["sheet_id"] for m in matched],
                              "authorizing_provider_id": authorizing_provider_id,
                              "actor_role": user.get("role")},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(doc)


@api.put("/notes/{note_id}", response_model=NoteOut)
async def update_note(note_id: str, payload: NoteIn, request: Request,
                      user=Depends(require_roles("practitioner", "admin", "medical_assistant"))):
    """Draft-only edit. Once finalized, editing is refused (must amend instead)."""
    note = await _fetch_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if note.get("status") == "finalized":
        raise HTTPException(status_code=409, detail={
            "code": "note_finalized",
            "message": "This note is finalized and cannot be edited. Use /amend to add an addendum.",
        })
    # Delegated edit gate for non-provider actors.
    authorizing_provider_id = None
    if user["role"] == "practitioner":
        if note.get("practitioner_id") != user["id"]:
            raise HTTPException(status_code=403, detail="Only the assigned provider may edit this draft")
    else:
        deleg = await has_active_delegation(user, note.get("client_id"),
                                            provider_id=note.get("practitioner_id"))
        if not deleg:
            raise HTTPException(status_code=403, detail={
                "code": "delegation_required",
                "message": "Provider authorization is required to edit this draft.",
            })
        authorizing_provider_id = deleg.get("provider_id")
    updates = payload.dict()

    # Patient and encounter linkage are immutable after the
    # clinical note is created. Draft edits may change only
    # the SOAP content.
    updates.pop("client_id", None)
    updates.pop("appointment_id", None)

    updates["updated_at"] = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await cm_repo.update_note(pg, note_id, updates)
    await log_audit(db, user["id"], user["email"], "note.update_draft",
                    resource_type="note", resource_id=note_id,
                    metadata={"fields": list(updates.keys()),
                              "authorizing_provider_id": authorizing_provider_id,
                              "actor_role": user.get("role")},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    note = await _fetch_note(note_id)
    return _strip_id(note)


@api.post("/notes/{note_id}/finalize", response_model=NoteOut)
async def finalize_note(note_id: str, request: Request,
                        user=Depends(require_roles("practitioner"))):
    """Transition a draft note to `finalized`. The finalized version is
    immutable — future changes must go through `/amend`. Provider-only."""
    note = await _fetch_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if note.get("status") == "finalized":
        return _strip_id(note)
    if note.get("practitioner_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Only the assigned provider may finalize")
    now = datetime.now(timezone.utc)
    # Snapshot the current content as the immutable version 1 + chain the hash.
    snapshot = {
        "version": 1,
        "subjective": note.get("subjective"),
        "objective": note.get("objective"),
        "assessment": note.get("assessment"),
        "plan": note.get("plan"),
        "author_id": note.get("practitioner_id"),
        "author_name": note.get("practitioner_name"),
        "finalized_at": now.isoformat(),
    }
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            prev = list(note.get("prior_versions") or [])
            prev.append(snapshot)

            await cm_repo.update_note(
                pg,
                note_id,
                {"prior_versions": prev},
            )

            finalized = await cm_repo.finalize_note(
                pg,
                note_id,
                user_id=user["id"],
            )

            # A finalized SOAP note linked to a telehealth
            # appointment completes the documentation workflow.
            appointment_id = (
                (finalized or note).get("appointment_id")
            )

            if appointment_id:
                appointment = (
                    await sched_repo.get_appointment(
                        pg,
                        appointment_id,
                    )
                )

                if (
                    appointment
                    and appointment.get("visit_mode")
                    == "telehealth"
                ):
                    telehealth = dict(
                        appointment.get("telehealth") or {}
                    )

                    telehealth.update({
                        "documentation_status": "complete",
                        "documentation_completed_at":
                            now.isoformat(),
                        "documentation_completed_by":
                            user["id"],
                        "finalized_note_id": note_id,
                    })

                    await sched_repo.update_appointment(
                        pg,
                        appointment_id,
                        {
                            "telehealth": telehealth,
                        },
                    )
    await log_audit(db, user["id"], user["email"], "note.finalize",
                    resource_type="note", resource_id=note_id,
                    severity="high", outcome="success",
                    metadata={"client_id": note.get("client_id"), "version": 1,
                              "note_hash": (finalized or {}).get("note_hash")},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return finalized or note


async def _fan_out_supplements_for_note(note: dict, user: dict) -> list:
    """Scan a SOAP note's free-text fields for references to active supplement
    sheets (case-insensitive substring on title) and create assignment rows so
    the patient's portal "My Plan" page surfaces those PDFs automatically."""
    haystack = " ".join([
        note.get("subjective") or "",
        note.get("objective") or "",
        note.get("assessment") or "",
        note.get("plan") or "",
    ]).lower()
    if not haystack.strip():
        return []
    sheets = await list_active_supplement_sheets(limit=200)
    matched = []
    now = datetime.now(timezone.utc)
    for s in sheets:
        title = (s.get("title") or "").strip()
        if len(title) < 4:
            continue  # avoid spurious matches on tiny titles
        if title.lower() in haystack:
            # idempotent — only create when not already linked
            existing = await find_active_assignment(note["client_id"], s["id"])
            if existing:
                # bump last_referenced + add note ref
                await touch_assignment_reference(existing["id"], ts=now, note_id=note["id"])
                matched.append({"sheet_id": s["id"], "sheet_title": title, "assignment_id": existing["id"], "newly_assigned": False})
            else:
                a = {
                    "id": new_id(),
                    "client_id": note["client_id"],
                    "sheet_id": s["id"],
                    "sheet_title": title,
                    "sheet_summary": s.get("summary") or "",
                    "items_snapshot": s.get("items") or [],
                    "active": True,
                    "assigned_by_id": user["id"],
                    "assigned_by_name": user.get("full_name") or "",
                    "assigned_at": now,
                    "last_referenced_at": now,
                    "note_ids": [note["id"]],
                    "source": "auto_soap",
                }
                await insert_assignment(a)
                matched.append({"sheet_id": s["id"], "sheet_title": title, "assignment_id": a["id"], "newly_assigned": True})
                # Mirror to audit log so admins have a single trail regardless of source
                try:
                    await log_audit(db, user["id"], user["email"], "supplement_assignment.create",
                                    resource_type="client", resource_id=note["client_id"],
                                    metadata={"sheet_id": s["id"], "source": "auto_soap", "note_id": note["id"]})
                except Exception:
                    pass
                # Push notification to the client portal user
                try:
                    note_client = await find_client(client_id=note["client_id"])
                    if note_client and (c_user_id := note_client.get("user_id")):
                        await push_to_user(
                            c_user_id,
                            "New supplement directions",
                            f"Dr. {user.get('full_name') or ''} attached \"{title}\" to your plan.",
                            url="/portal/patient/plan",
                            tag=f"supp-{a['id']}",
                        )
                except Exception:
                    pass
    return matched


# ---- Client supplement assignments CRUD ----
@api.get("/clients/{client_id}/supplement-assignments")
async def list_client_supplement_assignments(client_id: str, user=Depends(get_current_user)):
    if user["role"] == "client":
        sc = await _resolve_self_client(user)
        if not sc or sc["id"] != client_id:
            raise HTTPException(status_code=403, detail="Forbidden")
    rows = await list_active_assignments_for_client(client_id, limit=200)
    return [_strip_id(r) for r in rows]


@api.post("/clients/{client_id}/supplement-assignments")
async def create_client_supplement_assignment(client_id: str, payload: dict, request: Request,
                                              user=Depends(require_roles("admin", "practitioner"))):
    sheet_id = payload.get("sheet_id")
    if not sheet_id:
        raise HTTPException(status_code=400, detail="sheet_id required")
    sheet = await find_supplement_sheet(sheet_id)
    if not sheet:
        raise HTTPException(status_code=404, detail="Sheet not found")
    client = await find_client(client_id=client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Patient not found")
    existing = await find_active_assignment(client_id, sheet_id)
    if existing:
        return _strip_id(existing)
    now = datetime.now(timezone.utc)
    a = {
        "id": new_id(),
        "client_id": client_id,
        "sheet_id": sheet_id,
        "sheet_title": sheet.get("title"),
        "sheet_summary": sheet.get("summary") or "",
        "items_snapshot": sheet.get("items") or [],
        "active": True,
        "assigned_by_id": user["id"],
        "assigned_by_name": user.get("full_name"),
        "assigned_at": now,
        "last_referenced_at": now,
        "note_ids": [],
        "source": "manual",
    }
    await insert_assignment(a)
    await log_audit(db, user["id"], user["email"], "supplement_assignment.create",
                    resource_type="client", resource_id=client_id,
                    metadata={"sheet_id": sheet_id},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(a)


@api.delete("/clients/{client_id}/supplement-assignments/{assignment_id}")
async def remove_client_supplement_assignment(client_id: str, assignment_id: str, request: Request,
                                              user=Depends(require_roles("admin", "practitioner"))):
    a = await find_assignment(assignment_id)
    if not a or a.get("client_id") != client_id:
        raise HTTPException(status_code=404, detail="Assignment not found")
    await deactivate_assignment(assignment_id, by_id=user["id"])
    await log_audit(db, user["id"], user["email"], "supplement_assignment.remove",
                    resource_type="client", resource_id=client_id,
                    metadata={"assignment_id": assignment_id},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


@api.post("/notes/{note_id}/amend", response_model=NoteOut)
async def amend_note(note_id: str, payload: AmendIn, request: Request,
                     user=Depends(require_roles("practitioner"))):
    note = await _fetch_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    # Amendment workflow only applies to finalized notes. Drafts should be edited via PUT.
    if note.get("status") != "finalized":
        # Backfill: legacy notes without a status are treated as finalized so the
        # amend endpoint remains callable on historical rows.
        if note.get("status") not in (None, "finalized"):
            raise HTTPException(status_code=409, detail={
                "code": "not_finalized",
                "message": "Amendment is only supported on finalized notes. Finalize first.",
            })
    reason = (getattr(payload, "reason", None) or "").strip()
    if not payload.content or len(payload.content.strip()) < 4:
        raise HTTPException(status_code=400, detail="Amendment content required")
    if len(reason) < 4:
        raise HTTPException(status_code=400, detail={
            "code": "amendment_reason_required",
            "message": "Amendment reason is required (min 4 characters) for HIPAA-aligned audit.",
        })
    amendment = {
        "author_id": user["id"],
        "author_name": user.get("full_name", ""),
        "content": payload.content,
        "reason": reason,
        "ts": datetime.now(timezone.utc),
    }
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await cm_repo.append_amendment(pg, note_id, amendment)
    await log_audit(db, user["id"], user["email"], "note.amend",
                    resource_type="note", resource_id=note_id,
                    severity="high", outcome="success",
                    metadata={"client_id": note.get("client_id"), "reason_preview": reason[:80]},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    note = await _fetch_note(note_id)
    return _strip_id(note)


# =================== FILES ===================
ALLOWED_CATEGORIES = {"lab", "intake", "image", "doc", "other"}
# Content-type allowlist. Enforced on upload; unknown MIME → 415.
ALLOWED_MIME_PREFIXES = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.",  # docx/xlsx/pptx
    "application/msword", "application/vnd.ms-excel",
    "application/json", "text/plain", "text/csv",
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/heic", "image/heif",
    "audio/", "video/",  # for telehealth recordings
)
MAX_UPLOAD_BYTES = int(20 * 1024 * 1024)  # 20 MiB


def _safe_filename(name: str) -> str:
    """Strip path components + control chars; keep a POSIX-safe basename."""
    import re
    base = (name or "upload").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    base = re.sub(r"[\x00-\x1f]+", "", base).strip()
    base = re.sub(r"[^A-Za-z0-9._\-]+", "_", base)
    return base[:180] or "upload"


@api.post("/files/upload", response_model=FileMetaOut)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    client_id: Optional[str] = Form(None),
    category: str = Form("other"),
    user=Depends(get_current_user),
):
    import hashlib as _hashlib
    # Auditor is read-only; refuse any upload path even though the endpoint
    # otherwise uses get_current_user for the client-uploads-own-file case.
    if user.get("role") == "auditor":
        raise HTTPException(status_code=403, detail={
            "code": "auditor_read_only",
            "message": "Auditor accounts cannot upload files.",
        })
    if category not in ALLOWED_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Category must be one of {ALLOWED_CATEGORIES}")
    mime = (file.content_type or "").lower()
    if not any(mime.startswith(p) for p in ALLOWED_MIME_PREFIXES):
        raise HTTPException(status_code=415, detail=f"Unsupported media type: {mime or 'unknown'}")

    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            raise HTTPException(status_code=404, detail="Patient record missing")
        client_id = self_client["id"]
    else:
        # Workforce upload must specify a client the actor can see.
        if client_id:
            target = await find_client(client_id=client_id)
            if not target:
                raise HTTPException(status_code=404, detail="Patient not found")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (20 MiB max)")

    checksum = _hashlib.sha256(content).hexdigest()
    safe_name = _safe_filename(file.filename)

    # Opaque object key — never derived from PHI or user-visible names.
    storage = get_storage()
    file_id = new_id()
    storage_key = f"clients/{client_id or 'nocli'}/{file_id[:2]}/{file_id}"
    obj_meta = await storage.put_bytes(
        storage_key, content,
        content_type=mime or "application/octet-stream",
        sha256=checksum,
        metadata={"category": category},
    )
    meta = {
        "id": file_id,
        "storage_backend": obj_meta.backend,
        "storage_key": storage_key,
        "bucket": obj_meta.bucket,
        "version_id": obj_meta.version_id,
        "filename": safe_name,
        "mime": mime or "application/octet-stream",
        "size": len(content),
        "sha256": checksum,
        "category": category,
        "client_id": client_id,
        "uploaded_by": user["id"],
        "uploaded_by_name": user.get("full_name", ""),
        "created_at": datetime.now(timezone.utc),
        "deleted_at": None,
        # Quarantine until scanner clears.
        "scan_status": "pending",
        "scan_provider": None,
        "scan_result": None,
        "scan_engine": None,
        "scanned_at": None,
    }
    await db.files.insert_one(meta)
    # Synchronous inline scan — small files (≤20 MiB) complete in well under a
    # second on clamd, and this keeps the contract simple: by the time the
    # client sees a 200 the row is either `clean` or quarantined. Downloads
    # gate on `scan_status == 'clean'`.
    from malware_scan import scan_and_update_file
    scan_result = await scan_and_update_file(
        db, meta["id"], content, log_audit_fn=log_audit,
        user_id=user["id"], user_email=user["email"],
    )
    meta["scan_status"] = scan_result["status"]
    meta["scan_result"] = scan_result.get("signature")
    meta["scan_engine"] = scan_result.get("engine")
    meta["scanned_at"] = scan_result.get("ts")
    await log_audit(db, user["id"], user["email"], "file.upload",
                    resource_type="file", resource_id=meta["id"],
                    metadata={"client_id": client_id, "category": category,
                              "size": len(content), "sha256": checksum, "mime": mime,
                              "scan_status": meta["scan_status"]},
                    severity="high" if meta["scan_status"] == "infected" else "info",
                    outcome="deny" if meta["scan_status"] == "infected" else "success",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(meta)


@api.get("/files", response_model=List[FileMetaOut])
async def list_files(client_id: Optional[str] = None, user=Depends(get_current_user)):
    q: Dict[str, Any] = {"deleted_at": None}
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            return []
        q["client_id"] = self_client["id"]
    elif client_id:
        q["client_id"] = client_id
    items = await db.files.find(q).sort("created_at", -1).to_list(500)
    return [_strip_id(i) for i in items]


@api.get("/files/{file_id}/download")
async def download_file(file_id: str, request: Request, user=Depends(get_current_user)):
    meta = await db.files.find_one({"id": file_id})
    if not meta:
        raise HTTPException(status_code=404, detail="File not found")
    if meta.get("deleted_at"):
        raise HTTPException(status_code=404, detail="File not found")
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client or meta.get("client_id") != self_client["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
    # Downloads and clinical attachments gate on scanner-verified `clean` status.
    scan_status = (meta.get("scan_status") or "pending").lower()
    if scan_status == "pending":
        raise HTTPException(status_code=425, detail={
            "code": "scan_pending", "message": "File is awaiting malware scan.",
        })
    if scan_status == "infected":
        # High-severity access-denied audit; DO NOT reveal signature name to
        # the caller (avoid signature-oracle disclosure).
        await log_audit(db, user["id"], user["email"], "file.download_denied",
                        resource_type="file", resource_id=file_id,
                        severity="high", outcome="deny",
                        metadata={"reason": "malware_quarantine"},
                        ip=get_client_ip(request),
                        user_agent=request.headers.get("user-agent"))
        raise HTTPException(status_code=451, detail={
            "code": "file_quarantined", "message": "File is quarantined; contact your administrator.",
        })
    if scan_status == "error":
        raise HTTPException(status_code=503, detail={
            "code": "scan_error", "message": "Scan failed; retry after operator review.",
        })
    if scan_status != "clean":
        raise HTTPException(status_code=403, detail="File not available")
    # Fetch bytes from the storage adapter. Legacy GridFS-only rows (no
    # storage_key) are treated as missing — they must be backfilled first.
    storage_key = meta.get("storage_key")
    if not storage_key:
        raise HTTPException(status_code=410, detail={
            "code": "storage_not_migrated",
            "message": "This file lives in legacy GridFS. Run the S3 backfill script.",
        })
    try:
        data = await get_storage().get_bytes(storage_key)
    except StorageNotFound:
        raise HTTPException(status_code=404, detail="File not found in storage")
    await log_audit(db, user["id"], user["email"], "file.download",
                    resource_type="file", resource_id=file_id,
                    metadata={"client_id": meta.get("client_id"), "sha256": meta.get("sha256"),
                              "size": meta.get("size")},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    fname = _safe_filename(meta["filename"])
    return StreamingResponse(
        io.BytesIO(data),
        media_type=meta.get("mime", "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@api.delete("/files/{file_id}")
async def delete_file(file_id: str, request: Request,
                      user=Depends(require_roles("admin", "practitioner"))):
    """Soft-delete: mark `deleted_at` + record who + high-severity audit. The
    GridFS blob is NOT purged (retention-ready)."""
    meta = await db.files.find_one({"id": file_id})
    if not meta:
        raise HTTPException(status_code=404, detail="File not found")
    if meta.get("deleted_at"):
        return {"ok": True, "already_deleted": True}
    await db.files.update_one({"id": file_id}, {"$set": {
        "deleted_at": datetime.now(timezone.utc),
        "deleted_by": user["id"],
        "deleted_by_name": user.get("full_name") or user.get("email"),
    }})
    await log_audit(db, user["id"], user["email"], "file.delete",
                    resource_type="file", resource_id=file_id,
                    severity="high", outcome="success",
                    metadata={"client_id": meta.get("client_id"), "sha256": meta.get("sha256")},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


