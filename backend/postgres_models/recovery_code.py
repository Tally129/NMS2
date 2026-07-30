"""Recovery code model (Session 2c).

Single-use MFA fallback codes. Only cryptographic hashes are persisted;
plaintext is shown to the user exactly once at issuance. Marking a code
used is atomic (see repositories.recovery_codes.claim_by_hash) so
concurrent redemptions cannot double-consume the same code.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class RecoveryCode(Base):
    __tablename__ = "auth_recovery_codes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # sha256(uppercased_code) hex digest.
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now(),
    )
