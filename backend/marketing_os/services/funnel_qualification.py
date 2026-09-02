"""Deterministic Marketing OS Phase 7 qualification + offer matching.

This module:
- performs no DB writes;
- performs no network calls;
- performs no outreach;
- performs no advertising-provider actions;
- accepts marketing-safe qualification fields only;
- rejects PHI/contact-detail payloads;
- never uses AI to decide qualification or offer assignment.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from marketing_os.services.lead_pipeline import priority_from_score
from marketing_os.services.measurement import (
    MarketingDataPolicyError,
    assert_non_phi_marketing_payload,
)


ALLOWED_QUALIFICATION_FIELDS: frozenset[str] = frozenset({
    "service_interest",
    "urgency",
    "preferred_location",
    "preferred_contact_window",
    "appointment_readiness",
    "timeline",
    "contact_consent",
})

LEAD_PATCH_FIELDS: frozenset[str] = frozenset({
    "service_interest",
    "urgency",
    "preferred_location",
    "preferred_contact_window",
    "appointment_readiness",
})

SUPPORTED_RULE_OPERATORS: frozenset[str] = frozenset({
    "equals",
    "in",
    "truthy",
})

QUALIFICATION_STATUSES: tuple[str, ...] = (
    "unqualified",
    "in_review",
    "qualified",
)


class QualificationRuleError(ValueError):
    """Raised when deterministic scoring configuration is malformed."""


def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value).strip() or None
    return value.strip() or None


def normalize_qualification_answers(
    answers: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and normalize one marketing-safe qualification submission."""

    if not isinstance(answers, Mapping):
        raise MarketingDataPolicyError(
            "qualification answers must be an object"
        )

    raw = dict(answers)

    unknown = sorted(set(raw) - ALLOWED_QUALIFICATION_FIELDS)
    if unknown:
        raise MarketingDataPolicyError(
            "unsupported qualification fields: "
            + ", ".join(unknown)
        )

    # Reuse the authoritative Marketing OS PHI/contact-data guard.
    assert_non_phi_marketing_payload(raw)

    normalized: dict[str, Any] = {}

    for field in ALLOWED_QUALIFICATION_FIELDS:
        if field not in raw:
            continue

        value = raw[field]

        if field == "contact_consent":
            if not isinstance(value, bool):
                raise MarketingDataPolicyError(
                    "contact_consent must be boolean"
                )
            normalized[field] = value
            continue

        cleaned = _clean_text(value)
        if cleaned is not None:
            normalized[field] = cleaned

    return normalized


def _rule_matches(
    answers: Mapping[str, Any],
    rule: Mapping[str, Any],
) -> bool:
    field = str(rule.get("field") or "").strip()
    operator = str(rule.get("operator") or "").strip().lower()

    if not field or field not in ALLOWED_QUALIFICATION_FIELDS:
        raise QualificationRuleError(
            f"unsupported scoring field: {field!r}"
        )

    if operator not in SUPPORTED_RULE_OPERATORS:
        raise QualificationRuleError(
            f"unsupported scoring operator: {operator!r}"
        )

    actual = answers.get(field)

    if operator == "truthy":
        return bool(actual)

    if operator == "equals":
        expected = rule.get("value")

        if isinstance(actual, str) and isinstance(expected, str):
            return actual.strip().lower() == expected.strip().lower()

        return actual == expected

    expected_values = rule.get("values")

    if not isinstance(expected_values, list):
        raise QualificationRuleError(
            "'in' scoring rule requires a values list"
        )

    if isinstance(actual, str):
        actual_normalized = actual.strip().lower()
        return any(
            isinstance(item, str)
            and item.strip().lower() == actual_normalized
            for item in expected_values
        )

    return actual in expected_values


def score_qualification(
    answers: Mapping[str, Any],
    rules: Iterable[Mapping[str, Any]],
) -> int:
    """Return deterministic 0..100 score from explicit scoring rules."""

    normalized = normalize_qualification_answers(answers)

    total = 0

    for rule in rules:
        if not isinstance(rule, Mapping):
            raise QualificationRuleError(
                "each scoring rule must be an object"
            )

        points = rule.get("points", 0)

        if isinstance(points, bool) or not isinstance(
            points, (int, float)
        ):
            raise QualificationRuleError(
                "scoring rule points must be numeric"
            )

        if _rule_matches(normalized, rule):
            total += int(points)

    return max(0, min(100, total))


def qualification_status_from_score(
    score: int,
    *,
    qualify_at: int = 70,
    review_at: int = 40,
) -> str:
    """Map a deterministic score to existing Marketing Lead qualification."""

    if not 0 <= review_at <= qualify_at <= 100:
        raise QualificationRuleError(
            "thresholds must satisfy 0 <= review_at <= qualify_at <= 100"
        )

    if score >= qualify_at:
        return "qualified"

    if score >= review_at:
        return "in_review"

    return "unqualified"


def match_offer(
    answers: Mapping[str, Any],
    score: int,
    offers: Iterable[Mapping[str, Any]],
) -> Optional[dict[str, Any]]:
    """Return the best deterministic active offer match, or None."""

    normalized = normalize_qualification_answers(answers)

    service_interest = _clean_text(
        normalized.get("service_interest")
    )
    preferred_location = _clean_text(
        normalized.get("preferred_location")
    )

    candidates: list[dict[str, Any]] = []

    for raw_offer in offers:
        offer = dict(raw_offer)

        if str(offer.get("status") or "").strip().lower() != "active":
            continue

        offer_id = _clean_text(offer.get("id"))
        if not offer_id:
            continue

        minimum = offer.get("min_qualification_score", 0)

        if isinstance(minimum, bool) or not isinstance(minimum, int):
            raise QualificationRuleError(
                "offer min_qualification_score must be an integer"
            )

        if score < minimum:
            continue

        required_service = _clean_text(
            offer.get("service_interest")
        )

        if required_service:
            if not service_interest:
                continue
            if required_service.lower() != service_interest.lower():
                continue

        locations = offer.get("eligible_locations") or []

        if not isinstance(locations, list):
            raise QualificationRuleError(
                "offer eligible_locations must be a list"
            )

        if locations:
            if not preferred_location:
                continue

            allowed = {
                str(location).strip().lower()
                for location in locations
                if str(location).strip()
            }

            if preferred_location.lower() not in allowed:
                continue

        offer["id"] = offer_id
        offer["_match_minimum"] = minimum
        candidates.append(offer)

    if not candidates:
        return None

    # Highest qualifying threshold wins; ID makes tie behavior stable.
    candidates.sort(
        key=lambda offer: (
            -int(offer["_match_minimum"]),
            str(offer["id"]),
        )
    )

    winner = dict(candidates[0])
    winner.pop("_match_minimum", None)
    return winner


def evaluate_qualification(
    *,
    answers: Mapping[str, Any],
    scoring_rules: Iterable[Mapping[str, Any]],
    offers: Iterable[Mapping[str, Any]],
    qualify_at: int = 70,
    review_at: int = 40,
) -> dict[str, Any]:
    """Evaluate one marketing-safe submission and build Lead CRM patch data."""

    normalized = normalize_qualification_answers(answers)

    score = score_qualification(
        normalized,
        scoring_rules,
    )

    status = qualification_status_from_score(
        score,
        qualify_at=qualify_at,
        review_at=review_at,
    )

    offer = match_offer(
        normalized,
        score,
        offers,
    )

    lead_patch = {
        field: normalized[field]
        for field in LEAD_PATCH_FIELDS
        if field in normalized
    }

    lead_patch.update({
        "qualification_score": score,
        "qualification_status": status,
        "priority": priority_from_score(score),
    })

    if offer is not None:
        lead_patch["offer_id"] = offer["id"]

    return {
        "qualification_score": score,
        "qualification_status": status,
        "matched_offer_id": (
            offer["id"] if offer is not None else None
        ),
        "normalized_fields": normalized,
        "lead_patch": lead_patch,
    }
