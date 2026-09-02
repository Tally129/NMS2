from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from postgres_models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


class PaymentTerminal(Base):
    __tablename__ = "payment_terminals"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=_uuid,
    )

    provider: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    provider_device_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    display_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    location_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )

    connection_type: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    # "configured" describes NMS configuration.
    # It does NOT mean the physical terminal is online.
    configured: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    # Last normalized provider-reported connection state.
    status: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="unknown",
    )

    capabilities: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )

    # SAFE metadata only.
    # Never PAN/CVV/PIN/track/bank credentials.
    metadata_json: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
    )

    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_by: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    updated_by: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        onupdate=_now,
    )

    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_device_id",
            name="uq_payment_terminal_provider_device",
        ),
        Index(
            "ix_payment_terminals_active",
            "enabled",
            "archived_at",
        ),
        Index(
            "ix_payment_terminals_location_provider",
            "location_id",
            "provider",
        ),
    )


class TerminalPaymentAttempt(Base):
    __tablename__ = "terminal_payment_attempts"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=_uuid,
    )

    transaction_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    terminal_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    provider: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    provider_request_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    provider_transaction_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    amount_cents: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default="USD",
    )

    status: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="created",
        index=True,
    )

    card_brand: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    # Display-only masked identifier.
    last4: Mapped[str | None] = mapped_column(
        String(4),
        nullable=True,
    )

    failure_code: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    failure_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Provider payload after explicit safe-field filtering.
    safe_response: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )

    created_by: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        onupdate=_now,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index(
            "ix_terminal_attempt_transaction_status",
            "transaction_id",
            "status",
        ),
    )
