"""PostgreSQL models for Phase 3 Search Intelligence (marketing-only, no PHI).

Competitors, keyword-gap snapshots, backlink snapshots, local rank snapshots.
Provider-neutral: metrics stay NULL when no provider supplied them.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class _TS:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())


class MarketingSearchCompetitor(_TS, Base):
    __tablename__ = "marketing_search_competitors"
    __table_args__ = (
        UniqueConstraint("site_id", "normalized_domain",
                         name="uq_marketing_competitor_scope"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    site_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("marketing_search_sites.id",
                               ondelete="CASCADE"), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_domain: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True)
    display_name: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, server_default="true", index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    last_analyzed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True)


class MarketingKeywordGapSnapshot(_TS, Base):
    __tablename__ = "marketing_keyword_gap_snapshots"
    __table_args__ = (
        UniqueConstraint("site_id", "competitor_id", "normalized_keyword",
                         "captured_date", "source",
                         name="uq_marketing_keyword_gap_scope"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    site_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("marketing_search_sites.id",
                               ondelete="CASCADE"), nullable=False, index=True)
    competitor_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("marketing_search_competitors.id",
                               ondelete="CASCADE"), nullable=True, index=True)
    keyword: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_keyword: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True)
    nms_position: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)
    nms_source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    competitor_position: Mapped[Optional[int]] = mapped_column(
        Integer(), nullable=True)
    competitor_source: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True)
    search_volume: Mapped[Optional[int]] = mapped_column(
        BigInteger(), nullable=True)
    keyword_difficulty: Mapped[Optional[int]] = mapped_column(
        Integer(), nullable=True)
    intent: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="unknown")
    opportunity: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="unknown", index=True)
    captured_date: Mapped[date] = mapped_column(
        Date(), nullable=False, index=True)
    source: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="unknown")


class MarketingBacklinkSnapshot(_TS, Base):
    __tablename__ = "marketing_backlink_snapshots"
    __table_args__ = (
        UniqueConstraint("site_id", "source_url", "target_url", "provider",
                         name="uq_marketing_backlink_scope"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    site_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("marketing_search_sites.id",
                               ondelete="CASCADE"), nullable=False, index=True)
    referring_domain: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True)
    source_url: Mapped[str] = mapped_column(Text(), nullable=False)
    target_url: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    anchor_text: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    first_seen: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
    last_seen: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="active", index=True)
    rel_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="unknown")
    authority: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(9, 3), nullable=True)
    provider: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="unknown")
    captured_date: Mapped[date] = mapped_column(
        Date(), nullable=False, index=True)


class MarketingLocalRankSnapshot(_TS, Base):
    __tablename__ = "marketing_local_rank_snapshots"
    __table_args__ = (
        UniqueConstraint("site_id", "location_id", "normalized_keyword",
                         "captured_date", "provider",
                         name="uq_marketing_local_rank_scope"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    site_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("marketing_search_sites.id",
                               ondelete="CASCADE"), nullable=False, index=True)
    location_id: Mapped[str] = mapped_column(String(64), nullable=False)
    location_name: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    target_service: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True)
    target_keyword: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_keyword: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True)
    local_rank: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)
    provider: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="unknown")
    captured_date: Mapped[date] = mapped_column(
        Date(), nullable=False, index=True)
