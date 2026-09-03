"""
Patient account-activity messages.

Creates non-human system messages for patient-facing account events such as
forms, appointments, invoices, payments, and other portal activity.

These messages live in the secure messaging data store so the patient sees
them in the consolidated Messages experience, but they remain distinguishable
from human care-team messages.
"""

from datetime import datetime, timezone
from typing import Optional

from deps import db
from models import new_id
from pg_shims import find_client


async def add_patient_activity_message(
    *,
    client_id: str,
    body: str,
    event_type: str,
    source_id: str,
    portal_path: Optional[str] = None,
    sender_role: str = "system",
    sender_name: str = "Natural Medical Solutions",
) -> Optional[dict]:
    """
    Add one idempotent system activity message for a patient.

    The event_type + source_id pair prevents duplicate activity messages if
    the originating operation is retried.
    """

    if not client_id or not body or not event_type or not source_id:
        return None

    client = await find_client(client_id=client_id)

    if not client or not client.get("user_id"):
        return None

    idempotency_key = f"patient-activity:{event_type}:{source_id}"

    existing = await db.messages.find_one({
        "activity_idempotency_key": idempotency_key,
    })

    if existing:
        return existing

    # Reuse the patient's most recent secure conversation when one exists.
    # If none exists, create a system-owned account activity thread.
    thread = await db.message_threads.find_one(
        {"client_id": client_id},
        sort=[("last_message_at", -1), ("created_at", -1)],
    )

    now = datetime.now(timezone.utc)

    if not thread:
        thread = {
            "id": new_id(),
            "client_id": client_id,
            "practitioner_id": None,
            "subject": "Account Updates",
            "thread_type": "patient_account_activity",
            "last_message_at": None,
            "last_message_preview": None,
            "created_at": now,
        }
        await db.message_threads.insert_one(thread)

    message = {
        "id": new_id(),
        "thread_id": thread["id"],
        "sender_id": "billing" if sender_role == "staff" else "system",
        "sender_role": sender_role,
        "sender_name": sender_name,
        "body": body,
        "attachment_file_ids": [],
        "read_by": [],
        "created_at": now,
        "message_type": "account_activity",
        "activity_event_type": event_type,
        "activity_source_id": source_id,
        "activity_idempotency_key": idempotency_key,
        "portal_path": portal_path,
    }

    await db.messages.insert_one(message)

    await db.message_threads.update_one(
        {"id": thread["id"]},
        {
            "$set": {
                "last_message_at": now,
                "last_message_preview": body[:140],
            }
        },
    )

    return message
