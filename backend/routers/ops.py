"""
Operations routes: Treatments, Inventory, POS, Transactions, Time Clock,
Front Desk, CSV client import, Analytics overview, EOD cash-drawer report.

Extracted from server.py during Phase 16 refactor.
"""
from __future__ import annotations

import csv
import io as _io
import io
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as pdfcanvas

from audit import get_client_ip, log_audit
from notifiers import push_to_user
from pydantic import BaseModel, Field, EmailStr
from deps import (
    _resolve_self_client, _strip_id, api, db, get_current_user,
    logger, require_roles,
)
from models import (
    FrontDeskCheckIn, FrontDeskOut, FrontDeskUpdate,
    InventoryAdjustIn, InventoryItemIn, InventoryItemOut,
    PosCheckoutIn, TimeEditIn, TimeEntryOut,
    TransactionOut, TreatmentIn, TreatmentOut, new_id,
)
from pg_shims import (
    count_clients, find_client, find_intake_by_client, find_user_by_id,
    find_users_by_ids, insert_client, list_users_by_roles,
)


# =================== PHASE 4: TREATMENTS / INVENTORY / POS / TRANSACTIONS / TIME CLOCK / FRONT DESK / IMPORT / ACCOUNT ===================

# ---------- Treatments ----------
@api.get("/treatments", response_model=List[TreatmentOut])
async def list_treatments(active_only: bool = False, user=Depends(require_roles("admin", "staff", "practitioner"))):
    q = {"active": True} if active_only else {}
    items = await db.treatments.find(q).sort("name", 1).to_list(500)
    return [_strip_id(i) for i in items]


@api.post("/treatments", response_model=TreatmentOut)
async def create_treatment(payload: TreatmentIn, request: Request,
                           user=Depends(require_roles("admin", "staff"))):
    doc = payload.dict()
    doc["id"] = new_id()
    doc["created_at"] = datetime.now(timezone.utc)
    await db.treatments.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "treatment.create",
                    resource_type="treatment", resource_id=doc["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(doc)


@api.put("/treatments/{tid}", response_model=TreatmentOut)
async def update_treatment(tid: str, payload: TreatmentIn, request: Request,
                           user=Depends(require_roles("admin", "staff"))):
    await db.treatments.update_one({"id": tid}, {"$set": payload.dict()})
    t = await db.treatments.find_one({"id": tid})
    if not t:
        raise HTTPException(status_code=404, detail="Not found")
    await log_audit(db, user["id"], user["email"], "treatment.update",
                    resource_type="treatment", resource_id=tid,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(t)


@api.delete("/treatments/{tid}")
async def delete_treatment(tid: str, request: Request, user=Depends(require_roles("admin"))):
    await db.treatments.delete_one({"id": tid})
    await log_audit(db, user["id"], user["email"], "treatment.delete",
                    resource_type="treatment", resource_id=tid,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True}


# ---------- Inventory ----------
@api.get("/inventory", response_model=List[InventoryItemOut])
async def list_inventory(user=Depends(require_roles("admin", "staff"))):
    items = await db.inventory_items.find().sort("name", 1).to_list(500)
    return [_strip_id(i) for i in items]


@api.post("/inventory", response_model=InventoryItemOut)
async def create_inventory(payload: InventoryItemIn, request: Request,
                           user=Depends(require_roles("admin", "staff"))):
    doc = payload.dict()
    doc["id"] = new_id()
    doc["created_at"] = datetime.now(timezone.utc)
    await db.inventory_items.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "inventory.create",
                    resource_type="inventory", resource_id=doc["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(doc)


@api.put("/inventory/{iid}", response_model=InventoryItemOut)
async def update_inventory(iid: str, payload: InventoryItemIn, request: Request,
                           user=Depends(require_roles("admin", "staff"))):
    await db.inventory_items.update_one({"id": iid}, {"$set": payload.dict()})
    item = await db.inventory_items.find_one({"id": iid})
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    await log_audit(db, user["id"], user["email"], "inventory.update",
                    resource_type="inventory", resource_id=iid,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return _strip_id(item)


@api.post("/inventory/{iid}/adjust", response_model=InventoryItemOut)
async def adjust_inventory(iid: str, payload: InventoryAdjustIn, request: Request,
                           user=Depends(require_roles("admin", "staff"))):
    item = await db.inventory_items.find_one({"id": iid})
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    new_stock = (item.get("stock", 0) or 0) + payload.delta
    await db.inventory_items.update_one({"id": iid}, {"$set": {"stock": new_stock}})
    await db.inventory_transactions.insert_one({
        "id": new_id(), "item_id": iid, "change": payload.delta,
        "reason": payload.reason, "note": payload.note,
        "user_id": user["id"], "ts": datetime.now(timezone.utc),
    })
    # Low stock alert (stubbed email)
    if new_stock <= (item.get("low_stock_threshold", 5) or 5):
        await db.integration_log.insert_one({
            "id": new_id(), "service": "sendgrid", "action": "low_stock_alert",
            "payload": {"item_id": iid, "name": item.get("name"), "stock": new_stock},
            "_stubbed": True, "ts": datetime.now(timezone.utc),
        })
    await log_audit(db, user["id"], user["email"], "inventory.adjust",
                    resource_type="inventory", resource_id=iid, metadata={"delta": payload.delta},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    item = await db.inventory_items.find_one({"id": iid})
    return _strip_id(item)


# ---------- POS Checkout & Transactions ----------
async def _hydrate_txn(t):
    t = _strip_id(t)
    if not t:
        return None
    if t.get("client_id"):
        c = await find_client(client_id=t["client_id"])
        if c:
            t["client_name"] = c.get("full_name")
    if t.get("created_by"):
        u = await find_user_by_id(t["created_by"])
        if u:
            t["created_by_name"] = u.get("full_name")
    return t


@api.post("/pos/checkout", response_model=TransactionOut)
async def pos_checkout(payload: PosCheckoutIn, request: Request,
                       user=Depends(require_roles("admin", "staff", "practitioner"))):
    if not payload.lines:
        raise HTTPException(status_code=400, detail="No line items")
    out_lines = []
    subtotal = 0.0
    # Decrement inventory & build out_lines
    for line in payload.lines:
        line_total = round(line.qty * line.unit_price, 2)
        out_lines.append({**line.dict(), "line_total": line_total})
        subtotal += line_total
        if line.type == "inventory" and line.ref_id:
            inv = await db.inventory_items.find_one({"id": line.ref_id})
            if inv:
                new_stock = (inv.get("stock", 0) or 0) - line.qty
                await db.inventory_items.update_one({"id": line.ref_id}, {"$set": {"stock": new_stock}})
                await db.inventory_transactions.insert_one({
                    "id": new_id(), "item_id": line.ref_id, "change": -line.qty,
                    "reason": "pos_sale", "ts": datetime.now(timezone.utc), "user_id": user["id"],
                })
                if new_stock <= (inv.get("low_stock_threshold", 5) or 5):
                    await db.integration_log.insert_one({
                        "id": new_id(), "service": "sendgrid", "action": "low_stock_alert",
                        "payload": {"item_id": line.ref_id, "stock": new_stock},
                        "_stubbed": True, "ts": datetime.now(timezone.utc),
                    })
                    # Push admins/staff
                    admins = await list_users_by_roles(["admin", "staff"], limit=50)
                    for u in admins:
                        await push_to_user(
                            u["id"],
                            "Low stock alert",
                            f"{inv.get('name','item')} now at {new_stock} (threshold {inv.get('low_stock_threshold',5)})",
                            url="/portal/admin/inventory",
                            tag=f"lowstock-{line.ref_id}",
                        )
    discount = max(0.0, payload.discount or 0.0)
    tip = max(0.0, payload.tip or 0.0)
    after_discount = max(0.0, subtotal - discount)
    tax = round(after_discount * (payload.tax_rate or 0.0), 2)
    total = round(after_discount + tax + tip, 2)

    txn = {
        "id": new_id(),
        "client_id": payload.client_id,
        "lines": out_lines,
        "subtotal": round(subtotal, 2),
        "discount": round(discount, 2),
        "tip": round(tip, 2),
        "tax": tax,
        "total": total,
        "payment_method": payload.payment_method,
        "payment_ref": payload.payment_ref,
        "status": "paid" if payload.payment_method != "stripe" else "pending",
        "paid_at": datetime.now(timezone.utc) if payload.payment_method != "stripe" else None,
        "note": payload.note,
        "created_by": user["id"],
        "created_at": datetime.now(timezone.utc),
    }
    await db.transactions.insert_one(txn)

    # Handoff #4: link back to the appointment so the two records stay in
    # sync. Only mark the appointment `completed` when the transaction was
    # actually paid (Stripe stubs stay in `pending` until confirmed).
    if payload.appointment_id:
        appt_updates = {"transaction_id": txn["id"]}
        if txn["status"] == "paid":
            appt_updates["status"] = "completed"
        await db.appointments.update_one(
            {"id": payload.appointment_id}, {"$set": appt_updates},
        )
        # Also flip the front-desk row to checked_out so the today view
        # collapses this visit into the "Completed" bucket.
        await db.front_desk_visits.update_many(
            {"appointment_id": payload.appointment_id, "status": {"$ne": "checked_out"}},
            {"$set": {
                "status": "checked_out",
                "checked_out_at": datetime.now(timezone.utc),
            }},
        )

    # Stripe stub
    if payload.payment_method == "stripe":
        await db.integration_log.insert_one({
            "id": new_id(), "service": "stripe", "action": "checkout_session",
            "payload": {"transaction_id": txn["id"], "amount_cents": int(total * 100)},
            "_stubbed": True, "ts": datetime.now(timezone.utc),
        })

    await log_audit(db, user["id"], user["email"], "pos.checkout",
                    resource_type="transaction", resource_id=txn["id"],
                    metadata={"total": total, "method": payload.payment_method},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))

    # Accounting event — safe fire-and-forget (never blocks checkout)
    try:
        from accounting.events import AccountingEvent, emit
        ctx_lines = [{
            "line_type": ln["type"], "ref_id": ln.get("ref_id"),
            "qty": ln.get("qty") or 1,
            "unit_price_cents": int(round(float(ln.get("unit_price") or 0) * 100)),
            "line_total_cents": int(round(float(ln.get("line_total") or 0) * 100)),
        } for ln in out_lines]
        await emit(AccountingEvent(
            event_type="SaleCompleted",
            occurred_at=txn["created_at"],
            source_module="pos", source_ref_type="transaction", source_ref_id=txn["id"],
            idempotency_key=f"transaction:{txn['id']}:SaleCompleted",
            amount_cents=int(round(total * 100)),
            context={
                "payment_method": payload.payment_method,
                "subtotal_cents": int(round(subtotal * 100)),
                "discount_cents": int(round(discount * 100)),
                "tip_cents": int(round(tip * 100)),
                "tax_cents": int(round(tax * 100)),
                "lines": ctx_lines,
            },
            actor_id=user["id"], actor_role=user["role"],
        ))
    except Exception:
        logger.exception("accounting emit failed for txn %s", txn.get("id"))
    return await _hydrate_txn(txn)


@api.get("/transactions", response_model=List[TransactionOut])
async def list_transactions(client_id: Optional[str] = None, limit: int = 200,
                            user=Depends(require_roles("admin", "staff"))):
    q = {}
    if client_id:
        q["client_id"] = client_id
    items = await db.transactions.find(q).sort("created_at", -1).to_list(min(limit, 500))
    return [await _hydrate_txn(i) for i in items]


@api.get("/transactions/{tid}/receipt")
async def transaction_receipt(tid: str, user=Depends(get_current_user)):
    t = await db.transactions.find_one({"id": tid})
    if not t:
        raise HTTPException(status_code=404, detail="Not found")
    if user["role"] == "client":
        self_client = await _resolve_self_client(user)
        if not self_client or t.get("client_id") != self_client["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
    buf = await _render_invoice_pdf(t)
    invoice_no = _invoice_number(t)
    return StreamingResponse(buf, media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{invoice_no}.pdf"'})


class InvoiceEmailIn(BaseModel):
    to: Optional[EmailStr] = None
    cc: Optional[EmailStr] = None
    note: Optional[str] = Field(default=None, max_length=1000)


@api.post("/transactions/{tid}/email")
async def email_invoice(tid: str, payload: InvoiceEmailIn, request: Request,
                        user=Depends(require_roles("admin", "staff", "practitioner"))):
    """Email a PDF invoice to the client (or explicit override recipient).
    Attaches the PDF via SendGrid when a live API key is configured; otherwise
    logs a stub delivery entry."""
    t = await db.transactions.find_one({"id": tid})
    if not t:
        raise HTTPException(status_code=404, detail="Not found")
    client = None
    if t.get("client_id"):
        client = await find_client(client_id=t["client_id"])
    target = (payload.to or (client or {}).get("email") or "").strip().lower()
    if not target:
        raise HTTPException(status_code=400, detail={
            "code": "no_recipient",
            "message": "No email on file for this client — provide a recipient in the request.",
        })

    buf = await _render_invoice_pdf(t)
    pdf_bytes = buf.getvalue()
    invoice_no = _invoice_number(t)
    subject = f"Invoice {invoice_no} · Natural Medical Solutions"
    body_note = f"<p>{payload.note}</p>" if payload.note else ""
    html = (
        f"<p>Hello {(client or {}).get('full_name') or 'there'},</p>"
        f"<p>Please find your invoice ({invoice_no}) attached.</p>"
        f"{body_note}"
        "<p>Total: <strong>${:.2f}</strong></p>".format(t.get("total", 0))
        + "<p>Thank you for choosing Natural Medical Solutions.</p>"
    )

    status = await _send_email_with_attachment(
        db, target, subject, html, pdf_bytes, filename=f"{invoice_no}.pdf",
    )
    await log_audit(db, user["id"], user["email"], "invoice.email",
                    resource_type="transaction", resource_id=tid,
                    metadata={"client_id": t.get("client_id"), "delivery": status,
                              "recipient_hash": _hash_email(target)},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"ok": True, "delivery": status, "recipient": target,
            "invoice_number": invoice_no}


# --------------------------------------------------------------------------- #
# Invoice PDF helpers (kept internal — no separate invoice model created)     #
# --------------------------------------------------------------------------- #
_PRACTICE_NAME = os.environ.get("PRACTICE_NAME", "Natural Medical Solutions Wellness Center")
_PRACTICE_ADDR = os.environ.get("PRACTICE_ADDRESS", "1130 Upper Hembree Rd, Roswell, GA 30076")
_PRACTICE_PHONE = os.environ.get("PRACTICE_PHONE", "(770) 674-6311")
_PRACTICE_EMAIL = os.environ.get("PRACTICE_EMAIL", "info@natmedsol.com")
_PRACTICE_WEB = os.environ.get("PRACTICE_WEBSITE", "natmedsol.com")


def _invoice_number(t: dict) -> str:
    """Human-readable invoice number derived from transaction id + created date."""
    created = t.get("created_at") or datetime.now(timezone.utc)
    if isinstance(created, str):
        try:
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except Exception:
            created = datetime.now(timezone.utc)
    return f"INV-{created.strftime('%Y%m%d')}-{str(t.get('id', ''))[:6].upper()}"


def _hash_email(email: str) -> str:
    import hashlib
    return hashlib.sha256(email.lower().strip().encode()).hexdigest()[:16]


async def _render_invoice_pdf(t: dict) -> "io.BytesIO":
    """Server-side rendered invoice PDF. Returns a rewound BytesIO."""
    client = None
    if t.get("client_id"):
        client = await find_client(client_id=t["client_id"])
    invoice_no = _invoice_number(t)
    created = t.get("created_at") or datetime.now(timezone.utc)
    subtotal = float(t.get("subtotal", 0) or 0)
    discount = float(t.get("discount", 0) or 0)
    tax = float(t.get("tax", 0) or 0)
    tip = float(t.get("tip", 0) or 0)
    total = float(t.get("total", 0) or 0)

    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=letter)
    width, height = letter
    left = 0.75 * inch
    right = width - 0.75 * inch

    # Header — brand mark
    c.setFillColorRGB(0.184, 0.290, 0.227)  # #2f4a3a (deep green)
    c.rect(0, height - 0.35 * inch, width, 0.35 * inch, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(left, height - 0.24 * inch, _PRACTICE_NAME.upper())
    c.setFillColorRGB(0.184, 0.290, 0.227)

    y = height - 0.85 * inch
    c.setFont("Helvetica-Bold", 20)
    c.drawString(left, y, "INVOICE")
    c.setFillColorRGB(0.20, 0.20, 0.20)
    c.setFont("Helvetica", 10)
    c.drawRightString(right, y, invoice_no)
    y -= 0.22 * inch
    c.setFont("Helvetica", 9)
    c.drawRightString(right, y,
                       created.strftime("Issued %b %d, %Y · %I:%M %p") if hasattr(created, "strftime") else "")
    y -= 0.5 * inch

    # From / To columns
    c.setFillColorRGB(0.542, 0.416, 0.235)  # eyebrow gold
    c.setFont("Helvetica-Bold", 8)
    c.drawString(left, y, "FROM")
    c.drawString(left + 3.2 * inch, y, "BILL TO")
    c.setFillColorRGB(0.12, 0.16, 0.14)
    c.setFont("Helvetica-Bold", 10)
    y -= 0.18 * inch
    c.drawString(left, y, _PRACTICE_NAME)
    c.drawString(left + 3.2 * inch, y, (client or {}).get("full_name") or "Walk-in customer")
    y -= 0.16 * inch
    c.setFont("Helvetica", 9)
    for line in (_PRACTICE_ADDR, f"Phone: {_PRACTICE_PHONE}",
                 f"{_PRACTICE_EMAIL} · {_PRACTICE_WEB}"):
        c.drawString(left, y, line)
        y -= 0.14 * inch
    # Reset y for right column height
    ry = y + 0.42 * inch
    if client:
        for line in [client.get("email") or "",
                      client.get("phone") or "",
                      f"MRN: {client.get('mrn')}" if client.get("mrn") else ""]:
            if not line:
                continue
            c.drawString(left + 3.2 * inch, ry, line)
            ry -= 0.14 * inch

    y = min(y, ry) - 0.15 * inch
    c.setStrokeColorRGB(0.9, 0.86, 0.79)
    c.line(left, y, right, y)
    y -= 0.28 * inch

    # Line items header
    c.setFillColorRGB(0.542, 0.416, 0.235)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(left, y, "DESCRIPTION")
    c.drawRightString(left + 4.0 * inch, y, "QTY")
    c.drawRightString(left + 5.0 * inch, y, "UNIT")
    c.drawRightString(right, y, "AMOUNT")
    y -= 0.06 * inch
    c.setStrokeColorRGB(0.85, 0.80, 0.68)
    c.line(left, y, right, y)
    y -= 0.20 * inch

    # Line items
    c.setFillColorRGB(0.12, 0.16, 0.14)
    c.setFont("Helvetica", 10)
    for line in t.get("lines", []):
        c.drawString(left, y, str(line.get("name", ""))[:60])
        c.drawRightString(left + 4.0 * inch, y, str(line.get("qty", 0)))
        c.drawRightString(left + 5.0 * inch, y, f"${(line.get('unit_price') or 0):.2f}")
        c.drawRightString(right, y, f"${(line.get('line_total') or 0):.2f}")
        y -= 0.18 * inch
        if y < 2.2 * inch:
            c.showPage(); y = height - 1 * inch

    y -= 0.05 * inch
    c.setStrokeColorRGB(0.9, 0.86, 0.79)
    c.line(left + 3.0 * inch, y, right, y)
    y -= 0.2 * inch

    # Totals block
    def _line(label, value, bold=False, negative=False):
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 10)
        c.drawRightString(right - 0.9 * inch, y, label)
        val_str = f"−${abs(value):.2f}" if negative else f"${value:.2f}"
        c.drawRightString(right, y, val_str)
        y -= 0.18 * inch

    _line("Subtotal", subtotal)
    if discount:
        _line("Discount", discount, negative=True)
    if tax:
        _line("Tax", tax)
    if tip:
        _line("Tip", tip)
    y -= 0.08 * inch
    c.setStrokeColorRGB(0.184, 0.290, 0.227)
    c.setLineWidth(1.2)
    c.line(right - 2.0 * inch, y, right, y)
    y -= 0.02 * inch
    c.setLineWidth(0.5)
    c.setFillColorRGB(0.184, 0.290, 0.227)
    c.setFont("Helvetica-Bold", 14)
    y -= 0.24 * inch
    c.drawRightString(right - 0.9 * inch, y, "TOTAL")
    c.drawRightString(right, y, f"${total:.2f}")
    y -= 0.35 * inch

    # Payment status
    c.setFillColorRGB(0.24, 0.42, 0.32)
    c.setFont("Helvetica-Bold", 10)
    pm = (t.get("payment_method") or "").replace("_", " ").title()
    status_label = "PAID" if total > 0 else "PAID (Zero)"
    c.drawString(left, y, f"{status_label}  ·  {pm}")
    if t.get("payment_ref"):
        c.setFont("Helvetica", 9)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        c.drawString(left + 2.5 * inch, y, f"Ref: {t.get('payment_ref')}")
    y -= 0.4 * inch

    # Notes
    if t.get("note"):
        c.setFillColorRGB(0.542, 0.416, 0.235)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(left, y, "NOTES")
        y -= 0.16 * inch
        c.setFillColorRGB(0.20, 0.20, 0.20)
        c.setFont("Helvetica", 9)
        for chunk in _wrap(t["note"], 100):
            c.drawString(left, y, chunk); y -= 0.13 * inch

    # Footer
    c.setFillColorRGB(0.46, 0.46, 0.46)
    c.setFont("Helvetica-Oblique", 8)
    c.drawCentredString(width / 2, 0.6 * inch,
                        f"Thank you for choosing {_PRACTICE_NAME}. "
                        f"Questions? Call {_PRACTICE_PHONE} or reply to {_PRACTICE_EMAIL}.")
    c.drawCentredString(width / 2, 0.45 * inch,
                        "Wellness services are not billed to insurance unless specifically arranged. "
                        "All sales final unless noted otherwise.")
    c.showPage(); c.save()
    buf.seek(0)
    return buf


def _wrap(text: str, width: int) -> list[str]:
    """Very small word wrapper for PDF footer text."""
    words = str(text or "").split()
    out, line = [], ""
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line); line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        out.append(line)
    return out or [""]


async def _send_email_with_attachment(db, to: str, subject: str, html: str,
                                       attachment: bytes, *, filename: str) -> str:
    """Send an email with a PDF attachment. Returns delivery status string."""
    import base64
    from notifiers import email_status
    now = datetime.now(timezone.utc)
    log_doc = {
        "service": "sendgrid",
        "action": "invoice.email_dispatch",
        "payload": {"to": to, "subject": subject, "filename": filename,
                     "size": len(attachment)},
        "ts": now,
    }
    if email_status() != "live":
        log_doc["_stubbed"] = True
        await db.integration_log.insert_one(log_doc)
        return "sent_stub"
    api_key = os.environ["SENDGRID_API_KEY"]
    from_email = os.environ["SENDGRID_FROM_EMAIL"]

    def _blocking() -> int:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import (
            Mail, Attachment, FileContent, FileName, FileType, Disposition,
        )
        msg = Mail(from_email=from_email, to_emails=to, subject=subject,
                   html_content=html)
        att = Attachment(
            FileContent(base64.b64encode(attachment).decode()),
            FileName(filename), FileType("application/pdf"),
            Disposition("attachment"),
        )
        msg.attachment = att
        sg = SendGridAPIClient(api_key)
        return sg.send(msg).status_code

    import asyncio
    try:
        code = await asyncio.to_thread(_blocking)
        log_doc.update({"status_code": code, "_stubbed": False})
        await db.integration_log.insert_one(log_doc)
        return "sent" if 200 <= code < 300 else "failed"
    except Exception as e:
        log_doc.update({"error": str(e), "_stubbed": False, "failed": True})
        await db.integration_log.insert_one(log_doc)
        return "failed"


# ---------- Time Clock ----------
def _calc_minutes(entry):
    if not entry.get("clock_in") or not entry.get("clock_out"):
        return None
    total = (entry["clock_out"] - entry["clock_in"]).total_seconds() / 60
    for b in entry.get("breaks", []) or []:
        if b.get("start") and b.get("end"):
            total -= (b["end"] - b["start"]).total_seconds() / 60
    return round(total, 1)


async def _hydrate_time(e):
    e = _strip_id(e)
    if not e:
        return None
    u = await find_user_by_id(e["user_id"])
    if u:
        e["user_name"] = u.get("full_name")
    e["total_minutes"] = _calc_minutes(e)
    return e


@api.post("/time-clock/punch-in", response_model=TimeEntryOut)
async def punch_in(user=Depends(require_roles("admin", "staff", "practitioner"))):
    open_e = await db.time_entries.find_one({"user_id": user["id"], "clock_out": None})
    if open_e:
        return await _hydrate_time(open_e)
    doc = {
        "id": new_id(),
        "user_id": user["id"],
        "clock_in": datetime.now(timezone.utc),
        "clock_out": None,
        "breaks": [],
        "note": None,
    }
    await db.time_entries.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "timeclock.in", resource_type="time_entry", resource_id=doc["id"])
    return await _hydrate_time(doc)


@api.post("/time-clock/punch-out", response_model=TimeEntryOut)
async def punch_out(user=Depends(require_roles("admin", "staff", "practitioner"))):
    e = await db.time_entries.find_one({"user_id": user["id"], "clock_out": None})
    if not e:
        raise HTTPException(status_code=400, detail="Not punched in")
    # auto-close any open break
    breaks = e.get("breaks") or []
    if breaks and not breaks[-1].get("end"):
        breaks[-1]["end"] = datetime.now(timezone.utc)
    await db.time_entries.update_one({"id": e["id"]}, {"$set": {"clock_out": datetime.now(timezone.utc), "breaks": breaks}})
    e = await db.time_entries.find_one({"id": e["id"]})
    await log_audit(db, user["id"], user["email"], "timeclock.out", resource_type="time_entry", resource_id=e["id"])
    return await _hydrate_time(e)


@api.post("/time-clock/break-start", response_model=TimeEntryOut)
async def break_start(user=Depends(require_roles("admin", "staff", "practitioner"))):
    e = await db.time_entries.find_one({"user_id": user["id"], "clock_out": None})
    if not e:
        raise HTTPException(status_code=400, detail="Punch in first")
    breaks = e.get("breaks") or []
    if breaks and not breaks[-1].get("end"):
        return await _hydrate_time(e)  # already on break
    breaks.append({"start": datetime.now(timezone.utc), "end": None})
    await db.time_entries.update_one({"id": e["id"]}, {"$set": {"breaks": breaks}})
    e = await db.time_entries.find_one({"id": e["id"]})
    return await _hydrate_time(e)


@api.post("/time-clock/break-end", response_model=TimeEntryOut)
async def break_end(user=Depends(require_roles("admin", "staff", "practitioner"))):
    e = await db.time_entries.find_one({"user_id": user["id"], "clock_out": None})
    if not e:
        raise HTTPException(status_code=400, detail="Not on a shift")
    breaks = e.get("breaks") or []
    if not breaks or breaks[-1].get("end"):
        return await _hydrate_time(e)
    breaks[-1]["end"] = datetime.now(timezone.utc)
    await db.time_entries.update_one({"id": e["id"]}, {"$set": {"breaks": breaks}})
    e = await db.time_entries.find_one({"id": e["id"]})
    return await _hydrate_time(e)


@api.get("/time-clock/me", response_model=List[TimeEntryOut])
async def my_time_entries(limit: int = 50, user=Depends(require_roles("admin", "staff", "practitioner"))):
    items = await db.time_entries.find({"user_id": user["id"]}).sort("clock_in", -1).to_list(min(limit, 200))
    return [await _hydrate_time(i) for i in items]


@api.get("/time-clock/all", response_model=List[TimeEntryOut])
async def all_time_entries(user=Depends(require_roles("admin"))):
    items = await db.time_entries.find().sort("clock_in", -1).to_list(500)
    return [await _hydrate_time(i) for i in items]


@api.put("/time-clock/{eid}", response_model=TimeEntryOut)
async def edit_time(eid: str, payload: TimeEditIn, request: Request, user=Depends(require_roles("admin"))):
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    if updates:
        updates["edited_by"] = user["id"]
        await db.time_entries.update_one({"id": eid}, {"$set": updates})
    e = await db.time_entries.find_one({"id": eid})
    if not e:
        raise HTTPException(status_code=404, detail="Not found")
    await log_audit(db, user["id"], user["email"], "timeclock.edit", resource_type="time_entry", resource_id=eid,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return await _hydrate_time(e)


# ---------- Front Desk ----------
# Front-desk visits and appointments are two parallel status machines. This
# module keeps them in sync (handoff #3) and hydrates readiness signals for
# the today view (handoff #2).

# Maps a front-desk lifecycle status onto the equivalent appointment status.
# `checked_out` deliberately does NOT auto-complete the appointment — the
# POS checkout path owns that transition (handoff #4).
_FD_TO_APPT_STATUS = {
    "checked_in": "arrived",
    "in_room": "in_session",
    "no_show": "no_show",
}


async def _hydrate_fd(v):
    v = _strip_id(v)
    if not v:
        return None
    c = await find_client(client_id=v["client_id"])
    if c:
        v["client_name"] = c.get("full_name")
    # Readiness signals (handoff #2). Computed from existing collections —
    # never persisted onto the front-desk row.
    intake = await find_intake_by_client(v["client_id"])
    v["intake_complete"] = bool(intake and (intake.get("demographics") or intake.get("completed")))
    v["forms_pending"] = await db.forms.count_documents({
        "client_id": v["client_id"],
        "status": {"$in": ["sent", "draft"]},
    })
    v["documents_ready"] = await db.files.count_documents({
        "client_id": v["client_id"],
        "deleted_at": None,
    }) > 0
    # Linked transaction (handoff #4) resolved by appointment_id.
    if v.get("appointment_id"):
        appt = await db.appointments.find_one(
            {"id": v["appointment_id"]}, {"transaction_id": 1},
        )
        if appt and appt.get("transaction_id"):
            v["transaction_id"] = appt["transaction_id"]
    return v


@api.get("/front-desk/today", response_model=List[FrontDeskOut])
async def front_desk_today(user=Depends(require_roles("admin", "staff", "practitioner"))):
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    items = await db.front_desk_visits.find({"created_at": {"$gte": start, "$lt": end}}).sort("created_at", 1).to_list(200)
    return [await _hydrate_fd(i) for i in items]


@api.post("/front-desk/check-in", response_model=FrontDeskOut)
async def front_desk_checkin(payload: FrontDeskCheckIn, request: Request,
                             user=Depends(require_roles("admin", "staff", "practitioner"))):
    c = await find_client(client_id=payload.client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    doc = {
        "id": new_id(),
        "client_id": payload.client_id,
        "appointment_id": payload.appointment_id,
        "walk_in": payload.walk_in,
        "status": "checked_in",
        "room": payload.room,
        "checked_in_at": datetime.now(timezone.utc),
        "checked_out_at": None,
        "created_at": datetime.now(timezone.utc),
    }
    await db.front_desk_visits.insert_one(doc)
    await log_audit(db, user["id"], user["email"], "frontdesk.check_in",
                    resource_type="visit", resource_id=doc["id"],
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return await _hydrate_fd(doc)


@api.put("/front-desk/{vid}", response_model=FrontDeskOut)
async def front_desk_update(vid: str, payload: FrontDeskUpdate, request: Request,
                            user=Depends(require_roles("admin", "staff", "practitioner"))):
    v_prev = await db.front_desk_visits.find_one({"id": vid})
    if not v_prev:
        raise HTTPException(status_code=404, detail="Not found")
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    if payload.status == "checked_out":
        updates["checked_out_at"] = datetime.now(timezone.utc)
    await db.front_desk_visits.update_one({"id": vid}, {"$set": updates})

    # Sync onto the linked appointment (handoff #3). No-op when the visit is
    # a walk-in without an appointment or when the status has no mapping
    # (e.g. `scheduled`, `checked_out` — the POS path owns completion).
    mapped = _FD_TO_APPT_STATUS.get(payload.status) if payload.status else None
    if mapped and v_prev.get("appointment_id"):
        await db.appointments.update_one(
            {"id": v_prev["appointment_id"]},
            {"$set": {"status": mapped}},
        )

    v = await db.front_desk_visits.find_one({"id": vid})
    if not v:
        raise HTTPException(status_code=404, detail="Not found")
    await log_audit(db, user["id"], user["email"], "frontdesk.update",
                    resource_type="visit", resource_id=vid, metadata=updates,
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return await _hydrate_fd(v)


# ---------- Import Clients (CSV) ----------
@api.post("/clients/import")
async def import_clients(
    request: Request,
    file: UploadFile = File(...),
    user=Depends(require_roles("admin")),
):
    raw = await file.read()
    try:
        reader = csv.DictReader(_io.StringIO(raw.decode("utf-8-sig")))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {e}")
    imported = 0
    skipped = 0
    errors = []
    for row in reader:
        full_name = (row.get("full_name") or row.get("name") or "").strip()
        email = (row.get("email") or "").strip().lower() or None
        if not full_name and not email:
            skipped += 1
            errors.append({"row": row, "reason": "missing name/email"})
            continue
        # dedupe by email if present
        if email and await find_client(email=email):
            skipped += 1
            continue
        doc = {
            "id": new_id(),
            "user_id": None,
            "full_name": full_name or email,
            "email": email,
            "phone": (row.get("phone") or "").strip() or None,
            "dob": (row.get("dob") or "").strip() or None,
            "sex": (row.get("sex") or "").strip() or None,
            "address": (row.get("address") or "").strip() or None,
            "emergency_contact": (row.get("emergency_contact") or "").strip() or None,
            "intake_completed": False,
            "created_at": datetime.now(timezone.utc),
        }
        # `address` and `emergency_contact` are JSONB in PG; wrap free-text strings.
        if isinstance(doc.get("address"), str):
            doc["address"] = {"raw": doc["address"]}
        if isinstance(doc.get("emergency_contact"), str):
            doc["emergency_contact"] = {"raw": doc["emergency_contact"]}
        await insert_client(doc)
        imported += 1
    await db.imported_batches.insert_one({
        "id": new_id(), "filename": file.filename,
        "imported": imported, "skipped": skipped,
        "by_user": user["id"], "ts": datetime.now(timezone.utc),
    })
    await log_audit(db, user["id"], user["email"], "clients.import",
                    metadata={"imported": imported, "skipped": skipped, "filename": file.filename},
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"imported": imported, "skipped": skipped, "errors": errors[:10]}



# ---------- Provider Analytics ----------
@api.get("/analytics/overview")
async def analytics_overview(
    days: int = 30,
    user=Depends(require_roles("practitioner", "admin", "staff")),
):
    """KPI overview for the practice (last N days)."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    # Revenue from transactions
    txns = await db.transactions.find({
        "status": "paid",
        "created_at": {"$gte": start, "$lt": end},
    }).to_list(2000)
    total_revenue = round(sum(t.get("total", 0) for t in txns), 2)
    revenue_by_method = {}
    for t in txns:
        m = t.get("payment_method", "other")
        revenue_by_method[m] = round(revenue_by_method.get(m, 0) + (t.get("total", 0) or 0), 2)

    # Daily revenue series
    by_day = {}
    for t in txns:
        d = t["created_at"].date().isoformat()
        by_day[d] = round(by_day.get(d, 0) + (t.get("total", 0) or 0), 2)
    revenue_series = [{"date": d, "revenue": by_day[d]} for d in sorted(by_day)]

    # Appointments
    appts = await db.appointments.find({
        "start_time": {"$gte": start, "$lt": end},
    }).to_list(2000)
    no_show = [a for a in appts if a.get("status") == "no_show"]
    completed = [a for a in appts if a.get("status") in ("completed", "checked_out")]
    avg_duration = 0
    if completed:
        durations = []
        for a in completed:
            if a.get("start_time") and a.get("end_time"):
                durations.append((a["end_time"] - a["start_time"]).total_seconds() / 60)
        if durations:
            avg_duration = round(sum(durations) / len(durations), 1)

    # Top treatments by line revenue
    line_rev = {}
    line_count = {}
    for t in txns:
        for line in t.get("lines", []) or []:
            if line.get("type") == "treatment":
                key = line.get("name", "Unknown")
                line_rev[key] = round(line_rev.get(key, 0) + (line.get("line_total", 0) or 0), 2)
                line_count[key] = line_count.get(key, 0) + (line.get("qty", 1) or 1)
    top_treatments = sorted(
        [{"name": k, "revenue": line_rev[k], "count": line_count.get(k, 0)} for k in line_rev],
        key=lambda x: x["revenue"], reverse=True
    )[:8]

    # New clients in window
    new_clients = await count_clients(created_since=start, created_before=end)

    # Active practitioners (with >=1 note in window)
    notes = await db.visit_notes.find({"created_at": {"$gte": start, "$lt": end}}).to_list(2000)
    by_provider = {}
    for n in notes:
        pid = n.get("provider_id") or "unknown"
        by_provider[pid] = by_provider.get(pid, 0) + 1
    # single $in lookup instead of N+1
    pids = [pid for pid in by_provider.keys() if pid != "unknown"]
    users_map = {}
    if pids:
        for u in await find_users_by_ids(pids):
            users_map[u["id"]] = u.get("full_name")
    notes_by_provider = []
    for pid, cnt in sorted(by_provider.items(), key=lambda x: x[1], reverse=True):
        notes_by_provider.append({
            "provider_id": pid,
            "provider_name": users_map.get(pid, pid),
            "notes": cnt,
        })

    # Inventory low-stock count
    inv = await db.inventory_items.find().to_list(500)
    low_stock = [i for i in inv if (i.get("stock", 0) or 0) <= (i.get("low_stock_threshold", 5) or 5)]

    return {
        "window_days": days,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "revenue": {
            "total": total_revenue,
            "by_method": revenue_by_method,
            "series": revenue_series,
        },
        "appointments": {
            "total": len(appts),
            "completed": len(completed),
            "no_shows": len(no_show),
            "no_show_rate": round((len(no_show) / len(appts) * 100), 1) if appts else 0,
            "avg_duration_min": avg_duration,
        },
        "clients": {"new_clients": new_clients},
        "top_treatments": top_treatments,
        "notes_by_provider": notes_by_provider[:10],
        "low_stock_items": len(low_stock),
    }


# ---------- End-of-Day Cash Drawer Report (PDF) ----------
@api.get("/reports/eod-cash-drawer")
async def eod_cash_drawer(user=Depends(require_roles("admin", "staff"))):
    """One-page PDF: today's revenue by method, top treatments, low-stock items."""
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    txns = await db.transactions.find({
        "status": "paid", "created_at": {"$gte": start, "$lt": now},
    }).to_list(2000)

    revenue_by_method = {}
    total = 0.0
    line_rev = {}
    line_count = {}
    for t in txns:
        m = t.get("payment_method", "other")
        revenue_by_method[m] = round(revenue_by_method.get(m, 0) + (t.get("total", 0) or 0), 2)
        total += t.get("total", 0) or 0
        for line in t.get("lines", []) or []:
            key = line.get("name", "Unknown")
            line_rev[key] = round(line_rev.get(key, 0) + (line.get("line_total", 0) or 0), 2)
            line_count[key] = line_count.get(key, 0) + (line.get("qty", 1) or 1)
    total = round(total, 2)
    top_items = sorted(
        [{"name": k, "qty": line_count.get(k, 0), "revenue": line_rev[k]} for k in line_rev],
        key=lambda x: x["revenue"], reverse=True
    )[:10]

    inv = await db.inventory_items.find().to_list(500)
    low = sorted(
        [i for i in inv if (i.get("stock", 0) or 0) <= (i.get("low_stock_threshold", 5) or 5)],
        key=lambda x: x.get("stock", 0)
    )

    METHOD = {
        "chase_pos": "Chase POS", "cash": "Cash", "check": "Check",
        "card_other": "Card", "stripe": "Stripe",
    }

    buf = _io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=letter)
    width, _ = letter
    y = 10.5 * inch
    c.setFont("Helvetica-Bold", 18)
    c.drawString(0.75 * inch, y, "Natural Medical Solutions Wellness Center")
    y -= 0.3 * inch
    c.setFont("Helvetica", 10)
    c.drawString(0.75 * inch, y, "End-of-Day Cash Drawer Report")
    c.drawRightString(width - 0.75 * inch, y, now.strftime("%A, %b %d %Y · %I:%M %p UTC"))
    y -= 0.4 * inch
    c.line(0.75 * inch, y, width - 0.75 * inch, y)
    y -= 0.3 * inch

    # Revenue summary
    c.setFont("Helvetica-Bold", 12)
    c.drawString(0.75 * inch, y, f"Today's revenue ({len(txns)} transactions)")
    y -= 0.25 * inch
    c.setFont("Helvetica", 10)
    for m, val in sorted(revenue_by_method.items(), key=lambda x: -x[1]):
        c.drawString(1.0 * inch, y, METHOD.get(m, m.replace("_", " ").title()))
        c.drawRightString(width - 0.75 * inch, y, f"${val:.2f}")
        y -= 0.2 * inch
    y -= 0.05 * inch
    c.line(1.0 * inch, y, width - 0.75 * inch, y)
    y -= 0.2 * inch
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1.0 * inch, y, "TOTAL")
    c.drawRightString(width - 0.75 * inch, y, f"${total:.2f}")
    y -= 0.45 * inch

    # Cash variance line for staff to fill in
    c.setFont("Helvetica-Bold", 11)
    c.drawString(0.75 * inch, y, "Drawer reconciliation")
    y -= 0.25 * inch
    c.setFont("Helvetica", 9)
    c.drawString(1.0 * inch, y, f"Cash expected:  ${revenue_by_method.get('cash', 0):.2f}")
    y -= 0.2 * inch
    c.drawString(1.0 * inch, y, "Cash counted:   $ ____________")
    y -= 0.2 * inch
    c.drawString(1.0 * inch, y, "Variance:       $ ____________")
    y -= 0.2 * inch
    c.drawString(1.0 * inch, y, "Closed by: ______________________   Initials: _______")
    y -= 0.4 * inch

    # Top items
    if top_items:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(0.75 * inch, y, "Top items today")
        y -= 0.25 * inch
        c.setFont("Helvetica-Bold", 9)
        c.drawString(1.0 * inch, y, "Item")
        c.drawString(4.5 * inch, y, "Qty")
        c.drawRightString(width - 0.75 * inch, y, "Revenue")
        y -= 0.2 * inch
        c.setFont("Helvetica", 9)
        for it in top_items:
            c.drawString(1.0 * inch, y, it["name"][:55])
            c.drawString(4.5 * inch, y, str(it["qty"]))
            c.drawRightString(width - 0.75 * inch, y, f"${it['revenue']:.2f}")
            y -= 0.2 * inch
        y -= 0.2 * inch

    # Low stock
    if low and y > 1.5 * inch:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(0.75 * inch, y, f"Low-stock items ({len(low)})")
        y -= 0.25 * inch
        c.setFont("Helvetica", 9)
        for i in low[:15]:
            c.drawString(1.0 * inch, y,
                         f"{i.get('name','—')[:50]} — stock {i.get('stock', 0)} (threshold {i.get('low_stock_threshold', 5)})")
            y -= 0.18 * inch
            if y < 1.0 * inch:
                break

    c.setFont("Helvetica-Oblique", 8)
    c.drawString(0.75 * inch, 0.5 * inch,
                 "Confidential · Generated by NatMedSol Portal · Demo environment")

    c.showPage()
    c.save()
    buf.seek(0)
    await log_audit(db, user["id"], user["email"], "report.eod_cash_drawer")
    return StreamingResponse(buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="eod-cash-drawer-{now.date().isoformat()}.pdf"'})


