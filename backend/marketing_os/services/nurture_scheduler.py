"""Phase 8A nurture scheduler — deterministic, never sends.

Claims due nurture enrollments with ``FOR UPDATE SKIP LOCKED`` and materializes
the due step(s) into ``marketing_nurture_actions`` rows as ``pending_approval``.
It NEVER performs external outreach and NEVER sends email — it only queues
actions for human review, advances enrollment state, and applies deterministic
stop/suppression logic.

Idempotency: each materialized action carries a unique ``idempotency_key``
(``enrollment_id:position``) enforced by a DB unique constraint, so duplicate
scheduler executions cannot create duplicate actions.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text

from postgres_db import AsyncSessionLocal
from marketing_os.services.nurture import (
    idempotency_key_for,
    ordered_steps,
    scheduled_at_for,
    should_stop,
)

logger = logging.getLogger("nms.marketing.nurture")


def _new_id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None or isinstance(value, datetime):
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _preview_for(step: dict[str, Any]) -> dict[str, Any]:
    """Bounded, non-PHI snapshot of the queued action."""
    config = step.get("config") or {}
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except (TypeError, ValueError):
            config = {}
    preview: dict[str, Any] = {
        "action_type": step.get("action_type"),
        "channel": step.get("channel"),
        "title": step.get("title"),
        "step_key": step.get("step_key"),
    }
    if step.get("action_type") == "send_email":
        preview["subject"] = step.get("subject")
        preview["has_body"] = bool(step.get("body_html"))
    elif step.get("action_type") == "create_task":
        preview["task_type"] = (config or {}).get("task_type")
    return preview


async def _materialize_action(pg, *, enrollment: dict[str, Any],
                              step: dict[str, Any], sequence_id: str,
                              scheduled_at: datetime, position: int) -> bool:
    """Insert one pending_approval action idempotently. Returns True if new."""
    idem = idempotency_key_for(enrollment["id"], position)
    row = (await pg.execute(
        text("""
            INSERT INTO marketing_nurture_actions
                (id, enrollment_id, sequence_id, step_id, lead_id,
                 marketing_subject_id, action_type, channel, scheduled_at,
                 status, approval_required, subject, preview,
                 idempotency_key, created_at, updated_at)
            VALUES
                (:id, :enrollment_id, :sequence_id, :step_id, :lead_id,
                 :subject_id, :action_type, :channel, :scheduled_at,
                 'pending_approval', true, :subject, CAST(:preview AS jsonb),
                 :idem, now(), now())
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id
        """),
        {
            "id": _new_id(),
            "enrollment_id": enrollment["id"],
            "sequence_id": sequence_id,
            "step_id": step["id"],
            "lead_id": enrollment["lead_id"],
            "subject_id": enrollment["marketing_subject_id"],
            "action_type": step["action_type"],
            "channel": step.get("channel") or "internal",
            "scheduled_at": scheduled_at,
            "subject": step.get("subject"),
            "preview": json.dumps(_preview_for(step)),
            "idem": idem,
        },
    )).first()
    return row is not None


async def _process_one(pg, enrollment: dict[str, Any], *,
                       now: datetime, counts: dict[str, int]) -> None:
    seq_row = (await pg.execute(
        text("""
            SELECT id, stop_on_statuses
            FROM marketing_nurture_sequences
            WHERE id = :id
        """),
        {"id": enrollment["sequence_id"]},
    )).first()
    if seq_row is None:
        await _finish(pg, enrollment["id"], status="failed",
                      stop_reason="sequence_missing")
        counts["enrollments_stopped"] += 1
        return

    stop_statuses = seq_row._mapping["stop_on_statuses"] or []

    lead_row = (await pg.execute(
        text("SELECT id, lead_status FROM marketing_leads WHERE id = :id"),
        {"id": enrollment["lead_id"]},
    )).first()
    if lead_row is None:
        await _finish(pg, enrollment["id"], status="failed",
                      stop_reason="lead_missing")
        counts["enrollments_stopped"] += 1
        return

    lead_status = lead_row._mapping["lead_status"]

    if should_stop(lead_status, stop_statuses):
        await _finish(pg, enrollment["id"], status="stopped",
                      stop_reason=f"lead_status:{lead_status}")
        counts["enrollments_stopped"] += 1
        return

    step_rows = await pg.execute(
        text("""
            SELECT id, step_key, position, action_type, channel,
                   delay_minutes, title, subject, body_html, config
            FROM marketing_nurture_steps
            WHERE sequence_id = :sid
        """),
        {"sid": enrollment["sequence_id"]},
    )
    steps = ordered_steps(dict(r._mapping) for r in step_rows)

    enrolled_at = _parse_dt(enrollment["enrolled_at"]) or now
    pos = int(enrollment["current_step_position"])

    final_status = "active"
    next_run_at: Optional[datetime] = None
    stop_reason: Optional[str] = None

    # Drain all steps that are currently due for this enrollment.
    while True:
        if pos >= len(steps):
            final_status = "completed"
            next_run_at = None
            break

        step = steps[pos]
        sched = scheduled_at_for(enrolled_at, step)
        if sched > now:
            next_run_at = sched
            break

        if step["action_type"] == "wait":
            pos += 1
            counts["waits"] += 1
            continue

        created = await _materialize_action(
            pg,
            enrollment=enrollment,
            step=step,
            sequence_id=enrollment["sequence_id"],
            scheduled_at=sched,
            position=pos,
        )
        if created:
            counts["actions_created"] += 1
        pos += 1

    await pg.execute(
        text("""
            UPDATE marketing_nurture_enrollments
            SET current_step_position = :pos,
                status = :status,
                next_run_at = :next_run_at,
                stop_reason = :stop_reason,
                completed_at = :completed_at,
                updated_at = now()
            WHERE id = :id
        """),
        {
            "pos": pos,
            "status": final_status,
            "next_run_at": next_run_at,
            "stop_reason": stop_reason,
            "completed_at": (
                now if final_status in ("completed", "stopped", "failed")
                else None
            ),
            "id": enrollment["id"],
        },
    )
    if final_status == "completed":
        counts["enrollments_completed"] += 1


async def _finish(pg, enrollment_id: str, *, status: str,
                  stop_reason: str) -> None:
    await pg.execute(
        text("""
            UPDATE marketing_nurture_enrollments
            SET status = :status,
                stop_reason = :stop_reason,
                next_run_at = NULL,
                completed_at = now(),
                updated_at = now()
            WHERE id = :id
        """),
        {"status": status, "stop_reason": stop_reason, "id": enrollment_id},
    )


async def process_due_nurture_enrollments(*, limit: int = 100,
                                          now: Optional[datetime] = None
                                          ) -> dict[str, int]:
    """Process due enrollments once. Safe to call concurrently.

    Returns a summary of work performed. Never sends email or performs any
    external provider write.
    """
    now = now or _now()
    counts = {
        "claimed": 0,
        "actions_created": 0,
        "enrollments_completed": 0,
        "enrollments_stopped": 0,
        "waits": 0,
    }

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            rows = await pg.execute(
                text("""
                    SELECT id, sequence_id, lead_id, marketing_subject_id,
                           status, current_step_position, enrolled_at,
                           next_run_at
                    FROM marketing_nurture_enrollments
                    WHERE status = 'active'
                      AND next_run_at IS NOT NULL
                      AND next_run_at <= :now
                    ORDER BY next_run_at ASC
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                """),
                {"now": now, "limit": limit},
            )
            enrollments = [dict(r._mapping) for r in rows]
            counts["claimed"] = len(enrollments)

            for enrollment in enrollments:
                await _process_one(pg, enrollment, now=now, counts=counts)

    return counts
