"""Clinical + Messaging + Files repositories (Phases 3.3 / 3.4).

Small, focused CRUD surface — routers still own their business logic. Every
helper opens/uses an AsyncSession supplied by the caller.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from postgres_models.clinical_and_messaging import (
    ClinicalDelegation, FormSubmission, FormTemplate, LabValue,
    LiveSoapDraft, Message, MessageThread, PushSubscription, SoapTemplate,
    Treatment, TreatmentPlan, VisitChat, VisitNote,
)


# =============================================================== helpers #
def _row_to_dict(row, cols: Iterable[str]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return {k: getattr(row, k) for k in cols}


_NOTE_COLS = (
    "id", "client_id", "practitioner_id", "practitioner_name",
    "drafted_by_id", "drafted_by_name", "drafted_by_role", "appointment_id",
    "subjective", "objective", "assessment", "plan", "free_text",
    "status", "finalized_at", "finalized_by",
    "prev_hash", "note_hash", "amendments", "prior_versions",
    "legacy_mongo_id", "created_at", "updated_at",
)


def note_to_dict(n) -> Optional[Dict[str, Any]]:
    return _row_to_dict(n, _NOTE_COLS)


# =============================================================== notes #
async def get_note(session: AsyncSession, note_id: str) -> Optional[Dict[str, Any]]:
    row = (await session.execute(
        select(VisitNote).where(VisitNote.id == note_id)
    )).scalar_one_or_none()
    return note_to_dict(row)


async def list_notes_for_client(session: AsyncSession, client_id: str,
                                  limit: int = 500) -> List[Dict[str, Any]]:
    stmt = (select(VisitNote)
            .where(VisitNote.client_id == client_id)
            .order_by(VisitNote.created_at.desc())
            .limit(limit))
    return [note_to_dict(n) for n in (await session.execute(stmt)).scalars().all()]


async def list_notes_by_practitioner(session: AsyncSession, prac_id: str,
                                        limit: int = 200) -> List[Dict[str, Any]]:
    stmt = (select(VisitNote)
            .where(VisitNote.practitioner_id == prac_id)
            .order_by(VisitNote.created_at.desc())
            .limit(limit))
    return [note_to_dict(n) for n in (await session.execute(stmt)).scalars().all()]


async def create_note(session: AsyncSession, doc: Dict[str, Any]) -> Dict[str, Any]:
    valid = {k: v for k, v in doc.items() if hasattr(VisitNote, k)}
    valid.setdefault("status", "draft")
    valid.setdefault("amendments", [])
    valid.setdefault("prior_versions", [])
    row = VisitNote(**valid)
    session.add(row)
    await session.flush()
    return note_to_dict(row)


async def update_note(session: AsyncSession, note_id: str,
                        fields: Dict[str, Any]) -> int:
    valid = {k: v for k, v in fields.items() if hasattr(VisitNote, k)}
    if not valid:
        return 0
    r = await session.execute(
        update(VisitNote).where(VisitNote.id == note_id).values(**valid)
    )
    return r.rowcount or 0


async def prev_note_hash_for_practitioner(session: AsyncSession,
                                            prac_id: str) -> str:
    """Return the `note_hash` of the last finalized note for `prac_id`, or
    the string `GENESIS` when the practitioner has none.
    """
    stmt = (select(VisitNote.note_hash)
            .where(VisitNote.practitioner_id == prac_id,
                   VisitNote.status == "finalized",
                   VisitNote.note_hash.is_not(None))
            .order_by(VisitNote.finalized_at.desc())
            .limit(1))
    row = (await session.execute(stmt)).scalar_one_or_none()
    return row or "GENESIS"


def compute_note_hash(note: Dict[str, Any], prev_hash: str) -> str:
    """SHA-256 over a canonical JSON representation of the finalized content.
    Deterministic — the same clinical payload always produces the same hash.
    """
    canonical = {
        "id": note.get("id"),
        "client_id": note.get("client_id"),
        "practitioner_id": note.get("practitioner_id"),
        "subjective": note.get("subjective") or "",
        "objective": note.get("objective") or "",
        "assessment": note.get("assessment") or "",
        "plan": note.get("plan") or "",
        "free_text": note.get("free_text") or "",
        "prev_hash": prev_hash,
    }
    blob = json.dumps(canonical, sort_keys=True,
                       separators=(",", ":"), default=str).encode()
    return hashlib.sha256(blob).hexdigest()


async def finalize_note(session: AsyncSession, note_id: str, *,
                          user_id: str) -> Optional[Dict[str, Any]]:
    """Idempotently finalize a note, computing + storing the hash chain."""
    note = await get_note(session, note_id)
    if not note:
        return None
    if note["status"] == "finalized":
        return note
    prac = note.get("practitioner_id") or ""
    prev_hash = await prev_note_hash_for_practitioner(session, prac)
    now = datetime.now(timezone.utc)
    final = {**note, "prev_hash": prev_hash}
    final["note_hash"] = compute_note_hash(final, prev_hash)
    await update_note(session, note_id, {
        "status": "finalized",
        "finalized_at": now,
        "finalized_by": user_id,
        "prev_hash": prev_hash,
        "note_hash": final["note_hash"],
    })
    return await get_note(session, note_id)


async def append_amendment(session: AsyncSession, note_id: str,
                             amendment: Dict[str, Any]) -> int:
    row = (await session.execute(
        select(VisitNote).where(VisitNote.id == note_id)
    )).scalar_one_or_none()
    if not row:
        return 0
    existing = list(row.amendments or [])
    existing.append(amendment)
    row.amendments = existing
    row.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return 1


# ========================================================== treatments #
_TP_COLS = ("id", "client_id", "practitioner_id", "title", "body", "goals",
            "interventions", "status", "starts_at", "ends_at",
            "legacy_mongo_id", "created_at", "updated_at")


def treatment_plan_to_dict(t) -> Optional[Dict[str, Any]]:
    return _row_to_dict(t, _TP_COLS)


async def list_treatment_plans(session: AsyncSession, *,
                                  client_id: Optional[str] = None,
                                  title_regex: Optional[str] = None,
                                  limit: int = 200) -> List[Dict[str, Any]]:
    stmt = select(TreatmentPlan)
    if client_id:
        stmt = stmt.where(TreatmentPlan.client_id == client_id)
    if title_regex:
        stmt = stmt.where(TreatmentPlan.title.op("~*")(title_regex))
    stmt = stmt.order_by(TreatmentPlan.created_at.desc()).limit(limit)
    return [treatment_plan_to_dict(t) for t in (await session.execute(stmt)).scalars().all()]


async def create_treatment_plan(session: AsyncSession,
                                  doc: Dict[str, Any]) -> Dict[str, Any]:
    valid = {k: v for k, v in doc.items() if hasattr(TreatmentPlan, k)}
    row = TreatmentPlan(**valid)
    session.add(row)
    await session.flush()
    return treatment_plan_to_dict(row)


_TR_COLS = ("id", "client_id", "created_by", "client_name", "created_by_name",
            "kind", "notes", "data", "ts", "legacy_mongo_id")


def treatment_to_dict(t) -> Optional[Dict[str, Any]]:
    return _row_to_dict(t, _TR_COLS)


async def list_treatments(session: AsyncSession, *,
                             client_id: Optional[str] = None,
                             limit: int = 200) -> List[Dict[str, Any]]:
    stmt = select(Treatment)
    if client_id:
        stmt = stmt.where(Treatment.client_id == client_id)
    stmt = stmt.order_by(Treatment.ts.desc()).limit(limit)
    return [treatment_to_dict(t) for t in (await session.execute(stmt)).scalars().all()]


async def create_treatment(session: AsyncSession,
                             doc: Dict[str, Any]) -> Dict[str, Any]:
    valid = {k: v for k, v in doc.items() if hasattr(Treatment, k)}
    row = Treatment(**valid)
    session.add(row)
    await session.flush()
    return treatment_to_dict(row)


# ========================================================== lab_values #
_LV_COLS = ("id", "client_id", "marker", "value", "unit", "reference_range",
            "collected_at", "ordering_provider_id", "ordering_provider_name",
            "status", "tasks", "notes", "legacy_mongo_id", "created_at")


def lab_to_dict(lv) -> Optional[Dict[str, Any]]:
    return _row_to_dict(lv, _LV_COLS)


async def get_lab(session: AsyncSession, lab_id: str) -> Optional[Dict[str, Any]]:
    row = (await session.execute(
        select(LabValue).where(LabValue.id == lab_id)
    )).scalar_one_or_none()
    return lab_to_dict(row)


async def list_labs(session: AsyncSession, *,
                      client_id: Optional[str] = None,
                      status_in: Optional[Iterable[str]] = None,
                      limit: int = 200) -> List[Dict[str, Any]]:
    stmt = select(LabValue)
    conds = []
    if client_id:
        conds.append(LabValue.client_id == client_id)
    if status_in:
        conds.append(LabValue.status.in_(list(status_in)))
    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.order_by(LabValue.created_at.desc()).limit(limit)
    return [lab_to_dict(lv) for lv in (await session.execute(stmt)).scalars().all()]


async def create_lab(session: AsyncSession,
                       doc: Dict[str, Any]) -> Dict[str, Any]:
    valid = {k: v for k, v in doc.items() if hasattr(LabValue, k)}
    valid.setdefault("status", "new")
    valid.setdefault("tasks", [])
    row = LabValue(**valid)
    session.add(row)
    await session.flush()
    return lab_to_dict(row)


async def update_lab(session: AsyncSession, lab_id: str,
                       fields: Dict[str, Any]) -> int:
    valid = {k: v for k, v in fields.items() if hasattr(LabValue, k)}
    if not valid:
        return 0
    r = await session.execute(
        update(LabValue).where(LabValue.id == lab_id).values(**valid)
    )
    return r.rowcount or 0


# ==================================================== live_soap_drafts #
async def get_live_soap(session: AsyncSession, appt_id: str) -> Optional[Dict[str, Any]]:
    row = (await session.execute(
        select(LiveSoapDraft).where(LiveSoapDraft.appointment_id == appt_id)
    )).scalar_one_or_none()
    if not row:
        return None
    return {"id": row.id, "appointment_id": row.appointment_id,
            "author_id": row.author_id, "body": row.body,
            "version": row.version, "updated_at": row.updated_at}


async def upsert_live_soap(session: AsyncSession, *, id: str,
                              appointment_id: str, author_id: str,
                              body: dict) -> Dict[str, Any]:
    existing = (await session.execute(
        select(LiveSoapDraft).where(LiveSoapDraft.appointment_id == appointment_id)
    )).scalar_one_or_none()
    if existing:
        existing.body = body
        existing.author_id = author_id
        existing.version = (existing.version or 0) + 1
        existing.updated_at = datetime.now(timezone.utc)
        await session.flush()
        return await get_live_soap(session, appointment_id)
    session.add(LiveSoapDraft(id=id, appointment_id=appointment_id,
                                author_id=author_id, body=body, version=1))
    await session.flush()
    return await get_live_soap(session, appointment_id)


# =========================================================== visit_chat #
async def list_visit_chat(session: AsyncSession, appt_id: str,
                            limit: int = 200) -> List[Dict[str, Any]]:
    stmt = (select(VisitChat)
            .where(VisitChat.appointment_id == appt_id)
            .order_by(VisitChat.ts.asc())
            .limit(limit))
    return [{"id": r.id, "appointment_id": r.appointment_id,
             "sender_id": r.sender_id, "sender_role": r.sender_role,
             "body": r.body, "ts": r.ts}
            for r in (await session.execute(stmt)).scalars().all()]


async def append_visit_chat(session: AsyncSession, doc: Dict[str, Any]) -> Dict[str, Any]:
    valid = {k: v for k, v in doc.items() if hasattr(VisitChat, k)}
    row = VisitChat(**valid)
    session.add(row)
    await session.flush()
    return {"id": row.id, "appointment_id": row.appointment_id,
             "sender_id": row.sender_id, "sender_role": row.sender_role,
             "body": row.body, "ts": row.ts}


# =================================================== clinical_delegations #
_DEL_COLS = ("id", "provider_id", "delegate_id", "client_id", "scope",
             "active", "expires_at", "reason", "revoked_at", "revoked_by",
             "revoke_reason", "legacy_mongo_id", "created_at")


def delegation_to_dict(d) -> Optional[Dict[str, Any]]:
    return _row_to_dict(d, _DEL_COLS)


async def find_active_delegation(session: AsyncSession, *, delegate_id: str,
                                    client_id: str) -> Optional[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    stmt = (select(ClinicalDelegation).where(
        ClinicalDelegation.delegate_id == delegate_id,
        ClinicalDelegation.client_id == client_id,
        ClinicalDelegation.active.is_(True),
        or_(ClinicalDelegation.expires_at.is_(None),
             ClinicalDelegation.expires_at > now),
    ).order_by(ClinicalDelegation.created_at.desc()).limit(1))
    return delegation_to_dict((await session.execute(stmt)).scalar_one_or_none())


async def list_delegations(session: AsyncSession, *,
                              provider_id: Optional[str] = None,
                              delegate_id: Optional[str] = None,
                              active_only: bool = False,
                              limit: int = 200) -> List[Dict[str, Any]]:
    stmt = select(ClinicalDelegation)
    if provider_id:
        stmt = stmt.where(ClinicalDelegation.provider_id == provider_id)
    if delegate_id:
        stmt = stmt.where(ClinicalDelegation.delegate_id == delegate_id)
    if active_only:
        stmt = stmt.where(ClinicalDelegation.active.is_(True))
    stmt = stmt.order_by(ClinicalDelegation.created_at.desc()).limit(limit)
    return [delegation_to_dict(d) for d in (await session.execute(stmt)).scalars().all()]


async def create_delegation(session: AsyncSession,
                              doc: Dict[str, Any]) -> Dict[str, Any]:
    valid = {k: v for k, v in doc.items() if hasattr(ClinicalDelegation, k)}
    valid.setdefault("active", True)
    row = ClinicalDelegation(**valid)
    session.add(row)
    await session.flush()
    return delegation_to_dict(row)


async def revoke_delegation(session: AsyncSession, deleg_id: str, *,
                              by_id: str, reason: Optional[str] = None) -> int:
    r = await session.execute(
        update(ClinicalDelegation).where(ClinicalDelegation.id == deleg_id)
        .values(active=False, revoked_at=datetime.now(timezone.utc),
                revoked_by=by_id, revoke_reason=reason)
    )
    return r.rowcount or 0


# ============================================================ messaging #
async def create_thread(session: AsyncSession, doc: Dict[str, Any]) -> Dict[str, Any]:
    valid = {k: v for k, v in doc.items() if hasattr(MessageThread, k)}
    row = MessageThread(**valid)
    session.add(row)
    await session.flush()
    return {"id": row.id, "client_id": row.client_id,
             "practitioner_id": row.practitioner_id,
             "subject": row.subject, "last_message_at": row.last_message_at,
             "created_at": row.created_at}


async def get_thread(session: AsyncSession, tid: str) -> Optional[Dict[str, Any]]:
    row = (await session.execute(
        select(MessageThread).where(MessageThread.id == tid)
    )).scalar_one_or_none()
    if not row:
        return None
    return {"id": row.id, "client_id": row.client_id,
             "practitioner_id": row.practitioner_id,
             "subject": row.subject, "last_message_at": row.last_message_at,
             "created_at": row.created_at}


async def list_threads(session: AsyncSession, *,
                          client_id: Optional[str] = None,
                          practitioner_id: Optional[str] = None,
                          limit: int = 100) -> List[Dict[str, Any]]:
    stmt = select(MessageThread)
    if client_id:
        stmt = stmt.where(MessageThread.client_id == client_id)
    if practitioner_id:
        stmt = stmt.where(MessageThread.practitioner_id == practitioner_id)
    stmt = stmt.order_by(MessageThread.last_message_at.desc().nullslast()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return [{"id": r.id, "client_id": r.client_id,
              "practitioner_id": r.practitioner_id, "subject": r.subject,
              "last_message_at": r.last_message_at,
              "created_at": r.created_at} for r in rows]


async def create_message(session: AsyncSession,
                            doc: Dict[str, Any]) -> Dict[str, Any]:
    valid = {k: v for k, v in doc.items() if hasattr(Message, k)}
    row = Message(**valid)
    session.add(row)
    await session.flush()
    # Bump thread.last_message_at
    if row.thread_id:
        await session.execute(
            update(MessageThread).where(MessageThread.id == row.thread_id)
            .values(last_message_at=row.created_at)
        )
    return {"id": row.id, "thread_id": row.thread_id,
             "sender_id": row.sender_id, "sender_role": row.sender_role,
             "body": row.body, "read_at": row.read_at,
             "created_at": row.created_at}


async def list_messages(session: AsyncSession, thread_id: str,
                           limit: int = 500) -> List[Dict[str, Any]]:
    stmt = (select(Message)
            .where(Message.thread_id == thread_id)
            .order_by(Message.created_at.asc()).limit(limit))
    return [{"id": m.id, "thread_id": m.thread_id,
              "sender_id": m.sender_id, "sender_role": m.sender_role,
              "body": m.body, "read_at": m.read_at,
              "created_at": m.created_at}
            for m in (await session.execute(stmt)).scalars().all()]


# =========================================================== forms #
async def list_form_templates(session: AsyncSession, *,
                                 builtin: Optional[bool] = None,
                                 limit: int = 200) -> List[Dict[str, Any]]:
    stmt = select(FormTemplate)
    if builtin is not None:
        stmt = stmt.where(FormTemplate.builtin.is_(builtin))
    stmt = stmt.order_by(FormTemplate.title.asc()).limit(limit)
    return [{"id": t.id, "title": t.title, "builtin": t.builtin,
              "schema": t.schema, "version": t.version,
              "created_at": t.created_at}
            for t in (await session.execute(stmt)).scalars().all()]


async def get_form_template(session: AsyncSession, tid: str) -> Optional[Dict[str, Any]]:
    row = (await session.execute(
        select(FormTemplate).where(FormTemplate.id == tid)
    )).scalar_one_or_none()
    if not row:
        return None
    return {"id": row.id, "title": row.title, "builtin": row.builtin,
             "schema": row.schema, "version": row.version,
             "created_at": row.created_at}


async def create_form_template(session: AsyncSession,
                                  doc: Dict[str, Any]) -> Dict[str, Any]:
    valid = {k: v for k, v in doc.items() if hasattr(FormTemplate, k)}
    valid.setdefault("builtin", False)
    valid.setdefault("version", 1)
    row = FormTemplate(**valid)
    session.add(row)
    await session.flush()
    return await get_form_template(session, row.id)


async def get_submission_by_token(session: AsyncSession,
                                     token: str) -> Optional[Dict[str, Any]]:
    row = (await session.execute(
        select(FormSubmission).where(FormSubmission.token == token)
    )).scalar_one_or_none()
    return _sub(row) if row else None


def _sub(row) -> Dict[str, Any]:
    return {"id": row.id, "token": row.token, "template_id": row.template_id,
             "client_id": row.client_id, "answers": row.answers,
             "submitted_at": row.submitted_at, "status": row.status,
             "created_at": row.created_at}


async def create_submission(session: AsyncSession,
                               doc: Dict[str, Any]) -> Dict[str, Any]:
    valid = {k: v for k, v in doc.items() if hasattr(FormSubmission, k)}
    valid.setdefault("status", "draft")
    row = FormSubmission(**valid)
    session.add(row)
    await session.flush()
    return _sub(row)


async def update_submission(session: AsyncSession, sub_id: str,
                                fields: Dict[str, Any]) -> int:
    valid = {k: v for k, v in fields.items() if hasattr(FormSubmission, k)}
    if not valid:
        return 0
    r = await session.execute(
        update(FormSubmission).where(FormSubmission.id == sub_id).values(**valid)
    )
    return r.rowcount or 0


async def list_submissions_for_client(session: AsyncSession, client_id: str,
                                          limit: int = 100) -> List[Dict[str, Any]]:
    stmt = (select(FormSubmission)
            .where(FormSubmission.client_id == client_id)
            .order_by(FormSubmission.created_at.desc()).limit(limit))
    return [_sub(r) for r in (await session.execute(stmt)).scalars().all()]


# =========================================================== soap_templates #
async def list_soap_templates(session: AsyncSession,
                                 limit: int = 100) -> List[Dict[str, Any]]:
    stmt = select(SoapTemplate).order_by(SoapTemplate.title.asc()).limit(limit)
    return [{"id": t.id, "title": t.title, "body": t.body,
              "created_at": t.created_at}
            for t in (await session.execute(stmt)).scalars().all()]


async def create_soap_template(session: AsyncSession,
                                  doc: Dict[str, Any]) -> Dict[str, Any]:
    valid = {k: v for k, v in doc.items() if hasattr(SoapTemplate, k)}
    row = SoapTemplate(**valid)
    session.add(row)
    await session.flush()
    return {"id": row.id, "title": row.title, "body": row.body,
             "created_at": row.created_at}


# ======================================================== push_subscriptions #
async def upsert_push_subscription(session: AsyncSession, *, user_id: str,
                                      endpoint: str, keys: Optional[dict],
                                      new_id_fn) -> Dict[str, Any]:
    existing = (await session.execute(
        select(PushSubscription)
        .where(PushSubscription.user_id == user_id,
               PushSubscription.endpoint == endpoint)
    )).scalar_one_or_none()
    if existing:
        existing.keys = keys
        await session.flush()
        row = existing
    else:
        row = PushSubscription(id=new_id_fn(), user_id=user_id,
                                 endpoint=endpoint, keys=keys)
        session.add(row)
        await session.flush()
    return {"id": row.id, "user_id": row.user_id, "endpoint": row.endpoint,
             "keys": row.keys, "created_at": row.created_at}


async def list_push_subscriptions(session: AsyncSession,
                                     user_id: str) -> List[Dict[str, Any]]:
    stmt = select(PushSubscription).where(PushSubscription.user_id == user_id)
    return [{"id": r.id, "user_id": r.user_id, "endpoint": r.endpoint,
              "keys": r.keys}
            for r in (await session.execute(stmt)).scalars().all()]


async def delete_push_subscription(session: AsyncSession,
                                     endpoint: str) -> int:
    r = await session.execute(
        delete(PushSubscription).where(PushSubscription.endpoint == endpoint)
    )
    return r.rowcount or 0
