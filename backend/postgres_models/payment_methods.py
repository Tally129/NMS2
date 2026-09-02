"""
Tokenized payment storage.

SECURITY BOUNDARY:
- Never store PAN/card number.
- Never store CVC/CVV.
- Never store Stripe client_secret.
- Never store payment processor secret keys.
- Never store PHI in processor identifiers/metadata.

Reusable payment credentials remain with the payment processor.
NMS stores only opaque provider IDs and display-safe card metadata.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .structured_rest import _Ph36Base


class PaymentCustomer(_Ph36Base, Base):
    __tablename__ = "emr_payment_customers"

    client_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "emr_clients.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        unique=True,
        index=True,
    )

    provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="stripe",
        index=True,
    )

    provider_customer_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class SavedPaymentMethod(_Ph36Base, Base):
    __tablename__ = "emr_saved_payment_methods"

    client_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "emr_clients.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="stripe",
        index=True,
    )

    provider_payment_method_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )

    payment_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="card",
    )

    brand: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
    )

    last4: Mapped[Optional[str]] = mapped_column(
        String(4),
        nullable=True,
    )

    exp_month: Mapped[Optional[str]] = mapped_column(
        String(2),
        nullable=True,
    )

    exp_year: Mapped[Optional[str]] = mapped_column(
        String(4),
        nullable=True,
    )

    is_default: Mapped[Optional[bool]] = mapped_column(
        nullable=True,
        default=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
