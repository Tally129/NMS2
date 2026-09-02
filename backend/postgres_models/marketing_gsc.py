"""PostgreSQL models for Google Search Console (read-only) metrics.

Marketing-only, non-PHI. Stores normalized first-party GSC Search Analytics
snapshots. No credentials/tokens are ever stored here.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class _TS:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MarketingGscSyncRun(_TS, Base):
    __tablename__ = "marketing_gsc_sync_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    site_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_search_sites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="completed", index=True
    )
    start_date: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
    rows_synced: Mapped[int] = mapped_column(
        Integer(), nullable=False, server_default="0"
    )
    source: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="google_search_console"
    )
    error: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )


class MarketingGscDailyMetric(_TS, Base):
    __tablename__ = "marketing_gsc_daily_metrics"

    __table_args__ = (
        UniqueConstraint(
            "site_id", "metric_date", "device", "country", "source",
            name="uq_marketing_gsc_daily_scope",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    site_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_search_sites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    metric_date: Mapped[date] = mapped_column(Date(), nullable=False, index=True)
    clicks: Mapped[int] = mapped_column(
        BigInteger(), nullable=False, server_default="0"
    )
    impressions: Mapped[int] = mapped_column(
        BigInteger(), nullable=False, server_default="0"
    )
    ctr: Mapped[Decimal] = mapped_column(
        Numeric(9, 6), nullable=False, server_default="0"
    )
    position: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(9, 3), nullable=True
    )
    device: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="all"
    )
    country: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="all"
    )
    source: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="google_search_console"
    )


class MarketingGscQueryMetric(_TS, Base):
    __tablename__ = "marketing_gsc_query_metrics"

    __table_args__ = (
        UniqueConstraint(
            "site_id", "captured_date", "normalized_query", "device",
            "country", "source",
            name="uq_marketing_gsc_query_scope",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    site_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_search_sites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    captured_date: Mapped[date] = mapped_column(
        Date(), nullable=False, index=True
    )
    query: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_query: Mapped[str] = mapped_column(
        String(512), nullable=False, index=True
    )
    clicks: Mapped[int] = mapped_column(
        BigInteger(), nullable=False, server_default="0"
    )
    impressions: Mapped[int] = mapped_column(
        BigInteger(), nullable=False, server_default="0"
    )
    ctr: Mapped[Decimal] = mapped_column(
        Numeric(9, 6), nullable=False, server_default="0"
    )
    position: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(9, 3), nullable=True
    )
    device: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="all"
    )
    country: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="all"
    )
    source: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="google_search_console"
    )


class MarketingGscPageMetric(_TS, Base):
    __tablename__ = "marketing_gsc_page_metrics"

    __table_args__ = (
        UniqueConstraint(
            "site_id", "captured_date", "page", "device", "country",
            "source",
            name="uq_marketing_gsc_page_scope",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    site_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_search_sites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    captured_date: Mapped[date] = mapped_column(
        Date(), nullable=False, index=True
    )
    page: Mapped[str] = mapped_column(Text(), nullable=False)
    clicks: Mapped[int] = mapped_column(
        BigInteger(), nullable=False, server_default="0"
    )
    impressions: Mapped[int] = mapped_column(
        BigInteger(), nullable=False, server_default="0"
    )
    ctr: Mapped[Decimal] = mapped_column(
        Numeric(9, 6), nullable=False, server_default="0"
    )
    position: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(9, 3), nullable=True
    )
    device: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="all"
    )
    country: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="all"
    )
    source: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="google_search_console"
    )
