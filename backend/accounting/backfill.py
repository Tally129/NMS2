"""
Historic Backfill — replays legacy operational data through the event bus.

Design principles
=================
* Idempotent by construction. Every event carries a stable idempotency_key
  (typically ``{collection}:{doc_id}:{event_type}``). Re-running a backfill
  never double-posts, because ``accounting.events.emit()`` short-circuits on
  duplicate keys.
* Resumable. Progress is persisted to ``db.accounting_backfill_runs`` on a
  per-source basis (``cursors`` map). A crashed or interrupted run can be
  resumed from where it left off by passing ``resume_run_id``.
* Dry-run first. A dry run enumerates the same event stream but skips
  ``emit()`` — instead it counts what *would* be posted plus what already
  exists as an event, so operators can preview impact.
* Zero writes to operational data. Backfill never modifies transactions,
  invoices, memberships, inventory, or expenses. It only reads them and
  emits accounting events.

Supported sources
-----------------
    pos            db.transactions (status='paid')      -> SaleCompleted
    invoices       db.invoices (status='due'|'paid'|…)  -> InvoiceIssued
    invoice_payments db.invoices (status='paid')        -> InvoicePaid
    memberships    db.memberships (started_at != null)  -> MembershipStarted
    inventory      db.inventory_transactions            -> InventoryAdjusted
                     (skips reason='pos_sale' — already handled by SaleCompleted)
    expenses       db.expenses                          -> ManualExpenseRecorded
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from deps import db
from models import new_id

from .events import AccountingEvent, emit

# ------------------------------------------------------------------ sources #
SUPPORTED_SOURCES = ("pos", "invoices", "invoice_payments",
                     "memberships", "inventory", "expenses")


def _to_cents(v) -> int:
    try:
        return int(round(float(v or 0) * 100))
    except Exception:
        return 0


def _norm_dt(v) -> datetime:
    if v is None:
        return datetime.now(timezone.utc)
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ builders #
async def _events_from_pos(cursor_iso: Optional[str], limit: int):
    q: dict = {"status": "paid"}
    if cursor_iso:
        q["created_at"] = {"$gt": _norm_dt(cursor_iso)}
    async for txn in db.transactions.find(q).sort("created_at", 1).limit(limit):
        ctx_lines = [{
            "line_type": ln.get("type"),
            "ref_id": ln.get("ref_id"),
            "qty": ln.get("qty") or 1,
            "unit_price_cents": _to_cents(ln.get("unit_price")),
            "line_total_cents": _to_cents(ln.get("line_total")),
        } for ln in (txn.get("lines") or [])]
        yield ("pos", _norm_dt(txn.get("created_at")), AccountingEvent(
            event_type="SaleCompleted",
            occurred_at=_norm_dt(txn.get("created_at")),
            source_module="backfill", source_ref_type="transaction",
            source_ref_id=txn["id"],
            idempotency_key=f"transaction:{txn['id']}:SaleCompleted",
            amount_cents=_to_cents(txn.get("total")),
            context={
                "payment_method": txn.get("payment_method"),
                "subtotal_cents": _to_cents(txn.get("subtotal")),
                "discount_cents": _to_cents(txn.get("discount")),
                "tip_cents": _to_cents(txn.get("tip")),
                "tax_cents": _to_cents(txn.get("tax")),
                "lines": ctx_lines,
                "backfilled": True,
            },
            actor_id=txn.get("created_by"), actor_role="system",
        ))


async def _events_from_invoices(cursor_iso: Optional[str], limit: int):
    q: dict = {}
    if cursor_iso:
        q["created_at"] = {"$gt": _norm_dt(cursor_iso)}
    async for inv in db.invoices.find(q).sort("created_at", 1).limit(limit):
        yield ("invoices", _norm_dt(inv.get("created_at")), AccountingEvent(
            event_type="InvoiceIssued",
            occurred_at=_norm_dt(inv.get("created_at")),
            source_module="backfill", source_ref_type="invoice",
            source_ref_id=inv["id"],
            idempotency_key=f"invoice:{inv['id']}:InvoiceIssued",
            amount_cents=_to_cents(inv.get("amount")),
            context={"client_id": inv.get("client_id"),
                     "description": inv.get("description"),
                     "backfilled": True},
            actor_id=None, actor_role="system",
        ))


async def _events_from_invoice_payments(cursor_iso: Optional[str], limit: int):
    q: dict = {"status": "paid"}
    if cursor_iso:
        q["paid_at"] = {"$gt": _norm_dt(cursor_iso)}
    async for inv in db.invoices.find(q).sort("paid_at", 1).limit(limit):
        paid_at = _norm_dt(inv.get("paid_at") or inv.get("created_at"))
        yield ("invoice_payments", paid_at, AccountingEvent(
            event_type="InvoicePaid",
            occurred_at=paid_at,
            source_module="backfill", source_ref_type="invoice",
            source_ref_id=inv["id"],
            idempotency_key=f"invoice:{inv['id']}:InvoicePaid",
            amount_cents=_to_cents(inv.get("amount")),
            context={"payment_method": inv.get("payment_method") or "other",
                     "backfilled": True},
            actor_id=None, actor_role="system",
        ))


async def _events_from_memberships(cursor_iso: Optional[str], limit: int):
    q: dict = {"started_at": {"$ne": None}}
    if cursor_iso:
        q["started_at"]["$gt"] = _norm_dt(cursor_iso)
    async for m in db.memberships.find(q).sort("started_at", 1).limit(limit):
        started = _norm_dt(m.get("started_at") or m.get("created_at"))
        yield ("memberships", started, AccountingEvent(
            event_type="MembershipStarted",
            occurred_at=started,
            source_module="backfill", source_ref_type="membership",
            source_ref_id=m["id"],
            idempotency_key=f"membership:{m['id']}:MembershipStarted",
            amount_cents=_to_cents(m.get("price")),
            context={"tier": m.get("tier"),
                     "payment_method": m.get("billing_method") or "stripe",
                     "backfilled": True},
            actor_id=None, actor_role="system",
        ))


async def _events_from_inventory(cursor_iso: Optional[str], limit: int):
    q: dict = {"reason": {"$ne": "pos_sale"}}
    if cursor_iso:
        q["ts"] = {"$gt": _norm_dt(cursor_iso)}
    async for row in db.inventory_transactions.find(q).sort("ts", 1).limit(limit):
        item = await db.inventory_items.find_one({"id": row.get("item_id")}) or {}
        unit_cost_cents = _to_cents(item.get("unit_price"))
        qty_delta = int(row.get("change") or 0)
        amt = abs(qty_delta) * unit_cost_cents
        ts = _norm_dt(row.get("ts"))
        yield ("inventory", ts, AccountingEvent(
            event_type="InventoryAdjusted",
            occurred_at=ts,
            source_module="backfill", source_ref_type="inventory_txn",
            source_ref_id=row["id"],
            idempotency_key=f"inventory_txn:{row['id']}:InventoryAdjusted",
            amount_cents=amt,
            context={"reason": row.get("reason") or "adjustment",
                     "qty_delta": qty_delta,
                     "unit_cost_cents": unit_cost_cents,
                     "backfilled": True},
            actor_id=row.get("user_id"), actor_role="system",
        ))


async def _events_from_expenses(cursor_iso: Optional[str], limit: int):
    q: dict = {}
    if cursor_iso:
        q["created_at"] = {"$gt": _norm_dt(cursor_iso)}
    async for exp in db.expenses.find(q).sort("created_at", 1).limit(limit):
        occurred = _norm_dt(exp.get("occurred_at") or exp.get("created_at"))
        yield ("expenses", occurred, AccountingEvent(
            event_type="ManualExpenseRecorded",
            occurred_at=occurred,
            source_module="backfill", source_ref_type="expense",
            source_ref_id=exp["id"],
            idempotency_key=f"expense:{exp['id']}:ManualExpenseRecorded",
            amount_cents=int(exp.get("amount_cents") or 0),
            context={"payment_method": exp.get("payment_method") or "check",
                     "expense_account": exp.get("expense_account") or "6900",
                     "memo": exp.get("memo"),
                     "vendor_id": exp.get("vendor_id"),
                     "backfilled": True},
            actor_id=exp.get("created_by"), actor_role="system",
        ))


SOURCE_BUILDERS = {
    "pos":               _events_from_pos,
    "invoices":          _events_from_invoices,
    "invoice_payments":  _events_from_invoice_payments,
    "memberships":       _events_from_memberships,
    "inventory":         _events_from_inventory,
    "expenses":          _events_from_expenses,
}


# ------------------------------------------------------------------ engine #
BATCH_SIZE = 500


def _empty_counters() -> dict:
    return {
        "candidates": 0,   # events considered
        "posted": 0,       # newly written
        "duplicates": 0,   # already had matching event
        "dead_letters": 0, # rule missing / write failed
        "errors": 0,       # exceptions
    }


async def preview(sources: list[str]) -> dict:
    """Dry-run: enumerate + classify without emitting."""
    sources = [s for s in sources if s in SOURCE_BUILDERS] or list(SUPPORTED_SOURCES)
    per_source: dict[str, dict] = {}
    grand = _empty_counters()
    for src in sources:
        counters = _empty_counters()
        builder = SOURCE_BUILDERS[src]
        cursor = None
        # scan in pages to keep memory small
        while True:
            page = []
            async for tag, ts, ev in builder(cursor, BATCH_SIZE):
                page.append((ts, ev))
            if not page:
                break
            for _ts, ev in page:
                counters["candidates"] += 1
                existing = await db.accounting_events.find_one(
                    {"idempotency_key": ev.idempotency_key},
                    {"id": 1},
                )
                if existing:
                    counters["duplicates"] += 1
                else:
                    counters["posted"] += 1     # would-be-posted
            cursor = page[-1][0].isoformat()
            if len(page) < BATCH_SIZE:
                break
        per_source[src] = counters
        for k in grand:
            grand[k] += counters[k]
    return {
        "mode": "dry_run",
        "sources": sources,
        "per_source": per_source,
        "totals": grand,
    }


async def _persist_run(run: dict) -> None:
    await db.accounting_backfill_runs.replace_one(
        {"id": run["id"]}, run, upsert=True,
    )


async def start_run(sources: list[str], actor: dict) -> dict:
    sources = [s for s in sources if s in SOURCE_BUILDERS] or list(SUPPORTED_SOURCES)
    now = datetime.now(timezone.utc)
    run = {
        "id": new_id(),
        "mode": "execute",
        "status": "running",
        "sources": sources,
        "cursors": {s: None for s in sources},
        "counters": {s: _empty_counters() for s in sources},
        "totals": _empty_counters(),
        "started_at": now,
        "updated_at": now,
        "finished_at": None,
        "error": None,
        "started_by": actor.get("id"),
        "started_by_name": actor.get("full_name") or actor.get("email"),
    }
    await _persist_run(run)
    return run


async def _process_source(run: dict, source: str) -> None:
    builder = SOURCE_BUILDERS[source]
    counters = run["counters"][source]
    cursor = run["cursors"].get(source)
    while True:
        page = []
        async for tag, ts, ev in builder(cursor, BATCH_SIZE):
            page.append((ts, ev))
        if not page:
            break
        for ts, ev in page:
            counters["candidates"] += 1
            try:
                _, status = await emit(ev)
                if status == "posted":
                    counters["posted"] += 1
                elif status == "duplicate":
                    counters["duplicates"] += 1
                elif status == "dead_letter":
                    counters["dead_letters"] += 1
            except Exception:
                counters["errors"] += 1
        cursor = page[-1][0].isoformat()
        run["cursors"][source] = cursor
        run["updated_at"] = datetime.now(timezone.utc)
        await _persist_run(run)
        if len(page) < BATCH_SIZE:
            break


async def execute_run(run_id: str) -> dict:
    """Blocking-style execute: runs each source in-order and persists progress."""
    run = await db.accounting_backfill_runs.find_one({"id": run_id})
    if not run:
        raise ValueError("run not found")
    run.pop("_id", None)
    run["status"] = "running"
    await _persist_run(run)
    try:
        for src in run["sources"]:
            await _process_source(run, src)
        # aggregate totals
        totals = _empty_counters()
        for s, c in run["counters"].items():
            for k in totals:
                totals[k] += c.get(k, 0)
        run["totals"] = totals
        run["status"] = "completed"
        run["finished_at"] = datetime.now(timezone.utc)
    except Exception as e:  # pragma: no cover
        run["status"] = "failed"
        run["error"] = str(e)[:400]
        run["finished_at"] = datetime.now(timezone.utc)
    await _persist_run(run)
    return run


def spawn_run_in_background(run_id: str) -> None:
    """Fire-and-forget: schedule execute_run on the event loop."""
    async def _runner():
        try:
            await execute_run(run_id)
        except Exception:
            # execute_run already persisted the failure
            pass
    loop = asyncio.get_event_loop()
    loop.create_task(_runner())


async def resume_run(run_id: str) -> dict:
    """Restart an interrupted/failed run at its saved cursor."""
    run = await db.accounting_backfill_runs.find_one({"id": run_id})
    if not run:
        raise ValueError("run not found")
    if run.get("status") == "completed":
        return run
    run["status"] = "running"
    run["error"] = None
    run.pop("_id", None)
    await _persist_run(run)
    return await execute_run(run_id)
