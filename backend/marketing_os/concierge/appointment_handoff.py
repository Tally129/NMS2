"""
Internal appointment-request handoff for the NMS AI Concierge.

This module does NOT expose a public route.

Concierge appointment writes require:
  * explicit visitor confirmation;
  * an opaque client-generated idempotency key;
  * durable PostgreSQL uniqueness.

No conversation transcript, medical free text, notes, or add-ons are copied
into the appointment request.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.exc import IntegrityError

from models import AppointmentRequestIn, new_id
from postgres_db import AsyncSessionLocal
from repositories import scheduling as sched_repo


_IDEMPOTENCY_KEY_RE = re.compile(
    r"^[A-Za-z0-9_-]{16,128}$"
)


@dataclass(frozen=True)
class ConciergeAppointmentRequest:
    full_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    returning: Optional[str] = None
    service: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None

    # Internal backward compatibility only.
    # These are never forwarded by Concierge submission.
    notes: Optional[str] = None
    add_ons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConciergeAppointmentSubmission:
    appointment_request: dict
    replayed: bool


def _clean_optional(
    value: Optional[str],
    max_length: int,
) -> Optional[str]:
    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    return value[:max_length]


def _normalize_idempotency_key(
    value: str,
) -> str:
    key = str(value or "").strip()

    if not _IDEMPOTENCY_KEY_RE.fullmatch(
        key
    ):
        raise ValueError(
            "idempotency_key must be an opaque "
            "16-128 character URL-safe value"
        )

    return key


def hash_idempotency_key(
    value: str,
) -> str:
    key = _normalize_idempotency_key(
        value
    )

    return hashlib.sha256(
        key.encode("utf-8")
    ).hexdigest()


def build_appointment_document(
    request: ConciergeAppointmentRequest,
    *,
    client_ip: Optional[str] = None,
    concierge_idempotency_key: Optional[str] = None,
) -> dict:
    full_name = str(
        request.full_name or ""
    ).strip()

    if not full_name:
        raise ValueError(
            "full_name is required"
        )

    if len(full_name) > 200:
        raise ValueError(
            "full_name is too long"
        )

    returning = _clean_optional(
        request.returning,
        16,
    )

    if returning not in (
        None,
        "first",
        "returning",
    ):
        raise ValueError(
            "returning must be 'first' or 'returning'"
        )

    cleaned_add_ons = [
        str(value).strip()[:200]
        for value in request.add_ons
        if str(value).strip()
    ]

    if len(cleaned_add_ons) > 20:
        raise ValueError(
            "too many add-ons"
        )

    return {
        "id": new_id(),
        "fullName": full_name,
        "email": _clean_optional(
            request.email,
            320,
        ),
        "phone": _clean_optional(
            request.phone,
            40,
        ),
        "returning": returning,
        "service": _clean_optional(
            request.service,
            200,
        ),
        "date": _clean_optional(
            request.date,
            32,
        ),
        "time": _clean_optional(
            request.time,
            32,
        ),
        "notes": _clean_optional(
            request.notes,
            4000,
        ),
        "addOns": cleaned_add_ons,
        "status": "new",
        "ip": _clean_optional(
            client_ip,
            64,
        ),
        "concierge_idempotency_key":
            concierge_idempotency_key,
    }


async def _find_existing(
    key_hash: str,
) -> Optional[dict]:
    async with AsyncSessionLocal() as pg:
        return await (
            sched_repo
            .get_appointment_request_by_concierge_idempotency_key(
                pg,
                key_hash,
            )
        )


async def create_concierge_appointment_request(
    request: ConciergeAppointmentRequest,
    *,
    confirmed: bool,
    idempotency_key: str,
    client_ip: Optional[str] = None,
) -> ConciergeAppointmentSubmission:
    """
    Submit a Concierge-originated appointment request exactly once.

    Confirmation is enforced here at the server-side write boundary.
    The browser's opaque idempotency key is SHA-256 hashed before storage.
    """

    if confirmed is not True:
        raise ValueError(
            "explicit confirmation is required"
        )

    key_hash = hash_idempotency_key(
        idempotency_key
    )

    existing = await _find_existing(
        key_hash
    )

    if existing is not None:
        return ConciergeAppointmentSubmission(
            appointment_request=existing,
            replayed=True,
        )

    doc = build_appointment_document(
        request,
        client_ip=client_ip,
        concierge_idempotency_key=key_hash,
    )

    # Concierge deliberately strips legacy free-form fields before
    # handing the request to the canonical appointment workflow.
    from appointment_requests import (
        create_appointment_request_workflow,
    )

    payload = AppointmentRequestIn(
        fullName=doc["fullName"],
        email=doc["email"],
        phone=doc["phone"],
        returning=doc["returning"],
        service=doc["service"],
        date=doc["date"],
        time=doc["time"],
        notes=None,
        addOns=[],
    )

    try:
        created = await create_appointment_request_workflow(
            payload,
            client_ip=doc["ip"],
            user_agent="nms-ai-concierge",
            marketing_attribution=None,
            concierge_idempotency_key=key_hash,
        )

    except IntegrityError:
        # PostgreSQL uniqueness is authoritative if two identical
        # submissions race after the initial lookup.
        existing = await _find_existing(
            key_hash
        )

        if existing is None:
            raise

        return ConciergeAppointmentSubmission(
            appointment_request=existing,
            replayed=True,
        )

    return ConciergeAppointmentSubmission(
        appointment_request=created,
        replayed=False,
    )
