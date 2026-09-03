"""Deterministic Marketing OS Phase 10 reputation + local-growth logic (pure).

No DB, no network, no AI, no PHI, no review text. All scores and opportunity
priorities are derived from explicit inputs so results are explainable and
reproducible. AI may later summarize these outputs but must not generate them.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional

from marketing_os.services.measurement import (
    MarketingDataPolicyError,
    assert_non_phi_marketing_payload,
)

KNOWN_PROVIDERS = (
    "google", "yelp", "bing", "apple", "facebook", "healthgrades", "other",
)
# Providers we expect a healthy multi-location practice to cover.
EXPECTED_CORE_PROVIDERS = ("google", "yelp", "bing", "apple")

LISTING_STATUSES = ("published", "missing", "unclaimed", "suspended", "unknown")
LOCATION_STATUSES = ("active", "inactive")

OPPORTUNITY_TYPES = (
    "incomplete_profile", "missing_hours", "nap_inconsistent",
    "low_review_velocity", "weak_response_rate", "missing_directory",
    "local_ranking_gap",
)
SEVERITIES = ("low", "medium", "high")

# Documented deterministic thresholds.
LOW_REVIEW_VELOCITY = 2          # reviews / 30d below this = low
WEAK_RESPONSE_RATE = 0.5         # response_rate below this = weak
LOCAL_RANK_GAP_THRESHOLD = 3     # best local_rank worse than this = gap

MAX_NAME_LEN = 200
MAX_SLUG_LEN = 160
MAX_JSON_CHARS = 20000
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-_]{0,159}$")
_PROFILE_FIELDS = (
    "name", "address", "phone", "website", "hours", "primary_category",
    "description", "photos",
)


class LocalConfigError(ValueError):
    """Raised when local-growth configuration is malformed (fail-closed)."""


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _req_str(v: Any, field: str, *, max_len: int, min_len: int = 1) -> str:
    if not isinstance(v, str):
        raise LocalConfigError(f"{field} must be a string")
    c = v.strip()
    if len(c) < min_len:
        raise LocalConfigError(f"{field} must not be empty")
    if len(c) > max_len:
        raise LocalConfigError(f"{field} exceeds max length {max_len}")
    return c


def validate_slug(v: Any) -> str:
    c = _req_str(v, "slug", max_len=MAX_SLUG_LEN)
    if not _SLUG_RE.match(c):
        raise LocalConfigError("slug must be lowercase alphanumeric with - or _")
    return c


def bounded_json(v: Any, field: str) -> dict:
    if v is None:
        return {}
    if not isinstance(v, Mapping):
        raise LocalConfigError(f"{field} must be an object")
    payload = dict(v)
    assert_non_phi_marketing_payload(payload)
    try:
        s = json.dumps(payload)
    except (TypeError, ValueError) as exc:
        raise LocalConfigError(f"{field} must be JSON-serializable") from exc
    if len(s) > MAX_JSON_CHARS:
        raise LocalConfigError(f"{field} exceeds max size")
    return payload


def validate_fields_present(v: Any) -> dict:
    """Presence-map of known profile fields only (booleans). No PHI-key guard.

    Restricts keys to the fixed profile-field vocabulary so field NAMES like
    'address'/'phone' (not values) don't trip the marketing PHI key guard.
    """
    if v is None:
        return {}
    if not isinstance(v, Mapping):
        raise LocalConfigError("fields_present must be an object")
    out: dict[str, bool] = {}
    for key, val in v.items():
        k = str(key).strip().lower()
        if k not in _PROFILE_FIELDS:
            raise LocalConfigError(f"unknown profile field: {key!r}")
        out[k] = bool(val)
    return out


def validate_provider(v: Any) -> str:
    if not isinstance(v, str) or not v.strip():
        raise LocalConfigError("provider is required")
    p = v.strip().lower()
    if p not in KNOWN_PROVIDERS:
        raise LocalConfigError(f"unsupported provider: {v!r}")
    return p


# --------------------------------------------------------------------------- #
# Deterministic scores
# --------------------------------------------------------------------------- #

def listing_completeness_score(fields_present: Mapping[str, Any]) -> float:
    """Fraction (0..1) of expected profile fields present."""
    if not isinstance(fields_present, Mapping):
        return 0.0
    present = sum(1 for f in _PROFILE_FIELDS if bool(fields_present.get(f)))
    return round(present / len(_PROFILE_FIELDS), 4)


def nap_consistency_score(listing: Mapping[str, Any]) -> float:
    """Fraction (0..1) of NAP+key fields that match the canonical location."""
    checks = [
        "name_matches", "address_matches", "phone_matches",
        "category_matches", "website_matches",
    ]
    vals = [listing.get(c) for c in checks]
    known = [v for v in vals if v is not None]
    if not known:
        return 0.0
    return round(sum(1 for v in known if v) / len(known), 4)


def reputation_trend(current_rating: Any, previous_rating: Any,
                     current_reviews: Any = None,
                     previous_reviews: Any = None) -> dict[str, Any]:
    """Deterministic trend from consecutive snapshots."""
    cr, pr = _num(current_rating), _num(previous_rating)
    rating_delta = None
    direction = "flat"
    if cr is not None and pr is not None:
        rating_delta = round(cr - pr, 3)
        if rating_delta > 0.05:
            direction = "up"
        elif rating_delta < -0.05:
            direction = "down"
    review_delta = None
    ccount, pcount = _num(current_reviews), _num(previous_reviews)
    if ccount is not None and pcount is not None:
        review_delta = int(ccount - pcount)
    return {
        "direction": direction,
        "rating_delta": rating_delta,
        "review_delta": review_delta,
    }


def classify_review_velocity(reviews_last_30d: Any) -> str:
    n = _num(reviews_last_30d)
    if n is None:
        return "unknown"
    if n < LOW_REVIEW_VELOCITY:
        return "low"
    if n < 8:
        return "medium"
    return "high"


def source_coverage(active_providers: Iterable[str],
                    expected: Iterable[str] = EXPECTED_CORE_PROVIDERS
                    ) -> dict[str, Any]:
    active = {str(p).strip().lower() for p in active_providers}
    exp = [str(p).strip().lower() for p in expected]
    covered = [p for p in exp if p in active]
    missing = [p for p in exp if p not in active]
    return {
        "coverage": round(len(covered) / len(exp), 4) if exp else 0.0,
        "covered": covered,
        "missing": missing,
    }


def location_health_score(*, completeness: float, nap: float,
                          rating: Any, review_velocity_class: str,
                          response_rate: Any) -> int:
    """Deterministic weighted 0..100 health score (documented weights)."""
    rating_norm = min(max((_num(rating) or 0.0) / 5.0, 0.0), 1.0)
    velocity_norm = {"low": 0.2, "medium": 0.6, "high": 1.0,
                     "unknown": 0.0}[review_velocity_class]
    rr = _num(response_rate)
    rr_norm = min(max(rr, 0.0), 1.0) if rr is not None else 0.0
    score = (
        completeness * 25.0 + nap * 25.0 + rating_norm * 20.0
        + velocity_norm * 15.0 + rr_norm * 15.0
    )
    return int(round(min(max(score, 0.0), 100.0)))


# --------------------------------------------------------------------------- #
# Deterministic opportunities
# --------------------------------------------------------------------------- #

def _opp(otype, severity, priority, title, detail, evidence, provider=None):
    key = otype if provider is None else f"{otype}:{provider}"
    return {
        "opportunity_key": key, "opportunity_type": otype,
        "severity": severity, "priority": priority, "title": title,
        "detail": detail, "evidence": evidence,
    }


def build_opportunities(*, location: Mapping[str, Any],
                        active_providers: Iterable[str],
                        latest_reputation: Mapping[str, Mapping[str, Any]],
                        latest_listing: Mapping[str, Mapping[str, Any]],
                        best_local_rank: Optional[int] = None
                        ) -> list[dict[str, Any]]:
    """Deterministic, explainable local-growth opportunities (advisory)."""
    opps: list[dict[str, Any]] = []

    # Missing hours on the canonical location.
    if not (location.get("hours") or {}):
        opps.append(_opp(
            "missing_hours", "medium", 60, "Business hours are missing",
            "Add opening hours to improve local listing completeness.",
            {"field": "hours"}))

    # Source coverage / missing directories.
    cov = source_coverage(active_providers)
    for provider in cov["missing"]:
        opps.append(_opp(
            "missing_directory", "medium", 55,
            f"No {provider} listing tracked",
            f"Add and monitor a {provider} listing to expand local presence.",
            {"provider": provider}, provider=provider))

    # Per-source listing + reputation opportunities.
    for provider, listing in (latest_listing or {}).items():
        completeness = listing_completeness_score(
            listing.get("fields_present") or {})
        nap = nap_consistency_score(listing)
        if listing.get("listing_status") in ("missing", "unclaimed",
                                              "suspended"):
            opps.append(_opp(
                "incomplete_profile", "high", 80,
                f"{provider} listing is {listing.get('listing_status')}",
                "Claim/complete this listing to appear in local search.",
                {"provider": provider,
                 "listing_status": listing.get("listing_status")},
                provider=provider))
        elif completeness < 0.75:
            opps.append(_opp(
                "incomplete_profile", "medium", 50,
                f"{provider} profile is incomplete",
                "Fill in missing profile fields to improve completeness.",
                {"provider": provider, "completeness": completeness},
                provider=provider))
        if nap < 1.0 and nap > 0.0:
            opps.append(_opp(
                "nap_inconsistent", "high", 75,
                f"NAP inconsistency on {provider}",
                "Align name/address/phone/website with the canonical record.",
                {"provider": provider, "nap_consistency": nap},
                provider=provider))

    for provider, rep in (latest_reputation or {}).items():
        if classify_review_velocity(rep.get("reviews_last_30d")) == "low":
            opps.append(_opp(
                "low_review_velocity", "medium", 45,
                f"Low review velocity on {provider}",
                "Request reviews from recent satisfied contacts (approval "
                "required before any outreach).",
                {"provider": provider,
                 "reviews_last_30d": rep.get("reviews_last_30d")},
                provider=provider))
        rr = _num(rep.get("response_rate"))
        if rr is not None and rr < WEAK_RESPONSE_RATE:
            opps.append(_opp(
                "weak_response_rate", "medium", 40,
                f"Weak review response rate on {provider}",
                "Respond to more reviews to improve reputation signals.",
                {"provider": provider, "response_rate": rr},
                provider=provider))

    # Local ranking gap (reuses Phase 3 local-rank data; read-only).
    if best_local_rank is not None and best_local_rank > LOCAL_RANK_GAP_THRESHOLD:
        opps.append(_opp(
            "local_ranking_gap", "high", 70,
            "Local ranking gap detected",
            "Best tracked local rank is outside the top positions; "
            "prioritize local SEO for this location.",
            {"best_local_rank": best_local_rank}))

    opps.sort(key=lambda o: (-o["priority"], o["opportunity_key"]))
    return opps
