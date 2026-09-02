"""Marketing OS Phase 7 — Funnel / Qualification / Offer API.

Internal Marketing OS configuration plus privacy-safe qualification intake.

Safety:
- no clinical tables;
- no patient/client foreign keys;
- opaque marketing_subject_id only;
- no provider advertising writes;
- no automatic outreach;
- qualification and offer matching are deterministic.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from deps import api, require_roles
from postgres_db import AsyncSessionLocal
from marketing_os.services.funnel_qualification import (
    QualificationRuleError,
    evaluate_qualification,
)
from marketing_os.services.measurement import MarketingDataPolicyError


MARKETING_ROLES = ("admin", "practitioner")

OFFER_STATUSES = ("draft", "active", "inactive", "archived")
FORM_STATUSES = ("draft", "active", "inactive", "archived")
FUNNEL_STATUSES = ("draft", "active", "inactive", "archived")
STEP_TYPES = (
    "landing",
    "qualification",
    "offer",
    "appointment",
    "thank_you",
)


def _new_id() -> str:
    return uuid.uuid4().hex


def _uid(user: dict) -> Optional[str]:
    value = user.get("id")
    return str(value) if value else None


def _serialize(row) -> dict[str, Any]:
    result = dict(row._mapping)

    for key, value in list(result.items()):
        if isinstance(value, Decimal):
            result[key] = float(value)
        elif isinstance(value, (date, datetime)):
            result[key] = value.isoformat()

    return result


def _validate_status(value: str, allowed: tuple[str, ...], label: str) -> str:
    normalized = (value or "").strip().lower()

    if normalized not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"invalid {label}: {normalized!r}",
        )

    return normalized


async def _fetch_one(pg, query: str, params: dict[str, Any]):
    result = await pg.execute(text(query), params)
    return result.first()


MARKETING_SAFE_QUALIFICATION_FIELDS = frozenset({
    "service_interest",
    "urgency",
    "preferred_location",
    "preferred_contact_window",
    "appointment_readiness",
    "timeline",
    "contact_consent",
})

SUPPORTED_SCORING_OPERATORS = frozenset({
    "equals",
    "in",
    "truthy",
})

QUALIFICATION_SCHEMA_KEYS = frozenset({
    "fields",
})

QUALIFICATION_CONFIG_KEYS = frozenset({
    "qualify_at",
    "review_at",
})


def _configuration_error(message: str):
    raise HTTPException(
        status_code=422,
        detail=message,
    )


def _validate_score_number(
    value: Any,
    label: str,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > 100
    ):
        _configuration_error(
            f"{label} must be an integer between 0 and 100"
        )

    return value


def _validate_qualification_schema(
    schema: dict[str, Any],
) -> set[str]:
    if not isinstance(schema, dict):
        _configuration_error(
            "qualification schema must be an object"
        )

    unknown_keys = (
        set(schema)
        - QUALIFICATION_SCHEMA_KEYS
    )

    if unknown_keys:
        _configuration_error(
            "unsupported qualification schema keys: "
            + ", ".join(sorted(unknown_keys))
        )

    fields = schema.get("fields", [])

    if not isinstance(fields, list):
        _configuration_error(
            "qualification schema fields must be a list"
        )

    if len(fields) != len(set(fields)):
        _configuration_error(
            "qualification schema fields must be unique"
        )

    for field in fields:
        if (
            not isinstance(field, str)
            or field
            not in MARKETING_SAFE_QUALIFICATION_FIELDS
        ):
            _configuration_error(
                f"unsupported qualification field: {field!r}"
            )

    return set(fields)


def _validate_scoring_rules(
    scoring_rules: list[dict[str, Any]],
    *,
    schema_fields: set[str] | None = None,
) -> None:
    if not isinstance(scoring_rules, list):
        _configuration_error(
            "scoring_rules must be a list"
        )

    for index, rule in enumerate(scoring_rules):
        label = f"scoring rule {index + 1}"

        if not isinstance(rule, dict):
            _configuration_error(
                f"{label} must be an object"
            )

        allowed_keys = {
            "field",
            "operator",
            "points",
            "value",
            "values",
        }

        unknown_keys = set(rule) - allowed_keys

        if unknown_keys:
            _configuration_error(
                f"{label} contains unsupported keys: "
                + ", ".join(sorted(unknown_keys))
            )

        field = rule.get("field")

        if (
            not isinstance(field, str)
            or field
            not in MARKETING_SAFE_QUALIFICATION_FIELDS
        ):
            _configuration_error(
                f"{label} uses unsupported field: {field!r}"
            )

        if (
            schema_fields is not None
            and field not in schema_fields
        ):
            _configuration_error(
                f"{label} field {field!r} is not present "
                "in qualification schema"
            )

        operator = rule.get("operator")

        if operator not in SUPPORTED_SCORING_OPERATORS:
            _configuration_error(
                f"{label} uses unsupported operator: "
                f"{operator!r}"
            )

        _validate_score_number(
            rule.get("points"),
            f"{label} points",
        )

        if operator == "equals":
            if "value" not in rule:
                _configuration_error(
                    f"{label} equals operator requires value"
                )

            if "values" in rule:
                _configuration_error(
                    f"{label} equals operator does not accept values"
                )

        elif operator == "in":
            values = rule.get("values")

            if (
                not isinstance(values, list)
                or len(values) == 0
            ):
                _configuration_error(
                    f"{label} in operator requires "
                    "a non-empty values list"
                )

            if "value" in rule:
                _configuration_error(
                    f"{label} in operator uses values, not value"
                )

        elif operator == "truthy":
            if "value" in rule or "values" in rule:
                _configuration_error(
                    f"{label} truthy operator does not "
                    "accept value or values"
                )


def _validate_qualification_config(
    config: dict[str, Any],
) -> None:
    if not isinstance(config, dict):
        _configuration_error(
            "qualification_config must be an object"
        )

    unknown_keys = (
        set(config)
        - QUALIFICATION_CONFIG_KEYS
    )

    if unknown_keys:
        _configuration_error(
            "unsupported qualification_config keys: "
            + ", ".join(sorted(unknown_keys))
        )

    qualify_at = config.get(
        "qualify_at",
        70,
    )

    review_at = config.get(
        "review_at",
        40,
    )

    qualify_at = _validate_score_number(
        qualify_at,
        "qualify_at",
    )

    review_at = _validate_score_number(
        review_at,
        "review_at",
    )

    if qualify_at < review_at:
        _configuration_error(
            "qualify_at must be greater than or equal "
            "to review_at"
        )


def _validate_qualification_configuration(
    schema: dict[str, Any],
    scoring_rules: list[dict[str, Any]],
    qualification_config: dict[str, Any],
) -> None:
    fields = _validate_qualification_schema(
        schema
    )

    _validate_scoring_rules(
        scoring_rules,
        schema_fields=fields,
    )

    _validate_qualification_config(
        qualification_config
    )


def _validate_offer_match_config(
    match_config: dict[str, Any],
) -> None:
    if not isinstance(match_config, dict):
        _configuration_error(
            "match_config must be an object"
        )

    # Phase 7 offer matching is driven by the typed top-level
    # service_interest, min_qualification_score, and
    # eligible_locations fields. No additional match_config
    # semantics are implemented yet, so fail closed rather
    # than persist configuration the engine does not execute.
    if match_config:
        _configuration_error(
            "match_config does not accept custom keys in Phase 7"
        )


class OfferCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=160)
    status: str = "draft"
    service_interest: Optional[str] = Field(default=None, max_length=160)
    description: Optional[str] = None
    min_qualification_score: int = Field(default=0, ge=0, le=100)
    eligible_locations: list[str] = Field(default_factory=list)
    match_config: dict[str, Any] = Field(default_factory=dict)


class OfferPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    status: Optional[str] = None
    service_interest: Optional[str] = Field(default=None, max_length=160)
    description: Optional[str] = None
    min_qualification_score: Optional[int] = Field(
        default=None,
        ge=0,
        le=100,
    )
    eligible_locations: Optional[list[str]] = None
    match_config: Optional[dict[str, Any]] = None


class QualificationFormCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=160)
    status: str = "draft"
    schema: dict[str, Any] = Field(default_factory=dict)
    scoring_rules: list[dict[str, Any]] = Field(default_factory=list)
    qualification_config: dict[str, Any] = Field(default_factory=dict)


class QualificationFormPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    status: Optional[str] = None
    schema: Optional[dict[str, Any]] = None
    scoring_rules: Optional[list[dict[str, Any]]] = None
    qualification_config: Optional[dict[str, Any]] = None


class FunnelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=160)
    status: str = "draft"
    landing_page: Optional[str] = Field(default=None, max_length=512)
    qualification_form_id: Optional[str] = None
    default_offer_id: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)


class FunnelPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    status: Optional[str] = None
    landing_page: Optional[str] = Field(default=None, max_length=512)
    qualification_form_id: Optional[str] = None
    default_offer_id: Optional[str] = None
    config: Optional[dict[str, Any]] = None


class FunnelStepCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_key: str = Field(min_length=1, max_length=96)
    step_type: str
    position: int = Field(ge=0)
    title: Optional[str] = Field(default=None, max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)


class QualificationSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marketing_subject_id: str = Field(min_length=1, max_length=128)
    answers: dict[str, Any]


@api.get("/marketing-os/offers")
async def list_offers(
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    del user

    async with AsyncSessionLocal() as pg:
        rows = await pg.execute(
            text("""
                SELECT *
                FROM marketing_offers
                ORDER BY created_at DESC, id
            """)
        )

        return [_serialize(row) for row in rows]


@api.post("/marketing-os/offers", status_code=201)
async def create_offer(
    payload: OfferCreate,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    status = _validate_status(payload.status, OFFER_STATUSES, "offer status")
    _validate_offer_match_config(
        payload.match_config
    )
    offer_id = _new_id()

    async with AsyncSessionLocal() as pg:
        existing = await _fetch_one(
            pg,
            "SELECT id FROM marketing_offers WHERE slug = :slug",
            {"slug": payload.slug},
        )

        if existing:
            raise HTTPException(status_code=409, detail="offer slug exists")

        await pg.execute(
            text("""
                INSERT INTO marketing_offers (
                    id,
                    name,
                    slug,
                    status,
                    service_interest,
                    description,
                    min_qualification_score,
                    eligible_locations,
                    match_config,
                    created_by,
                    created_at,
                    updated_at
                )
                VALUES (
                    :id,
                    :name,
                    :slug,
                    :status,
                    :service_interest,
                    :description,
                    :min_score,
                    CAST(:locations AS jsonb),
                    CAST(:match_config AS jsonb),
                    :created_by,
                    now(),
                    now()
                )
            """),
            {
                "id": offer_id,
                "name": payload.name.strip(),
                "slug": payload.slug.strip(),
                "status": status,
                "service_interest": (
                    payload.service_interest.strip()
                    if payload.service_interest
                    else None
                ),
                "description": payload.description,
                "min_score": payload.min_qualification_score,
                "locations": json.dumps(payload.eligible_locations),
                "match_config": json.dumps(payload.match_config),
                "created_by": _uid(user),
            },
        )

        await pg.commit()

        row = await _fetch_one(
            pg,
            "SELECT * FROM marketing_offers WHERE id = :id",
            {"id": offer_id},
        )

    return _serialize(row)


@api.patch("/marketing-os/offers/{offer_id}")
async def patch_offer(
    offer_id: str,
    payload: OfferPatch,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    del user

    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(status_code=422, detail="no changes supplied")

    if "status" in updates:
        updates["status"] = _validate_status(
            updates["status"],
            OFFER_STATUSES,
            "offer status",
        )

    if "match_config" in updates:
        _validate_offer_match_config(
            updates["match_config"]
        )

    columns = []
    params: dict[str, Any] = {"offer_id": offer_id}

    for field, value in updates.items():
        if field in {"eligible_locations", "match_config"}:
            columns.append(f"{field} = CAST(:{field} AS jsonb)")
            params[field] = json.dumps(value)
        else:
            columns.append(f"{field} = :{field}")
            params[field] = value

    columns.append("updated_at = now()")

    async with AsyncSessionLocal() as pg:
        existing = await _fetch_one(
            pg,
            "SELECT id FROM marketing_offers WHERE id = :id",
            {"id": offer_id},
        )

        if not existing:
            raise HTTPException(status_code=404, detail="offer not found")

        await pg.execute(
            text(f"""
                UPDATE marketing_offers
                SET {", ".join(columns)}
                WHERE id = :offer_id
            """),
            params,
        )

        await pg.commit()

        row = await _fetch_one(
            pg,
            "SELECT * FROM marketing_offers WHERE id = :id",
            {"id": offer_id},
        )

    return _serialize(row)


@api.get("/marketing-os/qualification-forms")
async def list_qualification_forms(
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    del user

    async with AsyncSessionLocal() as pg:
        rows = await pg.execute(
            text("""
                SELECT *
                FROM marketing_qualification_forms
                ORDER BY created_at DESC, id
            """)
        )

        return [_serialize(row) for row in rows]


@api.post("/marketing-os/qualification-forms", status_code=201)
async def create_qualification_form(
    payload: QualificationFormCreate,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    status = _validate_status(payload.status, FORM_STATUSES, "form status")
    form_id = _new_id()

    _validate_qualification_configuration(
        payload.schema,
        payload.scoring_rules,
        payload.qualification_config,
    )

    async with AsyncSessionLocal() as pg:
        existing = await _fetch_one(
            pg,
            """
            SELECT id
            FROM marketing_qualification_forms
            WHERE slug = :slug
            """,
            {"slug": payload.slug},
        )

        if existing:
            raise HTTPException(status_code=409, detail="form slug exists")

        await pg.execute(
            text("""
                INSERT INTO marketing_qualification_forms (
                    id,
                    name,
                    slug,
                    status,
                    schema,
                    scoring_rules,
                    qualification_config,
                    created_by,
                    created_at,
                    updated_at
                )
                VALUES (
                    :id,
                    :name,
                    :slug,
                    :status,
                    CAST(:schema AS jsonb),
                    CAST(:scoring_rules AS jsonb),
                    CAST(:qualification_config AS jsonb),
                    :created_by,
                    now(),
                    now()
                )
            """),
            {
                "id": form_id,
                "name": payload.name.strip(),
                "slug": payload.slug.strip(),
                "status": status,
                "schema": json.dumps(payload.schema),
                "scoring_rules": json.dumps(payload.scoring_rules),
                "qualification_config": json.dumps(
                    payload.qualification_config
                ),
                "created_by": _uid(user),
            },
        )

        await pg.commit()

        row = await _fetch_one(
            pg,
            """
            SELECT *
            FROM marketing_qualification_forms
            WHERE id = :id
            """,
            {"id": form_id},
        )

    return _serialize(row)


@api.patch("/marketing-os/qualification-forms/{form_id}")
async def patch_qualification_form(
    form_id: str,
    payload: QualificationFormPatch,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    del user

    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(status_code=422, detail="no changes supplied")

    if "status" in updates:
        updates["status"] = _validate_status(
            updates["status"],
            FORM_STATUSES,
            "form status",
        )

    columns = []
    params: dict[str, Any] = {"form_id": form_id}

    for field, value in updates.items():
        if field in {
            "schema",
            "scoring_rules",
            "qualification_config",
        }:
            columns.append(f"{field} = CAST(:{field} AS jsonb)")
            params[field] = json.dumps(value)
        else:
            columns.append(f"{field} = :{field}")
            params[field] = value

    columns.append("updated_at = now()")

    async with AsyncSessionLocal() as pg:
        existing = await _fetch_one(
            pg,
            """
            SELECT
                id,
                schema,
                scoring_rules,
                qualification_config
            FROM marketing_qualification_forms
            WHERE id = :id
            """,
            {"id": form_id},
        )

        if not existing:
            raise HTTPException(
                status_code=404,
                detail="qualification form not found",
            )

        current = existing._mapping

        merged_schema = updates.get(
            "schema",
            current["schema"] or {},
        )

        merged_scoring_rules = updates.get(
            "scoring_rules",
            current["scoring_rules"] or [],
        )

        merged_qualification_config = updates.get(
            "qualification_config",
            current["qualification_config"] or {},
        )

        _validate_qualification_configuration(
            merged_schema,
            merged_scoring_rules,
            merged_qualification_config,
        )

        await pg.execute(
            text(f"""
                UPDATE marketing_qualification_forms
                SET {", ".join(columns)}
                WHERE id = :form_id
            """),
            params,
        )

        await pg.commit()

        row = await _fetch_one(
            pg,
            """
            SELECT *
            FROM marketing_qualification_forms
            WHERE id = :id
            """,
            {"id": form_id},
        )

    return _serialize(row)


@api.get("/marketing-os/funnels")
async def list_funnels(
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    del user

    async with AsyncSessionLocal() as pg:
        rows = await pg.execute(
            text("""
                SELECT *
                FROM marketing_funnels
                ORDER BY created_at DESC, id
            """)
        )

        result = []

        for row in rows:
            item = _serialize(row)

            steps = await pg.execute(
                text("""
                    SELECT *
                    FROM marketing_funnel_steps
                    WHERE funnel_id = :funnel_id
                    ORDER BY position, id
                """),
                {"funnel_id": item["id"]},
            )

            item["steps"] = [_serialize(step) for step in steps]
            result.append(item)

    return result


@api.post("/marketing-os/funnels", status_code=201)
async def create_funnel(
    payload: FunnelCreate,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    status = _validate_status(payload.status, FUNNEL_STATUSES, "funnel status")
    funnel_id = _new_id()

    async with AsyncSessionLocal() as pg:
        existing = await _fetch_one(
            pg,
            "SELECT id FROM marketing_funnels WHERE slug = :slug",
            {"slug": payload.slug},
        )

        if existing:
            raise HTTPException(status_code=409, detail="funnel slug exists")

        if payload.qualification_form_id:
            form = await _fetch_one(
                pg,
                """
                SELECT id
                FROM marketing_qualification_forms
                WHERE id = :id
                """,
                {"id": payload.qualification_form_id},
            )

            if not form:
                raise HTTPException(
                    status_code=422,
                    detail="qualification form not found",
                )

        if payload.default_offer_id:
            offer = await _fetch_one(
                pg,
                "SELECT id FROM marketing_offers WHERE id = :id",
                {"id": payload.default_offer_id},
            )

            if not offer:
                raise HTTPException(
                    status_code=422,
                    detail="default offer not found",
                )

        await pg.execute(
            text("""
                INSERT INTO marketing_funnels (
                    id,
                    name,
                    slug,
                    status,
                    landing_page,
                    qualification_form_id,
                    default_offer_id,
                    config,
                    created_by,
                    created_at,
                    updated_at
                )
                VALUES (
                    :id,
                    :name,
                    :slug,
                    :status,
                    :landing_page,
                    :qualification_form_id,
                    :default_offer_id,
                    CAST(:config AS jsonb),
                    :created_by,
                    now(),
                    now()
                )
            """),
            {
                "id": funnel_id,
                "name": payload.name.strip(),
                "slug": payload.slug.strip(),
                "status": status,
                "landing_page": payload.landing_page,
                "qualification_form_id": payload.qualification_form_id,
                "default_offer_id": payload.default_offer_id,
                "config": json.dumps(payload.config),
                "created_by": _uid(user),
            },
        )

        await pg.commit()

        row = await _fetch_one(
            pg,
            "SELECT * FROM marketing_funnels WHERE id = :id",
            {"id": funnel_id},
        )

    return _serialize(row)


@api.patch("/marketing-os/funnels/{funnel_id}")
async def patch_funnel(
    funnel_id: str,
    payload: FunnelPatch,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    del user

    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(status_code=422, detail="no changes supplied")

    if "status" in updates:
        updates["status"] = _validate_status(
            updates["status"],
            FUNNEL_STATUSES,
            "funnel status",
        )

    async with AsyncSessionLocal() as pg:
        existing = await _fetch_one(
            pg,
            "SELECT id FROM marketing_funnels WHERE id = :id",
            {"id": funnel_id},
        )

        if not existing:
            raise HTTPException(status_code=404, detail="funnel not found")

        if updates.get("qualification_form_id"):
            form = await _fetch_one(
                pg,
                """
                SELECT id
                FROM marketing_qualification_forms
                WHERE id = :id
                """,
                {"id": updates["qualification_form_id"]},
            )

            if not form:
                raise HTTPException(
                    status_code=422,
                    detail="qualification form not found",
                )

        if updates.get("default_offer_id"):
            offer = await _fetch_one(
                pg,
                "SELECT id FROM marketing_offers WHERE id = :id",
                {"id": updates["default_offer_id"]},
            )

            if not offer:
                raise HTTPException(
                    status_code=422,
                    detail="default offer not found",
                )

        columns = []
        params: dict[str, Any] = {"funnel_id": funnel_id}

        for field, value in updates.items():
            if field == "config":
                columns.append("config = CAST(:config AS jsonb)")
                params["config"] = json.dumps(value)
            else:
                columns.append(f"{field} = :{field}")
                params[field] = value

        columns.append("updated_at = now()")

        await pg.execute(
            text(f"""
                UPDATE marketing_funnels
                SET {", ".join(columns)}
                WHERE id = :funnel_id
            """),
            params,
        )

        await pg.commit()

        row = await _fetch_one(
            pg,
            "SELECT * FROM marketing_funnels WHERE id = :id",
            {"id": funnel_id},
        )

    return _serialize(row)


@api.post(
    "/marketing-os/funnels/{funnel_id}/steps",
    status_code=201,
)
async def create_funnel_step(
    funnel_id: str,
    payload: FunnelStepCreate,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    del user

    step_type = (payload.step_type or "").strip().lower()

    if step_type not in STEP_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"invalid funnel step type: {step_type!r}",
        )

    step_id = _new_id()

    async with AsyncSessionLocal() as pg:
        funnel = await _fetch_one(
            pg,
            "SELECT id FROM marketing_funnels WHERE id = :id",
            {"id": funnel_id},
        )

        if not funnel:
            raise HTTPException(status_code=404, detail="funnel not found")

        duplicate = await _fetch_one(
            pg,
            """
            SELECT id
            FROM marketing_funnel_steps
            WHERE funnel_id = :funnel_id
              AND step_key = :step_key
            """,
            {
                "funnel_id": funnel_id,
                "step_key": payload.step_key,
            },
        )

        if duplicate:
            raise HTTPException(
                status_code=409,
                detail="funnel step key exists",
            )

        await pg.execute(
            text("""
                INSERT INTO marketing_funnel_steps (
                    id,
                    funnel_id,
                    step_key,
                    step_type,
                    position,
                    title,
                    config,
                    created_at,
                    updated_at
                )
                VALUES (
                    :id,
                    :funnel_id,
                    :step_key,
                    :step_type,
                    :position,
                    :title,
                    CAST(:config AS jsonb),
                    now(),
                    now()
                )
            """),
            {
                "id": step_id,
                "funnel_id": funnel_id,
                "step_key": payload.step_key.strip(),
                "step_type": step_type,
                "position": payload.position,
                "title": payload.title,
                "config": json.dumps(payload.config),
            },
        )

        await pg.commit()

        row = await _fetch_one(
            pg,
            "SELECT * FROM marketing_funnel_steps WHERE id = :id",
            {"id": step_id},
        )

    return _serialize(row)


@api.post(
    "/marketing-os/funnels/{funnel_id}/qualify",
    status_code=201,
)
async def submit_qualification(
    funnel_id: str,
    payload: QualificationSubmit,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    actor_id = _uid(user)

    async with AsyncSessionLocal() as pg:
        funnel_row = await _fetch_one(
            pg,
            """
            SELECT *
            FROM marketing_funnels
            WHERE id = :id
            """,
            {"id": funnel_id},
        )

        if not funnel_row:
            raise HTTPException(status_code=404, detail="funnel not found")

        funnel = _serialize(funnel_row)

        if funnel["status"] != "active":
            raise HTTPException(
                status_code=409,
                detail="funnel is not active",
            )

        form_id = funnel.get("qualification_form_id")

        if not form_id:
            raise HTTPException(
                status_code=409,
                detail="funnel has no qualification form",
            )

        form_row = await _fetch_one(
            pg,
            """
            SELECT *
            FROM marketing_qualification_forms
            WHERE id = :id
            """,
            {"id": form_id},
        )

        if not form_row:
            raise HTTPException(
                status_code=409,
                detail="qualification form missing",
            )

        form = _serialize(form_row)

        if form["status"] != "active":
            raise HTTPException(
                status_code=409,
                detail="qualification form is not active",
            )

        offer_rows = await pg.execute(
            text("""
                SELECT *
                FROM marketing_offers
                WHERE status = 'active'
                ORDER BY id
            """)
        )

        offers = [_serialize(row) for row in offer_rows]

        config = form.get("qualification_config") or {}
        qualify_at = int(config.get("qualify_at", 70))
        review_at = int(config.get("review_at", 40))

        try:
            evaluation = evaluate_qualification(
                answers=payload.answers,
                scoring_rules=form.get("scoring_rules") or [],
                offers=offers,
                qualify_at=qualify_at,
                review_at=review_at,
            )
        except (
            MarketingDataPolicyError,
            QualificationRuleError,
        ) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        matched_offer_id = evaluation["matched_offer_id"]

        if (
            matched_offer_id is None
            and funnel.get("default_offer_id")
        ):
            default_offer = await _fetch_one(
                pg,
                """
                SELECT id
                FROM marketing_offers
                WHERE id = :id
                  AND status = 'active'
                """,
                {"id": funnel["default_offer_id"]},
            )

            if default_offer:
                matched_offer_id = funnel["default_offer_id"]
                evaluation["matched_offer_id"] = matched_offer_id
                evaluation["lead_patch"]["offer_id"] = matched_offer_id

        submission_id = _new_id()

        await pg.execute(
            text("""
                INSERT INTO marketing_qualification_submissions (
                    id,
                    marketing_subject_id,
                    funnel_id,
                    qualification_form_id,
                    answers,
                    qualification_score,
                    qualification_status,
                    matched_offer_id,
                    normalized_fields,
                    submitted_at,
                    created_at
                )
                VALUES (
                    :id,
                    :subject,
                    :funnel_id,
                    :form_id,
                    CAST(:answers AS jsonb),
                    :score,
                    :status,
                    :offer_id,
                    CAST(:normalized AS jsonb),
                    now(),
                    now()
                )
            """),
            {
                "id": submission_id,
                "subject": payload.marketing_subject_id.strip(),
                "funnel_id": funnel_id,
                "form_id": form_id,
                "answers": json.dumps(payload.answers),
                "score": evaluation["qualification_score"],
                "status": evaluation["qualification_status"],
                "offer_id": matched_offer_id,
                "normalized": json.dumps(
                    evaluation["normalized_fields"]
                ),
            },
        )

        lead_row = await _fetch_one(
            pg,
            """
            SELECT *
            FROM marketing_leads
            WHERE marketing_subject_id = :subject
            """,
            {"subject": payload.marketing_subject_id.strip()},
        )

        lead_updated = False
        lead_id = None

        if lead_row:
            lead = _serialize(lead_row)
            lead_id = lead["id"]

            patch = dict(evaluation["lead_patch"])

            # Funnel context fills existing Phase 6 attribution fields.
            patch["landing_page"] = funnel.get("landing_page")

            columns = []
            params: dict[str, Any] = {"lead_id": lead_id}

            for field, value in patch.items():
                columns.append(f"{field} = :{field}")
                params[field] = value

            columns.extend([
                "last_activity_at = now()",
                "updated_at = now()",
            ])

            await pg.execute(
                text(f"""
                    UPDATE marketing_leads
                    SET {", ".join(columns)}
                    WHERE id = :lead_id
                """),
                params,
            )

            await pg.execute(
                text("""
                    INSERT INTO marketing_lead_activity (
                        id,
                        lead_id,
                        activity_type,
                        occurred_at,
                        actor_id,
                        summary,
                        details,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        :id,
                        :lead_id,
                        'qualification_submitted',
                        now(),
                        :actor_id,
                        'Marketing qualification submitted',
                        CAST(:details AS jsonb),
                        now(),
                        now()
                    )
                """),
                {
                    "id": _new_id(),
                    "lead_id": lead_id,
                    "actor_id": actor_id,
                    "details": json.dumps({
                        "funnel_id": funnel_id,
                        "qualification_form_id": form_id,
                        "qualification_score": (
                            evaluation["qualification_score"]
                        ),
                        "qualification_status": (
                            evaluation["qualification_status"]
                        ),
                        "matched_offer_id": matched_offer_id,
                    }),
                },
            )

            lead_updated = True

        await pg.commit()

        submission_row = await _fetch_one(
            pg,
            """
            SELECT *
            FROM marketing_qualification_submissions
            WHERE id = :id
            """,
            {"id": submission_id},
        )

    result = _serialize(submission_row)
    result["lead_updated"] = lead_updated
    result["lead_id"] = lead_id

    return result
