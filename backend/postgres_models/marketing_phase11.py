"""Marketing OS Phase 11 — Content + Social Intelligence (draft/planning only).

Privacy-minimized marketing domain only: no emr/patient/client/clinical FKs; no
PHI; provider-neutral. FKs only to internal/marketing tables (auth_users,
marketing_offers, marketing_funnels). Drafts/plans only — no autonomous publishing.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
    func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class _TS:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())


class MarketingContentTopic(_TS, Base):
    __tablename__ = "marketing_content_topics"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    topic: Mapped[str] = mapped_column(String(300), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True,
                                      index=True)
    target_keyword: Mapped[Optional[str]] = mapped_column(String(200),
                                                          nullable=True)
    search_intent: Mapped[Optional[str]] = mapped_column(String(32),
                                                         nullable=True)
    audience: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    funnel_stage: Mapped[Optional[str]] = mapped_column(String(32),
                                                        nullable=True)
    priority: Mapped[int] = mapped_column(Integer(), nullable=False,
                                          server_default="0", index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False,
                                        server_default="idea", index=True)
    source_refs: Mapped[dict] = mapped_column(JSONB, nullable=False,
        default=dict, server_default=text("'{}'::jsonb"))
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"))
    created_by: Mapped[Optional[str]] = mapped_column(String(64),
        ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True)


class MarketingContentBrief(_TS, Base):
    __tablename__ = "marketing_content_briefs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    topic_id: Mapped[Optional[str]] = mapped_column(String(64),
        ForeignKey("marketing_content_topics.id", ondelete="SET NULL"),
        nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    audience: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    funnel_stage: Mapped[Optional[str]] = mapped_column(String(32),
                                                        nullable=True)
    cta: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    campaign_theme: Mapped[Optional[str]] = mapped_column(String(200),
                                                          nullable=True)
    offer_id: Mapped[Optional[str]] = mapped_column(String(64),
        ForeignKey("marketing_offers.id", ondelete="SET NULL"), nullable=True)
    funnel_id: Mapped[Optional[str]] = mapped_column(String(64),
        ForeignKey("marketing_funnels.id", ondelete="SET NULL"), nullable=True)
    outline: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(String(24), nullable=False,
                                        server_default="planned", index=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(64),
        ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True)


class MarketingContentDraft(_TS, Base):
    __tablename__ = "marketing_content_drafts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    brief_id: Mapped[str] = mapped_column(String(64),
        ForeignKey("marketing_content_briefs.id", ondelete="CASCADE"),
        nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(24), nullable=False)
    # generic draft body
    headline: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    body: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    caption: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    cta: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    # TikTok / short-form specific fields
    hook: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    script: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    on_screen_text: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    shot_list: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"))
    generator: Mapped[str] = mapped_column(String(48), nullable=False,
                                           server_default="template")
    status: Mapped[str] = mapped_column(String(24), nullable=False,
                                        server_default="draft", index=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(64),
        ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True)


class MarketingSocialPlan(_TS, Base):
    __tablename__ = "marketing_social_plans"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    channel: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    campaign_theme: Mapped[Optional[str]] = mapped_column(String(200),
                                                          nullable=True)
    audience: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    cadence: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False,
                                        server_default="draft", index=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"))
    created_by: Mapped[Optional[str]] = mapped_column(String(64),
        ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True)


class MarketingContentCalendarItem(_TS, Base):
    __tablename__ = "marketing_content_calendar_items"
    __table_args__ = (
        UniqueConstraint("brief_id", name="uq_marketing_calendar_brief"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    brief_id: Mapped[Optional[str]] = mapped_column(String(64),
        ForeignKey("marketing_content_briefs.id", ondelete="SET NULL"),
        nullable=True, index=True)
    social_plan_id: Mapped[Optional[str]] = mapped_column(String(64),
        ForeignKey("marketing_social_plans.id", ondelete="SET NULL"),
        nullable=True)
    channel: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    planned_publish_at: Mapped[Optional[date]] = mapped_column(Date(),
        nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False,
                                        server_default="planned", index=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB,
        nullable=False, default=dict, server_default=text("'{}'::jsonb"))
