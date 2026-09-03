"""Pydantic contracts for the NMS public AI Concierge."""

from __future__ import annotations

from email_validator import EmailNotValidError, validate_email

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConciergeMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(
        ...,
        min_length=1,
        max_length=4000,
    )


class ConciergeChatRequest(BaseModel):
    """Future public-chat request contract.

    The public route is intentionally not enabled during the foundation
    step. This schema establishes the contract without exposing a route.
    """

    model_config = ConfigDict(extra="forbid")

    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
    )

    session_id: Optional[str] = Field(
        default=None,
        max_length=128,
    )

    page_url: Optional[str] = Field(
        default=None,
        max_length=2048,
    )

    page_title: Optional[str] = Field(
        default=None,
        max_length=300,
    )

    history: list[ConciergeMessage] = Field(
        default_factory=list,
        max_length=12,
    )


class ConciergeAppointmentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offered: bool = False
    inline_request_enabled: bool = False
    appointment_url: Optional[str] = None


class ConciergeChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    answer: str

    appointment_url: Optional[str] = None

    handoff_recommended: bool = False

    appointment_action: ConciergeAppointmentAction = Field(
        default_factory=ConciergeAppointmentAction,
    )

    source_pages: list[str] = Field(
        default_factory=list,
    )


class ConciergePublicAppointmentRequest(BaseModel):
    """Minimal non-clinical public appointment request."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    first_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
    )
    last_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
    )
    email: str = Field(
        ...,
        min_length=3,
        max_length=320,
    )
    phone: str = Field(
        ...,
        min_length=7,
        max_length=40,
    )

    returning: Optional[
        Literal["first", "returning"]
    ] = None

    # Browser sends an opaque ID. The server resolves it only against
    # active + concierge_public treatments.
    service_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )

    # Preferences only; never a booking confirmation.
    date: Optional[str] = Field(
        default=None,
        min_length=10,
        max_length=10,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    time: Optional[str] = Field(
        default=None,
        min_length=5,
        max_length=5,
        pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$",
    )

    confirmed: Literal[True]

    idempotency_key: str = Field(
        ...,
        min_length=16,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )

    @field_validator(
        "first_name",
        "last_name",
    )
    @classmethod
    def normalize_name(
        cls,
        value: str,
    ) -> str:
        value = " ".join(
            value.split()
        )

        if not value:
            raise ValueError(
                "name is required"
            )

        return value

    @field_validator("email")
    @classmethod
    def normalize_email(
        cls,
        value: str,
    ) -> str:
        try:
            result = validate_email(
                value,
                check_deliverability=False,
            )
        except EmailNotValidError as exc:
            raise ValueError(
                "invalid email"
            ) from exc

        return result.normalized.lower()

    @field_validator("phone")
    @classmethod
    def normalize_phone(
        cls,
        value: str,
    ) -> str:
        digits = "".join(
            ch
            for ch in value
            if ch.isdigit()
        )

        if (
            len(digits) == 11
            and digits.startswith("1")
        ):
            digits = digits[1:]

        if len(digits) != 10:
            raise ValueError(
                "invalid phone"
            )

        return (
            f"{digits[:3]}-"
            f"{digits[3:6]}-"
            f"{digits[6:]}"
        )

    @field_validator("date")
    @classmethod
    def validate_preferred_date(
        cls,
        value: Optional[str],
    ) -> Optional[str]:
        if value is None:
            return None

        from datetime import date

        try:
            parsed = date.fromisoformat(
                value
            )
        except ValueError as exc:
            raise ValueError(
                "invalid preferred date"
            ) from exc

        if parsed < date.today():
            raise ValueError(
                "preferred date cannot be in the past"
            )

        return parsed.isoformat()


class ConciergePublicAppointmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: Literal[True] = True
    request_id: str
    replayed: bool = False
