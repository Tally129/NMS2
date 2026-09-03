"""Marketing OS Phase 12 — AI Marketing Director.

Advisory marketing intelligence only.

This domain contains deterministic marketing signals and generated executive
briefs. It contains no patient/client/clinical foreign keys and must not store
PHI. AI summaries, when used, are advisory wording layered on top of
deterministic evidence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class _TS:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class MarketingDirectorSignal(_TS, Base):
    """One deterministic, explainable Marketing Director signal."""

    __tablename__ = "marketing_director_signals"

    __table_args__ = (
        UniqueConstraint(
            "signal_key",
            "snapshot_key",
            name="uq_marketing_director_signal_snapshot",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    signal_key: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        index=True,
    )

    snapshot_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    category: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    source_phase: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )

    severity: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        index=True,
    )

    priority: Mapped[int] = mapped_column(
        Integer(),
        nullable=False,
        server_default="0",
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
    )

    summary: Mapped[Optional[str]] = mapped_column(
        Text(),
        nullable=True,
    )

    evidence: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    recommended_action: Mapped[Optional[str]] = mapped_column(
        Text(),
        nullable=True,
    )

    expected_impact: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
    )

    confidence: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
    )

    data_quality: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        server_default="open",
        index=True,
    )

    human_approval_required: Mapped[bool] = mapped_column(
        nullable=False,
        server_default=text("true"),
    )

    external_execution_allowed: Mapped[bool] = mapped_column(
        nullable=False,
        server_default=text("false"),
    )

    created_by: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey(
            "auth_users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )


class MarketingDirectorBrief(_TS, Base):
    """Persisted snapshot of an advisory Marketing Director brief."""

    __tablename__ = "marketing_director_briefs"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    snapshot_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        server_default="ready",
        index=True,
    )

    deterministic_summary: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    signal_summary: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    ai_summary: Mapped[Optional[str]] = mapped_column(
        Text(),
        nullable=True,
    )

    ai_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="not_requested",
    )

    source_counts: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    human_approval_required: Mapped[bool] = mapped_column(
        nullable=False,
        server_default=text("true"),
    )

    external_execution_allowed: Mapped[bool] = mapped_column(
        nullable=False,
        server_default=text("false"),
    )

    created_by: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey(
            "auth_users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
