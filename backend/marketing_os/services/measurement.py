"""
Marketing OS measurement foundation.

Rules:
- Marketing data must remain non-PHI.
- No patient identifiers are accepted.
- No external provider writes occur here.
- Conversion recording is intentionally separate from
  clinical/patient data.
- Attribution is deterministic and explainable.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping


# ---------------------------------------------------------
# PHI / sensitive-field boundary
# ---------------------------------------------------------

PROHIBITED_MARKETING_FIELDS = frozenset({
    "patient_id",
    "patient_name",
    "first_name",
    "last_name",
    "full_name",
    "email",
    "email_address",
    "phone",
    "phone_number",
    "mobile",
    "mobile_number",
    "address",
    "street_address",
    "date_of_birth",
    "dob",
    "birth_date",
    "ssn",
    "social_security_number",
    "medical_record_number",
    "mrn",
    "diagnosis",
    "diagnoses",
    "condition",
    "conditions",
    "medication",
    "medications",
    "prescription",
    "prescriptions",
    "treatment",
    "treatments",
    "clinical_note",
    "clinical_notes",
    "provider_note",
    "provider_notes",
})


class MarketingDataPolicyError(ValueError):
    """Raised when marketing payload violates data policy."""


def _normalized_key(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def find_prohibited_fields(
    value: Any,
    *,
    path: str = "",
) -> list[str]:
    """
    Recursively inspect dictionaries/lists for prohibited keys.

    Values are deliberately not logged or returned.
    """

    violations: list[str] = []

    if isinstance(value, Mapping):

        for raw_key, child in value.items():

            key = _normalized_key(raw_key)

            child_path = (
                f"{path}.{key}"
                if path
                else key
            )

            if key in PROHIBITED_MARKETING_FIELDS:
                violations.append(child_path)

            violations.extend(
                find_prohibited_fields(
                    child,
                    path=child_path,
                )
            )

    elif isinstance(value, (list, tuple)):

        for index, child in enumerate(value):

            child_path = (
                f"{path}[{index}]"
                if path
                else f"[{index}]"
            )

            violations.extend(
                find_prohibited_fields(
                    child,
                    path=child_path,
                )
            )

    return violations


def assert_non_phi_marketing_payload(
    payload: Mapping[str, Any],
) -> None:
    """
    Reject payloads containing prohibited healthcare or
    direct-contact identifier fields.
    """

    violations = find_prohibited_fields(payload)

    if violations:

        raise MarketingDataPolicyError(
            "Marketing payload contains prohibited fields: "
            + ", ".join(sorted(set(violations)))
        )


# ---------------------------------------------------------
# Conversion event normalization
# ---------------------------------------------------------

ALLOWED_EVENT_TYPES = frozenset({
    "page_view",
    "service_page_view",
    "cta_click",
    "appointment_intent",
    "lead_submit",
    "phone_click",
    "directions_click",
    "content_engagement",
    "conversion",
})


@dataclass(frozen=True)
class NormalizedConversion:
    event_type: str
    marketing_subject_id: str | None
    session_id: str | None
    external_click_id: str | None
    source: str | None
    medium: str | None
    campaign: str | None
    content: str | None
    term: str | None
    value: Decimal | None
    currency: str | None
    properties: dict[str, Any]


def normalize_conversion_payload(
    payload: Mapping[str, Any],
) -> NormalizedConversion:

    assert_non_phi_marketing_payload(payload)

    event_type = str(
        payload.get("event_type", "")
    ).strip().lower()

    if event_type not in ALLOWED_EVENT_TYPES:
        raise MarketingDataPolicyError(
            f"Unsupported marketing event_type: {event_type!r}"
        )

    raw_value = payload.get("value")

    value = (
        Decimal(str(raw_value))
        if raw_value is not None
        else None
    )

    currency = payload.get("currency")

    if currency is not None:
        currency = str(currency).strip().upper()

        if len(currency) != 3:
            raise MarketingDataPolicyError(
                "currency must be a 3-letter code"
            )

    properties = dict(
        payload.get("properties") or {}
    )

    assert_non_phi_marketing_payload(
        properties
    )

    def optional_text(name: str) -> str | None:
        raw = payload.get(name)

        if raw is None:
            return None

        text = str(raw).strip()

        return text or None

    return NormalizedConversion(
        event_type=event_type,
        marketing_subject_id=optional_text(
            "marketing_subject_id"
        ),
        session_id=optional_text("session_id"),
        external_click_id=optional_text(
            "external_click_id"
        ),
        source=optional_text("source"),
        medium=optional_text("medium"),
        campaign=optional_text("campaign"),
        content=optional_text("content"),
        term=optional_text("term"),
        value=value,
        currency=currency,
        properties=properties,
    )


# ---------------------------------------------------------
# Attribution
# ---------------------------------------------------------

@dataclass(frozen=True)
class AttributionResult:
    model: str
    provider: str | None
    external_campaign_id: str | None
    source: str | None
    medium: str | None
    credit: Decimal
    attributed_value: Decimal | None
    reason: str


def last_touch_attribution(
    conversion: NormalizedConversion,
    *,
    provider: str | None = None,
    external_campaign_id: str | None = None,
) -> AttributionResult:
    """
    Deterministic last-touch attribution.

    No network calls.
    No external writes.
    """

    return AttributionResult(
        model="last_touch",
        provider=provider,
        external_campaign_id=external_campaign_id,
        source=conversion.source,
        medium=conversion.medium,
        credit=Decimal("1"),
        attributed_value=conversion.value,
        reason=(
            "Conversion credited to the most recent "
            "captured marketing touch."
        ),
    )


# ---------------------------------------------------------
# Aggregate metric helpers
# ---------------------------------------------------------

def safe_rate(
    numerator: int | Decimal,
    denominator: int | Decimal,
) -> Decimal | None:

    denominator_decimal = Decimal(
        str(denominator)
    )

    if denominator_decimal == 0:
        return None

    return (
        Decimal(str(numerator))
        / denominator_decimal
    )


def derive_metric_rates(
    *,
    impressions: int,
    clicks: int,
    spend: Decimal,
    leads: int,
    conversions: int,
    conversion_value: Decimal,
) -> dict[str, Decimal | None]:

    return {
        "ctr": safe_rate(
            clicks,
            impressions,
        ),
        "cpc": (
            safe_rate(spend, clicks)
            if clicks
            else None
        ),
        "cpl": (
            safe_rate(spend, leads)
            if leads
            else None
        ),
        "conversion_rate": safe_rate(
            conversions,
            clicks,
        ),
        "roas": (
            safe_rate(
                conversion_value,
                spend,
            )
            if spend
            else None
        ),
    }
