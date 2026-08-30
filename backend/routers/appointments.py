"""
Phase 2: Appointments, Availability, Practitioners directory, Memberships,
Invoices, Treatment Plans, Reminder settings.

Extracted from server.py during Phase 16 refactor.
Phase 3.2 (2026-07-31): appointments/availability/reminders/reminder_settings
now live in PostgreSQL via `repositories.scheduling`.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, Query, Request

from audit import get_client_ip, log_audit
from delegations import has_active_delegation
from deps import (
    _resolve_self_client, _strip_id, api, db, get_current_user, require_roles,
)
from notifiers import push_to_user
from models import (
    AppointmentIn, AppointmentOut, AppointmentUpdate,
    AvailabilityIn, AvailabilityOut,
    InvoiceIn, InvoiceOut, MarkPaidIn,
    MembershipIn, MembershipOut,
    PlanIn, PlanOut,
    ReminderSettings, new_id,
)
from pg_shims import find_client, find_user_by_id, list_users_by_role
from postgres_db import AsyncSessionLocal
from repositories import scheduling as sched_repo

from services.payments import (
    construct_webhook_event,
    create_invoice_payment_intent,
    object_value as stripe_object_value,
    publishable_key as stripe_publishable_key,
    stripe_enabled,
)

TIER_PRICES = {"essentials": 99.0, "core": 199.0, "vip": 299.0}


# =================== PHASE 2: APPOINTMENTS / AVAILABILITY / PLANS / MEMBERSHIPS / INVOICES / REMINDERS ===================

TIER_PRICES = {"essentials": 99.0, "core": 199.0, "vip": 299.0}


async def _hydrate_appt(a):
    a = _strip_id(a)
    if not a:
        return None
    if a.get("client_id"):
        c = await find_client(client_id=a["client_id"])
        if c:
            a["client_name"] = c.get("full_name")
    if a.get("practitioner_id"):
        u = await find_user_by_id(a["practitioner_id"])
        if u:
            a["practitioner_name"] = u.get("full_name")
    return a


# ---------- Appointments ----------
@api.get("/appointments", response_model=List[AppointmentOut])
async def list_appointments(
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    practitioner_id: Optional[str] = None,
    client_id: Optional[str] = None,
    user=Depends(get_current_user),
):
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            return []
        client_id = self_client["id"]
    async with AsyncSessionLocal() as pg:
        items = await sched_repo.list_appointments(
            pg, client_id=client_id, practitioner_id=practitioner_id,
            start_gte=start, start_lte=end, limit=1000,
        )
    return [await _hydrate_appt(i) for i in items]


@api.post("/appointments", response_model=AppointmentOut)
async def create_appointment(payload: AppointmentIn, request: Request, user=Depends(get_current_user)):
    # Clients can only book for themselves
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            raise HTTPException(status_code=404, detail="Client record missing")
        if payload.client_id != self_client["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
        status_val = "requested"
    else:
        status_val = payload.status
    c = await find_client(client_id=payload.client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    doc = payload.dict()
    doc["id"] = new_id()
    doc["status"] = status_val
    doc["created_at"] = datetime.now(timezone.utc)
    doc["created_by"] = user["id"]
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            doc = await sched_repo.create_appointment(pg, doc)
    # Auto-schedule reminder (stubbed) — fresh session so the read/write
    # cycle above's transaction is fully committed first.
    async with AsyncSessionLocal() as pg:
        settings = await sched_repo.get_reminder_settings(pg) or {}
    hours_before = settings.get("appointment_reminder_hours_before", 24)
    channels = settings.get("appointment_reminder_channels") or ["email"]
    if settings.get("enabled", True):
        scheduled_at = doc["start"] - timedelta(hours=hours_before)
        async with AsyncSessionLocal() as pg:
            async with pg.begin():
                for ch in channels:
                    await sched_repo.create_reminder(pg, {
                        "id": new_id(),
                        "appointment_id": doc["id"],
                        "client_id": doc["client_id"],
                        "channel": ch,
                        "scheduled_at": scheduled_at,
                        "sent_at": None,
                        "status": "scheduled",
                    })

    await log_audit(db, user["id"], user["email"], "appointment.create",
                    resource_type="appointment", resource_id=doc["id"],
                    metadata={"client_id": payload.client_id},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return await _hydrate_appt(doc)


@api.put("/appointments/{appt_id}", response_model=AppointmentOut)
async def update_appointment(appt_id: str, payload: AppointmentUpdate, request: Request,
                             user=Depends(get_current_user)):
    async with AsyncSessionLocal() as pg:
        a = await sched_repo.get_appointment(pg, appt_id)
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client or a["client_id"] != self_client["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
        # Clients may only cancel their own
        if payload.status and payload.status != "canceled":
            raise HTTPException(status_code=403, detail="Clients may only cancel")
        updates = {"status": "canceled"}
    else:
        updates = {k: v for k, v in payload.dict().items() if v is not None}
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await sched_repo.update_appointment(pg, appt_id, updates)
    async with AsyncSessionLocal() as pg:
        a = await sched_repo.get_appointment(pg, appt_id)
    # Visit-started push: when telehealth appointment moves to in_session, ping the client
    if updates.get("status") == "in_session" and a.get("visit_mode") == "telehealth":
        client_doc = await find_client(client_id=a.get("client_id"))
        if client_doc and client_doc.get("user_id"):
            await push_to_user(
                client_doc["user_id"],
                "Your provider is ready",
                "Tap to join your telehealth visit now.",
                url=f"/portal/visit/{appt_id}",
                tag=f"visit-{appt_id}",
            )
    await log_audit(db, user["id"], user["email"], "appointment.update",
                    resource_type="appointment", resource_id=appt_id,
                    metadata={"fields": list(updates.keys())},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return await _hydrate_appt(a)


# ---------- Availability ----------
@api.get("/availability", response_model=List[AvailabilityOut])
async def list_availability(practitioner_id: Optional[str] = None, user=Depends(get_current_user)):
    if not practitioner_id and user["role"] == "practitioner":
        practitioner_id = user["id"]
    async with AsyncSessionLocal() as pg:
        items = await sched_repo.list_availability(pg, practitioner_id=practitioner_id, limit=200)
    return items


@api.post("/availability", response_model=AvailabilityOut)
async def create_availability(payload: AvailabilityIn, request: Request,
                              user=Depends(require_roles("practitioner", "admin"))):
    pid = payload.practitioner_id or user["id"]
    doc = payload.dict()
    doc["practitioner_id"] = pid
    doc["id"] = new_id()
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            doc = await sched_repo.create_availability(pg, doc)
    await log_audit(db, user["id"], user["email"], "availability.create",
                    resource_type="availability", resource_id=doc["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return doc


@api.delete("/availability/{avail_id}")
async def delete_availability(avail_id: str, request: Request,
                              user=Depends(require_roles("practitioner", "admin"))):
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await sched_repo.delete_availability(pg, avail_id)
    await log_audit(db, user["id"], user["email"], "availability.delete",
                    resource_type="availability", resource_id=avail_id,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


@api.get("/availability/slots")
async def availability_slots(
    practitioner_id: str,
    date: str,  # YYYY-MM-DD
    duration_min: int = 60,
    user=Depends(get_current_user),
):
    try:
        d = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date")
    weekday = d.weekday()
    async with AsyncSessionLocal() as pg:
        rules = await sched_repo.list_availability(
            pg, practitioner_id=practitioner_id, weekday=weekday,
            active_only=True, limit=50,
        )
        if not rules:
            return {"date": date, "slots": []}
        day_start = d.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        taken = await sched_repo.find_overlapping_appointments(
            pg, practitioner_id=practitioner_id,
            start=day_start, end=day_end,
        )
    slots = []
    for r in rules:
        sh, sm = map(int, r["start_time"].split(":"))
        eh, em = map(int, r["end_time"].split(":"))
        cur = day_start.replace(hour=sh, minute=sm)
        end = day_start.replace(hour=eh, minute=em)
        while cur + timedelta(minutes=duration_min) <= end:
            slot_end = cur + timedelta(minutes=duration_min)
            overlaps = any(
                not (t["end"] <= cur or t["start"] >= slot_end) for t in taken
            )
            if not overlaps:
                slots.append({"start": cur.isoformat(), "end": slot_end.isoformat()})
            cur = slot_end
    return {"date": date, "slots": slots}


# ---------- Practitioners directory (for patient booking) ----------
@api.get("/practitioners")
async def list_practitioners(user=Depends(get_current_user)):
    items = await list_users_by_role("practitioner", active_only=True, limit=100)
    return [{"id": u["id"], "full_name": u.get("full_name"), "email": u["email"]} for u in items]


# ---------- Memberships ----------
async def _hydrate_mem(m):
    m = _strip_id(m)
    if not m:
        return None
    c = await find_client(client_id=m["client_id"])
    if c:
        m["client_name"] = c.get("full_name")
    return m


@api.get("/memberships", response_model=List[MembershipOut])
async def list_memberships(user=Depends(require_roles("admin", "staff", "practitioner"))):
    items = await db.memberships.find().sort("created_at", -1).to_list(500)
    return [await _hydrate_mem(i) for i in items]


@api.get("/memberships/mine", response_model=Optional[MembershipOut])
async def my_membership(user=Depends(get_current_user)):
    self_client = await _resolve_self_client(user)
    if not self_client:
        return None
    m = await db.memberships.find_one({"client_id": self_client["id"], "status": {"$in": ["active", "pending", "paused"]}})
    return await _hydrate_mem(m) if m else None


@api.post("/memberships", response_model=MembershipOut)
async def create_membership(payload: MembershipIn, request: Request, user=Depends(get_current_user)):
    if payload.tier not in TIER_PRICES:
        raise HTTPException(status_code=400, detail="Invalid tier")
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            raise HTTPException(status_code=404, detail="Client record missing")
        client_id = self_client["id"]
    else:
        if not payload.client_id:
            raise HTTPException(status_code=400, detail="client_id required")
        client_id = payload.client_id

    # If stripe - create stubbed subscription id
    stripe_sub = None
    status_val = "pending"
    if payload.billing_method == "stripe":
        if not os.environ.get("STRIPE_SECRET_KEY"):
            # Stub flow
            stripe_sub = f"sub_stub_{new_id()[:8]}"
            await db.integration_log.insert_one({
                "id": new_id(), "service": "stripe", "action": "subscription.create",
                "payload": {"client_id": client_id, "tier": payload.tier},
                "_stubbed": True, "ts": datetime.now(timezone.utc),
            })
            status_val = "active"
        else:
            # Real wire-up point (left as stub entry for now)
            stripe_sub = f"sub_pending_{new_id()[:8]}"
            status_val = "pending"
    else:
        status_val = "active"  # chase_pos / manual — recorded, staff reconciles payment

    now = datetime.now(timezone.utc)
    doc = {
        "id": new_id(),
        "client_id": client_id,
        "tier": payload.tier,
        "price": TIER_PRICES[payload.tier],
        "status": status_val,
        "billing_method": payload.billing_method,
        "started_at": now if status_val == "active" else None,
        "next_bill_date": now + timedelta(days=30) if status_val == "active" else None,
        "stripe_subscription_id": stripe_sub,
        "created_at": now,
    }
    await db.memberships.insert_one(doc)

    # Auto-generate first invoice
    inv = {
        "id": new_id(),
        "client_id": client_id,
        "membership_id": doc["id"],
        "appointment_id": None,
        "description": f"Membership: {payload.tier.capitalize()} Wellness (first month)",
        "amount": TIER_PRICES[payload.tier],
        "status": "due",
        "paid_at": None,
        "payment_method": None,
        "external_ref": None,
        "created_at": now,
    }
    await db.invoices.insert_one(inv)

    await log_audit(db, user["id"], user["email"], "membership.create",
                    resource_type="membership", resource_id=doc["id"],
                    metadata={"tier": payload.tier, "method": payload.billing_method},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return await _hydrate_mem(doc)


@api.put("/memberships/{mem_id}/status", response_model=MembershipOut)
async def set_membership_status(mem_id: str, body: dict, request: Request,
                                user=Depends(require_roles("admin", "staff", "practitioner"))):
    status_val = (body or {}).get("status")
    if status_val not in ("active", "paused", "canceled"):
        raise HTTPException(status_code=400, detail="Invalid status")
    await db.memberships.update_one({"id": mem_id}, {"$set": {"status": status_val}})
    await log_audit(db, user["id"], user["email"], "membership.status",
                    resource_type="membership", resource_id=mem_id, metadata={"status": status_val},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    m = await db.memberships.find_one({"id": mem_id})
    return await _hydrate_mem(m)


# ---------- Invoices ----------
async def _hydrate_invoice(i):
    i = _strip_id(i)
    if not i:
        return None
    c = await find_client(client_id=i["client_id"])
    if c:
        i["client_name"] = c.get("full_name")
    return i


@api.get("/invoices", response_model=List[InvoiceOut])
async def list_invoices(client_id: Optional[str] = None, user=Depends(get_current_user)):
    q = {}
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            return []
        q["client_id"] = self_client["id"]
    elif client_id:
        q["client_id"] = client_id
    items = await db.invoices.find(q).sort("created_at", -1).to_list(500)
    return [await _hydrate_invoice(i) for i in items]


@api.post("/invoices", response_model=InvoiceOut)
async def create_invoice(payload: InvoiceIn, request: Request,
                         user=Depends(require_roles("admin", "staff", "practitioner"))):
    doc = payload.dict()
    doc["id"] = new_id()
    doc["status"] = "due"
    doc["paid_at"] = None
    doc["payment_method"] = None
    doc["external_ref"] = None
    doc["created_at"] = datetime.now(timezone.utc)
    await db.invoices.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "invoice.create",
                    resource_type="invoice", resource_id=doc["id"],
                    metadata={"client_id": payload.client_id, "amount": payload.amount},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return await _hydrate_invoice(doc)


@api.post("/invoices/{inv_id}/mark-paid", response_model=InvoiceOut)
async def mark_paid(inv_id: str, payload: MarkPaidIn, request: Request,
                    user=Depends(require_roles("admin", "staff", "practitioner"))):
    inv = await db.invoices.find_one({"id": inv_id})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    updates = {
        "status": "paid",
        "paid_at": datetime.now(timezone.utc),
        "payment_method": payload.method,
        "external_ref": payload.external_ref,
    }
    await db.invoices.update_one({"id": inv_id}, {"$set": updates})
    await log_audit(db, user["id"], user["email"], "invoice.mark_paid",
                    resource_type="invoice", resource_id=inv_id, metadata={"method": payload.method},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    # Accounting event
    try:
        from accounting.events import AccountingEvent, emit
        await emit(AccountingEvent(
            event_type="InvoicePaid",
            occurred_at=updates["paid_at"],
            source_module="invoices", source_ref_type="invoice", source_ref_id=inv_id,
            idempotency_key=f"invoice:{inv_id}:InvoicePaid",
            amount_cents=int(round(float(inv.get("amount") or 0) * 100)),
            context={"payment_method": payload.method},
            actor_id=user["id"], actor_role=user["role"],
        ))
    except Exception:
        pass
    inv = await db.invoices.find_one({"id": inv_id})
    return await _hydrate_invoice(inv)


async def _patient_activity(
    *,
    client_id: str,
    body: str,
    event_type: str,
    source_id: str,
    portal_path: str,
    sender_role: str = "system",
    sender_name: str = "Natural Medical Solutions",
):
    """Best-effort patient account activity; never blocks clinical operations."""
    try:
        from services.patient_activity import add_patient_activity_message

        return await add_patient_activity_message(
            client_id=client_id,
            body=body,
            event_type=event_type,
            source_id=source_id,
            portal_path=portal_path,
            sender_role=sender_role,
            sender_name=sender_name,
        )
    except Exception:
        # Patient activity is best-effort and must never block
        # authoritative payment settlement.
        return None


async def _settle_stripe_invoice_from_webhook(
    *,
    invoice: dict,
    payment_intent_id: str,
    stripe_event_id: str,
    amount_cents: int,
    currency: str,
):
    """
    Settle an NMS invoice only after a verified Stripe success event.

    This helper receives an event only after Stripe signature
    verification has succeeded.

    It deliberately does not trust browser state.
    """

    inv_id = str(invoice.get("id") or "")

    if not inv_id:
        raise ValueError("Invoice ID missing")

    expected_intent = str(
        invoice.get("stripe_payment_intent_id") or ""
    )

    if not expected_intent:
        raise ValueError(
            "Invoice has no bound Stripe PaymentIntent"
        )

    if expected_intent != str(payment_intent_id):
        raise ValueError(
            "Stripe PaymentIntent does not match invoice"
        )

    try:
        expected_cents = int(
            round(float(invoice.get("amount") or 0) * 100)
        )
    except (TypeError, ValueError):
        expected_cents = 0

    if expected_cents <= 0:
        raise ValueError("Invoice amount is invalid")

    if int(amount_cents) != expected_cents:
        raise ValueError(
            "Stripe amount does not match invoice"
        )

    if str(currency or "").lower() != "usd":
        raise ValueError(
            "Stripe currency does not match invoice"
        )

    # Stripe may retry the same webhook. If this exact invoice
    # is already paid by this exact PaymentIntent, return safely.
    if invoice.get("status") == "paid":
        if (
            str(invoice.get("external_ref") or "")
            == str(payment_intent_id)
            and
            str(invoice.get("payment_method") or "")
            == "stripe"
        ):
            return {
                "settled": False,
                "duplicate": True,
            }

        # Never overwrite payment provenance on an invoice that
        # was settled through another payment path.
        raise ValueError(
            "Invoice is already paid by another payment record"
        )

    if invoice.get("status") == "void":
        raise ValueError(
            "Void invoice cannot be settled"
        )

    paid_at = datetime.now(timezone.utc)

    updates = {
        "status": "paid",
        "paid_at": paid_at,
        "payment_method": "stripe",
        "external_ref": str(payment_intent_id),
        "stripe_payment_intent_id":
            str(payment_intent_id),
        "stripe_last_event_id":
            str(stripe_event_id),
    }

    # Conditional update protects against another request changing
    # the invoice between verification and settlement.
    result = await db.invoices.update_one(
        {
            "id": inv_id,
            "status": {"$ne": "paid"},
            "stripe_payment_intent_id":
                str(payment_intent_id),
        },
        {
            "$set": updates,
        },
    )

    modified = getattr(result, "modified_count", None)

    if modified == 0:
        latest = await db.invoices.find_one(
            {"id": inv_id}
        )

        if (
            latest
            and latest.get("status") == "paid"
            and str(latest.get("external_ref") or "")
                == str(payment_intent_id)
            and str(latest.get("payment_method") or "")
                == "stripe"
        ):
            return {
                "settled": False,
                "duplicate": True,
            }

        raise ValueError(
            "Invoice settlement state changed"
        )

    # Accounting uses the same invoice-level idempotency key as
    # the existing manual settlement path/backfill.
    try:
        from accounting.events import AccountingEvent, emit

        await emit(
            AccountingEvent(
                event_type="InvoicePaid",
                occurred_at=paid_at,
                source_module="invoices",
                source_ref_type="invoice",
                source_ref_id=inv_id,
                idempotency_key=(
                    f"invoice:{inv_id}:InvoicePaid"
                ),
                amount_cents=expected_cents,
                currency="USD",
                context={
                    "payment_method": "stripe",
                },
                actor_id=None,
                actor_role="system",
            )
        )
    except Exception:
        # Existing invoice settlement behavior treats accounting
        # as downstream and idempotently recoverable/backfillable.
        pass

    await _patient_activity(
        client_id=invoice["client_id"],
        body="Your payment was received. Thank you.",
        event_type="invoice_paid",
        source_id=inv_id,
        portal_path="/portal/patient/billing",
        sender_role="staff",
        sender_name="Billing Team",
    )

    return {
        "settled": True,
        "duplicate": False,
    }


@api.post("/invoices/{inv_id}/stripe-intent")
async def stripe_intent(
    inv_id: str,
    user=Depends(get_current_user),
):
    """
    Create a real Stripe PaymentIntent for the authenticated
    patient's own unpaid invoice.

    The amount always comes from the NMS invoice record.
    """

    inv, client = await _patient_owned_invoice(
        inv_id,
        user,
    )

    if inv.get("status") == "paid":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "invoice_already_paid",
                "message": "This invoice has already been paid.",
            },
        )

    if inv.get("status") == "void":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "invoice_void",
                "message": "This invoice is void and cannot be paid.",
            },
        )

    if not stripe_enabled():
        raise HTTPException(
            status_code=503,
            detail={
                "code": "payments_not_configured",
                "message": "Online card payments are not configured.",
            },
        )

    try:
        amount = float(inv.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0

    amount_cents = int(round(amount * 100))

    if amount_cents <= 0:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "invalid_invoice_amount",
                "message": "This invoice does not have a payable amount.",
            },
        )

    intent = await create_invoice_payment_intent(
        invoice_id=inv_id,
        amount_cents=amount_cents,
        currency="usd",
    )

    intent_id = getattr(intent, "id", None)
    client_secret = getattr(intent, "client_secret", None)

    if not intent_id or not client_secret:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "processor_response_invalid",
                "message": "Stripe did not return a valid payment session.",
            },
        )

    # Safe processor reference only. Never store the client secret.
    await db.invoices.update_one(
        {"id": inv_id},
        {
            "$set": {
                "stripe_payment_intent_id": intent_id,
            }
        },
    )

    await db.integration_log.insert_one({
        "id": new_id(),
        "service": "stripe",
        "action": "payment_intent.created",
        "payload": {
            "invoice_id": inv_id,
            "payment_intent_id": intent_id,
            "amount_cents": amount_cents,
        },
        "ts": datetime.now(timezone.utc),
    })

    return {
        "client_secret": client_secret,
        "payment_intent_id": intent_id,
        "publishable_key": stripe_publishable_key(),
    }

@api.post("/payments/stripe/webhook")
async def stripe_payment_webhook(request: Request):
    """
    Stripe is authoritative for online invoice settlement.

    This endpoint:
    1. reads the raw request body,
    2. verifies Stripe-Signature,
    3. accepts only payment_intent.succeeded for settlement,
    4. verifies invoice reference, PaymentIntent binding,
       amount and currency,
    5. then marks the NMS invoice paid.

    It does not require patient authentication because Stripe calls
    this endpoint directly. Authenticity comes from Stripe's signed
    webhook payload.
    """

    payload = await request.body()

    signature = request.headers.get(
        "stripe-signature",
        "",
    )

    try:
        event = construct_webhook_event(
            payload=payload,
            signature=signature,
        )
    except Exception:
        # Do not expose signature-verification internals.
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_stripe_webhook",
                "message": "Invalid Stripe webhook.",
            },
        )

    event_id = str(
        stripe_object_value(event, "id", "") or ""
    )

    event_type = str(
        stripe_object_value(event, "type", "") or ""
    )

    data = stripe_object_value(
        event,
        "data",
        {},
    ) or {}

    payment_intent = stripe_object_value(
        data,
        "object",
        {},
    ) or {}

    # Non-success events are acknowledged but cannot settle
    # an invoice.
    if event_type != "payment_intent.succeeded":
        return {
            "received": True,
            "settled": False,
        }

    payment_intent_id = str(
        stripe_object_value(
            payment_intent,
            "id",
            "",
        ) or ""
    )

    status = str(
        stripe_object_value(
            payment_intent,
            "status",
            "",
        ) or ""
    )

    amount_received = stripe_object_value(
        payment_intent,
        "amount_received",
        None,
    )

    currency = str(
        stripe_object_value(
            payment_intent,
            "currency",
            "",
        ) or ""
    ).lower()

    metadata = stripe_object_value(
        payment_intent,
        "metadata",
        {},
    ) or {}

    invoice_id = str(
        stripe_object_value(
            metadata,
            "nms_invoice_ref",
            "",
        ) or ""
    )

    if status != "succeeded":
        raise HTTPException(
            status_code=400,
            detail={
                "code": "stripe_status_mismatch",
                "message":
                    "Stripe payment is not succeeded.",
            },
        )

    if not event_id or not payment_intent_id:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "stripe_reference_missing",
                "message":
                    "Stripe payment reference is missing.",
            },
        )

    if not invoice_id:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invoice_reference_missing",
                "message":
                    "Invoice reference is missing.",
            },
        )

    try:
        amount_received = int(amount_received)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "stripe_amount_invalid",
                "message":
                    "Stripe payment amount is invalid.",
            },
        )

    invoice = await db.invoices.find_one(
        {"id": invoice_id}
    )

    if not invoice:
        # Signature verification already succeeded. This is an
        # unrecoverable NMS business-reference conflict, not a
        # transport/authentication failure. Acknowledge it so
        # Stripe does not retry the same valid event forever.
        await db.integration_log.insert_one({
            "id": new_id(),
            "service": "stripe",
            "action": "webhook.invoice_not_found",
            "payload": {
                "stripe_event_id": event_id,
                "payment_intent_id": payment_intent_id,
                "invoice_id": invoice_id,
            },
            "ts": datetime.now(timezone.utc),
        })

        return {
            "received": True,
            "settled": False,
            "conflict": True,
            "code": "invoice_not_found",
        }

    try:
        result = (
            await _settle_stripe_invoice_from_webhook(
                invoice=invoice,
                payment_intent_id=payment_intent_id,
                stripe_event_id=event_id,
                amount_cents=amount_received,
                currency=currency,
            )
        )
    except ValueError:
        # Signature verification succeeded, but NMS settlement
        # verification rejected the event. Never mark the invoice
        # paid. Record only safe opaque references and acknowledge
        # the event to avoid endless retries of an unrecoverable
        # business-state conflict.
        await db.integration_log.insert_one({
            "id": new_id(),
            "service": "stripe",
            "action": "webhook.settlement_conflict",
            "payload": {
                "stripe_event_id": event_id,
                "payment_intent_id": payment_intent_id,
                "invoice_id": invoice_id,
            },
            "ts": datetime.now(timezone.utc),
        })

        return {
            "received": True,
            "settled": False,
            "conflict": True,
            "code": "payment_verification_failed",
        }

    return {
        "received": True,
        "settled": bool(
            result.get("settled")
        ),
        "duplicate": bool(
            result.get("duplicate")
        ),
    }

async def _patient_owned_invoice(
    inv_id: str,
    user: dict,
):
    """
    Resolve an invoice strictly through the authenticated
    patient's own client identity.

    Never trust a client_id supplied by the browser.
    """
    if user.get("role") != "client":
        raise HTTPException(
            status_code=403,
            detail="Patient account required",
        )

    client = await _resolve_self_client(user)

    if not client:
        raise HTTPException(
            status_code=404,
            detail="Patient profile not found",
        )

    inv = await db.invoices.find_one(
        {"id": inv_id}
    )

    if not inv:
        raise HTTPException(
            status_code=404,
            detail="Invoice not found",
        )

    if str(inv.get("client_id")) != str(
        client.get("id")
    ):
        # Return 404 rather than revealing whether another
        # patient's invoice exists.
        raise HTTPException(
            status_code=404,
            detail="Invoice not found",
        )

    return inv, client

@api.get("/payments/apple-pay/status")
async def patient_apple_pay_status(
    user=Depends(get_current_user),
):
    if user.get("role") != "client":
        raise HTTPException(
            status_code=403,
            detail="Patient account required",
        )

    enabled = stripe_enabled()

    return {
        "enabled": enabled,
        "provider": "stripe",
        "requires_merchant_activation":
            not enabled,
    }


# ---------- Treatment Plans ----------
async def _hydrate_plan(p, user=None):
    p = _strip_id(p)
    if not p:
        return None
    if p.get("practitioner_id"):
        u = await find_user_by_id(p["practitioner_id"])
        if u:
            p["practitioner_name"] = u.get("full_name")
    # Clients only see patient_visible items
    if user and user.get("role") == "client":
        p["items"] = [i for i in (p.get("items") or []) if i.get("patient_visible")]
    return p


@api.get("/treatment-plans", response_model=List[PlanOut])
async def list_plans(client_id: Optional[str] = None, user=Depends(get_current_user)):
    q = {}
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client:
            return []
        q["client_id"] = self_client["id"]
    elif client_id:
        q["client_id"] = client_id
    items = await db.treatment_plans.find(q).sort("created_at", -1).to_list(200)
    return [await _hydrate_plan(i, user) for i in items]


@api.post("/treatment-plans", response_model=PlanOut)
async def create_plan(payload: PlanIn, request: Request,
                      user=Depends(require_roles("practitioner", "admin", "medical_assistant"))):
    c = await find_client(client_id=payload.client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    authorizing_provider_id = None
    if user["role"] != "practitioner":
        deleg = await has_active_delegation(user, payload.client_id)
        if not deleg:
            raise HTTPException(status_code=403, detail={
                "code": "delegation_required",
                "message": "Provider authorization is required to draft a treatment plan.",
            })
        authorizing_provider_id = deleg.get("provider_id")
    doc = payload.dict()
    doc["id"] = new_id()
    if user["role"] == "practitioner":
        doc["practitioner_id"] = user["id"]
    else:
        doc["practitioner_id"] = authorizing_provider_id
        doc["drafted_by_id"] = user["id"]
        doc["drafted_by_name"] = user.get("full_name", "")
        doc["drafted_by_role"] = user.get("role")
    doc["created_at"] = datetime.now(timezone.utc)
    doc["updated_at"] = doc["created_at"]
    doc["lifecycle_status"] = "draft"
    doc["amendments"] = []
    doc["prior_versions"] = []
    doc["finalized_at"] = None
    doc["finalized_by"] = None
    await db.treatment_plans.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "plan.create",
                    resource_type="plan", resource_id=doc["id"],
                    metadata={"client_id": payload.client_id,
                              "authorizing_provider_id": authorizing_provider_id,
                              "actor_role": user.get("role")},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return await _hydrate_plan(doc, user)


@api.put("/treatment-plans/{plan_id}", response_model=PlanOut)
async def update_plan(plan_id: str, payload: PlanIn, request: Request,
                      user=Depends(require_roles("practitioner", "admin", "medical_assistant"))):
    from clinical_lock import refuse_edit_if_finalized
    p = await db.treatment_plans.find_one({"id": plan_id})
    if not p:
        raise HTTPException(status_code=404, detail="Plan not found")
    refuse_edit_if_finalized(p, status_field="lifecycle_status")
    authorizing_provider_id = None
    if user["role"] == "practitioner":
        if p.get("practitioner_id") and p.get("practitioner_id") != user["id"]:
            raise HTTPException(status_code=403, detail="Only the assigned provider may edit this draft")
    else:
        deleg = await has_active_delegation(user, p.get("client_id"),
                                            provider_id=p.get("practitioner_id"))
        if not deleg:
            raise HTTPException(status_code=403, detail={
                "code": "delegation_required",
                "message": "Provider authorization is required to edit this draft.",
            })
        authorizing_provider_id = deleg.get("provider_id")
    updates = payload.dict()
    updates["updated_at"] = datetime.now(timezone.utc)
    await db.treatment_plans.update_one({"id": plan_id}, {"$set": updates})
    await log_audit(db, user["id"], user["email"], "plan.update",
                    resource_type="plan", resource_id=plan_id,
                    metadata={"authorizing_provider_id": authorizing_provider_id,
                              "actor_role": user.get("role")},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    p = await db.treatment_plans.find_one({"id": plan_id})
    return await _hydrate_plan(p, user)


@api.post("/treatment-plans/{plan_id}/finalize", response_model=PlanOut)
async def finalize_plan(plan_id: str, request: Request,
                        user=Depends(require_roles("practitioner"))):
    from clinical_lock import finalize_document
    doc = await finalize_document(
        db, "treatment_plans", plan_id, user,
        immutable_fields=("title", "objective", "steps", "duration_weeks",
                          "assessment", "plan", "notes"),
        audit_action="plan.finalize", request=request,
        status_field="lifecycle_status",
    )
    return await _hydrate_plan(doc, user)


@api.post("/treatment-plans/{plan_id}/amend", response_model=PlanOut)
async def amend_plan(plan_id: str, payload: dict, request: Request,
                     user=Depends(require_roles("practitioner"))):
    from clinical_lock import amend_document
    doc = await amend_document(
        db, "treatment_plans", plan_id, user,
        content=str(payload.get("content") or ""),
        reason=str(payload.get("reason") or ""),
        audit_action="plan.amend", request=request,
        status_field="lifecycle_status",
    )
    return await _hydrate_plan(doc, user)


# ---------- Reminder settings ----------
@api.get("/reminders/settings", response_model=ReminderSettings)
async def get_reminder_settings(user=Depends(require_roles("admin"))):
    async with AsyncSessionLocal() as pg:
        s = await sched_repo.get_reminder_settings(pg)
    if not s:
        return ReminderSettings()
    return ReminderSettings(**{k: v for k, v in s.items() if k in ReminderSettings.model_fields})


@api.put("/reminders/settings", response_model=ReminderSettings)
async def set_reminder_settings(payload: ReminderSettings, request: Request, user=Depends(require_roles("admin"))):
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await sched_repo.upsert_reminder_settings(pg, payload.dict())
    await log_audit(db, user["id"], user["email"], "reminders.settings_update",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return payload


@api.post("/reminders/run")
async def run_reminders(user=Depends(require_roles("admin"))):
    """Manually tick the reminder scheduler: send due reminders (stubbed)."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as pg:
        due = await sched_repo.list_due_reminders(pg, now=now, limit=200)
    sent = 0
    for r in due:
        # Email-only reminders (SMS retired 2026-08).
        if r["channel"] != "email":
            # Legacy scheduling rows that still say channel=sms are converted
            # to a no-op that is marked "sent" so we don't retry forever.
            await db.integration_log.insert_one({
                "id": new_id(),
                "service": "sendgrid",
                "action": f"reminder.{r['channel']}.skipped_sms_retired",
                "payload": {"appointment_id": r["appointment_id"],
                              "client_id": r["client_id"]},
                "_stubbed": True, "ts": now,
            })
        else:
            await db.integration_log.insert_one({
                "id": new_id(),
                "service": "sendgrid",
                "action": f"reminder.{r['channel']}",
                "payload": {"appointment_id": r["appointment_id"],
                              "client_id": r["client_id"]},
                "_stubbed": True, "ts": now,
            })
        async with AsyncSessionLocal() as pg:
            async with pg.begin():
                await sched_repo.mark_reminder_sent(pg, r["id"], now)
        sent += 1
    return {"processed": sent}

