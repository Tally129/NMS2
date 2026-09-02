"""User + Client repository. Returns dicts to keep downstream callers
compatible with the pre-migration Mongo shape."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from postgres_models import Client, User


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def user_to_dict(u: User) -> Dict[str, Any]:
    """Shape identical to what Motor returned before the migration."""
    return {
        "id": u.id,
        "email": u.email,
        "password_hash": u.password_hash,
        "full_name": u.full_name,
        "phone": u.phone,
        "role": u.role,
        "is_active": u.is_active,
        "mfa_enabled": u.mfa_enabled,
        "mfa_secret": u.mfa_secret,
        "mfa_bypass": u.mfa_bypass,
        "must_change_password": u.must_change_password,
        "onboarding_status": u.onboarding_status,
        "temporary_password_expires_at": u.temporary_password_expires_at,
        "session_version": u.session_version,
        "auth_provider": u.auth_provider,
        "picture_url": u.picture_url,
        "created_at": u.created_at,
        "last_login_at": u.last_login_at,
        "password_changed_at": u.password_changed_at,
    }


def client_to_dict(c: Client) -> Dict[str, Any]:
    return {
        "id": c.id,
        "user_id": c.user_id,
        "full_name": c.full_name,
        "email": c.email,
        "phone": c.phone,
        "intake_completed": c.intake_completed,
        "created_at": c.created_at,
    }


async def get_by_id(session: AsyncSession, user_id: str) -> Optional[Dict[str, Any]]:
    row = await session.get(User, user_id)
    return user_to_dict(row) if row else None


async def get_by_email(session: AsyncSession, email: str) -> Optional[Dict[str, Any]]:
    stmt = select(User).where(func.lower(User.email) == _normalize_email(email))
    row = (await session.execute(stmt)).scalar_one_or_none()
    return user_to_dict(row) if row else None


async def create_user(session: AsyncSession, *, user_id: str, email: str,
                      password_hash: Optional[str], full_name: str = "",
                      phone: Optional[str] = None, role: str = "client",
                      is_active: bool = True, mfa_enabled: bool = False,
                      mfa_secret: Optional[str] = None,
                      mfa_bypass: bool = False, must_change_password: bool = False,
                      onboarding_status: Optional[str] = None,
                      temporary_password_expires_at: Optional[datetime] = None,
                      session_version: int = 1,
                      auth_provider: Optional[str] = None,
                      picture_url: Optional[str] = None,
                      created_at: Optional[datetime] = None,
                      last_login_at: Optional[datetime] = None,
                      password_changed_at: Optional[datetime] = None) -> Dict[str, Any]:
    user = User(
        id=user_id, email=_normalize_email(email),
        password_hash=password_hash, full_name=full_name or "",
        phone=phone, role=role, is_active=is_active,
        mfa_enabled=mfa_enabled, mfa_secret=mfa_secret, mfa_bypass=mfa_bypass,
        must_change_password=must_change_password,
        onboarding_status=onboarding_status,
        temporary_password_expires_at=temporary_password_expires_at,
        session_version=session_version, auth_provider=auth_provider,
        picture_url=picture_url,
        created_at=created_at or datetime.now(timezone.utc),
        last_login_at=last_login_at,
        password_changed_at=password_changed_at,
    )
    session.add(user)
    await session.flush()
    return user_to_dict(user)


async def update_fields(session: AsyncSession, user_id: str, fields: Dict[str, Any]) -> int:
    """Partial UPDATE. Callers pass only the columns they mean to change."""
    if not fields:
        return 0
    result = await session.execute(
        update(User).where(User.id == user_id).values(**fields),
    )
    return result.rowcount or 0


async def bump_session_version(session: AsyncSession, user_id: str) -> None:
    """Increment `session_version` atomically at the row level."""
    await session.execute(
        update(User)
        .where(User.id == user_id)
        .values(session_version=User.session_version + 1),
    )


async def touch_last_login(session: AsyncSession, user_id: str) -> None:
    await session.execute(
        update(User).where(User.id == user_id)
        .values(last_login_at=datetime.now(timezone.utc)),
    )



async def list_recent(session: AsyncSession, *, limit: int = 200) -> List[Dict[str, Any]]:
    """List users newest-first — used by the admin user directory."""
    stmt = select(User).order_by(User.created_at.desc()).limit(min(max(1, limit), 5000))
    return [user_to_dict(u) for u in (await session.execute(stmt)).scalars().all()]


# ---------- Client ---------- #

async def get_client_by_user(session: AsyncSession, user_id: str) -> Optional[Dict[str, Any]]:
    stmt = select(Client).where(Client.user_id == user_id)
    row = (await session.execute(stmt)).scalar_one_or_none()
    return client_to_dict(row) if row else None


async def create_client(session: AsyncSession, *, client_id: str, user_id: str,
                        full_name: str, email: str, phone: Optional[str] = None,
                        intake_completed: bool = False) -> Dict[str, Any]:
    c = Client(
        id=client_id, user_id=user_id, full_name=full_name,
        email=_normalize_email(email), phone=phone,
        intake_completed=intake_completed,
        created_at=datetime.now(timezone.utc),
    )
    session.add(c)
    await session.flush()
    return client_to_dict(c)
