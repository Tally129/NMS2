"""
Telehealth routes: room/token/consent/recording APIs plus the
self-hosted WebRTC signaling WebSocket, chat, GridFS recording upload/
download, and AI-assisted live-SOAP drafting endpoints.

Extracted from server.py during Phase 16 refactor.
"""
from __future__ import annotations

import io
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import (
    Depends, File, HTTPException, Query, Request, UploadFile,
    WebSocket, WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse

from audit import get_client_ip, log_audit
from deps import (
    _resolve_self_client, _strip_id, api, db,
    get_current_user, logger, require_roles,
)
from storage import NotFound as StorageNotFound, get_storage
from models import TelehealthConsentIn, new_id
from auth_utils import decode_token
from pg_shims import find_client, find_intake_by_client, find_user_by_id
from postgres_db import AsyncSessionLocal
from repositories import scheduling as sched_repo


async def _get_appt(appt_id: str):
    """Wrapper: fetch an appointment as a dict from PostgreSQL."""
    async with AsyncSessionLocal() as pg:
        return await sched_repo.get_appointment(pg, appt_id)


def _json_safe(value):
    """Recursively convert values so PostgreSQL JSONB can serialize them."""
    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, dict):
        return {
            key: _json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]

    return value


async def _update_appt(appt_id: str, fields: dict) -> int:
    """Wrapper: update an appointment row with JSON-safe values."""
    safe_fields = _json_safe(fields)

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            return await sched_repo.update_appointment(
                pg,
                appt_id,
                safe_fields,
            )


# ---------- Waiting room helpers ----------
WAITING_ROOM_STATES = {
    "idle",
    "invited",
    "requested",
    "admitted",
    "declined",
    "expired",
    "ended",
}


def _serialize_waiting_room(wr: Optional[dict]) -> dict:
    if not wr:
        return {
            "state": "idle",
            "invited_at": None,
            "expires_at": None,
            "provider_id": None,
            "provider_name": None,
            "request_at": None,
            "admitted_at": None,
            "declined_at": None,
            "decline_reason": None,
            "ended_at": None,
        }

    return {
        "state": wr.get("state", "idle"),
        "invited_at": wr.get("invited_at"),
        "expires_at": wr.get("expires_at"),
        "provider_id": wr.get("provider_id"),
        "provider_name": wr.get("provider_name"),
        "request_at": wr.get("request_at"),
        "admitted_at": wr.get("admitted_at"),
        "declined_at": wr.get("declined_at"),
        "decline_reason": wr.get("decline_reason"),
        "ended_at": wr.get("ended_at"),
    }


async def _appointment_or_404(appt_id: str) -> dict:
    a = await _get_appt(appt_id)
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return a


async def _notify_visit_peers(appt_id: str, message: dict) -> None:
    """Best-effort broadcast to any peers connected to the WS for this appt."""
    room = _visit_rooms.get(appt_id) or {}
    for ws in list(room.values()):
        try:
            await ws.send_json(message)
        except Exception:
            pass


# ---------- Daily.co helpers (stubbed if DAILY_API_KEY unset) ----------
# ---------- Telehealth helpers ----------
DAILY_API_KEY = os.environ.get("DAILY_API_KEY", "")
DAILY_DOMAIN = os.environ.get("DAILY_DOMAIN", "")


async def daily_create_room(room_name: str, enable_recording: bool = False, enable_knocking: bool = True):
    """Create Daily room. Stubbed if no API key."""
    if not DAILY_API_KEY:
        return {
            "name": room_name,
            "url": f"https://stub.daily.local/{room_name}",
            "_stubbed": True,
        }
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(
                "https://api.daily.co/v1/rooms",
                headers={"Authorization": f"Bearer {DAILY_API_KEY}"},
                json={
                    "name": room_name,
                    "privacy": "private",
                    "properties": {
                        "enable_prejoin_ui": True,
                        "enable_knocking": enable_knocking,
                        "enable_chat": True,
                        "enable_screenshare": True,
                        "enable_recording": "cloud" if enable_recording else "off",
                    },
                },
            )
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.warning("Daily create_room failed: %s", e)
        return {"name": room_name, "url": f"https://stub.daily.local/{room_name}", "_stubbed": True, "error": str(e)}


async def daily_meeting_token(room_name: str, is_owner: bool, user_name: str, exp_minutes: int = 120):
    if not DAILY_API_KEY:
        return {"token": f"stub_token_{new_id()[:8]}", "_stubbed": True}
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(
                "https://api.daily.co/v1/meeting-tokens",
                headers={"Authorization": f"Bearer {DAILY_API_KEY}"},
                json={
                    "properties": {
                        "room_name": room_name,
                        "is_owner": is_owner,
                        "user_name": user_name,
                        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=exp_minutes)).timestamp()),
                    }
                },
            )
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.warning("Daily token failed: %s", e)
        return {"token": f"stub_token_{new_id()[:8]}", "_stubbed": True, "error": str(e)}


# ---------- Telehealth routes ----------
@api.post("/appointments/{appt_id}/telehealth/room")
async def create_telehealth_room(
    appt_id: str,
    request: Request,
    user=Depends(require_roles("practitioner", "admin", "staff")),
):
    a = await _get_appt(appt_id)
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if a.get("telehealth", {}).get("room_url"):
        return a["telehealth"]
    room_name = f"nms-{appt_id[:8]}"
    info = await daily_create_room(room_name, enable_recording=False, enable_knocking=True)
    telehealth = {
        "room_name": info.get("name", room_name),
        "room_url": info.get("url"),
        "waiting_room": True,
        "created_at": datetime.now(timezone.utc),
        "_stubbed": info.get("_stubbed", False),
    }
    await _update_appt(appt_id, {"telehealth": telehealth, "visit_mode": "telehealth"})
    await db.integration_log.insert_one({
        "id": new_id(), "service": "daily", "action": "room.create",
        "payload": {"appointment_id": appt_id, "room_name": room_name},
        "_stubbed": telehealth["_stubbed"], "ts": datetime.now(timezone.utc),
    })
    await log_audit(db, user["id"], user["email"], "telehealth.room_create",
                    resource_type="appointment", resource_id=appt_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return telehealth


@api.post("/appointments/{appt_id}/telehealth/invite")
async def invite_patient_to_telehealth(
    appt_id: str,
    request: Request,
    user=Depends(
        require_roles(
            "practitioner",
            "admin",
            "staff",
            "medical_assistant",
        )
    ),
):
    """Invite the assigned patient into an instant-visit waiting room."""
    appointment = await _appointment_or_404(appt_id)

    if appointment.get("visit_mode") != "telehealth":
        raise HTTPException(
            status_code=400,
            detail="This appointment is not a telehealth visit.",
        )

    assigned_provider_id = appointment.get("practitioner_id")

    if (
        user.get("role") == "practitioner"
        and assigned_provider_id
        and assigned_provider_id != user["id"]
    ):
        raise HTTPException(
            status_code=403,
            detail="Only the assigned provider may invite this patient.",
        )

    client = await find_client(
        client_id=appointment.get("client_id"),
    )

    if not client:
        raise HTTPException(
            status_code=404,
            detail="Patient not found",
        )

    patient_user_id = client.get("user_id")

    if not patient_user_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "patient_portal_account_required",
                "message": (
                    "This patient needs an active portal account before "
                    "an instant video invitation can be sent."
                ),
            },
        )

    patient_user = await find_user_by_id(patient_user_id)

    if not patient_user or not patient_user.get("is_active", True):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "patient_portal_account_inactive",
                "message": "The patient portal account is not active.",
            },
        )

    provider_id = assigned_provider_id or user["id"]
    provider = await find_user_by_id(provider_id)
    provider_name = (
        (provider or {}).get("full_name")
        or user.get("full_name")
        or "Your provider"
    )

    telehealth = appointment.get("telehealth") or {}

    if not telehealth.get("room_name"):
        room_name = f"nms-{appt_id[:8]}"
        info = await daily_create_room(
            room_name,
            enable_recording=False,
            enable_knocking=True,
        )

        telehealth = {
            "room_name": info.get("name", room_name),
            "room_url": info.get("url"),
            "waiting_room": True,
            "created_at": datetime.now(timezone.utc),
            "_stubbed": info.get("_stubbed", False),
        }

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=20)

    waiting_room = {
        "state": "invited",
        "invited_at": now,
        "expires_at": expires_at,
        "invited_by": user["id"],
        "provider_id": provider_id,
        "provider_name": provider_name,
        "request_at": None,
        "requested_by": None,
        "admitted_at": None,
        "admitted_by": None,
        "declined_at": None,
        "decline_reason": None,
        "ended_at": None,
    }

    await _update_appt(
        appt_id,
        {
            "telehealth": telehealth,
            "waiting_room": waiting_room,
            "status": "scheduled",
            "visit_mode": "telehealth",
        },
    )

    # Create or reuse a secure conversation dedicated to this appointment.
    thread = await db.message_threads.find_one({
        "linked_appointment_id": appt_id,
        "thread_type": "telehealth_invitation",
    })

    if not thread:
        thread = {
            "id": new_id(),
            "client_id": client["id"],
            "client_name": (
                client.get("full_name") or client.get("email")
            ),
            "practitioner_id": provider_id,
            "practitioner_name": provider_name,
            "subject": "Telehealth visit request",
            "thread_type": "telehealth_invitation",
            "linked_appointment_id": appt_id,
            "last_message_at": now,
            "last_message_preview": (
                "Your provider is inviting you to a video visit."
            ),
            "unread_for_client": 1,
            "unread_for_practitioner": 0,
            "created_at": now,
        }

        await db.message_threads.insert_one(thread)

    message = {
        "id": new_id(),
        "thread_id": thread["id"],
        "sender_id": user["id"],
        "sender_role": user.get("role"),
        "sender_name": (
            user.get("full_name") or user.get("email")
        ),
        "body": (
            f"{provider_name} is inviting you to a secure video visit. "
            "Open Telehealth and select Join waiting room."
        ),
        "attachment_file_ids": [],
        "read_by": [user["id"]],
        "message_type": "telehealth_invitation",
        "linked_appointment_id": appt_id,
        "action_url": f"/portal/visit/{appt_id}",
        "expires_at": expires_at,
        "created_at": now,
    }

    await db.messages.insert_one(message)

    await db.message_threads.update_one(
        {"id": thread["id"]},
        {
            "$set": {
                "last_message_at": now,
                "last_message_preview": message["body"][:140],
                "linked_appointment_id": appt_id,
                "thread_type": "telehealth_invitation",
            },
            "$inc": {"unread_for_client": 1},
        },
    )

    # Generic push only. No visit reason or other clinical detail.
    try:
        from notifiers import push_to_user

        await push_to_user(
            patient_user_id,
            "New telehealth request",
            "Your care team is inviting you to a secure video visit.",
            url="/portal/patient/telehealth",
            tag=f"telehealth-invite-{appt_id}",
        )
    except Exception as exc:
        logger.warning(
            "Telehealth invitation push failed for %s: %s",
            appt_id,
            exc,
        )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "telehealth.patient_invited",
        resource_type="appointment",
        resource_id=appt_id,
        metadata={
            "client_id": client["id"],
            "provider_id": provider_id,
            "expires_in_minutes": 20,
            "message_thread_id": thread["id"],
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    await _notify_visit_peers(
        appt_id,
        {
            "type": "waiting-room",
            **_serialize_waiting_room(waiting_room),
        },
    )

    return {
        "ok": True,
        "appointment_id": appt_id,
        "thread_id": thread["id"],
        "waiting_room": _serialize_waiting_room(waiting_room),
    }


@api.get("/appointments/{appt_id}/telehealth/token")
async def get_telehealth_token(appt_id: str, request: Request, user=Depends(get_current_user)):
    a = await _get_appt(appt_id)
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    # Access gate
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client or a["client_id"] != self_client["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
        if not a.get("consent_telehealth"):
            raise HTTPException(status_code=403, detail="Telehealth consent required")
    elif user["role"] not in ("practitioner", "admin", "staff"):
        raise HTTPException(status_code=403, detail="Forbidden")

    telehealth = a.get("telehealth") or {}
    if not telehealth.get("room_name"):
        # auto-create
        room_name = f"nms-{appt_id[:8]}"
        info = await daily_create_room(room_name)
        telehealth = {
            "room_name": info.get("name", room_name),
            "room_url": info.get("url"),
            "waiting_room": True,
            "created_at": datetime.now(timezone.utc),
            "_stubbed": info.get("_stubbed", False),
        }
        await _update_appt(appt_id, {"telehealth": telehealth})

    is_owner = user["role"] in ("practitioner", "admin", "staff")
    tok = await daily_meeting_token(telehealth["room_name"], is_owner=is_owner, user_name=user.get("full_name") or user["email"])
    await log_audit(db, user["id"], user["email"], "telehealth.token",
                    resource_type="appointment", resource_id=appt_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {
        "room_url": telehealth.get("room_url"),
        "room_name": telehealth.get("room_name"),
        "token": tok.get("token"),
        "is_owner": is_owner,
        "_stubbed": tok.get("_stubbed", False) or telehealth.get("_stubbed", False),
    }


@api.post("/appointments/{appt_id}/telehealth/consent")
async def telehealth_consent(appt_id: str, payload: TelehealthConsentIn, request: Request, user=Depends(get_current_user)):
    a = await _get_appt(appt_id)
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client or a["client_id"] != self_client["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
    now = datetime.now(timezone.utc)

    telehealth = dict(a.get("telehealth") or {})
    telehealth["recording_consent"] = bool(
        payload.recording_consent
    )
    telehealth["recording_consent_at"] = (
        now.isoformat()
        if payload.recording_consent
        else None
    )
    telehealth["recording_consent_signature"] = (
        payload.signature
        if payload.recording_consent
        else None
    )

    await _update_appt(appt_id, {
        "consent_telehealth": True,
        "consent_telehealth_at": now,
        "consent_telehealth_signature": payload.signature,
        "telehealth": telehealth,
    })
    await log_audit(db, user["id"], user["email"], "telehealth.consent",
                    resource_type="appointment", resource_id=appt_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


@api.post("/appointments/{appt_id}/telehealth/recording")
async def toggle_recording(appt_id: str, body: dict, user=Depends(require_roles("practitioner", "admin"))):
    """Stubbed start/stop recording."""
    action = (body or {}).get("action", "start")
    await db.integration_log.insert_one({
        "id": new_id(), "service": "daily", "action": f"recording.{action}",
        "payload": {"appointment_id": appt_id}, "_stubbed": not bool(DAILY_API_KEY),
        "ts": datetime.now(timezone.utc),
    })
    return {"ok": True, "action": action, "_stubbed": not bool(DAILY_API_KEY)}


# ---------- Self-hosted WebRTC signaling ----------

# Active sessions: {appt_id: {role: WebSocket}}
_visit_rooms = {}


# ---------- Waiting room ----------
@api.post("/appointments/{appt_id}/telehealth/request-join")
async def request_join(
    appt_id: str,
    request: Request,
    user=Depends(get_current_user),
):
    """Patient accepts an invitation and enters the waiting room."""
    if user.get("role") != "client":
        raise HTTPException(
            status_code=403,
            detail="Only the patient may join the waiting room.",
        )

    appointment = await _appointment_or_404(appt_id)
    self_client = await _resolve_self_client(user)

    if (
        not self_client
        or appointment.get("client_id") != self_client.get("id")
    ):
        raise HTTPException(
            status_code=403,
            detail="This visit does not belong to your account.",
        )

    waiting_room = appointment.get("waiting_room") or {}
    state = waiting_room.get("state") or "idle"

    expires_at = waiting_room.get("expires_at")

    if isinstance(expires_at, str):
        try:
            expires_at = datetime.fromisoformat(
                expires_at.replace("Z", "+00:00")
            )
        except ValueError:
            expires_at = None

    now = datetime.now(timezone.utc)

    if expires_at and expires_at < now:
        expired = {
            **waiting_room,
            "state": "expired",
            "expired_at": now,
        }

        await _update_appt(appt_id, {"waiting_room": expired})

        raise HTTPException(
            status_code=410,
            detail={
                "code": "telehealth_invitation_expired",
                "message": (
                    "This instant-visit invitation has expired. "
                    "Ask your provider to send a new invitation."
                ),
            },
        )

    if state not in {"invited", "requested", "admitted"}:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "visit_not_open",
                "message": (
                    "This visit is not currently accepting waiting-room "
                    "requests."
                ),
            },
        )

    # If the patient was already admitted, preserve that state.
    # This allows browser refreshes, network interruptions, and
    # device reconnects without requiring the provider to admit
    # the patient again.
    rejoining_active_visit = state == "admitted"

    new_waiting_room = {
        **waiting_room,
        "state": (
            "admitted"
            if rejoining_active_visit
            else "requested"
        ),
        "request_at": (
            waiting_room.get("request_at")
            if rejoining_active_visit
            else now
        ),
        "requested_by": (
            waiting_room.get("requested_by")
            if rejoining_active_visit
            else user["id"]
        ),
        "admitted_at": (
            waiting_room.get("admitted_at")
            if rejoining_active_visit
            else None
        ),
        "admitted_by": (
            waiting_room.get("admitted_by")
            if rejoining_active_visit
            else None
        ),
        "declined_at": None,
        "decline_reason": None,
    }

    await _update_appt(
        appt_id,
        {
            "waiting_room": new_waiting_room,
            "status": "arrived",
        },
    )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "telehealth.waiting_room_request",
        resource_type="appointment",
        resource_id=appt_id,
        metadata={"client_id": self_client["id"]},
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    await _notify_visit_peers(
        appt_id,
        {
            "type": "waiting-room",
            **_serialize_waiting_room(new_waiting_room),
        },
    )

    return _serialize_waiting_room(new_waiting_room)


@api.post("/appointments/{appt_id}/telehealth/admit")
async def admit_visitor(appt_id: str, request: Request,
                        user=Depends(require_roles("practitioner", "admin"))):
    """Provider admits the waiting patient. Only after this do WebRTC offers relay."""
    a = await _appointment_or_404(appt_id)
    wr = a.get("waiting_room") or {}
    if wr.get("state") not in ("requested", "admitted"):
        raise HTTPException(status_code=409, detail={
            "code": "no_pending_visitor",
            "state": wr.get("state") or "idle",
        })
    now = datetime.now(timezone.utc)
    new_wr = {**wr, "state": "admitted", "admitted_at": now, "admitted_by": user["id"]}
    await _update_appt(appt_id, {"waiting_room": new_wr})
    await log_audit(db, user["id"], user["email"], "telehealth.waiting_room_admit",
                    resource_type="appointment", resource_id=appt_id,
                    severity="info",
                    metadata={"client_id": a.get("client_id")},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    await _notify_visit_peers(appt_id, {"type": "waiting-room", **_serialize_waiting_room(new_wr)})
    return _serialize_waiting_room(new_wr)


@api.post("/appointments/{appt_id}/telehealth/decline")
async def decline_visitor(appt_id: str, payload: dict, request: Request,
                          user=Depends(require_roles("practitioner", "admin"))):
    """Provider declines the waiting patient with a short reason (shown to patient)."""
    a = await _appointment_or_404(appt_id)
    wr = a.get("waiting_room") or {}
    reason = (payload or {}).get("reason", "")
    reason = (reason or "").strip()
    if len(reason) < 3 or len(reason) > 240:
        raise HTTPException(status_code=400, detail={
            "code": "decline_reason_required",
            "message": "A short decline reason (3-240 chars) is required.",
        })
    if wr.get("state") not in ("requested", "admitted"):
        raise HTTPException(status_code=409, detail={
            "code": "no_pending_visitor",
            "state": wr.get("state") or "idle",
        })
    now = datetime.now(timezone.utc)
    new_wr = {**wr, "state": "declined", "declined_at": now,
              "decline_reason": reason, "declined_by": user["id"]}
    await _update_appt(appt_id, {"waiting_room": new_wr})
    await log_audit(db, user["id"], user["email"], "telehealth.waiting_room_decline",
                    resource_type="appointment", resource_id=appt_id,
                    severity="high", outcome="success",
                    metadata={"client_id": a.get("client_id"), "reason": reason[:200]},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    await _notify_visit_peers(appt_id, {"type": "waiting-room", **_serialize_waiting_room(new_wr)})
    return _serialize_waiting_room(new_wr)


@api.post("/appointments/{appt_id}/telehealth/end")
async def end_visit(
    appt_id: str,
    request: Request,
    body: Optional[dict] = None,
    user=Depends(
        require_roles("practitioner", "admin")
    ),
):
    """
    Provider ends a telehealth session.

    A clinical visit with recording consent must have either:
      1. a successfully persisted recording, or
      2. a documented recording exception.

    This prevents an admitted telehealth encounter from being
    silently ended without its documentation workflow.
    """
    a = await _appointment_or_404(appt_id)

    wr = a.get("waiting_room") or {}
    telehealth = dict(a.get("telehealth") or {})
    recordings = list(a.get("recordings") or [])
    payload = body or {}

    now = datetime.now(timezone.utc)

    exception_reason = str(
        payload.get("recording_exception_reason") or ""
    ).strip()

    exception_code = str(
        payload.get("recording_exception_code") or ""
    ).strip().lower()

    allowed_exception_codes = {
        "patient_declined",
        "consent_withdrawn",
        "technical_failure",
        "visit_did_not_occur",
        "other",
    }

    recording_consent = bool(
        telehealth.get("recording_consent")
    )

    has_recording = bool(recordings)

    # Once the patient consented to clinical recording, an admitted
    # encounter cannot quietly end without either the recording or
    # a documented exception.
    admitted = bool(
        wr.get("admitted_at")
        or wr.get("state") == "admitted"
    )

    if (
        admitted
        and not has_recording
    ):
        if (
            exception_code not in allowed_exception_codes
            or len(exception_reason) < 3
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "recording_or_exception_required",
                    "message": (
                        "This telehealth visit has no saved "
                        "recording. Stop and upload the recording "
                        "before ending the visit, or document why "
                        "recording could not be completed."
                    ),
                },
            )

    if has_recording:
        existing_documentation_status = str(
            telehealth.get("documentation_status") or ""
        ).strip().lower()

        if existing_documentation_status in {
            "transcription_failed",
            "soap_review_required",
            "complete",
        }:
            documentation_status = (
                existing_documentation_status
            )
        else:
            documentation_status = "transcribing"

        telehealth.update({
            "documentation_status":
                documentation_status,
            "recording_exception_code": None,
            "recording_exception_reason": None,
            "recording_exception_at": None,
            "recording_exception_by": None,
        })
    elif exception_reason:
        documentation_status = "recording_exception"

        telehealth.update({
            "documentation_status":
                documentation_status,
            "recording_exception_code":
                exception_code,
            "recording_exception_reason":
                exception_reason[:1000],
            "recording_exception_at":
                now.isoformat(),
            "recording_exception_by":
                user["id"],
        })
    else:
        # Waiting-room-only sessions may be ended without creating
        # a clinical recording exception.
        documentation_status = (
            telehealth.get("documentation_status")
            or "not_started"
        )

        telehealth["documentation_status"] = (
            documentation_status
        )

    new_wr = {
        **wr,
        "state": "ended",
        "ended_at": now,
        "ended_by": user["id"],
    }

    await _update_appt(
        appt_id,
        {
            "waiting_room": new_wr,
            "telehealth": telehealth,
        },
    )

    audit_action = (
        "telehealth.visit_end_recorded"
        if has_recording
        else (
            "telehealth.visit_end_recording_exception"
            if exception_reason
            else "telehealth.waiting_room_end"
        )
    )

    await log_audit(
        db,
        user["id"],
        user["email"],
        audit_action,
        resource_type="appointment",
        resource_id=appt_id,
        metadata={
            "client_id": a.get("client_id"),
            "has_recording": has_recording,
            "documentation_status":
                documentation_status,
            "recording_exception_code":
                exception_code or None,
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get(
            "user-agent"
        ),
    )

    await _notify_visit_peers(
        appt_id,
        {
            "type": "waiting-room",
            **_serialize_waiting_room(new_wr),
        },
    )

    return {
        **_serialize_waiting_room(new_wr),
        "documentation_status":
            documentation_status,
        "has_recording": has_recording,
    }


@api.get("/appointments/{appt_id}/telehealth/waiting-room")
async def waiting_room_status(appt_id: str, user=Depends(get_current_user)):
    """Poll waiting-room state (used by client + provider UIs)."""
    a = await _appointment_or_404(appt_id)
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client or a["client_id"] != self_client["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
    elif user["role"] not in ("practitioner", "admin", "staff", "medical_assistant"):
        raise HTTPException(status_code=403, detail="Forbidden")
    return _serialize_waiting_room(a.get("waiting_room"))


@api.get("/telehealth/waiting-room/queue")
async def waiting_room_queue(user=Depends(require_roles("practitioner", "admin", "staff", "medical_assistant"))):
    """Provider-facing queue: appointments with a client in the waiting room."""
    async with AsyncSessionLocal() as pg:
        rows = await sched_repo.list_appointments_with_waiting_state(
            pg, state="requested", limit=200,
        )
    out = []
    for a in rows:
        client = await find_client(client_id=a.get("client_id")) or {}
        out.append({
            "appointment_id": a.get("id"),
            "client_id": a.get("client_id"),
            "client_name": client.get("full_name") or client.get("email"),
            "start": a.get("start"),
            "visit_type": a.get("visit_type"),
            "reason": a.get("reason"),
            "waiting_room": _serialize_waiting_room(a.get("waiting_room")),
        })
    return out


@api.websocket("/ws/visit/{appt_id}")
async def ws_visit(websocket: WebSocket, appt_id: str,
                    token: Optional[str] = Query(None),
                    ticket: Optional[str] = Query(None)):
    """WebRTC signaling + chat relay. Auth via one-shot ticket (preferred) or JWT token (legacy)."""
    u = None
    if ticket:
        # One-shot ticket — burned on first use
        t = await db.ws_tickets.find_one_and_update(
            {"ticket": ticket, "appointment_id": appt_id, "used": False,
             "expires_at": {"$gte": datetime.now(timezone.utc)}},
            {"$set": {"used": True, "used_at": datetime.now(timezone.utc)}},
        )
        if not t:
            await websocket.close(code=4401)
            return
        u = await find_user_by_id(t["user_id"])
    elif token:
        try:
            payload = decode_token(token)
            u = await find_user_by_id(payload.get("sub"))
        except Exception:
            await websocket.close(code=4401)
            return
    if not u:
        await websocket.close(code=4401)
        return

    appt = await _get_appt(appt_id)
    if not appt:
        await websocket.close(code=4404)
        return

    role = "provider" if u["role"] in ("practitioner", "admin", "staff", "medical_assistant") else "client"
    if role == "client":
        sc = await _resolve_self_client(u)
        if not sc or appt.get("client_id") != sc["id"]:
            await websocket.close(code=4403)
            return

    await websocket.accept()
    room = _visit_rooms.setdefault(appt_id, {})
    # If a participant of the same role is already connected, close the old one
    if room.get(role):
        try:
            await room[role].close(code=4000)
        except Exception:
            pass
    room[role] = websocket

    # Tell both peers about presence
    other_role = "client" if role == "provider" else "provider"
    if room.get(other_role):
        try:
            await room[other_role].send_json({"type": "peer-joined", "role": role})
        except Exception:
            pass
    await websocket.send_json({"type": "joined", "role": role,
                               "peer_present": bool(room.get(other_role))})
    # Bootstrap the waiting-room state on both sides so UIs stay in sync.
    try:
        await websocket.send_json({"type": "waiting-room",
                                    **_serialize_waiting_room(appt.get("waiting_room"))})
    except Exception:
        pass

    # Audit join
    await log_audit(db, u["id"], u["email"], "telehealth.ws_join",
                    resource_type="appointment", resource_id=appt_id,
                    metadata={"role": role})

    try:
        while True:
            data = await websocket.receive_json()
            t = data.get("type")
            # WebRTC signaling is BLOCKED until the provider admits the client.
            if t in ("webrtc-offer", "webrtc-answer", "ice-candidate", "screen-share"):
                fresh = await _get_appt(appt_id)
                wr_state = ((fresh or {}).get("waiting_room") or {}).get("state")
                if wr_state != "admitted":
                    try:
                        await websocket.send_json({
                            "type": "waiting-room",
                            **_serialize_waiting_room((fresh or {}).get("waiting_room")),
                            "blocked": t,
                        })
                    except Exception:
                        pass
                    continue
                peer_ws = room.get(other_role)
                if peer_ws:
                    try:
                        await peer_ws.send_json({**data, "from": role})
                    except Exception:
                        pass
            elif t in ("chat", "media-state"):
                peer_ws = room.get(other_role)
                if peer_ws:
                    try:
                        await peer_ws.send_json({**data, "from": role})
                    except Exception:
                        pass
                if t == "chat":
                    # persist chat
                    from repositories import clinical_and_messaging as cm_repo
                    async with AsyncSessionLocal() as pg:
                        async with pg.begin():
                            await cm_repo.append_visit_chat(pg, {
                                "id": new_id(), "appointment_id": appt_id,
                                "sender_id": u["id"], "sender_role": role,
                                "body": data.get("body", "")[:2000],
                            })
            elif t == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("ws_visit error: %s", e)
    finally:
        if room.get(role) is websocket:
            room.pop(role, None)
        peer_ws = room.get(other_role)
        if peer_ws:
            try:
                await peer_ws.send_json({"type": "peer-left", "role": role})
            except Exception:
                pass
        if not room:
            _visit_rooms.pop(appt_id, None)
        await log_audit(db, u["id"], u["email"], "telehealth.ws_leave",
                        resource_type="appointment", resource_id=appt_id,
                        metadata={"role": role})


@api.get("/visits/{appt_id}/chat")
async def visit_chat_history(appt_id: str, user=Depends(get_current_user)):
    """Recent chat history for a visit (self-hosted)."""
    a = await _get_appt(appt_id)
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if user["role"] == "client":
        sc = await _resolve_self_client(user)
        if not sc or a.get("client_id") != sc["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
    from repositories import clinical_and_messaging as cm_repo
    async with AsyncSessionLocal() as pg:
        msgs = await cm_repo.list_visit_chat(pg, appt_id, limit=500)
    return msgs


# ---------- Visit recording upload (chunked WebM to GridFS) ----------
@api.post("/visits/{appt_id}/recording")
async def upload_visit_recording(
    appt_id: str,
    request: Request,
    file: UploadFile = File(...),
    user=Depends(require_roles("practitioner", "admin", "staff")),
):
    a = await _get_appt(appt_id)
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    contents = await file.read()
    fid = new_id()
    storage_key = f"visits/{appt_id}/{fid}.webm"
    upload_content_type = (
        file.content_type
        if file.content_type
        else "audio/webm"
    )

    obj_meta = await get_storage().put_bytes(
        storage_key,
        contents,
        content_type=upload_content_type,
        metadata={
            "appointment_id": appt_id,
            "uploader_id": user["id"],
            "kind": "visit_recording",
        },
    )
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await sched_repo.push_appointment_recording(pg, appt_id, {
                "file_id": fid, "storage_key": storage_key,
                "storage_backend": obj_meta.backend,
                "size": len(contents), "uploaded_by": user["id"],
                "ts": datetime.now(timezone.utc).isoformat(),
            })
    await log_audit(
        db,
        user["id"],
        user["email"],
        "telehealth.recording_upload",
        resource_type="appointment",
        resource_id=appt_id,
        metadata={"size": len(contents)},
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    # Start HealthScribe only after the recording has been
    # successfully persisted and attached to the appointment.
    transcription = None

    telehealth = a.get("telehealth") or {}

    if telehealth.get("recording_consent"):
        try:
            from services.telehealth_transcription import (
                normalize_recording_to_flac,
                start_job,
            )

            storage = get_storage()
            bucket = getattr(storage, "bucket", None)

            if (
                getattr(storage, "backend_name", "") == "s3"
                and bucket
            ):
                # Keep the original WebM recording, but create a
                # finalized FLAC copy specifically for HealthScribe.
                flac_contents = await normalize_recording_to_flac(
                    contents
                )

                transcription_key = (
                    f"visits/{appt_id}/"
                    f"{fid}.healthscribe.flac"
                )

                await storage.put_bytes(
                    transcription_key,
                    flac_contents,
                    content_type="audio/flac",
                    metadata={
                        "appointment_id": appt_id,
                        "source_recording_id": fid,
                        "kind": "healthscribe_input",
                    },
                )

                media_uri = (
                    f"s3://{bucket}/{transcription_key}"
                )

                transcription = await start_job(
                    appointment_id=appt_id,
                    recording_id=fid,
                    media_s3_uri=media_uri,
                )

                await log_audit(
                    db,
                    user["id"],
                    user["email"],
                    "telehealth.transcription_start",
                    resource_type="appointment",
                    resource_id=appt_id,
                    metadata={
                        "recording_id": fid,
                        "job_name": transcription.get(
                            "job_name"
                        ),
                    },
                    ip=get_client_ip(request),
                    user_agent=request.headers.get(
                        "user-agent"
                    ),
                )

                logger.info(
                    "HealthScribe started appointment=%s "
                    "recording=%s job=%s",
                    appt_id,
                    fid,
                    transcription.get("job_name"),
                )

        except Exception as exc:
            # Recording preservation must not fail merely because
            # downstream transcription could not start.
            logger.exception(
                "HealthScribe auto-start failed "
                "appointment=%s recording=%s: %s",
                appt_id,
                fid,
                exc,
            )

            transcription = {
                "status": "FAILED_TO_START",
                "error": str(exc),
            }

    # Persist documentation workflow state on the appointment.
    # The recording is already safely stored at this point.
    fresh = await _get_appt(appt_id)
    telehealth_state = dict(
        (fresh or a).get("telehealth") or {}
    )

    if (
        transcription
        and transcription.get("job_name")
    ):
        telehealth_state.update({
            "documentation_status": "transcribing",
            "transcription_job_name":
                transcription.get("job_name"),
            "transcription_status":
                transcription.get("status")
                or "IN_PROGRESS",
            "transcription_recording_id": fid,
            "transcription_started_at":
                datetime.now(timezone.utc).isoformat(),
        })
    elif (
        transcription
        and transcription.get("status")
        == "FAILED_TO_START"
    ):
        telehealth_state.update({
            "documentation_status":
                "transcription_failed",
            "transcription_status":
                "FAILED_TO_START",
            "transcription_recording_id": fid,
            "transcription_error":
                str(
                    transcription.get("error")
                    or ""
                )[:1000],
        })
    else:
        telehealth_state.update({
            "documentation_status":
                "recording_saved",
            "transcription_recording_id": fid,
        })

    await _update_appt(
        appt_id,
        {"telehealth": telehealth_state},
    )

    return {
        "file_id": fid,
        "size": len(contents),
        "transcription": transcription,
    }


@api.get("/visits/{appt_id}/recordings")
async def list_visit_recordings(appt_id: str, user=Depends(get_current_user)):
    """List recordings attached to an appointment."""
    a = await _get_appt(appt_id)
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if user["role"] == "client":
        sc = await _resolve_self_client(user)
        if not sc or a.get("client_id") != sc["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
    out = []
    for r in (a.get("recordings") or []):
        out.append({
            "file_id": r.get("file_id"),
            "size": r.get("size"),
            "ts": r.get("ts"),
            "uploaded_by": r.get("uploaded_by"),
            "download_url": f"/api/visits/{appt_id}/recordings/{r.get('file_id')}",
        })
    return out


@api.get("/visits/{appt_id}/recordings/{file_id}")
async def download_visit_recording(appt_id: str, file_id: str, request: Request,
                                   user=Depends(get_current_user)):
    """Stream a recorded visit WebM from GridFS. RBAC: client may only access their own."""
    a = await _get_appt(appt_id)
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if user["role"] == "client":
        sc = await _resolve_self_client(user)
        if not sc or a.get("client_id") != sc["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
    # Confirm file is bound to this appointment via recording metadata
    found = None
    for r in (a.get("recordings") or []):
        if r.get("file_id") == file_id:
            found = r
            break
    if not found:
        raise HTTPException(status_code=404, detail="Recording not found")
    storage_key = found.get("storage_key")
    if not storage_key:
        raise HTTPException(status_code=410, detail={
            "code": "storage_not_migrated",
            "message": "This recording lives in legacy GridFS. Run the S3 backfill script.",
        })
    try:
        stream_iter = get_storage().stream(storage_key)
    except StorageNotFound:
        raise HTTPException(status_code=404, detail="Recording not found in storage")
    await log_audit(db, user["id"], user["email"], "telehealth.recording_download",
                    resource_type="appointment", resource_id=appt_id,
                    metadata={"file_id": file_id},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return StreamingResponse(stream_iter, media_type="video/webm",
                             headers={"Content-Disposition": f'attachment; filename="visit-{appt_id}.webm"'})


# ---------- WS auth hardening: one-shot signed handshake ticket ----------
import secrets as _secrets

@api.post("/visits/{appt_id}/ws-ticket")
async def issue_ws_ticket(appt_id: str, user=Depends(get_current_user)):
    """Issue a one-shot ticket (60s TTL) so the WebSocket handshake never carries a JWT."""
    a = await _get_appt(appt_id)
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if user["role"] == "client":
        sc = await _resolve_self_client(user)
        if not sc or a.get("client_id") != sc["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
    ticket = _secrets.token_urlsafe(32)
    await db.ws_tickets.insert_one({
        "ticket": ticket, "appointment_id": appt_id,
        "user_id": user["id"], "user_role": user["role"],
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=60),
        "used": False,
    })
    return {"ticket": ticket, "expires_in": 60}


# ---------- WebRTC ICE config (STUN + optional TURN) ----------
@api.get("/webrtc/config")
async def webrtc_config(user=Depends(get_current_user)):
    """Return ICE servers — STUN public + optional self-hosted coturn from env."""
    servers = [
        {"urls": "stun:stun.l.google.com:19302"},
        {"urls": "stun:stun1.l.google.com:19302"},
    ]
    turn_url = os.environ.get("TURN_URL")
    if turn_url:
        entry = {"urls": turn_url}
        if os.environ.get("TURN_USERNAME"):
            entry["username"] = os.environ["TURN_USERNAME"]
        if os.environ.get("TURN_PASSWORD"):
            entry["credential"] = os.environ["TURN_PASSWORD"]
        servers.append(entry)
    return {"iceServers": servers}



# ---------- HealthScribe telehealth transcription ----------
@api.post("/visits/{appt_id}/transcription")
async def start_visit_transcription(
    appt_id: str,
    request: Request,
    user=Depends(
        require_roles(
            "practitioner",
            "admin",
        )
    ),
):
    """Start AWS HealthScribe for the latest recording on this visit."""
    appointment = await _get_appt(appt_id)

    if not appointment:
        raise HTTPException(
            status_code=404,
            detail="Appointment not found",
        )

    telehealth = appointment.get("telehealth") or {}

    if not telehealth.get("recording_consent"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "recording_consent_required",
                "message": (
                    "The patient has not consented to recording "
                    "and AI-assisted documentation."
                ),
            },
        )

    recordings = appointment.get("recordings") or []

    if not recordings:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "recording_required",
                "message": (
                    "Record and upload the telehealth visit "
                    "before generating a transcript."
                ),
            },
        )

    recording = recordings[-1]
    storage_key = recording.get("storage_key")
    recording_id = recording.get("file_id")

    if not storage_key or not recording_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "recording_not_migrated",
                "message": (
                    "The selected recording is not available "
                    "in object storage."
                ),
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

    media_uri = (
        f"s3://{bucket}/{storage_key}"
    )

    from services.telehealth_transcription import (
        start_job,
    )

    try:
        job = await start_job(
            appointment_id=appt_id,
            recording_id=recording_id,
            media_s3_uri=media_uri,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": str(exc)},
        )
    except Exception as exc:
        logger.warning(
            "HealthScribe start failed for %s: %s",
            appt_id,
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
        "telehealth.transcription_start",
        resource_type="appointment",
        resource_id=appt_id,
        metadata={
            "recording_id": recording_id,
            "job_name": job.get("job_name"),
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get(
            "user-agent"
        ),
    )

    return {
        "appointment_id": appt_id,
        "recording_id": recording_id,
        **job,
    }


@api.get("/visits/{appt_id}/transcription")
async def get_visit_transcription(
    appt_id: str,
    job_name: str,
    user=Depends(
        require_roles(
            "practitioner",
            "admin",
        )
    ),
):
    """Get AWS HealthScribe status and completed transcript outputs."""
    appointment = await _get_appt(appt_id)

    if not appointment:
        raise HTTPException(
            status_code=404,
            detail="Appointment not found",
        )

    # Prevent callers from using this endpoint as a generic
    # HealthScribe job lookup for unrelated encounters.
    expected_prefix = (
        f"nms-{appt_id}-"
    )

    if not job_name.startswith(
        expected_prefix
    ):
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
            detail={"code": str(exc)},
        )
    except Exception as exc:
        logger.warning(
            "HealthScribe status failed for %s: %s",
            appt_id,
            exc,
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "healthscribe_status_failed",
            },
        )

    result_status = str(
        result.get("status") or ""
    ).strip().upper()

    fresh = await _get_appt(appt_id)
    telehealth_state = dict(
        (fresh or appointment).get("telehealth") or {}
    )

    if result_status == "COMPLETED":
        telehealth_state.update({
            "documentation_status":
                "soap_review_required",
            "transcription_status": "COMPLETED",
            "transcription_completed_at":
                datetime.now(timezone.utc).isoformat(),
        })

        await _update_appt(
            appt_id,
            {"telehealth": telehealth_state},
        )

    elif result_status == "FAILED":
        telehealth_state.update({
            "documentation_status":
                "transcription_failed",
            "transcription_status": "FAILED",
            "transcription_error":
                str(
                    result.get("failure_reason")
                    or ""
                )[:1000],
        })

        await _update_appt(
            appt_id,
            {"telehealth": telehealth_state},
        )

    return {
        "appointment_id": appt_id,
        **result,
    }


# ---------- In-call SOAP autosave (provider-only) ----------
@api.put("/visits/{appt_id}/live-soap")
async def save_live_soap(appt_id: str, payload: dict,
                          user=Depends(require_roles("practitioner", "admin"))):
    a = await _get_appt(appt_id)
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    from repositories import clinical_and_messaging as cm_repo
    body = {
        "subjective": payload.get("subjective", ""),
        "objective": payload.get("objective", ""),
        "assessment": payload.get("assessment", ""),
        "plan": payload.get("plan", ""),
    }
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            saved = await cm_repo.upsert_live_soap(
                pg, id=new_id(), appointment_id=appt_id,
                author_id=user["id"], body=body,
            )
    return {"saved_at": (saved.get("updated_at") or datetime.now(timezone.utc)).isoformat()}


@api.get("/visits/{appt_id}/live-soap")
async def get_live_soap(appt_id: str, user=Depends(require_roles("practitioner", "admin"))):
    from repositories import clinical_and_messaging as cm_repo
    async with AsyncSessionLocal() as pg:
        d = await cm_repo.get_live_soap(pg, appt_id)
    if not d:
        return {"subjective": "", "objective": "", "assessment": "", "plan": ""}
    b = d.get("body") or {}
    return {**b, "updated_at": d.get("updated_at")}


@api.post("/visits/{appt_id}/promote-soap")
async def promote_live_soap(
    appt_id: str,
    request: Request,
    user=Depends(require_roles("practitioner")),
):
    """
    Promote the appointment's LiveSoapDraft into the permanent
    VisitNote workflow.

    Idempotent: if a VisitNote is already linked to this
    appointment, return that note instead of creating another.
    """
    appointment = await _get_appt(appt_id)

    if not appointment:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "appointment_not_found",
                "message": "Appointment not found.",
            },
        )

    if appointment.get("visit_mode") != "telehealth":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "not_telehealth_visit",
                "message":
                    "SOAP promotion is only available for "
                    "telehealth encounters.",
            },
        )

    client_id = appointment.get("client_id")

    if not client_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "appointment_missing_client",
                "message":
                    "This appointment is not linked to a patient.",
            },
        )

    from repositories import (
        clinical_and_messaging as cm_repo,
    )

    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as pg:
        async with pg.begin():

            # -------------------------------------------------
            # Never create duplicate encounter notes.
            # -------------------------------------------------

            existing = (
                await cm_repo.get_note_by_appointment(
                    pg,
                    appt_id,
                )
            )

            if existing:
                return {
                    "created": False,
                    "note_id": existing["id"],
                    "appointment_id": appt_id,
                    "status": existing.get("status"),
                    "note": existing,
                }

            # -------------------------------------------------
            # Retrieve the in-call/HealthScribe SOAP.
            # -------------------------------------------------

            live = await cm_repo.get_live_soap(
                pg,
                appt_id,
            )

            if not live:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "live_soap_not_found",
                        "message":
                            "No SOAP draft exists for this "
                            "telehealth encounter.",
                    },
                )

            body = live.get("body") or {}

            has_content = any(
                str(body.get(field) or "").strip()
                for field in (
                    "subjective",
                    "objective",
                    "assessment",
                    "plan",
                )
            )

            if not has_content:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "live_soap_empty",
                        "message":
                            "The telehealth SOAP draft is empty.",
                    },
                )

            # -------------------------------------------------
            # Create the permanent provider-owned VisitNote.
            # -------------------------------------------------

            note_id = new_id()

            note = await cm_repo.create_note(
                pg,
                {
                    "id": note_id,
                    "client_id": client_id,
                    "appointment_id": appt_id,
                    "practitioner_id": user["id"],
                    "practitioner_name":
                        user.get("full_name", ""),
                    "subjective":
                        body.get("subjective", ""),
                    "objective":
                        body.get("objective", ""),
                    "assessment":
                        body.get("assessment", ""),
                    "plan":
                        body.get("plan", ""),
                    "status": "draft",
                    "amendments": [],
                    "prior_versions": [],
                    "created_at": now,
                    "updated_at": now,
                    "finalized_at": None,
                    "finalized_by": None,
                },
            )

    # ---------------------------------------------------------
    # Keep encounter documentation state explicit.
    # ---------------------------------------------------------

    fresh = await _get_appt(appt_id)

    telehealth = dict(
        (fresh or appointment).get("telehealth") or {}
    )

    telehealth.update({
        "documentation_status":
            "soap_review_required",
        "draft_note_id": note["id"],
        "soap_promoted_at": now.isoformat(),
        "soap_promoted_by": user["id"],
    })

    await _update_appt(
        appt_id,
        {
            "telehealth": telehealth,
        },
    )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "telehealth.soap_promoted",
        resource_type="appointment",
        resource_id=appt_id,
        metadata={
            "client_id": client_id,
            "note_id": note["id"],
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get(
            "user-agent"
        ),
    )

    return {
        "created": True,
        "note_id": note["id"],
        "appointment_id": appt_id,
        "status": note.get("status"),
        "note": note,
    }


# ---------- Auto-draft visit summary from chat transcript ----------
@api.post("/visits/{appt_id}/auto-draft")
async def auto_draft_summary(appt_id: str, user=Depends(require_roles("practitioner", "admin"))):
    """Stitch chat transcript into a SOAP-shaped draft (rule-based, no LLM)."""
    a = await _get_appt(appt_id)
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    from repositories import clinical_and_messaging as cm_repo
    async with AsyncSessionLocal() as pg:
        msgs = await cm_repo.list_visit_chat(pg, appt_id, limit=500)
    client_lines = [m.get("body", "") for m in msgs if m.get("sender_role") == "client"]
    provider_lines = [m.get("body", "") for m in msgs if m.get("sender_role") == "provider"]
    subjective = " ".join(client_lines)[:2000]
    objective = "Telehealth visit · video and audio established · provider observed client throughout the visit."
    assessment = " ".join(provider_lines[: max(1, len(provider_lines) // 2)])[:1500]
    plan = " ".join(provider_lines[max(1, len(provider_lines) // 2):])[:1500]
    return {
        "subjective": subjective or "Client reported concerns during telehealth visit.",
        "objective": objective,
        "assessment": assessment or "Pending provider assessment.",
        "plan": plan or "Plan to be finalized by provider.",
        "source": "chat_transcript",
        "message_count": len(msgs),
    }


# ---------- LLM-assisted SOAP draft (Claude Sonnet 4.5 via Emergent LLM Key) ----------
@api.post("/visits/{appt_id}/llm-soap")
async def llm_soap_draft(appt_id: str, user=Depends(require_roles("practitioner", "admin"))):
    """Use Claude Sonnet 4.5 to draft a SOAP note from intake + last note + chat."""
    a = await _get_appt(appt_id)
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    client = await find_client(client_id=a.get("client_id"))
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    intake = await find_intake_by_client(client["id"]) or {}
    from repositories import clinical_and_messaging as cm_repo
    async with AsyncSessionLocal() as pg:
        notes = await cm_repo.list_notes_for_client(pg, client["id"], limit=1)
        msgs = await cm_repo.list_visit_chat(pg, appt_id, limit=500)
    last_note = notes[0] if notes else None
    transcript = "\n".join(
        f"[{m.get('sender_role','?')}] {m.get('body','')}" for m in msgs
    )[:6000]

    from llm_client import complete_text, DEFAULT_ANTHROPIC_MODEL, provider
    try:
        sys_msg = (
            "You are a clinical-documentation assistant helping a wellness practitioner "
            "draft a SOAP note from a telehealth visit. Output STRICT JSON with keys "
            "'subjective','objective','assessment','plan'. Keep each <250 words. "
            "Avoid medical diagnoses; this is a wellness setting. Never invent vitals you weren't told."
        )
        client_summary = (
            f"Client: {client.get('full_name','')} (MRN {client.get('mrn','')}). "
            f"Pronouns: {client.get('pronouns','—')}. "
            f"Primary concern: {client.get('primary_concern','—')}. "
            f"Wellness goals: {client.get('wellness_goals','—')}. "
            f"Allergies: {client.get('allergies','—')}. "
            f"Current supplements: {client.get('current_supplements','—')}."
        )
        intake_summary = ""
        if intake:
            intake_summary = "Recent intake answers:\n" + "\n".join(
                f"- {k}: {v}" for k, v in (intake.get("answers") or {}).items()
            )[:1500]
        last_summary = ""
        if last_note:
            last_summary = (
                "Previous SOAP note:\n"
                f"S: {last_note.get('subjective','')[:400]}\n"
                f"A: {last_note.get('assessment','')[:400]}\n"
                f"P: {last_note.get('plan','')[:400]}"
            )
        prompt = f"""{client_summary}

{intake_summary}

{last_summary}

In-call chat transcript:
{transcript or '(no chat messages were exchanged)'}

Produce a SOAP draft as STRICT JSON only — no commentary."""
        try:
            response = await complete_text(sys_msg, prompt, session_id=f"soap-{appt_id}")
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail={"code": str(exc)})
        # Robust JSON extraction
        import json as _json
        import re as _re
        m = _re.search(r"\{.*\}", response, _re.DOTALL)
        data = _json.loads(m.group(0)) if m else {}
        return {
            "subjective": data.get("subjective", "")[:4000],
            "objective": data.get("objective", "")[:4000],
            "assessment": data.get("assessment", "")[:4000],
            "plan": data.get("plan", "")[:4000],
            "source": "llm",
            "model": DEFAULT_ANTHROPIC_MODEL,
            "provider": provider(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("LLM SOAP draft failed: %s", e)
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")

