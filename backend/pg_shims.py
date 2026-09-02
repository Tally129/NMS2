"""PostgreSQL compatibility shims for Phase 3.1b Mongo → PG cutover.

Each helper opens its own AsyncSession, executes the query, and returns
Mongo-shape dicts so downstream routers keep working unchanged. Callers
must NOT touch `AsyncSessionLocal` directly through this module.

Domains covered:
    * users           → auth_users (via repositories.users)
    * clients         → emr_clients (via repositories.clients)
    * intake_forms    → emr_intake_forms (via repositories.clients)
    * supplement_sheets            → emr_supplement_sheets
    * client_supplement_assignments → emr_client_supplement_assignments
    * password_reset_tokens (staff/portal_ops) → emr_legacy_password_reset_tokens
"""
from __future__ import annotations

import re as _re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import String, and_, cast, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB

from postgres_db import AsyncSessionLocal
from postgres_models import (
    Client,
    ClientSupplementAssignment,
    IntakeForm,
    LegacyPasswordResetToken,
    SupplementSheet,
    User,
)
from repositories import clients as clients_repo
from repositories import supplements as supplements_repo
from repositories import users as users_repo


# --------------------------------------------------------------------- users #
def _user_dict(u: User) -> Dict[str, Any]:
    return users_repo.user_to_dict(u)


async def find_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    if not user_id:
        return None
    async with AsyncSessionLocal() as s:
        return await users_repo.get_by_id(s, user_id)


async def find_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    async with AsyncSessionLocal() as s:
        return await users_repo.get_by_email(s, email)


async def find_users_by_ids(ids: Iterable[str]) -> List[Dict[str, Any]]:
    ids_list = [i for i in (ids or []) if i]
    if not ids_list:
        return []
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(User).where(User.id.in_(ids_list)))).scalars().all()
        return [_user_dict(u) for u in rows]


async def list_users_by_role(role: str, active_only: bool = True, limit: int = 100) -> List[Dict[str, Any]]:
    async with AsyncSessionLocal() as s:
        stmt = select(User).where(User.role == role)
        if active_only:
            stmt = stmt.where(User.is_active.is_(True))
        stmt = stmt.order_by(User.created_at.desc()).limit(limit)
        return [_user_dict(u) for u in (await s.execute(stmt)).scalars().all()]


async def list_users_by_roles(roles: Iterable[str], limit: int = 50) -> List[Dict[str, Any]]:
    roles_list = [r for r in (roles or []) if r]
    if not roles_list:
        return []
    async with AsyncSessionLocal() as s:
        stmt = (select(User)
                .where(User.role.in_(roles_list))
                .order_by(User.created_at.desc())
                .limit(limit))
        return [_user_dict(u) for u in (await s.execute(stmt)).scalars().all()]


async def search_users(query: str, roles: Optional[Iterable[str]] = None,
                       limit: int = 25) -> List[Dict[str, Any]]:
    """Case-insensitive substring match on full_name OR email."""
    q = (query or "").strip()
    if not q:
        return []
    like = f"%{q}%"
    async with AsyncSessionLocal() as s:
        stmt = select(User).where(
            or_(func.lower(User.full_name).like(func.lower(like)),
                func.lower(User.email).like(func.lower(like)))
        )
        if roles:
            stmt = stmt.where(User.role.in_(list(roles)))
        stmt = stmt.limit(limit)
        return [_user_dict(u) for u in (await s.execute(stmt)).scalars().all()]


async def insert_user(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Mongo-shape insert. Accepts the fields the legacy routers pass."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            user = await users_repo.create_user(
                s,
                user_id=doc["id"],
                email=doc["email"],
                password_hash=doc.get("password_hash"),
                full_name=doc.get("full_name") or "",
                phone=doc.get("phone"),
                role=doc.get("role", "client"),
                is_active=doc.get("is_active", True),
                mfa_enabled=doc.get("mfa_enabled", False),
                mfa_secret=doc.get("mfa_secret"),
                mfa_bypass=doc.get("mfa_bypass", False),
                must_change_password=doc.get("must_change_password", False),
                onboarding_status=doc.get("onboarding_status"),
                temporary_password_expires_at=doc.get("temporary_password_expires_at"),
                session_version=doc.get("session_version", 1),
                auth_provider=doc.get("auth_provider"),
                picture_url=doc.get("picture_url"),
                created_at=doc.get("created_at"),
                last_login_at=doc.get("last_login_at"),
                password_changed_at=doc.get("password_changed_at"),
            )
            return user


async def update_user(user_id: str, fields: Dict[str, Any], *, inc: Optional[Dict[str, int]] = None) -> int:
    async with AsyncSessionLocal() as s:
        async with s.begin():
            n = 0
            if fields:
                n = await users_repo.update_fields(s, user_id, fields)
            if inc:
                for col, delta in inc.items():
                    if col == "session_version":
                        await users_repo.bump_session_version(s, user_id)
                        n = max(n, 1)
                    else:
                        # Generic increment (no other columns are used today).
                        column = getattr(User, col, None)
                        if column is not None:
                            r = await s.execute(
                                update(User).where(User.id == user_id).values({col: column + delta})
                            )
                            n = max(n, r.rowcount or 0)
            return n


async def delete_user(user_id: str) -> int:
    async with AsyncSessionLocal() as s:
        async with s.begin():
            r = await s.execute(delete(User).where(User.id == user_id))
            return r.rowcount or 0


# ------------------------------------------------------------------- clients #
async def find_client(*, client_id: Optional[str] = None,
                      user_id: Optional[str] = None,
                      email: Optional[str] = None) -> Optional[Dict[str, Any]]:
    async with AsyncSessionLocal() as s:
        stmt = select(Client)
        if client_id:
            stmt = stmt.where(Client.id == client_id)
        elif user_id:
            stmt = stmt.where(Client.user_id == user_id)
        elif email:
            stmt = stmt.where(func.lower(Client.email) == (email or "").strip().lower())
        else:
            return None
        row = (await s.execute(stmt)).scalar_one_or_none()
        if not row:
            return None
        return clients_repo._client_to_dict(row)


async def find_clients_by_ids(ids: Iterable[str]) -> List[Dict[str, Any]]:
    ids_list = [i for i in (ids or []) if i]
    if not ids_list:
        return []
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(Client).where(Client.id.in_(ids_list)))).scalars().all()
        return [clients_repo._client_to_dict(c) for c in rows]


async def list_clients(*, sort_desc: bool = True, limit: int = 500,
                        practitioner_id: Optional[str] = None,
                        assigned_only: bool = False) -> List[Dict[str, Any]]:
    async with AsyncSessionLocal() as s:
        stmt = select(Client)
        if assigned_only and practitioner_id:
            stmt = stmt.where(Client.assigned_practitioner_id == practitioner_id)
        order = Client.created_at.desc() if sort_desc else Client.created_at.asc()
        stmt = stmt.order_by(order).limit(limit)
        return [clients_repo._client_to_dict(c) for c in (await s.execute(stmt)).scalars().all()]


async def search_clients(query: str, limit: int = 25) -> List[Dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []
    like = f"%{q}%"
    async with AsyncSessionLocal() as s:
        stmt = select(Client).where(
            or_(
                func.lower(Client.full_name).like(func.lower(like)),
                func.lower(Client.email).like(func.lower(like)),
                Client.phone.like(like),
                func.lower(Client.mrn).like(func.lower(like)),
            )
        ).limit(limit)
        return [clients_repo._client_to_dict(c) for c in (await s.execute(stmt)).scalars().all()]


async def insert_client(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Insert a client using a Mongo-shape doc. Extra keys are ignored."""
    valid = {k: v for k, v in doc.items() if hasattr(Client, k)}
    valid.setdefault("intake_completed", False)
    valid.setdefault("created_at", datetime.now(timezone.utc))
    async with AsyncSessionLocal() as s:
        async with s.begin():
            row = Client(**valid)
            s.add(row)
            await s.flush()
            return clients_repo._client_to_dict(row)


async def update_client(client_id: str, fields: Dict[str, Any]) -> int:
    if not fields:
        return 0
    valid = {k: v for k, v in fields.items() if hasattr(Client, k)}
    async with AsyncSessionLocal() as s:
        async with s.begin():
            return await clients_repo.update_fields(s, client_id, valid)


async def delete_client(client_id: str) -> int:
    async with AsyncSessionLocal() as s:
        async with s.begin():
            return await clients_repo.delete_by_id(s, client_id)


async def count_clients(*, created_since: Optional[datetime] = None,
                         created_before: Optional[datetime] = None,
                         dob_regex: Optional[str] = None,
                         tags_any: Optional[Iterable[str]] = None,
                         ids: Optional[Iterable[str]] = None,
                         practitioner_id: Optional[str] = None) -> int:
    async with AsyncSessionLocal() as s:
        stmt = select(func.count(Client.id))
        conds = []
        if created_since is not None:
            conds.append(Client.created_at >= created_since)
        if created_before is not None:
            conds.append(Client.created_at < created_before)
        if dob_regex:
            conds.append(Client.dob.op("~")(dob_regex))
        if tags_any:
            tags_list = [t for t in tags_any if t]
            if tags_list:
                # tags stored as JSONB list; use JSONB ?| any operator.
                conds.append(Client.tags.op("?|")(tags_list))
        if ids is not None:
            ids_list = [i for i in ids if i]
            if not ids_list:
                return 0
            conds.append(Client.id.in_(ids_list))
        if practitioner_id:
            conds.append(Client.assigned_practitioner_id == practitioner_id)
        if conds:
            stmt = stmt.where(and_(*conds))
        return int((await s.execute(stmt)).scalar_one())


async def bulk_clear_marketing_consent(ids: Iterable[str]) -> int:
    ids_list = [i for i in (ids or []) if i]
    if not ids_list:
        return 0
    async with AsyncSessionLocal() as s:
        async with s.begin():
            r = await s.execute(
                update(Client).where(Client.id.in_(ids_list))
                .values(consent_marketing=False)
            )
            return r.rowcount or 0


async def list_clients_filtered_by_ids(*, include_ids: Optional[Iterable[str]] = None,
                                       exclude_ids: Optional[Iterable[str]] = None,
                                       limit: int = 5000) -> List[Dict[str, Any]]:
    """List clients optionally restricted to (or excluding) a set of ids.

    Emulates the `db.clients.find({"id": {"$in": [...]}})` and
    `{"$nin": [...]}` patterns used by campaign segmentation.
    """
    async with AsyncSessionLocal() as s:
        stmt = select(Client)
        if include_ids is not None:
            ids = [i for i in include_ids if i]
            if not ids:
                return []
            stmt = stmt.where(Client.id.in_(ids))
        if exclude_ids is not None:
            ids = [i for i in exclude_ids if i]
            if ids:
                stmt = stmt.where(~Client.id.in_(ids))
        stmt = stmt.limit(limit)
        return [clients_repo._client_to_dict(c) for c in (await s.execute(stmt)).scalars().all()]


async def find_client_by_id_projection_email(email: str) -> Optional[Dict[str, Any]]:
    return await find_client(email=email)


# ------------------------------------------------------------------- clients #
async def find_intake_by_client(client_id: str) -> Optional[Dict[str, Any]]:
    async with AsyncSessionLocal() as s:
        return await clients_repo.get_intake_for_client(s, client_id)


async def upsert_intake(*, intake_id: str, client_id: str, fields: Dict[str, Any]) -> None:
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await clients_repo.upsert_intake(s, intake_id=intake_id, client_id=client_id, fields=fields)


# ------------------------------------------------------- supplement sheets #
async def list_active_supplement_sheets(limit: int = 200) -> List[Dict[str, Any]]:
    async with AsyncSessionLocal() as s:
        return await supplements_repo.list_sheets(s, active_only=True, limit=limit)


async def find_supplement_sheet(sheet_id: str) -> Optional[Dict[str, Any]]:
    async with AsyncSessionLocal() as s:
        return await supplements_repo.get_sheet(s, sheet_id)


async def insert_supplement_sheet(doc: Dict[str, Any]) -> Dict[str, Any]:
    async with AsyncSessionLocal() as s:
        async with s.begin():
            return await supplements_repo.create_sheet(s, **doc)


async def deactivate_supplement_sheet(sheet_id: str) -> int:
    """Legacy `db.supplement_sheets.delete_one` maps to a soft-delete."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            return await supplements_repo.update_sheet(s, sheet_id, {"active": False})


# ------------------------------------------------ supplement assignments #
async def list_active_assignments_for_client(client_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    async with AsyncSessionLocal() as s:
        rows = await supplements_repo.list_active_for_client(s, client_id)
        return rows[:limit] if len(rows) > limit else rows


async def list_all_assignments_for_client(client_id: str) -> List[Dict[str, Any]]:
    async with AsyncSessionLocal() as s:
        stmt = (select(ClientSupplementAssignment)
                .where(ClientSupplementAssignment.client_id == client_id)
                .order_by(ClientSupplementAssignment.assigned_at.desc().nullslast()))
        rows = (await s.execute(stmt)).scalars().all()
        return [supplements_repo._assignment(a) for a in rows]


async def find_active_assignment(client_id: str, sheet_id: str) -> Optional[Dict[str, Any]]:
    async with AsyncSessionLocal() as s:
        stmt = select(ClientSupplementAssignment).where(
            ClientSupplementAssignment.client_id == client_id,
            ClientSupplementAssignment.sheet_id == sheet_id,
            ClientSupplementAssignment.active.is_(True),
        )
        row = (await s.execute(stmt)).scalar_one_or_none()
        if not row:
            return None
        return supplements_repo._assignment(row)


async def find_assignment(assignment_id: str) -> Optional[Dict[str, Any]]:
    async with AsyncSessionLocal() as s:
        row = (await s.execute(
            select(ClientSupplementAssignment).where(ClientSupplementAssignment.id == assignment_id)
        )).scalar_one_or_none()
        if not row:
            return None
        return supplements_repo._assignment(row)


async def insert_assignment(doc: Dict[str, Any]) -> Dict[str, Any]:
    async with AsyncSessionLocal() as s:
        async with s.begin():
            return await supplements_repo.create_assignment(s, **doc)


async def touch_assignment_reference(assignment_id: str, *, ts: datetime,
                                     note_id: Optional[str] = None) -> int:
    """Set last_referenced_at and append `note_id` to the JSONB note_ids array."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            row = (await s.execute(
                select(ClientSupplementAssignment)
                .where(ClientSupplementAssignment.id == assignment_id)
            )).scalar_one_or_none()
            if not row:
                return 0
            row.last_referenced_at = ts
            if note_id:
                existing = list(row.note_ids or [])
                if note_id not in existing:
                    existing.append(note_id)
                    row.note_ids = existing
            return 1


async def deactivate_assignment(assignment_id: str, *, by_id: str) -> int:
    async with AsyncSessionLocal() as s:
        async with s.begin():
            return await supplements_repo.deactivate(s, assignment_id, by_id=by_id)


# ---------------------------------------- portal_ops password reset tokens #
async def insert_portal_reset_token(*, token_id: str, user_id: str, token_hash: str,
                                     expires_at: datetime,
                                     email_hash: Optional[str] = None,
                                     ip: Optional[str] = None,
                                     purpose: Optional[str] = None) -> None:
    """Legacy `db.password_reset_tokens.insert_one` for portal_ops.
    The PG table stores only id/user_id/token_hash/expires_at/used_at/created_at;
    the extra Mongo-only fields (email_hash, ip, purpose) are ignored here as
    they were audit-only breadcrumbs, not referenced in queries.
    """
    async with AsyncSessionLocal() as s:
        async with s.begin():
            s.add(LegacyPasswordResetToken(
                id=token_id, user_id=user_id, token_hash=token_hash,
                expires_at=expires_at, created_at=datetime.now(timezone.utc),
            ))


async def find_latest_active_portal_reset(user_id: str) -> Optional[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as s:
        stmt = (select(LegacyPasswordResetToken)
                .where(LegacyPasswordResetToken.user_id == user_id,
                       LegacyPasswordResetToken.used_at.is_(None))
                .order_by(LegacyPasswordResetToken.created_at.desc())
                .limit(1))
        row = (await s.execute(stmt)).scalar_one_or_none()
        if not row:
            return None
        return {
            "id": row.id, "user_id": row.user_id, "token_hash": row.token_hash,
            "created_at": row.created_at,
            "expires_at": row.expires_at,
            "consumed_at": row.used_at,
            "purpose": "portal_invite",
        }


async def invalidate_portal_reset_tokens(user_id: str) -> int:
    """Mark all outstanding tokens as consumed. Returns rowcount."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            r = await s.execute(
                update(LegacyPasswordResetToken)
                .where(LegacyPasswordResetToken.user_id == user_id,
                       LegacyPasswordResetToken.used_at.is_(None))
                .values(used_at=now)
            )
            return r.rowcount or 0
