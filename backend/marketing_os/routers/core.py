"""Marketing OS core API.

Initial controlled release:
- health / capabilities
- goals CRUD
- budgets CRUD
- channel-account read access
- recommendations read access
- approval/rejection workflow

External advertising writes remain disabled.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from deps import api, require_roles
from postgres_db import AsyncSessionLocal

from marketing_os.capabilities import CAPABILITIES
from marketing_os.services.director import build_marketing_brief
from marketing_os.services.lead_opportunities import derive_lead_opportunities
from marketing_os.policy import DEFAULT_POLICY


# ---------------------------------------------------------------------------
# Access policy
# ---------------------------------------------------------------------------

MARKETING_ROLES = (
    "admin",
    "practitioner",
)


def new_marketing_id() -> str:
    return uuid.uuid4().hex


def user_id(user: dict) -> Optional[str]:
    value = user.get("id")
    return str(value) if value else None


def serialize_row(row) -> dict[str, Any]:
    result = dict(row._mapping)

    for key, value in list(result.items()):
        if isinstance(value, Decimal):
            result[key] = float(value)
        elif isinstance(value, (date, datetime)):
            result[key] = value.isoformat()

    return result


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class GoalCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    goal_type: str = Field(..., min_length=1, max_length=64)
    target_value: Optional[float] = None
    target_unit: Optional[str] = Field(default=None, max_length=64)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    service_line: Optional[str] = Field(default=None, max_length=160)
    geography: dict = Field(default_factory=dict)
    constraints: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
    status: str = Field(default="active", max_length=32)


class GoalPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=200)
    goal_type: Optional[str] = Field(default=None, max_length=64)
    target_value: Optional[float] = None
    target_unit: Optional[str] = Field(default=None, max_length=64)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    service_line: Optional[str] = Field(default=None, max_length=160)
    geography: Optional[dict] = None
    constraints: Optional[dict] = None
    metadata: Optional[dict] = None
    status: Optional[str] = Field(default=None, max_length=32)


class BudgetCreate(BaseModel):
    goal_id: Optional[str] = Field(default=None, max_length=64)
    name: str = Field(..., min_length=2, max_length=200)
    period_start: date
    period_end: date
    currency: str = Field(default="USD", min_length=3, max_length=3)
    approved_amount: float = Field(default=0, ge=0)
    daily_cap: Optional[float] = Field(default=None, ge=0)
    target_cpl: Optional[float] = Field(default=None, ge=0)
    target_cac: Optional[float] = Field(default=None, ge=0)
    minimum_roas: Optional[float] = Field(default=None, ge=0)
    allocation: dict = Field(default_factory=dict)
    rules: dict = Field(default_factory=dict)
    status: str = Field(default="draft", max_length=32)


class BudgetPatch(BaseModel):
    goal_id: Optional[str] = Field(default=None, max_length=64)
    name: Optional[str] = Field(default=None, min_length=2, max_length=200)
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    approved_amount: Optional[float] = Field(default=None, ge=0)
    daily_cap: Optional[float] = Field(default=None, ge=0)
    target_cpl: Optional[float] = Field(default=None, ge=0)
    target_cac: Optional[float] = Field(default=None, ge=0)
    minimum_roas: Optional[float] = Field(default=None, ge=0)
    allocation: Optional[dict] = None
    rules: Optional[dict] = None
    status: Optional[str] = Field(default=None, max_length=32)


class GoogleAdsAccountRegister(BaseModel):
    """Non-secret Google Ads account registration."""

    customer_id: str = Field(
        min_length=1,
        max_length=32,
    )
    account_name: Optional[str] = Field(
        default=None,
        max_length=255,
    )


class RecommendationDecision(BaseModel):
    decision: str
    reason: Optional[str] = Field(default=None, max_length=4000)


# ---------------------------------------------------------------------------
# Health / capability endpoints
# ---------------------------------------------------------------------------

@api.get("/marketing-os/health")
async def marketing_os_health(
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    return {
        "status": "ok",
        "module": "marketing_os",
        "external_writes_enabled": DEFAULT_POLICY.external_writes_enabled,
        "human_approval_required": DEFAULT_POLICY.human_approval_required,
    }


@api.get("/marketing-os/capabilities")
async def marketing_os_capabilities(
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    return {
        "capabilities": CAPABILITIES,
        "policy": {
            "external_writes_enabled": DEFAULT_POLICY.external_writes_enabled,
            "automatic_budget_changes_enabled":
                DEFAULT_POLICY.automatic_budget_changes_enabled,
            "automatic_campaign_creation_enabled":
                DEFAULT_POLICY.automatic_campaign_creation_enabled,
            "automatic_publishing_enabled":
                DEFAULT_POLICY.automatic_publishing_enabled,
            "human_approval_required":
                DEFAULT_POLICY.human_approval_required,
        },
    }


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------

@api.get("/marketing-os/goals")
async def list_marketing_goals(
    limit: int = Query(default=100, ge=1, le=500),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    async with AsyncSessionLocal() as pg:
        result = await pg.execute(
            text("""
                SELECT *
                FROM marketing_goals
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            {"limit": limit},
        )

        return [serialize_row(row) for row in result]


@api.post("/marketing-os/goals", status_code=201)
async def create_marketing_goal(
    payload: GoalCreate,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    if (
        payload.start_date
        and payload.end_date
        and payload.end_date < payload.start_date
    ):
        raise HTTPException(
            status_code=400,
            detail="end_date must be on or after start_date",
        )

    goal_id = new_marketing_id()

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            result = await pg.execute(
                text("""
                    INSERT INTO marketing_goals (
                        id,
                        name,
                        status,
                        goal_type,
                        target_value,
                        target_unit,
                        start_date,
                        end_date,
                        service_line,
                        geography,
                        constraints,
                        metadata,
                        created_by
                    )
                    VALUES (
                        :id,
                        :name,
                        :status,
                        :goal_type,
                        :target_value,
                        :target_unit,
                        :start_date,
                        :end_date,
                        :service_line,
                        CAST(:geography AS jsonb),
                        CAST(:constraints AS jsonb),
                        CAST(:metadata AS jsonb),
                        :created_by
                    )
                    RETURNING *
                """),
                {
                    "id": goal_id,
                    "name": payload.name,
                    "status": payload.status,
                    "goal_type": payload.goal_type,
                    "target_value": payload.target_value,
                    "target_unit": payload.target_unit,
                    "start_date": payload.start_date,
                    "end_date": payload.end_date,
                    "service_line": payload.service_line,
                    "geography": __import__("json").dumps(payload.geography),
                    "constraints": __import__("json").dumps(payload.constraints),
                    "metadata": __import__("json").dumps(payload.metadata),
                    "created_by": user_id(user),
                },
            )

            row = result.first()

    return serialize_row(row)


@api.patch("/marketing-os/goals/{goal_id}")
async def patch_marketing_goal(
    goal_id: str,
    payload: GoalPatch,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    values = payload.model_dump(exclude_unset=True)

    if not values:
        raise HTTPException(status_code=400, detail="No changes supplied")

    allowed = {
        "name",
        "goal_type",
        "target_value",
        "target_unit",
        "start_date",
        "end_date",
        "service_line",
        "geography",
        "constraints",
        "metadata",
        "status",
    }

    json_fields = {
        "geography",
        "constraints",
        "metadata",
    }

    assignments = []
    params: dict[str, Any] = {"goal_id": goal_id}

    import json

    for key, value in values.items():
        if key not in allowed:
            continue

        if key in json_fields:
            assignments.append(
                f"{key} = CAST(:{key} AS jsonb)"
            )
            params[key] = json.dumps(value)
        else:
            assignments.append(f"{key} = :{key}")
            params[key] = value

    assignments.append("updated_at = now()")

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            result = await pg.execute(
                text(f"""
                    UPDATE marketing_goals
                    SET {", ".join(assignments)}
                    WHERE id = :goal_id
                    RETURNING *
                """),
                params,
            )

            row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Goal not found")

    return serialize_row(row)


@api.delete("/marketing-os/goals/{goal_id}")
async def delete_marketing_goal(
    goal_id: str,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            result = await pg.execute(
                text("""
                    DELETE FROM marketing_goals
                    WHERE id = :goal_id
                    RETURNING id
                """),
                {"goal_id": goal_id},
            )

            row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Goal not found")

    return {
        "deleted": True,
        "id": goal_id,
    }


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

@api.get("/marketing-os/budgets")
async def list_marketing_budgets(
    limit: int = Query(default=100, ge=1, le=500),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    async with AsyncSessionLocal() as pg:
        result = await pg.execute(
            text("""
                SELECT *
                FROM marketing_budgets
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            {"limit": limit},
        )

        return [serialize_row(row) for row in result]


@api.post("/marketing-os/budgets", status_code=201)
async def create_marketing_budget(
    payload: BudgetCreate,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    if payload.period_end < payload.period_start:
        raise HTTPException(
            status_code=400,
            detail="period_end must be on or after period_start",
        )

    import json

    budget_id = new_marketing_id()

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            result = await pg.execute(
                text("""
                    INSERT INTO marketing_budgets (
                        id,
                        goal_id,
                        name,
                        period_start,
                        period_end,
                        currency,
                        approved_amount,
                        daily_cap,
                        target_cpl,
                        target_cac,
                        minimum_roas,
                        allocation,
                        rules,
                        status,
                        created_by
                    )
                    VALUES (
                        :id,
                        :goal_id,
                        :name,
                        :period_start,
                        :period_end,
                        :currency,
                        :approved_amount,
                        :daily_cap,
                        :target_cpl,
                        :target_cac,
                        :minimum_roas,
                        CAST(:allocation AS jsonb),
                        CAST(:rules AS jsonb),
                        :status,
                        :created_by
                    )
                    RETURNING *
                """),
                {
                    "id": budget_id,
                    "goal_id": payload.goal_id,
                    "name": payload.name,
                    "period_start": payload.period_start,
                    "period_end": payload.period_end,
                    "currency": payload.currency.upper(),
                    "approved_amount": payload.approved_amount,
                    "daily_cap": payload.daily_cap,
                    "target_cpl": payload.target_cpl,
                    "target_cac": payload.target_cac,
                    "minimum_roas": payload.minimum_roas,
                    "allocation": json.dumps(payload.allocation),
                    "rules": json.dumps(payload.rules),
                    "status": payload.status,
                    "created_by": user_id(user),
                },
            )

            row = result.first()

    return serialize_row(row)


@api.patch("/marketing-os/budgets/{budget_id}")
async def patch_marketing_budget(
    budget_id: str,
    payload: BudgetPatch,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    values = payload.model_dump(exclude_unset=True)

    if not values:
        raise HTTPException(status_code=400, detail="No changes supplied")

    allowed = {
        "goal_id",
        "name",
        "period_start",
        "period_end",
        "currency",
        "approved_amount",
        "daily_cap",
        "target_cpl",
        "target_cac",
        "minimum_roas",
        "allocation",
        "rules",
        "status",
    }

    json_fields = {
        "allocation",
        "rules",
    }

    import json

    assignments = []
    params: dict[str, Any] = {"budget_id": budget_id}

    for key, value in values.items():
        if key not in allowed:
            continue

        if key == "currency" and value:
            value = value.upper()

        if key in json_fields:
            assignments.append(
                f"{key} = CAST(:{key} AS jsonb)"
            )
            params[key] = json.dumps(value)
        else:
            assignments.append(f"{key} = :{key}")
            params[key] = value

    assignments.append("updated_at = now()")

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            result = await pg.execute(
                text(f"""
                    UPDATE marketing_budgets
                    SET {", ".join(assignments)}
                    WHERE id = :budget_id
                    RETURNING *
                """),
                params,
            )

            row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Budget not found")

    return serialize_row(row)


@api.delete("/marketing-os/budgets/{budget_id}")
async def delete_marketing_budget(
    budget_id: str,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            result = await pg.execute(
                text("""
                    DELETE FROM marketing_budgets
                    WHERE id = :budget_id
                    RETURNING id
                """),
                {"budget_id": budget_id},
            )

            row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Budget not found")

    return {
        "deleted": True,
        "id": budget_id,
    }


# ---------------------------------------------------------------------------
# Read-only campaign inventory
# ---------------------------------------------------------------------------



@api.get("/marketing-os/lead-opportunities")
async def list_marketing_lead_opportunities(
    user=Depends(
        require_roles(*MARKETING_ROLES)
    ),
):
    """
    Return privacy-minimized lead opportunities derived
    from existing Marketing OS conversion events.

    Safety:
    - read-only;
    - no provider calls;
    - no campaign or budget changes;
    - no outreach;
    - no direct-contact identifiers;
    - no clinical or patient fields.
    """

    del user

    async with AsyncSessionLocal() as pg:
        result = await pg.execute(
            text(
                """
                SELECT
                    event_type,
                    occurred_at,
                    marketing_subject_id,
                    session_id,
                    external_click_id,
                    source,
                    medium,
                    campaign,
                    content,
                    term,
                    value,
                    currency,
                    properties
                FROM marketing_conversion_events
                WHERE marketing_subject_id IS NOT NULL
                  AND BTRIM(marketing_subject_id) <> ''
                ORDER BY
                    marketing_subject_id,
                    occurred_at
                """
            )
        )

        events = [
            dict(row)
            for row
            in result.mappings().all()
        ]

    return derive_lead_opportunities(
        events
    )


@api.get("/marketing-os/campaigns")
async def list_marketing_campaigns(
    user=Depends(
        require_roles(*MARKETING_ROLES)
    ),
):
    """List locally observed advertising campaigns.

    This reads only aggregate Marketing OS performance
    already stored in Postgres.

    It does not contact Google, Meta, TikTok, Microsoft,
    or any other advertising provider.
    """

    from marketing_os.services.campaign_inventory import (
        list_campaign_inventory,
    )

    async with AsyncSessionLocal() as pg:
        return await list_campaign_inventory(
            pg
        )


# ---------------------------------------------------------------------------
# Read-only account visibility
# ---------------------------------------------------------------------------

@api.get(
    "/marketing-os/channel-accounts/google-ads/readiness"
)
async def google_ads_connection_readiness(
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    """Report Google Ads connection readiness without contacting Google."""

    from marketing_os.integrations.google_ads import (
        credential_readiness,
    )

    credentials = credential_readiness()

    async with AsyncSessionLocal() as pg:
        result = await pg.execute(
            text(
                """
                SELECT
                    id,
                    external_account_id,
                    account_name,
                    status,
                    read_enabled,
                    write_enabled,
                    last_sync_at
                FROM marketing_channel_accounts
                WHERE provider = 'google_ads'
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
        )

        account = result.mappings().first()

    if account is None:
        state = "not_registered"

    elif account["write_enabled"]:
        state = "unsafe_configuration"

    elif not credentials["required_configured"]:
        state = "credentials_missing"

    elif (
        account["status"] != "connected"
        or not account["read_enabled"]
    ):
        state = "registered_but_not_authenticated"

    else:
        state = "ready_for_read_sync"

    account_payload = None

    if account is not None:
        account_payload = {
            "id": account["id"],
            "external_account_id":
                account["external_account_id"],
            "account_name":
                account["account_name"],
            "status": account["status"],
            "read_enabled":
                bool(account["read_enabled"]),
            "write_enabled":
                bool(account["write_enabled"]),
            "last_sync_at":
                (
                    account["last_sync_at"].isoformat()
                    if account["last_sync_at"]
                    else None
                ),
        }

    return {
        "provider": "google_ads",
        "state": state,
        "registered": account is not None,
        "credentials": credentials,
        "account": account_payload,
        "read_only": True,
        "google_api_called": False,
        "external_writes_enabled": False,
    }


@api.post(
    "/marketing-os/channel-accounts/google-ads",
    status_code=201,
)
async def register_google_ads_account(
    payload: GoogleAdsAccountRegister,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    """Register a Google Ads customer without storing secrets.

    This performs no Google API request and grants no write
    capability. Credentials remain server-side environment secrets.
    """

    from marketing_os.integrations.google_ads import (
        _clean_customer_id,
    )

    try:
        customer_id = _clean_customer_id(
            payload.customer_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    account_id = new_marketing_id()

    async with AsyncSessionLocal() as pg:
        async with pg.begin():

            existing = await pg.execute(
                text(
                    """
                    SELECT *
                    FROM marketing_channel_accounts
                    WHERE provider = 'google_ads'
                      AND external_account_id = :customer_id
                    """
                ),
                {
                    "customer_id": customer_id,
                },
            )

            existing_row = existing.mappings().first()

            if existing_row:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Google Ads customer is "
                        "already registered"
                    ),
                )

            result = await pg.execute(
                text(
                    """
                    INSERT INTO marketing_channel_accounts (
                        id,
                        provider,
                        external_account_id,
                        account_name,
                        status,
                        read_enabled,
                        write_enabled,
                        configuration,
                        created_by
                    )
                    VALUES (
                        :id,
                        'google_ads',
                        :customer_id,
                        :account_name,
                        'disconnected',
                        FALSE,
                        FALSE,
                        CAST(:configuration AS jsonb),
                        :created_by
                    )
                    RETURNING *
                    """
                ),
                {
                    "id": account_id,
                    "customer_id": customer_id,
                    "account_name": payload.account_name,
                    "configuration":
                        __import__("json").dumps(
                            {
                                "read_only": True,
                                "credentials_source":
                                    "server_environment",
                            }
                        ),
                    "created_by": user_id(user),
                },
            )

            row = result.mappings().one()

    return serialize_row(row)


@api.get("/marketing-os/channel-accounts")
async def list_marketing_channel_accounts(
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    async with AsyncSessionLocal() as pg:
        result = await pg.execute(
            text("""
                SELECT
                    id,
                    provider,
                    external_account_id,
                    account_name,
                    status,
                    currency,
                    timezone,
                    read_enabled,
                    write_enabled,
                    last_sync_at,
                    created_at,
                    updated_at
                FROM marketing_channel_accounts
                ORDER BY provider, account_name
            """)
        )

        return [serialize_row(row) for row in result]


# ---------------------------------------------------------------------------
# Recommendations / human approval
# ---------------------------------------------------------------------------

@api.get("/marketing-os/recommendations")
async def list_marketing_recommendations(
    status: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    params: dict[str, Any] = {"limit": limit}

    where = ""

    if status:
        where = "WHERE status = :status"
        params["status"] = status

    async with AsyncSessionLocal() as pg:
        result = await pg.execute(
            text(f"""
                SELECT *
                FROM marketing_recommendations
                {where}
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            params,
        )

        return [serialize_row(row) for row in result]


@api.post(
    "/marketing-os/recommendations/{recommendation_id}/decision"
)
async def decide_marketing_recommendation(
    recommendation_id: str,
    payload: RecommendationDecision,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    from marketing_os.services.workflow import (
        RecommendationNotFoundError,
        RecommendationStateError,
        decide_recommendation,
    )

    decision = payload.decision.lower().strip()

    if decision not in {
        "approved",
        "rejected",
    }:
        raise HTTPException(
            status_code=400,
            detail="decision must be approved or rejected",
        )

    try:
        async with AsyncSessionLocal() as pg:
            async with pg.begin():
                result = await decide_recommendation(
                    pg,
                    recommendation_id=recommendation_id,
                    decision=decision,
                    reason=payload.reason,
                    decided_by=user_id(user),
                )

    except RecommendationNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except RecommendationStateError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    return result


# ---------------------------------------------------------------------------
# Marketing Director intelligence
# ---------------------------------------------------------------------------

@api.get("/marketing-os/director/brief")
async def marketing_director_brief(
    current_user=Depends(
        require_roles(*MARKETING_ROLES)
    ),
):
    """Return an advisory Marketing Director brief.

    Reads Marketing OS goals and aggregate daily metrics.

    This endpoint:
    - performs no external writes;
    - performs no budget changes;
    - performs no campaign creation;
    - performs no publishing;
    - persists advisory recommendations for human review.
    """

    async with AsyncSessionLocal() as pg:

        goals_result = await pg.execute(
            text(
                """
                SELECT *
                FROM marketing_goals
                ORDER BY created_at DESC
                """
            )
        )

        budget_result = await pg.execute(
            text(
                """
                SELECT *
                FROM marketing_budgets
                ORDER BY created_at DESC
                """
            )
        )

        metric_result = await pg.execute(
            text(
                """
                SELECT *
                FROM marketing_daily_metrics
                ORDER BY metric_date DESC
                """
            )
        )

        goals = [
            dict(row._mapping)
            for row in goals_result
        ]

        budgets = [
            dict(row._mapping)
            for row in budget_result
        ]

        rows = [
            dict(row._mapping)
            for row in metric_result
        ]

    # Aggregate database rows by channel before
    # passing them into the deterministic Director.

    aggregated = {}

    for row in rows:

        channel = str(
            row.get("channel")
            or row.get("provider")
            or "unknown"
        ).strip().lower()

        item = aggregated.setdefault(
            channel,
            {
                "channel": channel,
                "impressions": 0,
                "clicks": 0,
                "conversions": 0,
                "spend": 0.0,
                "revenue": 0.0,
            },
        )

        for field in (
            "impressions",
            "clicks",
        ):
            try:
                item[field] += int(
                    row.get(field) or 0
                )
            except (TypeError, ValueError):
                pass

        try:
            item["conversions"] += float(
                row.get("conversions") or 0
            )
        except (TypeError, ValueError):
            pass

        try:
            item["spend"] += float(
                row.get("spend") or 0
            )
        except (TypeError, ValueError):
            pass

        # Database schema stores attributed value as
        # conversion_value. The deterministic Director
        # calls the same concept revenue for ROAS analysis.
        try:
            item["revenue"] += float(
                row.get("conversion_value") or 0
            )
        except (TypeError, ValueError):
            pass

    brief = build_marketing_brief(
        goals=goals,
        budgets=budgets,
        performance=aggregated.values(),

        # Keep raw campaign/day rows available for
        # exact budget allocation matching. Channel
        # analysis continues to use aggregates above.
        budget_performance=rows,
    )

    from marketing_os.services.recommendation_persistence import (
        persist_director_recommendations,
    )

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            persistence = await (
                persist_director_recommendations(
                    pg,
                    recommendations=brief.get(
                        "recommendations",
                        [],
                    ),
                    created_by=user_id(
                        current_user
                    ),
                )
            )

    brief["source"] = {
        "goals": "marketing_goals",
        "budgets": "marketing_budgets",
        "performance": "marketing_daily_metrics",
        "goal_rows": len(goals),
        "budget_rows": len(budgets),
        "metric_rows": len(rows),
    }

    brief["persistence"] = persistence

    return brief

# Register secure first-party marketing event ingestion routes.
from marketing_os.routers import ingestion as _marketing_ingestion_routes  # noqa: F401,E402

# Register read-only Search Intelligence routes.
from marketing_os.routers import search as _marketing_search_routes  # noqa: F401,E402

# Register read-only Google Search Console + rank-tracking routes (Phase 2).
from marketing_os.routers import search_console as _marketing_gsc_routes  # noqa: F401,E402

# Register Phase 3 competitor/keyword-gap/backlink/local routes.
from marketing_os.routers import search_phase3 as _marketing_phase3_routes  # noqa: F401,E402
