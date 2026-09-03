"""Marketing OS Phase 10 — Reputation + Local Growth intelligence.

Read-only intelligence layer. Privacy-minimized marketing domain only:
- no emr/patient/client/clinical foreign keys;
- NO review text (aggregate metrics + metadata only, never patient health info);
- provider-neutral, opaque external identifiers;
- FKs only to internal/marketing tables (auth_users, marketing_search_sites,
  and self Phase 10 tables).

No automatic listing/review writes anywhere; any external action stays human
approval gated elsewhere.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class _P10TS:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MarketingLocation(_P10TS, Base):
    __tablename__ = "marketing_locations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    site_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("marketing_search_sites.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(160), nullable=False, unique=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="active", index=True
    )
    # Business NAP (the practice's own listing data; not patient PHI).
    address_line: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    website_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    primary_category: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )
    hours: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )


class MarketingReputationSource(_P10TS, Base):
    __tablename__ = "marketing_reputation_sources"
    __table_args__ = (
        UniqueConstraint("location_id", "provider",
                         name="uq_marketing_reputation_sources"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    location_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("marketing_locations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # provider-neutral: google|yelp|bing|apple|facebook|healthgrades|other
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    external_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    listing_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, server_default=text("true")
    )
    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class MarketingReputationSnapshot(_P10TS, Base):
    __tablename__ = "marketing_reputation_snapshots"
    __table_args__ = (
        UniqueConstraint("source_id", "captured_date",
                         name="uq_marketing_reputation_snapshot"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    location_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("marketing_locations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    source_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_reputation_sources.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    captured_date: Mapped[date] = mapped_column(Date(), nullable=False, index=True)
    rating: Mapped[Optional[Decimal]] = mapped_column(Numeric(3, 2), nullable=True)
    review_count: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)
    reviews_last_30d: Mapped[Optional[int]] = mapped_column(
        Integer(), nullable=True
    )
    response_rate: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 4), nullable=True
    )
    avg_response_hours: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    unanswered_count: Mapped[Optional[int]] = mapped_column(
        Integer(), nullable=True
    )
    # Aggregates/metadata ONLY. Never store review text (may contain PHI).
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb")
    )


class MarketingLocalListingSnapshot(_P10TS, Base):
    __tablename__ = "marketing_local_listing_snapshots"
    __table_args__ = (
        UniqueConstraint("source_id", "captured_date",
                         name="uq_marketing_local_listing_snapshot"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    location_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("marketing_locations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    source_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_reputation_sources.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    captured_date: Mapped[date] = mapped_column(Date(), nullable=False, index=True)
    # published|missing|unclaimed|suspended|unknown
    listing_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="unknown"
    )
    name_matches: Mapped[Optional[bool]] = mapped_column(Boolean(), nullable=True)
    address_matches: Mapped[Optional[bool]] = mapped_column(Boolean(), nullable=True)
    phone_matches: Mapped[Optional[bool]] = mapped_column(Boolean(), nullable=True)
    category_matches: Mapped[Optional[bool]] = mapped_column(
        Boolean(), nullable=True
    )
    website_matches: Mapped[Optional[bool]] = mapped_column(
        Boolean(), nullable=True
    )
    hours_present: Mapped[Optional[bool]] = mapped_column(Boolean(), nullable=True)
    fields_present: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb")
    )


class MarketingLocalOpportunity(_P10TS, Base):
    __tablename__ = "marketing_local_opportunities"
    __table_args__ = (
        UniqueConstraint("location_id", "opportunity_key",
                         name="uq_marketing_local_opportunity"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    location_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("marketing_locations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    source_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("marketing_reputation_sources.id", ondelete="SET NULL"),
        nullable=True,
    )
    # deterministic idempotent key = opportunity_type[:provider]
    opportunity_key: Mapped[str] = mapped_column(String(160), nullable=False)
    opportunity_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    severity: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="medium"
    )
    priority: Mapped[int] = mapped_column(
        Integer(), nullable=False, server_default="0", index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="open", index=True
    )
    evidence: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
