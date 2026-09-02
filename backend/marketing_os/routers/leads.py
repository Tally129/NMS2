"""Marketing OS — Lead CRM + Appointment Setter workspace API (Phase 6).

Internal staff workflow only. Mutations here are NMS operational actions
(assign owner, change lead stage, manage follow-up tasks) — NOT external
advertising-provider writes, and never touch clinical data. Privacy-safe:
opaque marketing identifiers only, no PHI, no automatic outreach.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from deps import api, require_roles
from postgres_db import AsyncSessionLocal
from marketing_os.services.lead_pipeline import (
    LeadTransitionError,
    PRIORITIES,
    QUALIFICATION_STATUSES,
    TASK_STATUSES,
    TASK_TYPES,
    priority_from_score,
    setter_metrics,
    validate_transition,
)
from marketing_os.services.measurement import (
    MarketingDataPolicyError,
    assert_non_phi_marketing_payload,
)

MARKETING_ROLES = ("admin", "practitioner")


def _new_id() -> str:
    return uuid.uuid4().hex


def _uid(user: dict) -> Optional[str]:
    value = user.get("id")
    return str(value) if value else None


def _serialize(row) -> dict[str, Any]:
    result = dict(row._mapping)
    for key, value in list(result.items()):
        if isinstance(value, Decimal):
            result[key] = float(value)
        elif isinstance(value, (date, datetime)):
            result[key] = value.isoformat()
    return result


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _log_activity(pg, *, lead_id, activity_type, actor_id=None,
                        summary=None, details=None):
    await pg.execute(
        text("""
            INSERT INTO marketing_lead_activity
                (id, lead_id, activity_type, occurred_at, actor_id,
                 summary, details)
            VALUES
                (:id, :lead_id, :activity_type, now(), :actor_id,
                 :summary, CAST(:details AS jsonb))
        """),
        {
            "id": _new_id(),
            "lead_id": lead_id,
            "activity_type": activity_type,
            "actor_id": actor_id,
            "summary": summary,
            "details": json.dumps(details or {}),
        },
    )


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #

class LeadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marketing_subject_id: str
    source: Optional[str] = None
    medium: Optional[str] = None
    provider: Optional[str] = None
    campaign_id: Optional[str] = None
    campaign_name: Optional[str] = None
    landing_page: Optional[str] = None
    offer_id: Optional[str] = None
    attribution_source: Optional[str] = None
    attribution_model: Optional[str] = None
    opportunity_score: Optional[int] = None
    qualification_score: Optional[int] = None
    service_interest: Optional[str] = None
    urgency: Optional[str] = None
    preferred_location: Optional[str] = None
    preferred_contact_window: Optional[str] = None
    appointment_readiness: Optional[str] = None


class LeadQualificationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    qualification_status: Optional[str] = None
    qualification_score: Optional[int] = None
    urgency: Optional[str] = None
    service_interest: Optional[str] = None
    preferred_location: Optional[str] = None
    preferred_contact_window: Optional[str] = None
    appointment_readiness: Optional[str] = None
    priority: Optional[str] = None
    next_action_type: Optional[str] = None
    next_action_at: Optional[datetime] = None


class LeadStatusPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_status: str
    note: Optional[str] = None


class LeadOwnerPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assigned_owner_id: Optional[str] = None
    note: Optional[str] = None


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: str
    task_type: str
    owner_id: Optional[str] = None
    due_at: Optional[datetime] = None
    notes: Optional[str] = None


class TaskPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Optional[str] = None
    owner_id: Optional[str] = None
    due_at: Optional[datetime] = None
    notes: Optional[str] = None


# --------------------------------------------------------------------------- #
# Static routes (declared BEFORE /leads/{lead_id} to avoid path capture)
# --------------------------------------------------------------------------- #

@api.get("/marketing-os/leads/metrics")
async def lead_metrics(user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    async with AsyncSessionLocal() as pg:
        leads = [
            _serialize(r) for r in await pg.execute(
                text("SELECT * FROM marketing_leads")
            )
        ]
        tasks = [
            _serialize(r) for r in await pg.execute(
                text("SELECT * FROM marketing_lead_tasks")
            )
        ]
    metrics = setter_metrics(leads, tasks)
    metrics["safety"] = {
        "external_writes": False,
        "automatic_outreach": False,
        "human_approval_required": True,
        "phi_used": False,
    }
    return metrics


@api.get("/marketing-os/leads/tasks")
async def list_tasks(
    owner_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    lead_id: Optional[str] = Query(None),
    overdue: bool = Query(False),
    limit: int = Query(200, ge=1, le=1000),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    del user
    clauses = []
    params: dict[str, Any] = {"limit": limit}
    if owner_id:
        clauses.append("owner_id = :owner_id")
        params["owner_id"] = owner_id
    if status:
        clauses.append("status = :status")
        params["status"] = status
    if lead_id:
        clauses.append("lead_id = :lead_id")
        params["lead_id"] = lead_id
    if overdue:
        clauses.append("status = 'open' AND due_at IS NOT NULL "
                       "AND due_at < now()")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    async with AsyncSessionLocal() as pg:
        rows = await pg.execute(
            text(f"""
                SELECT * FROM marketing_lead_tasks
                {where}
                ORDER BY (due_at IS NULL), due_at ASC
                LIMIT :limit
            """),
            params,
        )
        return {"tasks": [_serialize(r) for r in rows]}


@api.post("/marketing-os/leads/tasks", status_code=201)
async def create_task(payload: TaskCreate,
                      user=Depends(require_roles(*MARKETING_ROLES))):
    if payload.task_type not in TASK_TYPES:
        raise HTTPException(status_code=400,
                            detail=f"invalid task_type: {payload.task_type}")
    task_id = _new_id()
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            lead = (await pg.execute(
                text("SELECT id FROM marketing_leads WHERE id = :id"),
                {"id": payload.lead_id},
            )).first()
            if lead is None:
                raise HTTPException(status_code=404, detail="Lead not found")
            row = (await pg.execute(
                text("""
                    INSERT INTO marketing_lead_tasks
                        (id, lead_id, task_type, owner_id, due_at, status,
                         notes, created_by)
                    VALUES
                        (:id, :lead_id, :task_type, :owner_id, :due_at,
                         'open', :notes, :created_by)
                    RETURNING *
                """),
                {
                    "id": task_id,
                    "lead_id": payload.lead_id,
                    "task_type": payload.task_type,
                    "owner_id": payload.owner_id,
                    "due_at": payload.due_at,
                    "notes": payload.notes,
                    "created_by": _uid(user),
                },
            )).first()
            await _log_activity(
                pg, lead_id=payload.lead_id, activity_type="task_created",
                actor_id=_uid(user),
                summary=f"Task created: {payload.task_type}",
                details={"task_id": task_id, "task_type": payload.task_type},
            )
    return _serialize(row)


@api.patch("/marketing-os/leads/tasks/{task_id}")
async def patch_task(task_id: str, payload: TaskPatch,
                     user=Depends(require_roles(*MARKETING_ROLES))):
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status_code=400, detail="No changes supplied")
    if "status" in values and values["status"] not in TASK_STATUSES:
        raise HTTPException(status_code=400,
                            detail=f"invalid status: {values['status']}")

    assignments = []
    params: dict[str, Any] = {"task_id": task_id}
    for key in ("status", "owner_id", "due_at", "notes"):
        if key in values:
            assignments.append(f"{key} = :{key}")
            params[key] = values[key]
    if values.get("status") == "completed":
        assignments.append("completed_at = now()")
    assignments.append("updated_at = now()")

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            row = (await pg.execute(
                text(f"""
                    UPDATE marketing_lead_tasks
                    SET {', '.join(assignments)}
                    WHERE id = :task_id
                    RETURNING *
                """),
                params,
            )).first()
            if row is None:
                raise HTTPException(status_code=404, detail="Task not found")
            if values.get("status") in ("completed", "cancelled"):
                await _log_activity(
                    pg, lead_id=row._mapping["lead_id"],
                    activity_type="task_completed", actor_id=_uid(user),
                    summary=f"Task {values['status']}: "
                            f"{row._mapping['task_type']}",
                    details={"task_id": task_id},
                )
    return _serialize(row)


@api.post("/marketing-os/leads/sync")
async def sync_leads_from_opportunities(
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    """Deterministically create/refresh leads from marketing-safe events.

    Reuses the existing lead-opportunity engine. Never creates duplicates
    (keyed by opaque marketing_subject_id). Does not change staff-managed
    stages of existing leads; only refreshes scores/attribution.
    """
    from marketing_os.services.lead_opportunities import (
        derive_lead_opportunities,
    )
    from marketing_os.services.lead_pipeline import lead_fields_from_opportunity

    created, updated = 0, 0
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            events = [
                _serialize(r) for r in await pg.execute(
                    text("SELECT * FROM marketing_conversion_events "
                         "ORDER BY occurred_at ASC")
                )
            ]
            opportunities = derive_lead_opportunities(events)
            for opp in opportunities:
                fields = lead_fields_from_opportunity(opp)
                subject = fields["marketing_subject_id"]
                existing = (await pg.execute(
                    text("SELECT id FROM marketing_leads "
                         "WHERE marketing_subject_id = :s"),
                    {"s": subject},
                )).first()
                if existing is None:
                    lead_id = _new_id()
                    await pg.execute(
                        text("""
                            INSERT INTO marketing_leads
                                (id, marketing_subject_id, source, medium,
                                 campaign_name, service_interest,
                                 opportunity_score, qualification_score,
                                 priority, lead_status, qualification_status,
                                 attribution_source, attribution_model,
                                 lead_created_at, last_activity_at)
                            VALUES
                                (:id, :s, :source, :medium, :campaign,
                                 :service_interest, :opp, :qual, :priority,
                                 'new', 'unqualified',
                                 'deterministic_marketing_events',
                                 'last_touch', now(), now())
                        """),
                        {
                            "id": lead_id, "s": subject,
                            "source": fields.get("source"),
                            "medium": fields.get("medium"),
                            "campaign": fields.get("campaign_name"),
                            "service_interest": fields.get("service_interest"),
                            "opp": fields.get("opportunity_score"),
                            "qual": fields.get("qualification_score"),
                            "priority": fields.get("priority"),
                        },
                    )
                    await _log_activity(
                        pg, lead_id=lead_id, activity_type="lead_created",
                        actor_id=_uid(user),
                        summary="Lead created from marketing events",
                        details={"source": fields.get("source"),
                                 "campaign": fields.get("campaign_name")},
                    )
                    created += 1
                else:
                    await pg.execute(
                        text("""
                            UPDATE marketing_leads
                            SET opportunity_score = :opp,
                                qualification_score = :qual,
                                priority = :priority,
                                updated_at = now()
                            WHERE marketing_subject_id = :s
                        """),
                        {
                            "opp": fields.get("opportunity_score"),
                            "qual": fields.get("qualification_score"),
                            "priority": fields.get("priority"),
                            "s": subject,
                        },
                    )
                    updated += 1
    return {"created": created, "updated": updated,
            "total_opportunities": len(opportunities)}


@api.get("/marketing-os/leads")
async def list_leads(
    status: Optional[str] = Query(None),
    view: Optional[str] = Query(None),
    owner_id: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    campaign: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    del user
    clauses = []
    params: dict[str, Any] = {"limit": limit}

    view_map = {
        "new_leads": "l.lead_status = 'new'",
        "appointment_requested": "l.lead_status = 'appointment_requested'",
        "booked": "l.lead_status IN ('booked','confirmed')",
        "no_show": "l.lead_status = 'no_show'",
        "nurture": "l.lead_status = 'nurture'",
        "won": "l.lead_status = 'won'",
        "lost": "l.lead_status = 'lost'",
        "needs_attention": "l.lead_status IN ('new','contact_attempted')",
        "follow_up_today": (
            "(l.next_action_at::date = CURRENT_DATE OR EXISTS ("
            "SELECT 1 FROM marketing_lead_tasks t WHERE t.lead_id = l.id "
            "AND t.status='open' AND t.due_at::date <= CURRENT_DATE))"
        ),
    }
    if view and view in view_map:
        clauses.append(view_map[view])
    if status:
        clauses.append("l.lead_status = :status")
        params["status"] = status
    if owner_id:
        clauses.append("l.assigned_owner_id = :owner_id")
        params["owner_id"] = owner_id
    if source:
        clauses.append("l.source = :source")
        params["source"] = source
    if campaign:
        clauses.append("(l.campaign_name = :campaign "
                       "OR l.campaign_id = :campaign)")
        params["campaign"] = campaign
    if priority:
        clauses.append("l.priority = :priority")
        params["priority"] = priority

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    async with AsyncSessionLocal() as pg:
        rows = await pg.execute(
            text(f"""
                SELECT l.*,
                    (SELECT count(*) FROM marketing_lead_tasks t
                     WHERE t.lead_id = l.id AND t.status = 'open'
                       AND t.due_at IS NOT NULL AND t.due_at < now())
                       AS overdue_task_count
                FROM marketing_leads l
                {where}
                ORDER BY l.priority DESC,
                         COALESCE(l.opportunity_score, 0) DESC,
                         l.created_at DESC
                LIMIT :limit
            """),
            params,
        )
        return {"leads": [_serialize(r) for r in rows]}


@api.post("/marketing-os/leads", status_code=201)
async def create_lead(payload: LeadCreate,
                      user=Depends(require_roles(*MARKETING_ROLES))):
    try:
        assert_non_phi_marketing_payload(payload.model_dump())
    except MarketingDataPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not payload.marketing_subject_id.strip():
        raise HTTPException(status_code=422,
                            detail="marketing_subject_id is required")

    lead_id = _new_id()
    priority = priority_from_score(payload.opportunity_score)
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            dup = (await pg.execute(
                text("SELECT id FROM marketing_leads "
                     "WHERE marketing_subject_id = :s"),
                {"s": payload.marketing_subject_id},
            )).first()
            if dup is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Lead already exists for this subject",
                )
            row = (await pg.execute(
                text("""
                    INSERT INTO marketing_leads
                        (id, marketing_subject_id, source, medium, provider,
                         campaign_id, campaign_name, landing_page, offer_id,
                         attribution_source, attribution_model,
                         opportunity_score, qualification_score,
                         service_interest, urgency, preferred_location,
                         preferred_contact_window, appointment_readiness,
                         priority, lead_status, qualification_status,
                         lead_created_at, last_activity_at)
                    VALUES
                        (:id, :s, :source, :medium, :provider, :campaign_id,
                         :campaign_name, :landing_page, :offer_id,
                         :attr_source, :attr_model, :opp, :qual,
                         :service_interest, :urgency, :pref_loc, :pref_win,
                         :appt_ready, :priority, 'new', 'unqualified',
                         now(), now())
                    RETURNING *
                """),
                {
                    "id": lead_id,
                    "s": payload.marketing_subject_id,
                    "source": payload.source,
                    "medium": payload.medium,
                    "provider": payload.provider,
                    "campaign_id": payload.campaign_id,
                    "campaign_name": payload.campaign_name,
                    "landing_page": payload.landing_page,
                    "offer_id": payload.offer_id,
                    "attr_source": payload.attribution_source,
                    "attr_model": payload.attribution_model,
                    "opp": payload.opportunity_score,
                    "qual": payload.qualification_score,
                    "service_interest": payload.service_interest,
                    "urgency": payload.urgency,
                    "pref_loc": payload.preferred_location,
                    "pref_win": payload.preferred_contact_window,
                    "appt_ready": payload.appointment_readiness,
                    "priority": priority,
                },
            )).first()
            await _log_activity(
                pg, lead_id=lead_id, activity_type="lead_created",
                actor_id=_uid(user), summary="Lead created",
                details={"source": payload.source,
                         "campaign": payload.campaign_name},
            )
    return _serialize(row)


# --------------------------------------------------------------------------- #
# Param routes
# --------------------------------------------------------------------------- #

async def _get_lead_or_404(pg, lead_id: str):
    row = (await pg.execute(
        text("SELECT * FROM marketing_leads WHERE id = :id"),
        {"id": lead_id},
    )).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return row


@api.get("/marketing-os/leads/{lead_id}")
async def get_lead(lead_id: str,
                   user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    async with AsyncSessionLocal() as pg:
        row = await _get_lead_or_404(pg, lead_id)
        tasks = await pg.execute(
            text("SELECT * FROM marketing_lead_tasks WHERE lead_id = :id "
                 "ORDER BY (due_at IS NULL), due_at ASC"),
            {"id": lead_id},
        )
        return {"lead": _serialize(row),
                "tasks": [_serialize(t) for t in tasks]}


@api.get("/marketing-os/leads/{lead_id}/timeline")
async def lead_timeline(lead_id: str,
                        user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    async with AsyncSessionLocal() as pg:
        await _get_lead_or_404(pg, lead_id)
        rows = await pg.execute(
            text("SELECT * FROM marketing_lead_activity WHERE lead_id = :id "
                 "ORDER BY occurred_at DESC"),
            {"id": lead_id},
        )
        return {"lead_id": lead_id,
                "timeline": [_serialize(r) for r in rows]}


@api.patch("/marketing-os/leads/{lead_id}")
async def patch_lead_qualification(
    lead_id: str, payload: LeadQualificationPatch,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status_code=400, detail="No changes supplied")
    try:
        assert_non_phi_marketing_payload(values)
    except MarketingDataPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if ("qualification_status" in values and
            values["qualification_status"] not in QUALIFICATION_STATUSES):
        raise HTTPException(status_code=400, detail="invalid qualification")
    if "priority" in values and values["priority"] not in PRIORITIES:
        raise HTTPException(status_code=400, detail="invalid priority")

    allowed = {"qualification_status", "qualification_score", "urgency",
               "service_interest", "preferred_location",
               "preferred_contact_window", "appointment_readiness",
               "priority", "next_action_type", "next_action_at"}
    assignments = []
    params: dict[str, Any] = {"lead_id": lead_id}
    for key, value in values.items():
        if key in allowed:
            assignments.append(f"{key} = :{key}")
            params[key] = value
    assignments.append("updated_at = now()")
    assignments.append("last_activity_at = now()")

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await _get_lead_or_404(pg, lead_id)
            row = (await pg.execute(
                text(f"UPDATE marketing_leads SET {', '.join(assignments)} "
                     "WHERE id = :lead_id RETURNING *"),
                params,
            )).first()
            await _log_activity(
                pg, lead_id=lead_id, activity_type="qualification_updated",
                actor_id=_uid(user), summary="Qualification updated",
                details={k: str(v) for k, v in values.items()},
            )
    return _serialize(row)


# Stage -> timestamp/appointment side effects (deterministic).
_STAGE_TIMESTAMP = {
    "contacted": "first_contact_at",
    "contact_attempted": "first_contact_attempt_at",
    "appointment_requested": "appointment_requested_at",
    "booked": "booked_at",
}
_STAGE_APPT = {
    "appointment_requested": "requested",
    "booked": "booked",
    "confirmed": "confirmed",
    "showed": "showed",
    "no_show": "no_show",
}


@api.patch("/marketing-os/leads/{lead_id}/status")
async def patch_lead_status(lead_id: str, payload: LeadStatusPatch,
                            user=Depends(require_roles(*MARKETING_ROLES))):
    target = payload.lead_status.strip().lower()
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            lead = await _get_lead_or_404(pg, lead_id)
            current = (lead._mapping["lead_status"] or "new").lower()
            try:
                validate_transition(current, target)
            except LeadTransitionError as exc:
                raise HTTPException(status_code=409, detail=str(exc))

            assignments = ["lead_status = :target", "updated_at = now()",
                           "last_activity_at = now()"]
            params: dict[str, Any] = {"lead_id": lead_id, "target": target}

            ts_col = _STAGE_TIMESTAMP.get(target)
            if ts_col:
                assignments.append(f"{ts_col} = COALESCE({ts_col}, now())")
            if target == "contacted" and lead._mapping.get(
                "first_response_seconds"
            ) is None:
                created = lead._mapping.get("lead_created_at") or \
                    lead._mapping.get("created_at")
                if created is not None:
                    assignments.append(
                        "first_response_seconds = GREATEST(0, "
                        "EXTRACT(EPOCH FROM (now() - "
                        "COALESCE(lead_created_at, created_at)))::int)"
                    )
            if target in _STAGE_APPT:
                assignments.append("appointment_status = :appt")
                params["appt"] = _STAGE_APPT[target]

            row = (await pg.execute(
                text(f"UPDATE marketing_leads SET {', '.join(assignments)} "
                     "WHERE id = :lead_id RETURNING *"),
                params,
            )).first()
            await _log_activity(
                pg, lead_id=lead_id, activity_type="status_changed",
                actor_id=_uid(user),
                summary=f"Stage {current} -> {target}",
                details={"from": current, "to": target,
                         "note": payload.note},
            )
    return _serialize(row)


@api.patch("/marketing-os/leads/{lead_id}/owner")
async def patch_lead_owner(lead_id: str, payload: LeadOwnerPatch,
                           user=Depends(require_roles(*MARKETING_ROLES))):
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            lead = await _get_lead_or_404(pg, lead_id)
            previous = lead._mapping.get("assigned_owner_id")
            new_owner = payload.assigned_owner_id
            if new_owner:
                owner_row = (await pg.execute(
                    text("SELECT id FROM auth_users WHERE id = :id"),
                    {"id": new_owner},
                )).first()
                if owner_row is None:
                    raise HTTPException(
                        status_code=400,
                        detail="assigned_owner_id is not a known staff user",
                    )
            row = (await pg.execute(
                text("UPDATE marketing_leads SET assigned_owner_id = :owner, "
                     "updated_at = now(), last_activity_at = now() "
                     "WHERE id = :lead_id RETURNING *"),
                {"owner": new_owner, "lead_id": lead_id},
            )).first()
            await pg.execute(
                text("""
                    INSERT INTO marketing_lead_assignments
                        (id, lead_id, previous_owner_id, new_owner_id,
                         assigned_by, note)
                    VALUES
                        (:id, :lead_id, :prev, :new, :by, :note)
                """),
                {"id": _new_id(), "lead_id": lead_id, "prev": previous,
                 "new": new_owner, "by": _uid(user), "note": payload.note},
            )
            await _log_activity(
                pg, lead_id=lead_id, activity_type="owner_assigned",
                actor_id=_uid(user),
                summary="Owner reassigned",
                details={"previous_owner_id": previous,
                         "new_owner_id": new_owner},
            )
    return _serialize(row)
