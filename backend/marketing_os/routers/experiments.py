"""Marketing OS — Phase 9 Conversion Optimization + Experimentation API.

Internal staff workflow. Deterministic A/B assignment, deterministic
conversion reporting, and an advisory (non-publishing) winner recommendation.
No PHI, no SMS, no provider/ad-platform writes, no autonomous publishing.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from deps import api, require_roles
from postgres_db import AsyncSessionLocal
from marketing_os.services.measurement import MarketingDataPolicyError
from marketing_os.services import experiments as ex
from marketing_os.services.experiments import ExperimentConfigError

MARKETING_ROLES = ("admin", "practitioner")

SAFETY_STATE = {
    "external_writes": False,
    "autonomous_publishing": False,
    "automatic_budget_changes": False,
    "automatic_winner_selection": False,
    "human_approval_required": True,
    "ai_advisory_only": True,
    "phi_used": False,
    "sms_enabled": False,
}


def _new_id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid(user: dict) -> Optional[str]:
    v = user.get("id")
    return str(v) if v else None


def _serialize(row) -> dict[str, Any]:
    result = dict(row._mapping)
    for k, v in list(result.items()):
        if isinstance(v, Decimal):
            result[k] = float(v)
        elif isinstance(v, (date, datetime)):
            result[k] = v.isoformat()
    return result


def _cfg_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


async def _one(pg, sql: str, params: dict):
    return (await pg.execute(text(sql), params)).first()


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #

class ExperimentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    slug: str
    experiment_type: str
    primary_metric: Optional[str] = "conversion"
    exposure_metric: Optional[str] = "impression"
    hypothesis: Optional[str] = None
    funnel_id: Optional[str] = None
    config: Optional[dict] = None


class ExperimentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = None
    primary_metric: Optional[str] = None
    exposure_metric: Optional[str] = None
    hypothesis: Optional[str] = None
    funnel_id: Optional[str] = None
    config: Optional[dict] = None


class VariantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variant_key: str
    name: str
    is_control: bool = False
    allocation_pct: int = 0
    offer_id: Optional[str] = None
    funnel_step_id: Optional[str] = None
    config: Optional[dict] = None


class TransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str  # activate | pause | complete | archive


class AssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    marketing_subject_id: str


class OutcomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric_type: str
    marketing_subject_id: Optional[str] = None
    variant_id: Optional[str] = None
    value: Optional[float] = None
    currency: Optional[str] = None
    idempotency_key: Optional[str] = None
    properties: Optional[dict] = None


_ACTION_TO_STATUS = {
    "activate": "active", "pause": "paused",
    "complete": "completed", "archive": "archived",
}


# --------------------------------------------------------------------------- #
# Experiments CRUD
# --------------------------------------------------------------------------- #

@api.get("/marketing-os/experiments")
async def list_experiments(
    status: Optional[str] = Query(None),
    experiment_type: Optional[str] = Query(None),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    del user
    clauses, params = [], {}
    if status:
        clauses.append("status = :status")
        params["status"] = status
    if experiment_type:
        clauses.append("experiment_type = :etype")
        params["etype"] = experiment_type
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    async with AsyncSessionLocal() as pg:
        rows = await pg.execute(
            text(f"SELECT * FROM marketing_experiments {where} "
                 "ORDER BY created_at DESC"),
            params,
        )
        return {"experiments": [_serialize(r) for r in rows],
                "safety": SAFETY_STATE}


@api.post("/marketing-os/experiments", status_code=201)
async def create_experiment(payload: ExperimentCreate,
                            user=Depends(require_roles(*MARKETING_ROLES))):
    try:
        v = ex.validate_experiment_payload(payload.model_dump())
    except (ExperimentConfigError, MarketingDataPolicyError) as exc:
        raise _cfg_error(exc) from exc

    exp_id = _new_id()
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            if await _one(pg, "SELECT id FROM marketing_experiments "
                              "WHERE slug = :s", {"s": v["slug"]}):
                raise HTTPException(status_code=409, detail="slug exists")
            if payload.funnel_id and not await _one(
                pg, "SELECT id FROM marketing_funnels WHERE id = :i",
                {"i": payload.funnel_id},
            ):
                raise HTTPException(status_code=422, detail="unknown funnel_id")
            row = (await pg.execute(
                text("""
                    INSERT INTO marketing_experiments
                      (id, name, slug, experiment_type, status, primary_metric,
                       exposure_metric, hypothesis, funnel_id, config,
                       created_by, created_at, updated_at)
                    VALUES
                      (:id, :name, :slug, :etype, 'draft', :pm, :em, :hyp,
                       :funnel_id, CAST(:config AS jsonb), :cb, now(), now())
                    RETURNING *
                """),
                {"id": exp_id, "name": v["name"], "slug": v["slug"],
                 "etype": v["experiment_type"], "pm": v["primary_metric"],
                 "em": v["exposure_metric"], "hyp": v["hypothesis"],
                 "funnel_id": payload.funnel_id,
                 "config": json.dumps(v["config"]), "cb": _uid(user)},
            )).first()
    return _serialize(row)


@api.get("/marketing-os/experiments/overview")
async def experiments_overview(user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    async with AsyncSessionLocal() as pg:
        by_status = await pg.execute(text(
            "SELECT status, count(*) c FROM marketing_experiments "
            "GROUP BY status"))
        by_type = await pg.execute(text(
            "SELECT experiment_type, count(*) c FROM marketing_experiments "
            "GROUP BY experiment_type"))
        return {
            "by_status": {r._mapping["status"]: int(r._mapping["c"])
                          for r in by_status},
            "by_type": {r._mapping["experiment_type"]: int(r._mapping["c"])
                        for r in by_type},
            "safety": SAFETY_STATE,
        }


@api.get("/marketing-os/experiments/{experiment_id}")
async def get_experiment(experiment_id: str,
                         user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    async with AsyncSessionLocal() as pg:
        exp = await _one(pg, "SELECT * FROM marketing_experiments "
                             "WHERE id = :i", {"i": experiment_id})
        if not exp:
            raise HTTPException(status_code=404, detail="experiment not found")
        variants = await pg.execute(
            text("SELECT * FROM marketing_experiment_variants "
                 "WHERE experiment_id = :i ORDER BY variant_key ASC"),
            {"i": experiment_id})
        result = _serialize(exp)
        result["variants"] = [_serialize(v) for v in variants]
        return result


@api.patch("/marketing-os/experiments/{experiment_id}")
async def patch_experiment(experiment_id: str, payload: ExperimentPatch,
                           user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status_code=400, detail="No changes supplied")
    assigns, params = [], {"i": experiment_id}
    try:
        if "name" in values:
            params["name"] = ex._req_str(values["name"], "name",
                                         max_len=ex.MAX_NAME_LEN)
            assigns.append("name = :name")
        if "primary_metric" in values:
            pm = str(values["primary_metric"]).strip().lower()
            if pm not in ex.PRIMARY_METRICS:
                raise ExperimentConfigError(f"invalid primary_metric: {pm!r}")
            params["pm"] = pm
            assigns.append("primary_metric = :pm")
        if "exposure_metric" in values:
            em = str(values["exposure_metric"]).strip().lower()
            if em not in ex.EXPOSURE_METRICS:
                raise ExperimentConfigError(f"invalid exposure_metric: {em!r}")
            params["em"] = em
            assigns.append("exposure_metric = :em")
        if "hypothesis" in values:
            params["hyp"] = ex._opt_str(values["hypothesis"], "hypothesis",
                                        max_len=ex.MAX_HYPOTHESIS_LEN)
            assigns.append("hypothesis = :hyp")
        if "config" in values:
            params["config"] = json.dumps(
                ex._bounded_json(values["config"], "config"))
            assigns.append("config = CAST(:config AS jsonb)")
    except (ExperimentConfigError, MarketingDataPolicyError) as exc:
        raise _cfg_error(exc) from exc

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            exp = await _one(pg, "SELECT status, funnel_id FROM "
                                 "marketing_experiments WHERE id = :i",
                             {"i": experiment_id})
            if not exp:
                raise HTTPException(status_code=404,
                                    detail="experiment not found")
            if exp._mapping["status"] != "draft":
                raise HTTPException(status_code=409,
                                    detail="only draft experiments editable")
            if "funnel_id" in values:
                if values["funnel_id"] and not await _one(
                    pg, "SELECT id FROM marketing_funnels WHERE id = :i",
                    {"i": values["funnel_id"]},
                ):
                    raise HTTPException(status_code=422,
                                        detail="unknown funnel_id")
                params["funnel_id"] = values["funnel_id"]
                assigns.append("funnel_id = :funnel_id")
            assigns.append("updated_at = now()")
            row = (await pg.execute(
                text(f"UPDATE marketing_experiments SET {', '.join(assigns)} "
                     "WHERE id = :i RETURNING *"), params)).first()
    return _serialize(row)


# --------------------------------------------------------------------------- #
# Variants
# --------------------------------------------------------------------------- #

@api.post("/marketing-os/experiments/{experiment_id}/variants",
          status_code=201)
async def add_variant(experiment_id: str, payload: VariantCreate,
                      user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    try:
        v = ex.validate_variant_payload(payload.model_dump())
    except (ExperimentConfigError, MarketingDataPolicyError) as exc:
        raise _cfg_error(exc) from exc

    vid = _new_id()
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            exp = await _one(pg, "SELECT status, experiment_type FROM "
                                 "marketing_experiments WHERE id = :i",
                             {"i": experiment_id})
            if not exp:
                raise HTTPException(status_code=404,
                                    detail="experiment not found")
            if exp._mapping["status"] != "draft":
                raise HTTPException(status_code=409,
                                    detail="add variants while draft only")
            if await _one(pg, "SELECT id FROM marketing_experiment_variants "
                              "WHERE experiment_id = :e AND variant_key = :k",
                          {"e": experiment_id, "k": v["variant_key"]}):
                raise HTTPException(status_code=409,
                                    detail="variant_key exists")
            if v["offer_id"] and not await _one(
                pg, "SELECT id FROM marketing_offers WHERE id = :i",
                {"i": v["offer_id"]},
            ):
                raise HTTPException(status_code=422, detail="unknown offer_id")
            if v["funnel_step_id"] and not await _one(
                pg, "SELECT id FROM marketing_funnel_steps WHERE id = :i",
                {"i": v["funnel_step_id"]},
            ):
                raise HTTPException(status_code=422,
                                    detail="unknown funnel_step_id")
            row = (await pg.execute(
                text("""
                    INSERT INTO marketing_experiment_variants
                      (id, experiment_id, variant_key, name, is_control,
                       allocation_pct, offer_id, funnel_step_id, config,
                       created_at, updated_at)
                    VALUES
                      (:id, :e, :k, :name, :ctrl, :alloc, :offer, :step,
                       CAST(:config AS jsonb), now(), now())
                    RETURNING *
                """),
                {"id": vid, "e": experiment_id, "k": v["variant_key"],
                 "name": v["name"], "ctrl": v["is_control"],
                 "alloc": v["allocation_pct"], "offer": v["offer_id"],
                 "step": v["funnel_step_id"],
                 "config": json.dumps(v["config"])},
            )).first()
    return _serialize(row)


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #

@api.post("/marketing-os/experiments/{experiment_id}/transition")
async def transition_experiment(experiment_id: str, payload: TransitionRequest,
                                user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    action = (payload.action or "").strip().lower()
    if action not in _ACTION_TO_STATUS:
        raise HTTPException(status_code=400, detail="invalid action")
    target = _ACTION_TO_STATUS[action]

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            exp = await _one(pg, "SELECT * FROM marketing_experiments "
                                 "WHERE id = :i", {"i": experiment_id})
            if not exp:
                raise HTTPException(status_code=404,
                                    detail="experiment not found")
            current = exp._mapping["status"]
            try:
                ex.assert_can_transition(current, target)
            except ExperimentConfigError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

            if target == "active":
                variants = [
                    _serialize(r) for r in await pg.execute(
                        text("SELECT * FROM marketing_experiment_variants "
                             "WHERE experiment_id = :i"),
                        {"i": experiment_id})
                ]
                try:
                    ex.validate_activation(variants)
                except ExperimentConfigError as exc:
                    raise HTTPException(status_code=409,
                                        detail=str(exc)) from exc

            ts_col = {"active": "started_at", "paused": "paused_at",
                      "completed": "completed_at",
                      "archived": "archived_at"}[target]
            row = (await pg.execute(
                text(f"UPDATE marketing_experiments SET status = :s, "
                     f"{ts_col} = now(), updated_at = now() "
                     "WHERE id = :i RETURNING *"),
                {"s": target, "i": experiment_id})).first()
    return _serialize(row)


# --------------------------------------------------------------------------- #
# Deterministic assignment
# --------------------------------------------------------------------------- #

@api.post("/marketing-os/experiments/{experiment_id}/assign")
async def assign(experiment_id: str, payload: AssignRequest,
                 user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    subject = (payload.marketing_subject_id or "").strip()
    if not subject:
        raise HTTPException(status_code=422,
                            detail="marketing_subject_id required")
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            exp = await _one(pg, "SELECT status FROM marketing_experiments "
                                 "WHERE id = :i", {"i": experiment_id})
            if not exp:
                raise HTTPException(status_code=404,
                                    detail="experiment not found")
            if exp._mapping["status"] != "active":
                raise HTTPException(status_code=409,
                                    detail="experiment is not active")
            existing = await _one(
                pg, "SELECT * FROM marketing_experiment_assignments "
                    "WHERE experiment_id = :e AND marketing_subject_id = :s",
                {"e": experiment_id, "s": subject})
            if existing:
                out = _serialize(existing)
                out["reused"] = True
                return out
            variants = [
                _serialize(r) for r in await pg.execute(
                    text("SELECT * FROM marketing_experiment_variants "
                         "WHERE experiment_id = :i"), {"i": experiment_id})
            ]
            chosen = ex.assign_variant(experiment_id, subject, variants)
            if not chosen:
                raise HTTPException(status_code=409,
                                    detail="experiment has no variants")
            row = (await pg.execute(
                text("""
                    INSERT INTO marketing_experiment_assignments
                      (id, experiment_id, variant_id, marketing_subject_id,
                       assigned_at, created_at, updated_at)
                    VALUES (:id, :e, :v, :s, now(), now(), now())
                    ON CONFLICT (experiment_id, marketing_subject_id)
                    DO NOTHING
                    RETURNING *
                """),
                {"id": _new_id(), "e": experiment_id, "v": chosen["id"],
                 "s": subject})).first()
            if row is None:  # race: fetch the committed one
                row = await _one(
                    pg, "SELECT * FROM marketing_experiment_assignments "
                        "WHERE experiment_id = :e AND "
                        "marketing_subject_id = :s",
                    {"e": experiment_id, "s": subject})
            out = _serialize(row)
            out["reused"] = False
            return out


# --------------------------------------------------------------------------- #
# Outcomes (marketing-safe metrics) + Phase 5 conversion reuse
# --------------------------------------------------------------------------- #

@api.post("/marketing-os/experiments/{experiment_id}/outcomes",
          status_code=201)
async def record_outcome(experiment_id: str, payload: OutcomeRequest,
                         user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    metric = (payload.metric_type or "").strip().lower()
    if metric not in ex.METRIC_TYPES:
        raise HTTPException(status_code=422,
                            detail=f"invalid metric_type: {metric}")
    props = payload.properties or {}
    try:
        ex._bounded_json(props, "properties")
    except (ExperimentConfigError, MarketingDataPolicyError) as exc:
        raise _cfg_error(exc) from exc
    currency = payload.currency
    if currency is not None and len(str(currency)) != 3:
        raise HTTPException(status_code=422, detail="currency must be 3 chars")

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            exp = await _one(pg, "SELECT id FROM marketing_experiments "
                                 "WHERE id = :i", {"i": experiment_id})
            if not exp:
                raise HTTPException(status_code=404,
                                    detail="experiment not found")
            variant_id = payload.variant_id
            assignment_id = None
            subject = (payload.marketing_subject_id or "").strip() or None

            if variant_id:
                vrow = await _one(
                    pg, "SELECT id FROM marketing_experiment_variants "
                        "WHERE id = :v AND experiment_id = :e",
                    {"v": variant_id, "e": experiment_id})
                if not vrow:
                    raise HTTPException(status_code=422,
                                        detail="unknown variant_id")
            if subject:
                arow = await _one(
                    pg, "SELECT id, variant_id FROM "
                        "marketing_experiment_assignments "
                        "WHERE experiment_id = :e AND "
                        "marketing_subject_id = :s",
                    {"e": experiment_id, "s": subject})
                if arow:
                    assignment_id = arow._mapping["id"]
                    variant_id = variant_id or arow._mapping["variant_id"]
            if not variant_id:
                raise HTTPException(
                    status_code=422,
                    detail="provide variant_id or an assigned "
                           "marketing_subject_id")

            row = (await pg.execute(
                text("""
                    INSERT INTO marketing_experiment_outcomes
                      (id, experiment_id, variant_id, assignment_id,
                       marketing_subject_id, metric_type, value, currency,
                       occurred_at, idempotency_key, properties,
                       created_at, updated_at)
                    VALUES
                      (:id, :e, :v, :a, :s, :m, :val, :cur, now(), :idem,
                       CAST(:props AS jsonb), now(), now())
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING *
                """),
                {"id": _new_id(), "e": experiment_id, "v": variant_id,
                 "a": assignment_id, "s": subject, "m": metric,
                 "val": payload.value, "cur": currency,
                 "idem": payload.idempotency_key,
                 "props": json.dumps(props)})).first()
            if row is None:
                return {"status": "duplicate_ignored"}
    return _serialize(row)


@api.post("/marketing-os/experiments/{experiment_id}/ingest-conversions")
async def ingest_conversions(experiment_id: str,
                             user=Depends(require_roles(*MARKETING_ROLES))):
    """Reuse Phase 5 conversion events for assigned subjects (idempotent)."""
    del user
    created = 0
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            exp = await _one(pg, "SELECT id, started_at FROM "
                                 "marketing_experiments WHERE id = :i",
                             {"i": experiment_id})
            if not exp:
                raise HTTPException(status_code=404,
                                    detail="experiment not found")
            started_at = exp._mapping["started_at"]
            rows = await pg.execute(
                text("""
                    SELECT a.id AS assignment_id, a.variant_id,
                           a.marketing_subject_id, c.id AS event_id,
                           c.event_type, c.value, c.currency
                    FROM marketing_experiment_assignments a
                    JOIN marketing_conversion_events c
                      ON c.marketing_subject_id = a.marketing_subject_id
                    WHERE a.experiment_id = :e
                      AND (:since::timestamptz IS NULL
                           OR c.occurred_at >= :since)
                """),
                {"e": experiment_id, "since": started_at})
            for r in rows:
                m = r._mapping
                metric = str(m["event_type"]).strip().lower()
                if metric not in ex.METRIC_TYPES:
                    continue
                idem = f"{experiment_id}:{m['event_id']}"
                res = (await pg.execute(
                    text("""
                        INSERT INTO marketing_experiment_outcomes
                          (id, experiment_id, variant_id, assignment_id,
                           marketing_subject_id, metric_type, value, currency,
                           occurred_at, source_event_id, idempotency_key,
                           properties, created_at, updated_at)
                        VALUES
                          (:id, :e, :v, :a, :s, :m, :val, :cur, now(),
                           :src, :idem, '{}'::jsonb, now(), now())
                        ON CONFLICT (idempotency_key) DO NOTHING
                        RETURNING id
                    """),
                    {"id": _new_id(), "e": experiment_id,
                     "v": m["variant_id"], "a": m["assignment_id"],
                     "s": m["marketing_subject_id"], "m": metric,
                     "val": m["value"], "cur": m["currency"],
                     "src": m["event_id"], "idem": idem})).first()
                if res is not None:
                    created += 1
    return {"outcomes_created": created, "safety": SAFETY_STATE}


# --------------------------------------------------------------------------- #
# Deterministic report
# --------------------------------------------------------------------------- #

@api.get("/marketing-os/experiments/{experiment_id}/report")
async def experiment_report(experiment_id: str,
                            user=Depends(require_roles(*MARKETING_ROLES))):
    del user
    async with AsyncSessionLocal() as pg:
        exp = await _one(pg, "SELECT * FROM marketing_experiments "
                             "WHERE id = :i", {"i": experiment_id})
        if not exp:
            raise HTTPException(status_code=404, detail="experiment not found")
        experiment = _serialize(exp)
        variants = [
            _serialize(r) for r in await pg.execute(
                text("SELECT * FROM marketing_experiment_variants "
                     "WHERE experiment_id = :i"), {"i": experiment_id})
        ]
        assign_rows = await pg.execute(
            text("SELECT variant_id, count(*) c FROM "
                 "marketing_experiment_assignments WHERE experiment_id = :i "
                 "GROUP BY variant_id"), {"i": experiment_id})
        assign_counts = {r._mapping["variant_id"]: int(r._mapping["c"])
                         for r in assign_rows}
        metric_rows = await pg.execute(
            text("SELECT variant_id, metric_type, count(*) cnt, "
                 "COALESCE(sum(value),0) s FROM marketing_experiment_outcomes "
                 "WHERE experiment_id = :i GROUP BY variant_id, metric_type"),
            {"i": experiment_id})
        grouped: dict[str, list] = {}
        for r in metric_rows:
            m = r._mapping
            grouped.setdefault(m["variant_id"], []).append(
                {"metric_type": m["metric_type"], "cnt": m["cnt"], "sum": m["s"]}
            )
        per_variant = {
            v["id"]: ex.aggregate_variant(
                grouped.get(v["id"], []), assign_counts.get(v["id"], 0))
            for v in variants
        }
        report = ex.build_report(experiment, variants, per_variant)
        report["safety"] = SAFETY_STATE
        return report
