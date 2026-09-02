"""Phase 8A nurture action dispatch — policy-gated, no automatic outreach.

This module centralizes what happens when a human approves a queued nurture
action:

- ``create_task`` actions execute internally: a Marketing OS Lead CRM task is
  created (reusing ``marketing_lead_tasks``) and the lead's ``next_action_*``
  fields are updated. No external provider is touched.

- ``send_email`` actions are ALWAYS held in Phase 8A. No real SendGrid send is
  performed, and no recipient email address is ever accepted or stored. The
  action records an auditable hold reason (``outreach_disabled``). There is no
  configuration flag that releases previously held actions; a future real-send
  capability must go through an explicit recipient-resolution/dispatch boundary
  with deliberate human authorization.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from sqlalchemy import text

# Auditable hold reason for held email actions.
OUTREACH_HOLD_REASON = "outreach_disabled"


def _new_id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


def email_hold_decision() -> dict[str, Any]:
    """Deterministic Phase 8A email outcome: always held, never sent."""
    return {
        "status": "held",
        "delivery_status": OUTREACH_HOLD_REASON,
        "hold_reason": OUTREACH_HOLD_REASON,
        "sent": False,
    }


async def _log_activity(pg, *, lead_id: str, activity_type: str,
                        actor_id: Optional[str], summary: str,
                        details: Mapping[str, Any]) -> None:
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
            "details": json.dumps(dict(details)),
        },
    )


async def execute_create_task(pg, *, action: Mapping[str, Any],
                              step: Mapping[str, Any],
                              actor_id: Optional[str]) -> str:
    """Create a Lead CRM task from an approved create_task action.

    Reuses existing ``marketing_lead_tasks`` + ``marketing_leads`` tables.
    Returns the new task id. Caller manages the transaction.
    """
    config = step.get("config") or {}
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except (TypeError, ValueError):
            config = {}

    task_type = str(config.get("task_type") or "follow_up_later").strip().lower()
    notes = config.get("notes")
    owner_id = config.get("owner_id") or action.get("assigned_owner_id")

    due_at = None
    due_in = config.get("due_in_minutes")
    if isinstance(due_in, int) and not isinstance(due_in, bool):
        due_at = _now() + timedelta(minutes=due_in)

    task_id = _new_id()
    lead_id = action["lead_id"]

    await pg.execute(
        text("""
            INSERT INTO marketing_lead_tasks
                (id, lead_id, task_type, owner_id, due_at, status,
                 notes, created_by, created_at, updated_at)
            VALUES
                (:id, :lead_id, :task_type, :owner_id, :due_at, 'open',
                 :notes, :created_by, now(), now())
        """),
        {
            "id": task_id,
            "lead_id": lead_id,
            "task_type": task_type,
            "owner_id": owner_id,
            "due_at": due_at,
            "notes": notes,
            "created_by": actor_id,
        },
    )

    # Reuse existing next-action fields on the lead (do not overwrite an
    # earlier/sooner scheduled action).
    await pg.execute(
        text("""
            UPDATE marketing_leads
            SET next_action_type = :task_type,
                next_action_at = COALESCE(
                    LEAST(next_action_at, :due_at), :due_at, next_action_at
                ),
                last_activity_at = now(),
                updated_at = now()
            WHERE id = :lead_id
        """),
        {"task_type": task_type, "due_at": due_at, "lead_id": lead_id},
    )

    await _log_activity(
        pg,
        lead_id=lead_id,
        activity_type="nurture_task_created",
        actor_id=actor_id,
        summary=f"Nurture task created: {task_type}",
        details={
            "action_id": action["id"],
            "task_id": task_id,
            "task_type": task_type,
            "sequence_id": action.get("sequence_id"),
        },
    )

    return task_id
