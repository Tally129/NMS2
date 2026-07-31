"""
Provider-authorized delegated editing for clinical documentation.

A provider may grant a Medical Assistant or Admin the ability to draft or
edit unsigned clinical documents on their behalf, either blanket (all
patients assigned to the provider) or scoped to a specific client. Only
providers may finalize / amend / sign / prescribe / lock — that stays hard-
coded at the route level.

Data model  (`db.clinical_delegations`):
    id, provider_id, provider_name,
    delegate_id, delegate_name, delegate_role,
    client_id: Optional[str]     # None = all of provider's patients
    scope: "documentation"       # forward-compatible (future scopes)
    created_at, expires_at, revoked_at
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from postgres_db import AsyncSessionLocal
from repositories import clinical_and_messaging as cm_repo


ELIGIBLE_DELEGATE_ROLES = {"medical_assistant", "admin"}
DEFAULT_TTL = timedelta(hours=24)
MAX_TTL = timedelta(days=7)


async def has_active_delegation(
    user: dict,
    client_id: Optional[str],
    provider_id: Optional[str] = None,
) -> Optional[dict]:
    """Return the active delegation doc if user is delegated to draft on
    behalf of a provider for `client_id`. Providers never need delegation
    for their own records; this helper returns None for provider callers.
    """
    role = user.get("role")
    if role not in ELIGIBLE_DELEGATE_ROLES:
        return None
    async with AsyncSessionLocal() as pg:
        if client_id:
            deleg = await cm_repo.find_active_delegation(
                pg, delegate_id=user["id"], client_id=client_id,
            )
            if deleg:
                if provider_id and deleg.get("provider_id") != provider_id:
                    return None
                return deleg
            # Fall through to blanket search (client_id NULL)
        # Blanket delegation: client_id IS NULL — issue a manual query.
        from sqlalchemy import select
        from postgres_models.clinical_and_messaging import ClinicalDelegation
        now = datetime.now(timezone.utc)
        stmt = select(ClinicalDelegation).where(
            ClinicalDelegation.delegate_id == user["id"],
            ClinicalDelegation.client_id.is_(None),
            ClinicalDelegation.active.is_(True),
        )
        if provider_id:
            stmt = stmt.where(ClinicalDelegation.provider_id == provider_id)
        stmt = stmt.order_by(ClinicalDelegation.created_at.desc()).limit(1)
        row = (await pg.execute(stmt)).scalar_one_or_none()
        if not row:
            return None
        if row.expires_at and row.expires_at <= now:
            return None
        return cm_repo.delegation_to_dict(row)


def compute_edit_state(user: dict, record_status: Optional[str], delegation: Optional[dict]) -> str:
    """UI-facing state string.

    - `finalized` — record is locked; only amend (provider) allowed
    - `draft_editing` — user is authorized to edit the draft
    - `awaiting_review` — the record is a draft but user cannot edit (no auth)
    - `read_only` — user has no edit path
    """
    status = (record_status or "draft").lower()
    role = user.get("role")
    if status == "finalized":
        return "finalized"
    if role == "practitioner":
        return "draft_editing"
    if role in ELIGIBLE_DELEGATE_ROLES and delegation:
        return "draft_editing"
    if role in ELIGIBLE_DELEGATE_ROLES:
        return "read_only"
    return "read_only"
