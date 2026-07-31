"""Motor-compatible PostgreSQL adapter for the Phase 3.4b retired collections.

Presents a Motor-shaped surface (`find` / `find_one` / `insert_one` /
`update_one` / `count_documents` / etc.) over the 8 PostgreSQL tables that
back the retired Mongo collections:

    messages, message_threads, form_templates, form_submissions,
    soap_templates, lab_values, treatment_plans, treatments

Every table has a JSONB `payload` column carrying router-provided fields
that aren't first-class typed columns. On insert we split incoming dicts
into (known columns, payload bucket). On read we merge `payload` back into
the returned document. Filters + sorts + array pushes fall back to the
`payload->>key` / `payload['key']` JSONB path when the field isn't a
column.

Deliberately the smallest possible bridge — routers can keep calling
``db.messages.find_one(...)`` unchanged while all reads/writes hit PG.
"""
from __future__ import annotations

import copy
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB

from postgres_db import AsyncSessionLocal
from postgres_models.clinical_and_messaging import (
    FormSubmission, FormTemplate, LabValue, Message, MessageThread,
    SoapTemplate, Treatment, TreatmentPlan,
)
from postgres_models.crm_and_ops import (
    Campaign, FileMeta, FrontDeskVisit, IntegrationLog, InternalTask,
    ProtocolEnrollment, ProtocolTemplate,
)


_MODEL_BY_NAME = {
    # Phase 3.4b — clinical/messaging
    "message_threads": MessageThread,
    "messages": Message,
    "form_templates": FormTemplate,
    "form_submissions": FormSubmission,
    "soap_templates": SoapTemplate,
    "lab_values": LabValue,
    "treatment_plans": TreatmentPlan,
    "treatments": Treatment,
    # Phase 3.5 — CRM & operations
    "campaigns": Campaign,
    "front_desk_visits": FrontDeskVisit,
    "internal_tasks": InternalTask,
    "integration_log": IntegrationLog,
    "protocol_enrollments": ProtocolEnrollment,
    "protocol_templates": ProtocolTemplate,
    "files": FileMeta,
}


# ---------- helpers ---------------------------------------------------- #
def _model_columns(model) -> set:
    return {c.name for c in model.__table__.columns}


def _to_jsonable(v: Any) -> Any:
    """Coerce values headed for a JSONB payload column into JSON-friendly
    scalars. Datetimes → ISO strings. Everything else is passed through."""
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _to_jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_to_jsonable(x) for x in v]
    return v


def _split_doc(model, doc: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Split an incoming Mongo-shaped dict into (typed_columns, payload).
    Reserved: `_id` is dropped."""
    cols = _model_columns(model)
    typed: Dict[str, Any] = {}
    payload: Dict[str, Any] = {}
    for k, v in doc.items():
        if k == "_id":
            continue
        if k in cols and k != "payload":
            typed[k] = v
        else:
            payload[k] = _to_jsonable(v)
    return typed, payload


def _row_to_dict(row) -> Optional[Dict[str, Any]]:
    """Return a Mongo-shaped dict: payload merged first, then column values
    override (columns are authoritative for their fields)."""
    if row is None:
        return None
    payload = dict(row.payload or {})
    out = dict(payload)
    for c in row.__table__.columns:
        if c.name == "payload":
            continue
        out[c.name] = getattr(row, c.name)
    return out


def _col_or_jsonb(model, key: str):
    """Return a SQLAlchemy expression for the given field: the typed column
    when it exists, otherwise a JSONB text extraction from `payload->>key`."""
    col = getattr(model, key, None)
    if col is not None and key != "payload":
        return col, True  # typed
    return model.payload[key].astext, False  # jsonb text


def _jsonb_eq(model, key: str, val: Any):
    """Type-safe equality on payload[key] using JSONB containment so
    booleans / numbers / null behave correctly."""
    if val is None:
        return or_(
            ~model.payload.has_key(key),  # noqa: W601
            model.payload[key].astext.is_(None),
        )
    return model.payload.contains({key: _to_jsonable(val)})


def _jsonb_ne(model, key: str, val: Any):
    return ~_jsonb_eq(model, key, val)


def _cast_scalar_for_column(col, val: Any) -> Any:
    """Best-effort coerce a raw scalar to the column type where needed."""
    return val


_MONGO_OPS_STRIP = {"$options"}


def _apply_filter(stmt, model, filt: Dict[str, Any]):
    if not filt:
        return stmt
    for key, val in filt.items():
        if key == "$or":
            stmt = stmt.where(or_(*[_build_or_clause(model, c) for c in val]))
            continue
        expr, typed = _col_or_jsonb(model, key)
        if isinstance(val, dict):
            for op_key, op_val in val.items():
                if op_key in _MONGO_OPS_STRIP:
                    continue
                if op_key == "$in":
                    if typed:
                        stmt = stmt.where(expr.in_(list(op_val)))
                    else:
                        stmt = stmt.where(or_(*[_jsonb_eq(model, key, x) for x in op_val]))
                elif op_key == "$nin":
                    if typed:
                        stmt = stmt.where(~expr.in_(list(op_val)))
                    else:
                        stmt = stmt.where(~or_(*[_jsonb_eq(model, key, x) for x in op_val]))
                elif op_key == "$gte":
                    stmt = stmt.where(expr >= (op_val if typed else _to_jsonable(op_val)))
                elif op_key == "$lte":
                    stmt = stmt.where(expr <= (op_val if typed else _to_jsonable(op_val)))
                elif op_key == "$gt":
                    stmt = stmt.where(expr > (op_val if typed else _to_jsonable(op_val)))
                elif op_key == "$lt":
                    stmt = stmt.where(expr < (op_val if typed else _to_jsonable(op_val)))
                elif op_key == "$ne":
                    if typed:
                        stmt = stmt.where(or_(expr.is_(None), expr != op_val))
                    else:
                        stmt = stmt.where(_jsonb_ne(model, key, op_val))
                elif op_key == "$exists":
                    if typed:
                        stmt = stmt.where(expr.is_not(None) if op_val else expr.is_(None))
                    else:
                        has = model.payload.has_key(key)  # noqa: W601
                        stmt = stmt.where(has if op_val else ~has)
                elif op_key == "$regex":
                    flags = val.get("$options", "")
                    pattern = op_val
                    if "i" in flags:
                        stmt = stmt.where(expr.op("~*")(pattern))
                    else:
                        stmt = stmt.where(expr.op("~")(pattern))
                # $options handled inline for $regex
        else:
            if typed:
                if val is None:
                    stmt = stmt.where(expr.is_(None))
                else:
                    stmt = stmt.where(expr == val)
            else:
                stmt = stmt.where(_jsonb_eq(model, key, val))
    return stmt


def _build_or_clause(model, clause: Dict[str, Any]):
    """Build a single OR sub-clause from a Mongo-shaped filter fragment."""
    from sqlalchemy import and_ as _and
    parts = []
    for key, val in clause.items():
        expr, typed = _col_or_jsonb(model, key)
        if isinstance(val, dict):
            for op_key, op_val in val.items():
                if op_key == "$in":
                    if typed:
                        parts.append(expr.in_(list(op_val)))
                    else:
                        parts.append(or_(*[_jsonb_eq(model, key, x) for x in op_val]))
                elif op_key == "$ne":
                    if typed:
                        parts.append(or_(expr.is_(None), expr != op_val))
                    else:
                        parts.append(_jsonb_ne(model, key, op_val))
                elif op_key == "$exists":
                    if typed:
                        parts.append(expr.is_not(None) if op_val else expr.is_(None))
                    else:
                        has = model.payload.has_key(key)  # noqa: W601
                        parts.append(has if op_val else ~has)
        else:
            if typed:
                parts.append(expr == val)
            else:
                parts.append(_jsonb_eq(model, key, val))
    return _and(*parts) if parts else func.true()


# ---------- cursor ----------------------------------------------------- #
class _AsyncCursor:
    """Emulates Motor's cursor: supports `.sort().limit().to_list()`."""

    def __init__(self, model, filt: Dict[str, Any]):
        self._model = model
        self._filt = filt
        self._sort: Optional[list] = None
        self._limit: Optional[int] = None
        self._skip: int = 0

    def sort(self, key_or_list, direction: int = 1):
        if isinstance(key_or_list, list):
            self._sort = list(key_or_list)
        else:
            self._sort = [(key_or_list, direction)]
        return self

    def limit(self, n: int):
        self._limit = int(n)
        return self

    def skip(self, n: int):
        self._skip = int(n)
        return self

    async def to_list(self, length: Optional[int] = None):
        n = length if length is not None else (self._limit or 500)
        async with AsyncSessionLocal() as pg:
            stmt = select(self._model)
            stmt = _apply_filter(stmt, self._model, self._filt)
            if self._sort:
                for key, direction in self._sort:
                    expr, _typed = _col_or_jsonb(self._model, key)
                    stmt = stmt.order_by(expr.desc() if direction < 0 else expr.asc())
            if self._skip:
                stmt = stmt.offset(self._skip)
            if n is not None:
                stmt = stmt.limit(n)
            rows = (await pg.execute(stmt)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def __aiter__(self):
        self._iter = None
        return self

    async def __anext__(self):
        if self._iter is None:
            self._iter = iter(await self.to_list(self._limit or 1000))
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


# ---------- collection ------------------------------------------------- #
class _UpdateResult:
    def __init__(self, matched: int, modified: int, upserted_id: Optional[str] = None):
        self.matched_count = matched
        self.modified_count = modified
        self.upserted_id = upserted_id


class _DeleteResult:
    def __init__(self, n: int):
        self.deleted_count = n


class _InsertOneResult:
    def __init__(self, inserted_id: Any):
        self.inserted_id = inserted_id


class _InsertManyResult:
    def __init__(self, inserted_ids: List[Any]):
        self.inserted_ids = inserted_ids


class MotorCompatCollection:
    """Motor-shaped collection over a SQLAlchemy model."""

    def __init__(self, name: str):
        self._name = name
        self._model = _MODEL_BY_NAME[name]

    # -------- reads --------
    def find(self, filt: Optional[Dict[str, Any]] = None,
             projection: Optional[Dict[str, int]] = None):
        # Projections are ignored — return the full row.
        return _AsyncCursor(self._model, filt or {})

    async def find_one(self, filt: Dict[str, Any] = None,
                        projection: Optional[Dict[str, int]] = None,
                        sort: Optional[list] = None) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as pg:
            stmt = _apply_filter(select(self._model), self._model, filt or {})
            if sort:
                for key, direction in sort:
                    expr, _typed = _col_or_jsonb(self._model, key)
                    stmt = stmt.order_by(expr.desc() if direction < 0 else expr.asc())
            stmt = stmt.limit(1)
            row = (await pg.execute(stmt)).scalar_one_or_none()
            return _row_to_dict(row)

    async def count_documents(self, filt: Optional[Dict[str, Any]] = None) -> int:
        async with AsyncSessionLocal() as pg:
            stmt = _apply_filter(
                select(func.count()).select_from(self._model),
                self._model, filt or {},
            )
            return int((await pg.execute(stmt)).scalar_one())

    async def distinct(self, key: str, filt: Optional[Dict[str, Any]] = None) -> List[Any]:
        expr, _typed = _col_or_jsonb(self._model, key)
        async with AsyncSessionLocal() as pg:
            stmt = _apply_filter(select(expr).distinct(), self._model, filt or {})
            return [r for r in (await pg.execute(stmt)).scalars().all()]

    # -------- inserts --------
    async def insert_one(self, doc: Dict[str, Any]) -> _InsertOneResult:
        doc = dict(doc or {})
        doc.setdefault("id", uuid.uuid4().hex)
        typed, payload = _split_doc(self._model, doc)
        typed["payload"] = payload
        async with AsyncSessionLocal() as pg:
            async with pg.begin():
                row = self._model(**typed)
                pg.add(row)
                await pg.flush()
        return _InsertOneResult(doc["id"])

    async def insert_many(self, docs: List[Dict[str, Any]]) -> _InsertManyResult:
        ids = []
        async with AsyncSessionLocal() as pg:
            async with pg.begin():
                for d in docs:
                    d = dict(d)
                    d.setdefault("id", uuid.uuid4().hex)
                    ids.append(d["id"])
                    typed, payload = _split_doc(self._model, d)
                    typed["payload"] = payload
                    pg.add(self._model(**typed))
        return _InsertManyResult(ids)

    # -------- updates --------
    async def _apply_update_ops(self, row, update_ops: Dict[str, Any]) -> None:
        set_vals: Dict[str, Any] = dict(update_ops.get("$set") or {})
        unset_vals: Dict[str, Any] = dict(update_ops.get("$unset") or {})
        push_ops: Dict[str, Any] = dict(update_ops.get("$push") or {})
        add_to_set: Dict[str, Any] = dict(update_ops.get("$addToSet") or {})
        pull_ops: Dict[str, Any] = dict(update_ops.get("$pull") or {})
        inc_ops: Dict[str, Any] = dict(update_ops.get("$inc") or {})

        cols = _model_columns(self._model)
        payload = dict(row.payload or {})

        # $set
        for k, v in set_vals.items():
            if k in cols and k != "payload":
                setattr(row, k, v)
            else:
                payload[k] = _to_jsonable(v)
        # $unset
        for k in unset_vals.keys():
            if k in cols and k != "payload":
                setattr(row, k, None)
            elif k in payload:
                payload.pop(k, None)
        # $inc
        for k, v in inc_ops.items():
            if k in cols and k != "payload":
                cur = getattr(row, k, 0) or 0
                setattr(row, k, cur + v)
            else:
                payload[k] = (payload.get(k) or 0) + v
        # $push
        for k, v in push_ops.items():
            if k in cols and k != "payload":
                cur = list(getattr(row, k) or [])
                cur.append(v)
                setattr(row, k, cur)
            else:
                cur = list(payload.get(k) or [])
                cur.append(_to_jsonable(v))
                payload[k] = cur
        # $addToSet
        for k, v in add_to_set.items():
            values = v.get("$each") if isinstance(v, dict) and "$each" in v else [v]
            if k in cols and k != "payload":
                cur = list(getattr(row, k) or [])
                for item in values:
                    if item not in cur:
                        cur.append(item)
                setattr(row, k, cur)
            else:
                cur = list(payload.get(k) or [])
                for item in values:
                    jitem = _to_jsonable(item)
                    if jitem not in cur:
                        cur.append(jitem)
                payload[k] = cur
        # $pull
        for k, v in pull_ops.items():
            if k in cols and k != "payload":
                cur = list(getattr(row, k) or [])
                setattr(row, k, [x for x in cur if x != v])
            else:
                cur = list(payload.get(k) or [])
                jv = _to_jsonable(v)
                payload[k] = [x for x in cur if x != jv]

        # Assign a fresh dict so SQLAlchemy detects the mutation on JSONB.
        row.payload = payload

    async def update_one(self, filt: Dict[str, Any], update_ops: Dict[str, Any],
                          upsert: bool = False) -> _UpdateResult:
        modified = 0
        upserted_id: Optional[str] = None
        async with AsyncSessionLocal() as pg:
            async with pg.begin():
                stmt = _apply_filter(select(self._model), self._model, filt or {}).limit(1)
                row = (await pg.execute(stmt)).scalar_one_or_none()
                if row:
                    await self._apply_update_ops(row, update_ops)
                    modified = 1
                elif upsert:
                    # Build a synthetic doc from the filter + $set + $setOnInsert
                    doc: Dict[str, Any] = {}
                    for k, v in (filt or {}).items():
                        if not isinstance(v, dict):
                            doc[k] = v
                    for src in ("$setOnInsert", "$set"):
                        for k, v in (update_ops.get(src) or {}).items():
                            doc.setdefault(k, v)
                    doc.setdefault("id", uuid.uuid4().hex)
                    typed, payload = _split_doc(self._model, doc)
                    typed["payload"] = payload
                    row = self._model(**typed)
                    pg.add(row)
                    await pg.flush()
                    # Apply any $push / $addToSet from the update ops
                    remainder = {k: v for k, v in update_ops.items()
                                 if k in ("$push", "$addToSet", "$inc")}
                    if remainder:
                        await self._apply_update_ops(row, remainder)
                    upserted_id = doc["id"]
        return _UpdateResult(modified + (1 if upserted_id else 0),
                              modified, upserted_id)

    async def update_many(self, filt: Dict[str, Any],
                           update_ops: Dict[str, Any]) -> _UpdateResult:
        modified = 0
        async with AsyncSessionLocal() as pg:
            async with pg.begin():
                stmt = _apply_filter(select(self._model), self._model, filt or {})
                for row in (await pg.execute(stmt)).scalars().all():
                    await self._apply_update_ops(row, update_ops)
                    modified += 1
        return _UpdateResult(modified, modified)

    async def find_one_and_update(self, filt: Dict[str, Any],
                                    update_ops: Dict[str, Any], *,
                                    return_document: Any = None,
                                    **_kwargs) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as pg:
            async with pg.begin():
                stmt = _apply_filter(select(self._model), self._model, filt or {}).limit(1)
                row = (await pg.execute(stmt)).scalar_one_or_none()
                if not row:
                    return None
                # ReturnDocument.BEFORE preserves the pre-update snapshot.
                before = _row_to_dict(row) if return_document is not None else None
                await self._apply_update_ops(row, update_ops)
                await pg.flush()
                after = _row_to_dict(row)
        # Mongo's `ReturnDocument.AFTER` == 1 (True-ish); .BEFORE == 0. We
        # can't import pymongo here, so we treat any truthy value as AFTER.
        if return_document:
            return after
        return before if before is not None else after

    # -------- deletes --------
    async def delete_one(self, filt: Dict[str, Any]) -> _DeleteResult:
        async with AsyncSessionLocal() as pg:
            async with pg.begin():
                stmt = _apply_filter(select(self._model), self._model, filt or {}).limit(1)
                row = (await pg.execute(stmt)).scalar_one_or_none()
                if row:
                    await pg.delete(row)
                    n = 1
                else:
                    n = 0
        return _DeleteResult(n)

    async def delete_many(self, filt: Dict[str, Any]) -> _DeleteResult:
        async with AsyncSessionLocal() as pg:
            async with pg.begin():
                stmt = _apply_filter(delete(self._model), self._model, filt or {})
                r = await pg.execute(stmt)
        return _DeleteResult(r.rowcount or 0)

    # -------- indexes --------
    async def create_index(self, *_args, **_kwargs):
        # Alembic owns index topology for these tables.
        return None

    async def create_indexes(self, *_args, **_kwargs):
        return None

    # -------- misc --------
    async def aggregate(self, pipeline, **_kwargs):
        # Not used by any Phase 3.4b caller. Return an empty async iterator.
        class _Empty:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

            async def to_list(self, length=None):
                return []
        return _Empty()


# ---------- database facade ------------------------------------------- #
class MotorCompatDb:
    """Wraps a Motor database, transparently returning MotorCompatCollection
    for retired collections and delegating everything else to Motor.

    Retired collection names are RE-ROUTED to PostgreSQL with no possibility
    of Mongo fallback for those 8 collections. Every other collection is
    passed through unchanged to Motor."""

    _RETIRED = frozenset(_MODEL_BY_NAME.keys())

    def __init__(self, motor_db):
        self._motor = motor_db
        self._overrides = {n: MotorCompatCollection(n) for n in self._RETIRED}

    # Motor exposes collection access via both attribute and index. Cover
    # both so router code keeps working.
    def __getattr__(self, name: str):
        # __getattr__ is only called when the attribute isn't found normally
        overrides = self.__dict__.get("_overrides") or {}
        if name in overrides:
            return overrides[name]
        return getattr(self.__dict__["_motor"], name)

    def __getitem__(self, name: str):
        if name in self._overrides:
            return self._overrides[name]
        return self._motor[name]

    # For repr and debugging.
    def __repr__(self) -> str:  # pragma: no cover
        return f"<MotorCompatDb wrapping {self._motor!r} retired={sorted(self._RETIRED)}>"
