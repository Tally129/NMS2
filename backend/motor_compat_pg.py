"""Motor-compatible PostgreSQL adapter for the Phase 3.4b retired collections.

Wraps `repositories.clinical_and_messaging` and `repositories.scheduling` in
a minimal `find_one` / `find` / `insert_one` / `update_one` / `delete_one` /
`count_documents` surface so the remaining routers can call
``db.message_threads.find_one(...)`` etc. without individual rewrites.

This adapter is intentionally the smallest possible bridge — it exists only
to complete Phase 3.4b's "no runtime Mongo dependency" requirement while a
follow-up sub-phase migrates each caller to the native async repository API.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from postgres_db import AsyncSessionLocal
from postgres_models.clinical_and_messaging import (
    FormSubmission, FormTemplate, LabValue, Message, MessageThread,
    SoapTemplate, Treatment, TreatmentPlan,
)


_MODEL_BY_NAME = {
    "message_threads": MessageThread,
    "messages": Message,
    "form_templates": FormTemplate,
    "form_submissions": FormSubmission,
    "soap_templates": SoapTemplate,
    "lab_values": LabValue,
    "treatment_plans": TreatmentPlan,
    "treatments": Treatment,
}


def _row_to_dict(row) -> Dict[str, Any]:
    if row is None:
        return None
    d = {}
    for c in row.__table__.columns:
        val = getattr(row, c.name)
        d[c.name] = val
    return d


def _apply_filter(stmt, model, filt: Dict[str, Any]):
    if not filt:
        return stmt
    for key, val in filt.items():
        col = getattr(model, key, None)
        if col is None:
            # Unknown field — no rows match.
            return stmt.where(model.id == "__nope__")
        if isinstance(val, dict):
            for op_key, op_val in val.items():
                if op_key == "$in":
                    stmt = stmt.where(col.in_(list(op_val)))
                elif op_key == "$nin":
                    stmt = stmt.where(~col.in_(list(op_val)))
                elif op_key == "$gte":
                    stmt = stmt.where(col >= op_val)
                elif op_key == "$lte":
                    stmt = stmt.where(col <= op_val)
                elif op_key == "$gt":
                    stmt = stmt.where(col > op_val)
                elif op_key == "$lt":
                    stmt = stmt.where(col < op_val)
                elif op_key == "$ne":
                    stmt = stmt.where(col != op_val)
                elif op_key == "$exists":
                    stmt = stmt.where(col.is_not(None) if op_val else col.is_(None))
                elif op_key == "$regex":
                    flags = val.get("$options", "")
                    if "i" in flags:
                        stmt = stmt.where(col.op("~*")(op_val))
                    else:
                        stmt = stmt.where(col.op("~")(op_val))
                # $options is consumed by $regex above
        else:
            stmt = stmt.where(col == val)
    return stmt


class _AsyncCursor:
    """Emulates Motor's cursor: supports `.sort().limit().to_list()`."""

    def __init__(self, model, filt: Dict[str, Any]):
        self._model = model
        self._filt = filt
        self._sort: Optional[list] = None
        self._limit: Optional[int] = None

    def sort(self, key, direction=1):
        self._sort = (key, direction)
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    async def to_list(self, length: Optional[int] = None):
        n = length or self._limit or 500
        async with AsyncSessionLocal() as pg:
            stmt = select(self._model)
            stmt = _apply_filter(stmt, self._model, self._filt)
            if self._sort:
                key, direction = self._sort
                col = getattr(self._model, key, None)
                if col is not None:
                    stmt = stmt.order_by(col.desc() if direction < 0 else col.asc())
            stmt = stmt.limit(n)
            return [_row_to_dict(r) for r in (await pg.execute(stmt)).scalars().all()]

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


class MotorCompatCollection:
    """Motor-shaped collection over a SQLAlchemy model."""

    def __init__(self, name: str):
        self._name = name
        self._model = _MODEL_BY_NAME[name]

    def find(self, filt: Optional[Dict[str, Any]] = None,
             projection: Optional[Dict[str, int]] = None):
        # Projections are ignored — return the full row.
        return _AsyncCursor(self._model, filt or {})

    async def find_one(self, filt: Dict[str, Any],
                        projection: Optional[Dict[str, int]] = None,
                        sort: Optional[list] = None) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as pg:
            stmt = _apply_filter(select(self._model), self._model, filt or {})
            if sort:
                for key, direction in sort:
                    col = getattr(self._model, key, None)
                    if col is not None:
                        stmt = stmt.order_by(col.desc() if direction < 0 else col.asc())
            stmt = stmt.limit(1)
            return _row_to_dict((await pg.execute(stmt)).scalar_one_or_none())

    async def count_documents(self, filt: Optional[Dict[str, Any]] = None) -> int:
        async with AsyncSessionLocal() as pg:
            stmt = _apply_filter(select(func.count(self._model.id)),
                                  self._model, filt or {})
            return int((await pg.execute(stmt)).scalar_one())

    async def insert_one(self, doc: Dict[str, Any]) -> Any:
        cols = {k: v for k, v in doc.items() if hasattr(self._model, k)}
        async with AsyncSessionLocal() as pg:
            async with pg.begin():
                row = self._model(**cols)
                pg.add(row)
                await pg.flush()
        class _R:
            inserted_id = doc.get("id")
        return _R()

    async def insert_many(self, docs: List[Dict[str, Any]]):
        async with AsyncSessionLocal() as pg:
            async with pg.begin():
                for d in docs:
                    cols = {k: v for k, v in d.items() if hasattr(self._model, k)}
                    pg.add(self._model(**cols))
        class _R:
            inserted_ids = [d.get("id") for d in docs]
        return _R()

    async def update_one(self, filt: Dict[str, Any], update_ops: Dict[str, Any],
                          upsert: bool = False):
        set_vals: Dict[str, Any] = dict(update_ops.get("$set") or {})
        push_ops = update_ops.get("$push") or {}
        addToSet = update_ops.get("$addToSet") or {}
        setOnInsert = update_ops.get("$setOnInsert") or {}
        set_vals = {k: v for k, v in set_vals.items() if hasattr(self._model, k)}
        modified = 0
        upserted = 0
        async with AsyncSessionLocal() as pg:
            async with pg.begin():
                stmt = _apply_filter(select(self._model), self._model, filt or {}).limit(1)
                row = (await pg.execute(stmt)).scalar_one_or_none()
                if row:
                    for k, v in set_vals.items():
                        setattr(row, k, v)
                    for k, v in push_ops.items():
                        col = getattr(row, k, None)
                        if isinstance(col, list) or col is None:
                            col = list(col or [])
                            col.append(v)
                            setattr(row, k, col)
                    for k, v in addToSet.items():
                        col = list(getattr(row, k, None) or [])
                        if v not in col:
                            col.append(v)
                            setattr(row, k, col)
                    modified = 1
                elif upsert:
                    cols = {k: v for k, v in set_vals.items() if hasattr(self._model, k)}
                    for k, v in (filt or {}).items():
                        if hasattr(self._model, k) and not isinstance(v, dict):
                            cols.setdefault(k, v)
                    for k, v in setOnInsert.items():
                        if hasattr(self._model, k):
                            cols.setdefault(k, v)
                    if "id" not in cols:
                        import uuid
                        cols["id"] = uuid.uuid4().hex
                    pg.add(self._model(**cols))
                    upserted = 1
        class _R:
            matched_count = modified
            modified_count = modified
            upserted_id = None if not upserted else cols.get("id")
        return _R()

    async def update_many(self, filt: Dict[str, Any],
                           update_ops: Dict[str, Any]):
        set_vals = dict(update_ops.get("$set") or {})
        set_vals = {k: v for k, v in set_vals.items() if hasattr(self._model, k)}
        async with AsyncSessionLocal() as pg:
            async with pg.begin():
                stmt = _apply_filter(update(self._model).values(**set_vals),
                                      self._model, filt or {})
                r = await pg.execute(stmt)
        class _R:
            matched_count = r.rowcount or 0
            modified_count = r.rowcount or 0
        return _R()

    async def delete_one(self, filt: Dict[str, Any]):
        async with AsyncSessionLocal() as pg:
            async with pg.begin():
                stmt = _apply_filter(select(self._model), self._model, filt or {}).limit(1)
                row = (await pg.execute(stmt)).scalar_one_or_none()
                if row:
                    await pg.delete(row)
                    n = 1
                else:
                    n = 0
        class _R:
            deleted_count = n
        return _R()

    async def delete_many(self, filt: Dict[str, Any]):
        async with AsyncSessionLocal() as pg:
            async with pg.begin():
                stmt = _apply_filter(delete(self._model), self._model, filt or {})
                r = await pg.execute(stmt)
        class _R:
            deleted_count = r.rowcount or 0
        return _R()

    async def create_index(self, *_args, **_kwargs):
        # Alembic owns the index topology for these tables.
        return None


class MotorCompatDb:
    """Wraps a Motor database, transparently returning MotorCompatCollection
    for retired collections and delegating everything else to Motor."""

    def __init__(self, motor_db):
        self._motor = motor_db
        self._overrides = {n: MotorCompatCollection(n) for n in _MODEL_BY_NAME}

    def __getattr__(self, name: str):
        if name in self._overrides:
            return self._overrides[name]
        return getattr(self._motor, name)

    def __getitem__(self, name: str):
        if name in self._overrides:
            return self._overrides[name]
        return self._motor[name]
