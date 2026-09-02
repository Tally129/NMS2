from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

from deps import api, db, require_roles
from postgres_db import AsyncSessionLocal
from repositories import terminals as terminal_repo
from services.terminals.factory import (
    supported_terminal_providers,
)

from audit import log_audit, get_client_ip


_FORBIDDEN_KEYS = {
    "card_number",
    "cardnumber",
    "pan",
    "full_pan",
    "cvv",
    "cvc",
    "pin",
    "track_data",
    "routing_number",
    "account_number",
}


def _validate_safe_mapping(
    value: Dict[str, Any],
    label: str,
):
    def walk(obj, path=""):
        if isinstance(obj, dict):
            for key, val in obj.items():
                normalized = str(key).lower().replace("-", "_")

                if normalized in _FORBIDDEN_KEYS:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"{label} contains forbidden "
                            f"sensitive field: {key}"
                        ),
                    )

                walk(
                    val,
                    f"{path}.{key}" if path else str(key),
                )

        elif isinstance(obj, list):
            for idx, item in enumerate(obj):
                walk(item, f"{path}[{idx}]")

    walk(value or {})


class TerminalCreateIn(BaseModel):
    provider: str
    provider_device_id: str = Field(
        min_length=1,
        max_length=255,
    )
    display_name: str = Field(
        min_length=1,
        max_length=255,
    )
    location_id: Optional[str] = None
    connection_type: Optional[str] = None
    enabled: bool = True
    is_default: bool = False
    capabilities: Dict[str, Any] = Field(
        default_factory=dict
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict
    )


class TerminalUpdateIn(BaseModel):
    display_name: Optional[str] = None
    location_id: Optional[str] = None
    connection_type: Optional[str] = None
    enabled: Optional[bool] = None
    is_default: Optional[bool] = None
    capabilities: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


@api.get("/terminals/providers")
async def providers(
    user=Depends(require_roles("admin")),
):
    return {
        "providers": supported_terminal_providers()
    }


@api.get("/terminals")
async def list_terminals(
    location_id: Optional[str] = None,
    provider: Optional[str] = None,
    user=Depends(require_roles("admin")),
):
    async with AsyncSessionLocal() as pg:
        return await terminal_repo.list_terminals(
            pg,
            location_id=location_id,
            provider=provider,
        )


@api.get("/terminals/{terminal_id}")
async def get_terminal(
    terminal_id: str,
    user=Depends(require_roles("admin")),
):
    async with AsyncSessionLocal() as pg:
        row = await terminal_repo.get_terminal(
            pg,
            terminal_id,
        )

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Terminal not found",
        )

    return row


@api.post("/terminals")
async def create_terminal(
    payload: TerminalCreateIn,
    request: Request,
    user=Depends(require_roles("admin")),
):
    providers = set(
        supported_terminal_providers()
    )

    if payload.provider not in providers:
        raise HTTPException(
            status_code=400,
            detail="Unsupported terminal provider",
        )

    _validate_safe_mapping(
        payload.capabilities,
        "capabilities",
    )
    _validate_safe_mapping(
        payload.metadata,
        "metadata",
    )

    doc = payload.model_dump()

    doc["configured"] = False
    doc["status"] = "unknown"
    doc["created_by"] = user["id"]
    doc["updated_by"] = user["id"]

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            if doc["is_default"]:
                await terminal_repo.clear_defaults(
                    pg,
                    location_id=doc.get("location_id"),
                )

            row = await terminal_repo.create_terminal(
                pg,
                doc,
            )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "terminal.create",
        resource_type="payment_terminal",
        resource_id=row["id"],
        metadata={
            "provider": row["provider"],
            "display_name": row["display_name"],
            "location_id": row.get("location_id"),
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return row


@api.patch("/terminals/{terminal_id}")
async def update_terminal(
    terminal_id: str,
    payload: TerminalUpdateIn,
    request: Request,
    user=Depends(require_roles("admin")),
):
    fields = payload.model_dump(
        exclude_unset=True
    )

    if "capabilities" in fields:
        _validate_safe_mapping(
            fields["capabilities"] or {},
            "capabilities",
        )

    if "metadata" in fields:
        _validate_safe_mapping(
            fields["metadata"] or {},
            "metadata",
        )

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            current = await terminal_repo.get_terminal(
                pg,
                terminal_id,
            )

            if not current:
                raise HTTPException(
                    status_code=404,
                    detail="Terminal not found",
                )

            if fields.get("is_default") is True:
                location_id = fields.get(
                    "location_id",
                    current.get("location_id"),
                )

                await terminal_repo.clear_defaults(
                    pg,
                    location_id=location_id,
                )

            fields["updated_by"] = user["id"]

            await terminal_repo.update_terminal(
                pg,
                terminal_id,
                fields,
            )

            updated = await terminal_repo.get_terminal(
                pg,
                terminal_id,
            )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "terminal.update",
        resource_type="payment_terminal",
        resource_id=terminal_id,
        metadata={
            "fields": sorted(fields.keys())
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return updated


@api.delete("/terminals/{terminal_id}")
async def delete_terminal(
    terminal_id: str,
    request: Request,
    user=Depends(require_roles("admin")),
):
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            current = await terminal_repo.get_terminal(
                pg,
                terminal_id,
            )

            if not current:
                raise HTTPException(
                    status_code=404,
                    detail="Terminal not found",
                )

            await terminal_repo.archive_terminal(
                pg,
                terminal_id,
                updated_by=user["id"],
            )

    await log_audit(
        db,
        user["id"],
        user["email"],
        "terminal.archive",
        resource_type="payment_terminal",
        resource_id=terminal_id,
        metadata={
            "provider": current["provider"],
            "display_name": current["display_name"],
        },
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return {"ok": True}


@api.post("/terminals/{terminal_id}/health")
async def terminal_health(
    terminal_id: str,
    user=Depends(require_roles("admin")),
):
    async with AsyncSessionLocal() as pg:
        row = await terminal_repo.get_terminal(
            pg,
            terminal_id,
        )

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Terminal not found",
        )

    # Provider adapters are intentionally not activated yet.
    # A DB record must never be mistaken for live connectivity.
    return {
        "terminal_id": terminal_id,
        "provider": row["provider"],
        "configured": row["configured"],
        "status": row["status"],
        "connected": False,
        "reason": "provider_not_configured",
    }
