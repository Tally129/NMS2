"""Marketing OS — Phase 8A Nurture + Appointment-Recovery API.

Internal staff workflow only. Deterministic nurture sequences, manual
enrollment, a pending-approval action queue, human approve/skip, and internal
create_task execution. Email actions are always held (no external outreach).
No PHI, no SMS, no AI decisioning, no external provider writes.
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
from marketing_os.services.measurement import MarketingDataPolicyError
from marketing_os.services import nurture as rules
from marketing_os.services.nurture import NurtureConfigError
from marketing_os.services.nurture_dispatch import (
    email_hold_decision,
    execute_create_task,
)
from marketing_os.services.nurture_scheduler import (
    process_due_nurture_enrollments,
)

MARKETING_ROLES = ("admin", "practitioner")

SAFETY_STATE = {
    "external_writes": False,
    "automatic_campaign_creation": False,
    "automatic_campaign_publishing": False,
    "automatic_budget_changes": False,
    "automatic_outreach": False,
    "human_approval_required": True,
    "ai_advisory_only": True,
    "phi_used": False,
    "sms_enabled": False,
}


def _new_id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
    if "metadata_json" in result and "metadata" not in result:
        result["metadata"] = result.pop("metadata_json")
    return result


def _config_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


async def _fetch_one(pg, sql: str, params: dict) -> Optional[Any]:
    return (await pg.execute(text(sql), params)).first()


async def _log_activity(pg, *, lead_id, activity_type, actor_id=None,
                        summary=None, details=None):
    await pg.execute(
        text("""
            INSERT INTO marketing_lead_activity
                (id, lead_id, activity_type, occurred_at, actor_id,
                 summary, details, created_at, updated_at)
            VALUES
                (:id, :lead_id, :activity_type, now(), :actor_id,
                 :summary, CAST(:details AS jsonb), now(), now())
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

class SequenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    slug: str
    status: Optional[str] = "draft"
    trigger_type: Optional[str] = "manual"
    trigger_config: Optional[dict] = None
    stop_on_statuses: Optional[list] = None
    audience_config: Optional[dict] = None


class SequencePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    status: Optional[str] = None
    trigger_type: Optional[str] = None
    trigger_config: Optional[dict] = None
    stop_on_statuses: Optional[list] = None
    audience_config: Optional[dict] = None


class StepCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_key: str
    action_type: str
    position: int = 0
    delay_minutes: int = 0
    title: Optional[str] = None
    subject: Optional[str] = None
    body_html: Optional[str] = None
    config: Optional[dict] = None


class StepPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: Optional[int] = None
    delay_minutes: Optional[int] = None
    title: Optional[str] = None
    subject: Optional[str] = None
    body_html: Optional[str] = None
    config: Optional[dict] = None


class EnrollCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence_id: str
    lead_id: str


class EnrollmentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str  # "stop"
    reason: Optional[str] = None


class ActionSkip(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Optional[str] = None


class TickRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: Optional[int] = 100


# --------------------------------------------------------------------------- #
# Sequences
# --------------------------------------------------------------------------- #

@api.get("/marketing-os/nurture/sequences")
async def list_sequences(
    status: Optional[str] = Query(None),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    del user
    clauses = []
    params: dict[str, Any] = {}
    if status:
        clauses.append("status = :status")
        params["status"] = status
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    async with AsyncSessionLocal() as pg:
        rows = await pg.execute(
            text(f"""
                SELECT * FROM marketing_nurture_sequences
                {where}
                ORDER BY created_at DESC
            """),
            params,
        )
        return {"sequences": [_serialize(r) for r in rows]}


@api.post("/marketing-os/nurture/sequences", status_code=201)
async def create_sequence(payload: SequenceCreate,
                          user=Depends(require_roles(*MARKETING_ROLES))):
    try:
        validated = rules.validate_sequence_payload(payload.model_dump())
    except (NurtureConfigError, MarketingDataPolicyError) as exc:
        raise _config_error(exc) from exc

    seq_id = _new_id()
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            dup = await _fetch_one(
                pg,
                "SELECT id FROM marketing_nurture_sequences WHERE slug = :slug",
                {"slug": validated["slug"]},
            )
            if dup:
                raise HTTPException(status_code=409, detail="slug exists")
            row = (await pg.execute(
                text("""
                    INSERT INTO marketing_nurture_sequences
                        (id, name, slug, status, trigger_type, trigger_config,
                         stop_on_statuses, audience_config, created_by,
                         created_at, updated_at)
                    VALUES
                        (:id, :name, :slug, :status, :trigger_type,
                         CAST(:trigger_config AS jsonb),
                         CAST(:stop_on_statuses AS jsonb),
                         CAST(:audience_config AS jsonb), :created_by,
                         now(), now())
                    RETURNING *
                """),
                {
                    "id": seq_id,
                    "name": validated["name"],
                    "slug": validated["slug"],
                    "status": validated["status"],
                    "trigger_type": validated["trigger_type"],
                    "trigger_config": json.dumps(validated["trigger_config"]),
                    "stop_on_statuses": json.dumps(
                        validated["stop_on_statuses"]
                    ),
                    "audience_config": json.dumps(validated["audience_config"]),
                    "created_by": _uid(user),
                },
            )).first()
    return _serialize(row)


@api.get("/marketing-os/nurture/sequences/{sequence_id}")
async def get_sequence(sequence_id: str,
                       user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    async with AsyncSessionLocal() as pg:
        seq = await _fetch_one(
            pg,
            "SELECT * FROM marketing_nurture_sequences WHERE id = :id",
            {"id": sequence_id},
        )
        if not seq:
            raise HTTPException(status_code=404, detail="sequence not found")
        steps = await pg.execute(
            text("""
                SELECT * FROM marketing_nurture_steps
                WHERE sequence_id = :sid
                ORDER BY position ASC, step_key ASC
            """),
            {"sid": sequence_id},
        )
        result = _serialize(seq)
        result["steps"] = [_serialize(s) for s in steps]
    return result


@api.patch("/marketing-os/nurture/sequences/{sequence_id}")
async def patch_sequence(sequence_id: str, payload: SequencePatch,
                         user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status_code=400, detail="No changes supplied")

    assignments: list[str] = []
    params: dict[str, Any] = {"id": sequence_id}
    try:
        if "name" in values:
            params["name"] = rules._require_str(
                values["name"], "name", max_len=rules.MAX_NAME_LEN
            )
            assignments.append("name = :name")
        if "status" in values:
            status = str(values["status"]).strip().lower()
            if status not in rules.SEQUENCE_STATUSES:
                raise NurtureConfigError(f"invalid status: {status!r}")
            params["status"] = status
            assignments.append("status = :status")
        if "trigger_type" in values or "trigger_config" in values:
            ttype, tconfig = rules.validate_trigger(
                values.get("trigger_type", "manual"),
                values.get("trigger_config", {}),
            )
            if "trigger_type" in values:
                params["trigger_type"] = ttype
                assignments.append("trigger_type = :trigger_type")
            if "trigger_config" in values:
                params["trigger_config"] = json.dumps(tconfig)
                assignments.append(
                    "trigger_config = CAST(:trigger_config AS jsonb)"
                )
        if "stop_on_statuses" in values:
            params["stop_on_statuses"] = json.dumps(
                rules.validate_stop_statuses(values["stop_on_statuses"])
            )
            assignments.append(
                "stop_on_statuses = CAST(:stop_on_statuses AS jsonb)"
            )
        if "audience_config" in values:
            params["audience_config"] = json.dumps(
                rules.validate_audience_config(values["audience_config"])
            )
            assignments.append(
                "audience_config = CAST(:audience_config AS jsonb)"
            )
    except (NurtureConfigError, MarketingDataPolicyError) as exc:
        raise _config_error(exc) from exc

    assignments.append("updated_at = now()")
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            row = (await pg.execute(
                text(f"""
                    UPDATE marketing_nurture_sequences
                    SET {', '.join(assignments)}
                    WHERE id = :id
                    RETURNING *
                """),
                params,
            )).first()
            if row is None:
                raise HTTPException(
                    status_code=404, detail="sequence not found"
                )
    return _serialize(row)


# --------------------------------------------------------------------------- #
# Steps
# --------------------------------------------------------------------------- #

@api.post("/marketing-os/nurture/sequences/{sequence_id}/steps",
          status_code=201)
async def create_step(sequence_id: str, payload: StepCreate,
                      user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    try:
        validated = rules.validate_step_payload(payload.model_dump())
    except (NurtureConfigError, MarketingDataPolicyError) as exc:
        raise _config_error(exc) from exc

    step_id = _new_id()
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            seq = await _fetch_one(
                pg,
                "SELECT id FROM marketing_nurture_sequences WHERE id = :id",
                {"id": sequence_id},
            )
            if not seq:
                raise HTTPException(
                    status_code=404, detail="sequence not found"
                )
            count_row = await _fetch_one(
                pg,
                """SELECT count(*) AS c FROM marketing_nurture_steps
                   WHERE sequence_id = :sid""",
                {"sid": sequence_id},
            )
            if int(count_row._mapping["c"]) >= rules.MAX_STEPS_PER_SEQUENCE:
                raise HTTPException(
                    status_code=422, detail="too many steps in sequence"
                )
            dup = await _fetch_one(
                pg,
                """SELECT id FROM marketing_nurture_steps
                   WHERE sequence_id = :sid AND step_key = :key""",
                {"sid": sequence_id, "key": validated["step_key"]},
            )
            if dup:
                raise HTTPException(status_code=409, detail="step_key exists")
            row = (await pg.execute(
                text("""
                    INSERT INTO marketing_nurture_steps
                        (id, sequence_id, step_key, position, action_type,
                         channel, delay_minutes, title, subject, body_html,
                         config, created_at, updated_at)
                    VALUES
                        (:id, :sid, :step_key, :position, :action_type,
                         :channel, :delay_minutes, :title, :subject,
                         :body_html, CAST(:config AS jsonb), now(), now())
                    RETURNING *
                """),
                {
                    "id": step_id,
                    "sid": sequence_id,
                    "step_key": validated["step_key"],
                    "position": validated["position"],
                    "action_type": validated["action_type"],
                    "channel": validated["channel"],
                    "delay_minutes": validated["delay_minutes"],
                    "title": validated["title"],
                    "subject": validated["subject"],
                    "body_html": validated["body_html"],
                    "config": json.dumps(validated["config"]),
                },
            )).first()
    return _serialize(row)


@api.patch("/marketing-os/nurture/sequences/{sequence_id}/steps/{step_id}")
async def patch_step(sequence_id: str, step_id: str, payload: StepPatch,
                     user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status_code=400, detail="No changes supplied")

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            existing = await _fetch_one(
                pg,
                """SELECT * FROM marketing_nurture_steps
                   WHERE id = :id AND sequence_id = :sid""",
                {"id": step_id, "sid": sequence_id},
            )
            if not existing:
                raise HTTPException(status_code=404, detail="step not found")

            current = _serialize(existing)
            merged = {
                "step_key": current["step_key"],
                "action_type": current["action_type"],
                "position": values.get("position", current["position"]),
                "delay_minutes": values.get(
                    "delay_minutes", current["delay_minutes"]
                ),
                "title": values.get("title", current["title"]),
                "subject": values.get("subject", current["subject"]),
                "body_html": values.get("body_html", current["body_html"]),
                "config": values.get("config", current["config"]),
            }
            try:
                validated = rules.validate_step_payload(merged)
            except (NurtureConfigError, MarketingDataPolicyError) as exc:
                raise _config_error(exc) from exc

            row = (await pg.execute(
                text("""
                    UPDATE marketing_nurture_steps
                    SET position = :position,
                        delay_minutes = :delay_minutes,
                        title = :title,
                        subject = :subject,
                        body_html = :body_html,
                        channel = :channel,
                        config = CAST(:config AS jsonb),
                        updated_at = now()
                    WHERE id = :id
                    RETURNING *
                """),
                {
                    "id": step_id,
                    "position": validated["position"],
                    "delay_minutes": validated["delay_minutes"],
                    "title": validated["title"],
                    "subject": validated["subject"],
                    "body_html": validated["body_html"],
                    "channel": validated["channel"],
                    "config": json.dumps(validated["config"]),
                },
            )).first()
    return _serialize(row)


# --------------------------------------------------------------------------- #
# Enrollment (manual)
# --------------------------------------------------------------------------- #

@api.post("/marketing-os/nurture/enroll", status_code=201)
async def enroll_lead(payload: EnrollCreate,
                      user=Depends(require_roles(*MARKETING_ROLES))):
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            seq = await _fetch_one(
                pg,
                "SELECT * FROM marketing_nurture_sequences WHERE id = :id",
                {"id": payload.sequence_id},
            )
            if not seq:
                raise HTTPException(
                    status_code=404, detail="sequence not found"
                )
            sequence = _serialize(seq)
            if sequence["status"] != "active":
                raise HTTPException(
                    status_code=409, detail="sequence is not active"
                )

            lead = await _fetch_one(
                pg,
                """SELECT id, marketing_subject_id, lead_status
                   FROM marketing_leads WHERE id = :id""",
                {"id": payload.lead_id},
            )
            if not lead:
                raise HTTPException(status_code=404, detail="lead not found")
            lead_map = dict(lead._mapping)

            if rules.should_stop(
                lead_map["lead_status"], sequence["stop_on_statuses"]
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "lead is in a non-nurturable status: "
                        f"{lead_map['lead_status']}"
                    ),
                )

            existing = await _fetch_one(
                pg,
                """SELECT id FROM marketing_nurture_enrollments
                   WHERE sequence_id = :sid AND lead_id = :lid
                     AND status = 'active'""",
                {"sid": payload.sequence_id, "lid": payload.lead_id},
            )
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail="lead already actively enrolled in this sequence",
                )

            step_rows = await pg.execute(
                text("""
                    SELECT id, step_key, position, action_type, delay_minutes
                    FROM marketing_nurture_steps
                    WHERE sequence_id = :sid
                """),
                {"sid": payload.sequence_id},
            )
            steps = rules.ordered_steps(
                dict(r._mapping) for r in step_rows
            )
            if not steps:
                raise HTTPException(
                    status_code=409, detail="sequence has no steps"
                )

            enrolled_at = _now()
            next_run_at = rules.scheduled_at_for(enrolled_at, steps[0])
            enrollment_id = _new_id()

            row = (await pg.execute(
                text("""
                    INSERT INTO marketing_nurture_enrollments
                        (id, sequence_id, lead_id, marketing_subject_id,
                         status, current_step_position, enrolled_at,
                         next_run_at, enrolled_by, metadata,
                         created_at, updated_at)
                    VALUES
                        (:id, :sid, :lid, :subject, 'active', 0,
                         :enrolled_at, :next_run_at, :enrolled_by,
                         '{}'::jsonb, now(), now())
                    RETURNING *
                """),
                {
                    "id": enrollment_id,
                    "sid": payload.sequence_id,
                    "lid": payload.lead_id,
                    "subject": lead_map["marketing_subject_id"],
                    "enrolled_at": enrolled_at,
                    "next_run_at": next_run_at,
                    "enrolled_by": _uid(user),
                },
            )).first()

            await _log_activity(
                pg,
                lead_id=payload.lead_id,
                activity_type="nurture_enrolled",
                actor_id=_uid(user),
                summary=f"Enrolled in nurture sequence: {sequence['name']}",
                details={
                    "sequence_id": payload.sequence_id,
                    "enrollment_id": enrollment_id,
                },
            )
    return _serialize(row)


@api.get("/marketing-os/nurture/enrollments")
async def list_enrollments(
    lead_id: Optional[str] = Query(None),
    sequence_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    del user
    clauses = []
    params: dict[str, Any] = {"limit": limit}
    if lead_id:
        clauses.append("lead_id = :lead_id")
        params["lead_id"] = lead_id
    if sequence_id:
        clauses.append("sequence_id = :sequence_id")
        params["sequence_id"] = sequence_id
    if status:
        clauses.append("status = :status")
        params["status"] = status
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    async with AsyncSessionLocal() as pg:
        rows = await pg.execute(
            text(f"""
                SELECT * FROM marketing_nurture_enrollments
                {where}
                ORDER BY (next_run_at IS NULL), next_run_at ASC,
                         created_at DESC
                LIMIT :limit
            """),
            params,
        )
        return {"enrollments": [_serialize(r) for r in rows]}


@api.patch("/marketing-os/nurture/enrollments/{enrollment_id}")
async def patch_enrollment(enrollment_id: str, payload: EnrollmentPatch,
                           user=Depends(require_roles(*MARKETING_ROLES))):
    action = (payload.action or "").strip().lower()
    if action != "stop":
        raise HTTPException(
            status_code=400, detail="unsupported action (only 'stop')"
        )
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            existing = await _fetch_one(
                pg,
                "SELECT * FROM marketing_nurture_enrollments WHERE id = :id",
                {"id": enrollment_id},
            )
            if not existing:
                raise HTTPException(
                    status_code=404, detail="enrollment not found"
                )
            current = _serialize(existing)
            if current["status"] != "active":
                raise HTTPException(
                    status_code=409,
                    detail=f"enrollment is {current['status']}",
                )
            reason = "manual_stop"
            if payload.reason:
                reason = f"manual_stop:{str(payload.reason)[:120]}"
            row = (await pg.execute(
                text("""
                    UPDATE marketing_nurture_enrollments
                    SET status = 'stopped', stop_reason = :reason,
                        next_run_at = NULL, completed_at = now(),
                        updated_at = now()
                    WHERE id = :id
                    RETURNING *
                """),
                {"reason": reason, "id": enrollment_id},
            )).first()
            # Cancel any still-pending actions for this enrollment.
            await pg.execute(
                text("""
                    UPDATE marketing_nurture_actions
                    SET status = 'cancelled', updated_at = now()
                    WHERE enrollment_id = :id
                      AND status IN ('pending_approval', 'scheduled')
                """),
                {"id": enrollment_id},
            )
            await _log_activity(
                pg,
                lead_id=current["lead_id"],
                activity_type="nurture_stopped",
                actor_id=_uid(user),
                summary="Nurture enrollment stopped",
                details={"enrollment_id": enrollment_id, "reason": reason},
            )
    return _serialize(row)


# --------------------------------------------------------------------------- #
# Action queue + approval
# --------------------------------------------------------------------------- #

@api.get("/marketing-os/nurture/actions")
async def list_actions(
    status: Optional[str] = Query(None),
    lead_id: Optional[str] = Query(None),
    enrollment_id: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    del user
    clauses = []
    params: dict[str, Any] = {"limit": limit}
    if status:
        clauses.append("status = :status")
        params["status"] = status
    if lead_id:
        clauses.append("lead_id = :lead_id")
        params["lead_id"] = lead_id
    if enrollment_id:
        clauses.append("enrollment_id = :enrollment_id")
        params["enrollment_id"] = enrollment_id
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    async with AsyncSessionLocal() as pg:
        rows = await pg.execute(
            text(f"""
                SELECT * FROM marketing_nurture_actions
                {where}
                ORDER BY scheduled_at ASC
                LIMIT :limit
            """),
            params,
        )
        return {"actions": [_serialize(r) for r in rows]}


async def _get_action_and_step(pg, action_id: str):
    action = await _fetch_one(
        pg,
        "SELECT * FROM marketing_nurture_actions WHERE id = :id",
        {"id": action_id},
    )
    if not action:
        raise HTTPException(status_code=404, detail="action not found")
    action_map = _serialize(action)
    step = await _fetch_one(
        pg,
        "SELECT * FROM marketing_nurture_steps WHERE id = :id",
        {"id": action_map["step_id"]},
    )
    step_map = _serialize(step) if step else {}
    return action_map, step_map


@api.post("/marketing-os/nurture/actions/{action_id}/approve")
async def approve_action(action_id: str,
                         user=Depends(require_roles(*MARKETING_ROLES))):
    actor_id = _uid(user)
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            action, step = await _get_action_and_step(pg, action_id)
            if action["status"] != "pending_approval":
                raise HTTPException(
                    status_code=409,
                    detail=f"action is {action['status']}",
                )

            action_type = action["action_type"]

            if action_type == "create_task":
                task_id = await execute_create_task(
                    pg, action=action, step=step, actor_id=actor_id
                )
                row = (await pg.execute(
                    text("""
                        UPDATE marketing_nurture_actions
                        SET status = 'approved',
                            approved_by = :actor, approved_at = now(),
                            executed_at = now(),
                            delivery_status = 'task_created',
                            lead_task_id = :task_id,
                            updated_at = now()
                        WHERE id = :id
                        RETURNING *
                    """),
                    {"actor": actor_id, "task_id": task_id, "id": action_id},
                )).first()

            elif action_type == "send_email":
                # Phase 8A: email is ALWAYS held. No send, no recipient stored.
                decision = email_hold_decision()
                row = (await pg.execute(
                    text("""
                        UPDATE marketing_nurture_actions
                        SET status = :status,
                            approved_by = :actor, approved_at = now(),
                            delivery_status = :delivery_status,
                            hold_reason = :hold_reason,
                            updated_at = now()
                        WHERE id = :id
                        RETURNING *
                    """),
                    {
                        "status": decision["status"],
                        "actor": actor_id,
                        "delivery_status": decision["delivery_status"],
                        "hold_reason": decision["hold_reason"],
                        "id": action_id,
                    },
                )).first()
                await _log_activity(
                    pg,
                    lead_id=action["lead_id"],
                    activity_type="nurture_email_held",
                    actor_id=actor_id,
                    summary="Nurture email approved but held (outreach off)",
                    details={
                        "action_id": action_id,
                        "hold_reason": decision["hold_reason"],
                        "sequence_id": action["sequence_id"],
                    },
                )
            else:
                raise HTTPException(
                    status_code=409,
                    detail=f"unsupported action_type: {action_type}",
                )
    return _serialize(row)


@api.post("/marketing-os/nurture/actions/{action_id}/skip")
async def skip_action(action_id: str, payload: ActionSkip,
                      user=Depends(require_roles(*MARKETING_ROLES))):
    actor_id = _uid(user)
    reason = "skipped"
    if payload.reason:
        reason = f"skipped:{str(payload.reason)[:120]}"
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            action = await _fetch_one(
                pg,
                "SELECT * FROM marketing_nurture_actions WHERE id = :id",
                {"id": action_id},
            )
            if not action:
                raise HTTPException(status_code=404, detail="action not found")
            action_map = _serialize(action)
            if action_map["status"] not in ("pending_approval", "scheduled"):
                raise HTTPException(
                    status_code=409,
                    detail=f"action is {action_map['status']}",
                )
            row = (await pg.execute(
                text("""
                    UPDATE marketing_nurture_actions
                    SET status = 'skipped', hold_reason = :reason,
                        approved_by = :actor, updated_at = now()
                    WHERE id = :id
                    RETURNING *
                """),
                {"reason": reason, "actor": actor_id, "id": action_id},
            )).first()
            await _log_activity(
                pg,
                lead_id=action_map["lead_id"],
                activity_type="nurture_action_skipped",
                actor_id=actor_id,
                summary="Nurture action skipped",
                details={"action_id": action_id, "reason": reason},
            )
    return _serialize(row)


# --------------------------------------------------------------------------- #
# Scheduler (manual tick) + overview
# --------------------------------------------------------------------------- #

@api.post("/marketing-os/nurture/scheduler/tick")
async def scheduler_tick(payload: Optional[TickRequest] = None,
                         user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    limit = 100
    if payload and payload.limit:
        limit = max(1, min(1000, int(payload.limit)))
    summary = await process_due_nurture_enrollments(limit=limit)
    summary["safety"] = SAFETY_STATE
    return summary


@api.get("/marketing-os/nurture/overview")
async def nurture_overview(user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    async with AsyncSessionLocal() as pg:
        seq_counts = await pg.execute(
            text("""
                SELECT status, count(*) AS c
                FROM marketing_nurture_sequences GROUP BY status
            """)
        )
        enr_counts = await pg.execute(
            text("""
                SELECT status, count(*) AS c
                FROM marketing_nurture_enrollments GROUP BY status
            """)
        )
        act_counts = await pg.execute(
            text("""
                SELECT status, count(*) AS c
                FROM marketing_nurture_actions GROUP BY status
            """)
        )
        overdue = await pg.execute(
            text("""
                SELECT * FROM marketing_nurture_actions
                WHERE status = 'pending_approval' AND scheduled_at <= now()
                ORDER BY scheduled_at ASC
                LIMIT 100
            """)
        )
        upcoming = await pg.execute(
            text("""
                SELECT * FROM marketing_nurture_actions
                WHERE status = 'pending_approval' AND scheduled_at > now()
                ORDER BY scheduled_at ASC
                LIMIT 100
            """)
        )
        overdue_actions = [_serialize(r) for r in overdue]
        upcoming_actions = [_serialize(r) for r in upcoming]
        return {
            "sequences_by_status": {
                r._mapping["status"]: int(r._mapping["c"])
                for r in seq_counts
            },
            "enrollments_by_status": {
                r._mapping["status"]: int(r._mapping["c"])
                for r in enr_counts
            },
            "actions_by_status": {
                r._mapping["status"]: int(r._mapping["c"])
                for r in act_counts
            },
            "pending_overdue_count": len(overdue_actions),
            "pending_upcoming_count": len(upcoming_actions),
            "overdue_actions": overdue_actions,
            "upcoming_actions": upcoming_actions,
            "safety": SAFETY_STATE,
        }
