"""Typed PostgreSQL models for Marketing OS Search Intelligence.

Search Intelligence is MARKETING-ONLY. These tables must never store PHI
or patient/contact identifiers (names, emails, phones, MRNs, diagnoses,
medications, chart data). See marketing_os.services.measurement for the
enforced non-PHI boundary applied on write paths.

No external provider writes, publishing, or crawling-at-scale is performed
by these models. They store first-party, read-only search diagnostics.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class _SearchTimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class MarketingSearchSite(_SearchTimestampMixin, Base):
    __tablename__ = "marketing_search_sites"

    __table_args__ = (
        UniqueConstraint(
            "normalized_url",
            name="uq_marketing_search_sites_normalized_url",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    site_url: Mapped[str] = mapped_column(String(512), nullable=False)

    normalized_url: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        index=True,
    )

    label: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean(),
        nullable=False,
        server_default="true",
    )

    created_by: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )


class MarketingSearchKeyword(_SearchTimestampMixin, Base):
    __tablename__ = "marketing_search_keywords"

    __table_args__ = (
        UniqueConstraint(
            "site_id",
            "normalized_keyword",
            "location",
            "device",
            name="uq_marketing_search_keyword_scope",
        ),
        CheckConstraint(
            "keyword_difficulty IS NULL OR "
            "(keyword_difficulty >= 0 AND keyword_difficulty <= 100)",
            name="ck_marketing_search_keyword_difficulty",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    site_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_search_sites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    keyword: Mapped[str] = mapped_column(String(255), nullable=False)

    normalized_keyword: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    intent: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="unknown",
        index=True,
    )

    search_volume: Mapped[Optional[int]] = mapped_column(
        BigInteger(),
        nullable=True,
    )

    keyword_difficulty: Mapped[Optional[int]] = mapped_column(
        Integer(),
        nullable=True,
    )

    cpc: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    location: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        server_default="global",
    )

    device: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="desktop",
    )

    source: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default="manual",
        index=True,
    )

    is_tracked: Mapped[bool] = mapped_column(
        Boolean(),
        nullable=False,
        server_default="true",
        index=True,
    )

    created_by: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )


class MarketingKeywordRankSnapshot(_SearchTimestampMixin, Base):
    __tablename__ = "marketing_keyword_rank_snapshots"

    __table_args__ = (
        UniqueConstraint(
            "keyword_id",
            "captured_date",
            "source",
            name="uq_marketing_keyword_rank_snapshot_scope",
        ),
        CheckConstraint(
            "current_rank IS NULL OR current_rank >= 1",
            name="ck_marketing_keyword_rank_positive",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    keyword_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_search_keywords.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    current_rank: Mapped[Optional[int]] = mapped_column(
        Integer(),
        nullable=True,
    )

    ranking_url: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)

    serp_features: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )

    source: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default="manual",
    )

    captured_date: Mapped[date] = mapped_column(
        Date(),
        nullable=False,
        index=True,
    )


class MarketingSiteAuditRun(_SearchTimestampMixin, Base):
    __tablename__ = "marketing_site_audit_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    site_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_search_sites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="completed",
        index=True,
    )

    pages_scanned: Mapped[int] = mapped_column(
        Integer(),
        nullable=False,
        server_default="0",
    )

    issues_total: Mapped[int] = mapped_column(
        Integer(),
        nullable=False,
        server_default="0",
    )

    critical_count: Mapped[int] = mapped_column(
        Integer(),
        nullable=False,
        server_default="0",
    )

    warning_count: Mapped[int] = mapped_column(
        Integer(),
        nullable=False,
        server_default="0",
    )

    opportunity_count: Mapped[int] = mapped_column(
        Integer(),
        nullable=False,
        server_default="0",
    )

    informational_count: Mapped[int] = mapped_column(
        Integer(),
        nullable=False,
        server_default="0",
    )

    summary: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_by: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )


class MarketingSiteAuditIssue(_SearchTimestampMixin, Base):
    __tablename__ = "marketing_site_audit_issues"

    __table_args__ = (
        CheckConstraint(
            "severity IN "
            "('critical', 'warning', 'opportunity', 'informational')",
            name="ck_marketing_site_audit_issue_severity",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_site_audit_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    severity: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )

    category: Mapped[str] = mapped_column(String(64), nullable=False)

    issue_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    url: Mapped[str] = mapped_column(Text(), nullable=False)

    description: Mapped[str] = mapped_column(Text(), nullable=False)

    recommended_action: Mapped[str] = mapped_column(Text(), nullable=False)

    details: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
