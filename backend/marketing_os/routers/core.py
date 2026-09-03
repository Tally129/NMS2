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

import json
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
from marketing_os.services.director_signals import build_cross_phase_signals
from marketing_os.services.director_persistence import persist_director_snapshot
from marketing_os.services.director_ai import build_director_summary
from marketing_os.services.executive_command_center import build_executive_command_center
from marketing_os.services.execution_policy import (
    ALLOWED_ACTIONS,
    SUPPORTED_PROVIDERS,
    canonical_provider,
)
from marketing_os.services.execution_queue import (
    decide_request,
    execution_request_matches_existing,
    perform_dry_run,
    prepare_execution_request,
    submit_for_approval,
)
from marketing_os.services.lead_opportunities import derive_lead_opportunities
from marketing_os.services.paid_media import build_paid_media_overview
from marketing_os.services.journey import (
    compute_channel_economics,
    compute_funnel,
    compute_revenue,
)
from marketing_os.services.lead_pipeline import setter_metrics
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

class ExecutionRequestCreate(BaseModel):
    provider: str = Field(..., min_length=2, max_length=64)
    action_type: str = Field(..., min_length=3, max_length=100)
    target_type: str = Field(..., min_length=1, max_length=100)
    target_id: Optional[str] = Field(default=None, max_length=255)
    payload: dict = Field(default_factory=dict)
    operation_token: str = Field(
        ...,
        min_length=16,
        max_length=128,
    )
    dry_run: bool = True


class ExecutionDecision(BaseModel):
    decision: str = Field(..., min_length=6, max_length=10)
    reason: Optional[str] = Field(default=None, max_length=2000)


class ExecutionPolicyUpdate(BaseModel):
    enabled: bool
    allowed_actions: list[str] = Field(default_factory=list)


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
    ai_summary: bool = Query(default=False),
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

        conversion_result = await pg.execute(
            text(
                """
                SELECT
                    event_type,
                    occurred_at,
                    marketing_subject_id,
                    source,
                    medium,
                    campaign,
                    value,
                    properties
                FROM marketing_conversion_events
                ORDER BY occurred_at ASC
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

        conversion_events = [
            dict(row._mapping)
            for row in conversion_result
        ]

        lead_rows = [
            serialize_row(row)
            for row in await pg.execute(
                text("SELECT * FROM marketing_leads")
            )
        ]

        lead_task_rows = [
            serialize_row(row)
            for row in await pg.execute(
                text("SELECT * FROM marketing_lead_tasks")
            )
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

    # Phase 9-11 Director inputs are intentionally bounded and read-only.
    # SELECT to_jsonb(row) avoids coupling the Director to every source-table
    # column while preserving the source modules as the systems of record.
    async with AsyncSessionLocal() as pg:
        experiment_result = await pg.execute(text("""
            SELECT to_jsonb(e) AS data
            FROM marketing_experiments e
            ORDER BY e.created_at DESC
            LIMIT 25
        """))
        experiment_rows = [
            dict(row._mapping["data"])
            for row in experiment_result
            if row._mapping["data"]
        ]

        local_result = await pg.execute(text("""
            SELECT to_jsonb(o) AS data
            FROM marketing_local_opportunities o
            WHERE COALESCE(o.status, 'open') NOT IN ('dismissed', 'actioned')
            ORDER BY o.priority DESC, o.created_at DESC
            LIMIT 50
        """))
        local_opportunity_rows = [
            dict(row._mapping["data"])
            for row in local_result
            if row._mapping["data"]
        ]

        content_result = await pg.execute(text("""
            SELECT to_jsonb(t) AS data
            FROM marketing_content_topics t
            WHERE COALESCE(t.status, 'idea') NOT IN ('archived', 'dismissed')
            ORDER BY t.priority DESC, t.created_at DESC
            LIMIT 50
        """))
        content_topic_rows = [
            dict(row._mapping["data"])
            for row in content_result
            if row._mapping["data"]
        ]

    director_signals = build_cross_phase_signals(
        paid_media=aggregated.values(),
        funnel=compute_funnel(conversion_events),
        lead_operations=setter_metrics(lead_rows, lead_task_rows),
        experiments=experiment_rows,
        local_growth=local_opportunity_rows,
        content_topics=content_topic_rows,
    )

    brief = build_marketing_brief(
        goals=goals,
        budgets=budgets,
        performance=aggregated.values(),

        # Keep raw campaign/day rows available for
        # exact budget allocation matching. Channel
        # analysis continues to use aggregates above.
        budget_performance=rows,

        # Read-only paid-media readiness + normalized metrics for
        # google_ads / meta_ads / microsoft_ads. Disconnected channels
        # surface honestly (null metrics) and never drive recommendations.
        paid_media=build_paid_media_overview(rows),

        # First-party lead -> appointment -> revenue outcomes. Deterministic,
        # PHI-free. Unavailable stages stay null and never fabricate zero.
        funnel=compute_funnel(conversion_events),
        channel_economics=compute_channel_economics(
            conversion_events, rows
        ),
        revenue=compute_revenue(conversion_events),

        # Operational setter/lead-workspace insights (advisory only).
        lead_operations=setter_metrics(lead_rows, lead_task_rows),
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
        "phase9_experiment_rows": len(experiment_rows),
        "phase10_local_opportunity_rows": len(local_opportunity_rows),
        "phase11_content_topic_rows": len(content_topic_rows),
    }

    director_summary, director_ai_status = await build_director_summary(
        director_signals,
        use_ai=ai_summary,
    )

    brief["director_summary"] = director_summary
    brief["director_ai_status"] = director_ai_status

    executive_command_center = build_executive_command_center(
        paid_media=aggregated.values(),
        funnel=compute_funnel(conversion_events),
        lead_operations=setter_metrics(
            lead_rows,
            lead_task_rows,
        ),
        director_signals=director_signals,
        director_summary=director_summary,
        revenue=brief.get("revenue") or {},
    )

    brief["executive_command_center"] = executive_command_center
    brief["director_signals"] = director_signals
    brief["safety"] = {
        "advisory_only": True,
        "ai_decides_priority": False,
        "automatic_execution": False,
        "external_execution_allowed": False,
        "human_approval_required": True,
        "phi_used": False,
    }

    director_source_counts = {
        "goal_rows": len(goals),
        "budget_rows": len(budgets),
        "metric_rows": len(rows),
        "phase9_experiment_rows": len(experiment_rows),
        "phase10_local_opportunity_rows": len(
            local_opportunity_rows
        ),
        "phase11_content_topic_rows": len(
            content_topic_rows
        ),
        "signal_rows": len(
            director_signals.get("signals") or []
        ),
    }

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            director_persistence = await persist_director_snapshot(
                pg,
                director_signals=director_signals,
                deterministic_brief={
                    "executive_summary": brief.get(
                        "executive_summary"
                    ),
                    "channel_health": brief.get(
                        "channel_health"
                    ),
                    "recommendation_count": len(
                        brief.get("recommendations") or []
                    ),
                    "director_summary": director_summary,
                    "director_ai_status": director_ai_status,
                },
                source_counts=director_source_counts,
                created_by=user_id(current_user),
            )

    brief["director_persistence"] = director_persistence
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

# Register Phase 4 read-only paid-media (Google/Meta/Microsoft) routes.
from marketing_os.routers import paid_media as _marketing_paid_media_routes  # noqa: F401,E402

# Register Phase 5 lead->appointment->revenue attribution routes.
from marketing_os.routers import attribution as _marketing_attribution_routes  # noqa: F401,E402

# Register Phase 6 Lead CRM + setter workspace routes.
from marketing_os.routers import leads as _marketing_leads_routes  # noqa: F401,E402

# Phase 7 — funnels / qualification forms / offer library.
from marketing_os.routers import funnels as _marketing_funnels_routes  # noqa: F401,E402

# Phase 8A — nurture sequences + appointment-recovery engine.
from marketing_os.routers import nurture as _marketing_nurture_routes  # noqa: F401,E402

# Phase 9 — conversion optimization + experimentation.
from marketing_os.routers import experiments as _marketing_experiments_routes  # noqa: F401,E402

# Phase 10 — reputation + local growth intelligence.
from marketing_os.routers import local_growth as _marketing_local_growth_routes  # noqa: F401,E402

# Phase 11 — content + social intelligence (draft/planning only).
from marketing_os.routers import content as _marketing_content_routes  # noqa: F401,E402




# ---------------------------------------------------------------------------
# Phase 14 — Controlled provider execution
#
# IMPORTANT:
# - all provider adapters remain dry-run only
# - no external provider writes occur here
# - human approval is mandatory
# - provider policy must explicitly enable dry runs + action type
# ---------------------------------------------------------------------------


def _execution_actor_id(user: dict) -> str:
    value = user_id(user)

    if not value:
        raise HTTPException(
            status_code=403,
            detail="Authenticated user id required",
        )

    return value


def _idempotency_reuse_conflict() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": (
                "idempotency_key_reused_with_different_request"
            ),
            "message": (
                "Operation token was already used for a "
                "different execution request."
            ),
        },
    )


def _serialize_and_validate_execution_replay(
    row,
    *,
    incoming_request: dict[str, Any],
    actor: str,
) -> dict[str, Any]:
    existing = serialize_row(row)

    if not execution_request_matches_existing(
        existing,
        incoming_request,
        actor=actor,
    ):
        raise _idempotency_reuse_conflict()

    existing["idempotent_replay"] = True
    existing["live_execution_enabled"] = False

    return existing


async def _get_execution_request(
    pg,
    request_id: str,
    *,
    for_update: bool = False,
):
    lock_clause = (
        "FOR UPDATE"
        if for_update
        else ""
    )

    result = await pg.execute(
        text(f"""
            SELECT
                id,
                provider,
                action_type,
                target_type,
                target_id,
                idempotency_key,
                request_payload,
                dry_run,
                status,
                human_approval_required,
                approved_by,
                approved_at,
                executed_by,
                executed_at,
                created_by,
                failure_code,
                failure_message,
                created_at,
                updated_at
            FROM marketing_execution_requests
            WHERE id = :request_id
            {lock_clause}
            LIMIT 1
        """),
        {
            "request_id": request_id,
        },
    )

    return result.first()


async def _get_execution_policy(
    pg,
    provider: str,
):
    result = await pg.execute(
        text("""
            SELECT
                id,
                provider,
                enabled,
                dry_run_only,
                human_approval_required,
                allowed_actions,
                created_by,
                created_at,
                updated_at
            FROM marketing_provider_execution_policies
            WHERE provider = :provider
            LIMIT 1
        """),
        {
            "provider": provider,
        },
    )

    return result.first()


@api.get("/marketing-os/execution/providers")
async def marketing_execution_providers(
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    return {
        "providers": sorted(SUPPORTED_PROVIDERS),
        "supported_actions": sorted(ALLOWED_ACTIONS),
        "live_execution_enabled": False,
        "dry_run_only": True,
        "human_approval_required": True,
    }


@api.get("/marketing-os/execution/policies")
async def marketing_execution_policies(
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    async with AsyncSessionLocal() as pg:
        result = await pg.execute(
            text("""
                SELECT
                    id,
                    provider,
                    enabled,
                    dry_run_only,
                    human_approval_required,
                    allowed_actions,
                    created_by,
                    created_at,
                    updated_at
                FROM marketing_provider_execution_policies
                ORDER BY provider ASC
            """)
        )

        rows = [
            serialize_row(row)
            for row in result.fetchall()
        ]

    return {
        "items": rows,
        "live_execution_enabled": False,
    }


@api.put("/marketing-os/execution/policies/{provider}")
async def marketing_execution_policy_update(
    provider: str,
    body: ExecutionPolicyUpdate,
    user=Depends(require_roles("admin")),
):
    actor = _execution_actor_id(user)
    provider = canonical_provider(provider)

    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported marketing provider",
        )

    normalized_actions = []

    for action in body.allowed_actions:
        value = str(action or "").strip().lower()

        if value not in ALLOWED_ACTIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported action: {value}",
            )

        if value not in normalized_actions:
            normalized_actions.append(value)

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            existing = await _get_execution_policy(
                pg,
                provider,
            )

            if existing:
                await pg.execute(
                    text("""
                        UPDATE marketing_provider_execution_policies
                        SET
                            enabled = :enabled,
                            dry_run_only = true,
                            human_approval_required = true,
                            allowed_actions =
                                CAST(:allowed_actions AS jsonb),
                            updated_at = now()
                        WHERE provider = :provider
                    """),
                    {
                        "provider": provider,
                        "enabled": bool(body.enabled),
                        "allowed_actions": json.dumps(
                            normalized_actions
                        ),
                    },
                )

            else:
                await pg.execute(
                    text("""
                        INSERT INTO marketing_provider_execution_policies (
                            id,
                            provider,
                            enabled,
                            dry_run_only,
                            human_approval_required,
                            allowed_actions,
                            created_by
                        )
                        VALUES (
                            :id,
                            :provider,
                            :enabled,
                            true,
                            true,
                            CAST(:allowed_actions AS jsonb),
                            :created_by
                        )
                    """),
                    {
                        "id": new_marketing_id(),
                        "provider": provider,
                        "enabled": bool(body.enabled),
                        "allowed_actions": json.dumps(
                            normalized_actions
                        ),
                        "created_by": actor,
                    },
                )

    return {
        "provider": provider,
        "enabled": bool(body.enabled),
        "dry_run_only": True,
        "human_approval_required": True,
        "allowed_actions": normalized_actions,
        "live_execution_enabled": False,
    }


@api.get("/marketing-os/execution/requests")
async def marketing_execution_requests(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    params = {
        "limit": limit,
    }

    where = ""

    if status:
        where = "WHERE status = :status"
        params["status"] = str(status).strip().lower()

    async with AsyncSessionLocal() as pg:
        result = await pg.execute(
            text(f"""
                SELECT
                    id,
                    provider,
                    action_type,
                    target_type,
                    target_id,
                    idempotency_key,
                    request_payload,
                    dry_run,
                    status,
                    human_approval_required,
                    approved_by,
                    approved_at,
                    executed_by,
                    executed_at,
                    created_by,
                    failure_code,
                    failure_message,
                    created_at,
                    updated_at
                FROM marketing_execution_requests
                {where}
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            params,
        )

        rows = [
            serialize_row(row)
            for row in result.fetchall()
        ]

    return {
        "items": rows,
        "count": len(rows),
        "live_execution_enabled": False,
    }


@api.post(
    "/marketing-os/execution/requests",
    status_code=201,
)
async def marketing_execution_request_create(
    body: ExecutionRequestCreate,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    actor = _execution_actor_id(user)

    if body.dry_run is not True:
        raise HTTPException(
            status_code=400,
            detail="Phase 14 supports dry-run requests only",
        )

    operation_token = body.operation_token.strip()
    if len(operation_token) < 16:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_operation_token",
                "message": (
                    "Operation token must contain at least "
                    "16 non-whitespace characters."
                ),
            },
        )

    prepared = prepare_execution_request(
        provider=body.provider,
        action_type=body.action_type,
        target_type=body.target_type,
        target_id=body.target_id,
        payload=body.payload,
        dry_run=True,
        operation_token=operation_token,
    )

    if not prepared.get("valid"):
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Invalid execution request",
                "errors": prepared.get("errors") or [],
                "payload_policy": (
                    prepared.get("payload_policy")
                    or {}
                ),
                "target_policy": (
                    prepared.get("target_policy")
                    or {}
                ),
            },
        )

    request = prepared["request"]

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            duplicate = await pg.execute(
                text("""
                    SELECT
                        id,
                        provider,
                        action_type,
                        target_type,
                        target_id,
                        idempotency_key,
                        request_payload,
                        dry_run,
                        status,
                        human_approval_required,
                        approved_by,
                        approved_at,
                        executed_by,
                        executed_at,
                        created_by,
                        failure_code,
                        failure_message,
                        created_at,
                        updated_at
                    FROM marketing_execution_requests
                    WHERE idempotency_key = :idempotency_key
                    LIMIT 1
                """),
                {
                    "idempotency_key":
                        request["idempotency_key"],
                },
            )

            duplicate_row = duplicate.first()

            if duplicate_row:
                return _serialize_and_validate_execution_replay(
                    duplicate_row,
                    incoming_request=request,
                    actor=actor,
                )

            insert_result = await pg.execute(
                text("""
                    INSERT INTO marketing_execution_requests (
                        id,
                        provider,
                        action_type,
                        target_type,
                        target_id,
                        idempotency_key,
                        request_payload,
                        dry_run,
                        status,
                        human_approval_required,
                        created_by
                    )
                    VALUES (
                        :id,
                        :provider,
                        :action_type,
                        :target_type,
                        :target_id,
                        :idempotency_key,
                        CAST(:request_payload AS jsonb),
                        true,
                        'draft',
                        true,
                        :created_by
                    )
                    ON CONFLICT (idempotency_key)
                    DO NOTHING
                    RETURNING id
                """),
                {
                    "id": request["id"],
                    "provider": request["provider"],
                    "action_type": request["action_type"],
                    "target_type": request["target_type"],
                    "target_id": request["target_id"],
                    "idempotency_key":
                        request["idempotency_key"],
                    "request_payload": json.dumps(
                        request["request_payload"]
                    ),
                    "created_by": actor,
                },
            )

            inserted_row = insert_result.first()

            if not inserted_row:
                # A concurrent request won the unique-key race.
                # PostgreSQL has already serialized the conflict;
                # re-read the committed winner and return it as an
                # idempotent replay rather than exposing a DB error.
                concurrent_duplicate = await pg.execute(
                    text("""
                        SELECT
                            id,
                            provider,
                            action_type,
                            target_type,
                            target_id,
                            idempotency_key,
                            request_payload,
                            dry_run,
                            status,
                            human_approval_required,
                            approved_by,
                            approved_at,
                            executed_by,
                            executed_at,
                            created_by,
                            failure_code,
                            failure_message,
                            created_at,
                            updated_at
                        FROM marketing_execution_requests
                        WHERE idempotency_key = :idempotency_key
                        LIMIT 1
                    """),
                    {
                        "idempotency_key":
                            request["idempotency_key"],
                    },
                )

                concurrent_row = (
                    concurrent_duplicate.first()
                )

                if not concurrent_row:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Concurrent execution request "
                            "could not be resolved"
                        ),
                    )

                return _serialize_and_validate_execution_replay(
                    concurrent_row,
                    incoming_request=request,
                    actor=actor,
                )

    return {
        **request,
        "created_by": actor,
        "idempotent_replay": False,
        "live_execution_enabled": False,
    }


@api.post(
    "/marketing-os/execution/requests/{request_id}/submit"
)
async def marketing_execution_request_submit(
    request_id: str,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    _execution_actor_id(user)

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            row = await _get_execution_request(
                pg,
                request_id,
                for_update=True,
            )

            if not row:
                raise HTTPException(
                    status_code=404,
                    detail="Execution request not found",
                )

            current = serialize_row(row)

            try:
                updated = submit_for_approval(current)
            except ValueError as exc:
                raise HTTPException(
                    status_code=409,
                    detail=str(exc),
                ) from exc

            await pg.execute(
                text("""
                    UPDATE marketing_execution_requests
                    SET
                        status = :status,
                        updated_at = now()
                    WHERE id = :request_id
                """),
                {
                    "status": updated["status"],
                    "request_id": request_id,
                },
            )

    return {
        "id": request_id,
        "status": updated["status"],
        "human_approval_required": True,
        "live_execution_enabled": False,
    }


@api.post(
    "/marketing-os/execution/requests/{request_id}/decision"
)
async def marketing_execution_request_decision(
    request_id: str,
    body: ExecutionDecision,
    user=Depends(require_roles("admin")),
):
    actor = _execution_actor_id(user)
    decision = str(body.decision or "").strip().lower()

    if decision not in {"approve", "reject"}:
        raise HTTPException(
            status_code=400,
            detail="Decision must be approve or reject",
        )

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            row = await _get_execution_request(
                pg,
                request_id,
                for_update=True,
            )

            if not row:
                raise HTTPException(
                    status_code=404,
                    detail="Execution request not found",
                )

            current = serialize_row(row)

            try:
                updated = decide_request(
                    current,
                    decision=decision,
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=409,
                    detail=str(exc),
                ) from exc

            await pg.execute(
                text("""
                    INSERT INTO marketing_execution_approvals (
                        id,
                        execution_request_id,
                        decision,
                        reason,
                        decided_by
                    )
                    VALUES (
                        :id,
                        :execution_request_id,
                        :decision,
                        :reason,
                        :decided_by
                    )
                """),
                {
                    "id": new_marketing_id(),
                    "execution_request_id": request_id,
                    "decision": decision,
                    "reason": body.reason,
                    "decided_by": actor,
                },
            )

            if decision == "approve":
                await pg.execute(
                    text("""
                        UPDATE marketing_execution_requests
                        SET
                            status = 'approved',
                            approved_by = :actor,
                            approved_at = now(),
                            updated_at = now()
                        WHERE id = :request_id
                    """),
                    {
                        "actor": actor,
                        "request_id": request_id,
                    },
                )

            else:
                await pg.execute(
                    text("""
                        UPDATE marketing_execution_requests
                        SET
                            status = 'rejected',
                            approved_by = NULL,
                            approved_at = NULL,
                            updated_at = now()
                        WHERE id = :request_id
                    """),
                    {
                        "request_id": request_id,
                    },
                )

    return {
        "id": request_id,
        "decision": decision,
        "status": updated["status"],
        "decided_by": actor,
        "human_approval_required": True,
        "live_execution_enabled": False,
    }


@api.get(
    "/marketing-os/execution/requests/{request_id}/approvals"
)
async def marketing_execution_request_approvals(
    request_id: str,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    async with AsyncSessionLocal() as pg:
        result = await pg.execute(
            text("""
                SELECT
                    id,
                    execution_request_id,
                    decision,
                    reason,
                    decided_by,
                    created_at
                FROM marketing_execution_approvals
                WHERE execution_request_id = :request_id
                ORDER BY created_at ASC
            """),
            {
                "request_id": request_id,
            },
        )

        rows = [
            serialize_row(row)
            for row in result.fetchall()
        ]

    return {
        "items": rows,
        "count": len(rows),
    }


@api.get(
    "/marketing-os/execution/requests/{request_id}/attempts"
)
async def marketing_execution_request_attempts(
    request_id: str,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    async with AsyncSessionLocal() as pg:
        result = await pg.execute(
            text("""
                SELECT
                    id,
                    execution_request_id,
                    attempt_number,
                    provider,
                    dry_run,
                    status,
                    request_snapshot,
                    response_snapshot,
                    error_code,
                    error_message,
                    started_at,
                    finished_at
                FROM marketing_execution_attempts
                WHERE execution_request_id = :request_id
                ORDER BY attempt_number ASC
            """),
            {
                "request_id": request_id,
            },
        )

        rows = [
            serialize_row(row)
            for row in result.fetchall()
        ]

    return {
        "items": rows,
        "count": len(rows),
    }


@api.post(
    "/marketing-os/execution/requests/{request_id}/dry-run"
)
async def marketing_execution_request_dry_run(
    request_id: str,
    user=Depends(require_roles(*MARKETING_ROLES)),
):
    _execution_actor_id(user)

    dry_run_exception = None

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            row = await _get_execution_request(
                pg,
                request_id,
                for_update=True,
            )

            if not row:
                raise HTTPException(
                    status_code=404,
                    detail="Execution request not found",
                )

            request = serialize_row(row)

            if request.get("status") != "approved":
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Execution request must be human-approved "
                        "before dry-run validation"
                    ),
                )

            if request.get("dry_run") is not True:
                raise HTTPException(
                    status_code=409,
                    detail="Live execution is not enabled",
                )

            policy_row = await _get_execution_policy(
                pg,
                request["provider"],
            )

            if policy_row:
                policy = serialize_row(policy_row)
            else:
                policy = {
                    "provider": request["provider"],
                    "enabled": False,
                    "dry_run_only": True,
                    "human_approval_required": True,
                    "allowed_actions": [],
                }

            # The request row was locked before lifecycle
            # validation. This also serializes attempt numbering.

            attempt_count = await pg.execute(
                text("""
                    SELECT COUNT(*) AS count
                    FROM marketing_execution_attempts
                    WHERE execution_request_id = :request_id
                """),
                {
                    "request_id": request_id,
                },
            )

            attempt_number = int(
                attempt_count.scalar() or 0
            ) + 1

            attempt_id = new_marketing_id()

            await pg.execute(
                text("""
                    INSERT INTO marketing_execution_attempts (
                        id,
                        execution_request_id,
                        attempt_number,
                        provider,
                        dry_run,
                        status,
                        request_snapshot
                    )
                    VALUES (
                        :id,
                        :execution_request_id,
                        :attempt_number,
                        :provider,
                        true,
                        'started',
                        CAST(:request_snapshot AS jsonb)
                    )
                """),
                {
                    "id": attempt_id,
                    "execution_request_id": request_id,
                    "attempt_number": attempt_number,
                    "provider": request["provider"],
                    "request_snapshot": json.dumps(
                        {
                            "provider":
                                request["provider"],
                            "action_type":
                                request["action_type"],
                            "target_type":
                                request["target_type"],
                            "target_id":
                                request["target_id"],
                            "request_payload":
                                request["request_payload"],
                            "dry_run": True,
                        },
                        default=str,
                    ),
                },
            )

            try:
                outcome = await perform_dry_run(
                    request,
                    provider_enabled=bool(
                        policy.get("enabled")
                    ),
                    provider_dry_run_only=True,
                    provider_human_approval_required=True,
                    provider_allowed_actions=(
                        policy.get("allowed_actions")
                        or []
                    ),
                )

                attempt_status = (
                    "dry_run_succeeded"
                    if outcome.get("allowed")
                    else "policy_blocked"
                )

                await pg.execute(
                    text("""
                        UPDATE marketing_execution_attempts
                        SET
                            status = :status,
                            response_snapshot =
                                CAST(:response_snapshot AS jsonb),
                            finished_at = now()
                        WHERE id = :attempt_id
                    """),
                    {
                        "status": attempt_status,
                        "response_snapshot": json.dumps(
                            outcome,
                            default=str,
                        ),
                        "attempt_id": attempt_id,
                    },
                )

            except Exception as exc:
                await pg.execute(
                    text("""
                        UPDATE marketing_execution_attempts
                        SET
                            status = 'failed',
                            error_code = 'dry_run_error',
                            error_message = :error_message,
                            finished_at = now()
                        WHERE id = :attempt_id
                    """),
                    {
                        "error_message": str(exc)[:2000],
                        "attempt_id": attempt_id,
                    },
                )

                # Do not raise inside pg.begin(); doing so would roll
                # back the failed-attempt audit update above.
                dry_run_exception = exc

    if dry_run_exception is not None:
        raise HTTPException(
            status_code=500,
            detail="Dry-run validation failed",
        ) from dry_run_exception

    return {
        "request_id": request_id,
        "attempt_id": attempt_id,
        "attempt_number": attempt_number,
        "outcome": outcome,
        "external_write_performed": False,
        "live_execution_enabled": False,
    }
