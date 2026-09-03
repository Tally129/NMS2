"""Deterministic Marketing OS Phase 9 experimentation logic (pure).

No DB, no network, no AI, no PHI. Deterministic A/B assignment (stable per
opaque marketing_subject_id + experiment id), deterministic conversion
reporting, and a deterministic *advisory* winner recommendation. Significance
uses a documented deterministic two-proportion z-test and clearly flags
insufficient samples — no fabricated confidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional

from marketing_os.services.measurement import (
    MarketingDataPolicyError,
    assert_non_phi_marketing_payload,
)

EXPERIMENT_TYPES: tuple[str, ...] = ("landing_page", "offer", "funnel_step")
EXPERIMENT_STATUSES: tuple[str, ...] = (
    "draft", "active", "paused", "completed", "archived",
)

# Marketing-safe outcome metrics (no PHI).
METRIC_TYPES: tuple[str, ...] = (
    "impression", "click", "lead", "appointment_request",
    "booked", "completed", "conversion", "spend",
)
# Count-style metrics (spend is value-only, revenue lives on 'conversion').
COUNT_METRICS: frozenset[str] = frozenset({
    "impression", "click", "lead", "appointment_request",
    "booked", "completed", "conversion",
})

PRIMARY_METRICS: frozenset[str] = frozenset({
    "conversion", "lead", "booked", "completed", "appointment_request",
})
EXPOSURE_METRICS: frozenset[str] = frozenset({
    "impression", "click", "assignment",
})

# Allowed lifecycle transitions.
STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"active", "archived"}),
    "active": frozenset({"paused", "completed", "archived"}),
    "paused": frozenset({"active", "completed", "archived"}),
    "completed": frozenset({"archived"}),
    "archived": frozenset(),
}

# Deterministic significance thresholds (documented, not adaptive).
MIN_EXPOSURES_FOR_SIGNIFICANCE = 100
Z_SIGNIFICANCE = 1.96  # ~95% two-sided (documented constant)

MAX_NAME_LEN = 200
MAX_SLUG_LEN = 160
MAX_KEY_LEN = 96
MAX_HYPOTHESIS_LEN = 4000
MAX_JSON_CHARS = 20000
MAX_VARIANTS = 20
_HASH_SPACE = 10_000  # allocation resolution (basis of 100.00%)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-_]{0,159}$")
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9\-_]{0,95}$")


class ExperimentConfigError(ValueError):
    """Raised when experiment configuration is malformed (fail-closed)."""


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def _req_str(value: Any, field: str, *, max_len: int, min_len: int = 1) -> str:
    if not isinstance(value, str):
        raise ExperimentConfigError(f"{field} must be a string")
    cleaned = value.strip()
    if len(cleaned) < min_len:
        raise ExperimentConfigError(f"{field} must not be empty")
    if len(cleaned) > max_len:
        raise ExperimentConfigError(f"{field} exceeds max length {max_len}")
    return cleaned


def _opt_str(value: Any, field: str, *, max_len: int) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ExperimentConfigError(f"{field} must be a string")
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > max_len:
        raise ExperimentConfigError(f"{field} exceeds max length {max_len}")
    return cleaned


def _bounded_json(value: Any, field: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ExperimentConfigError(f"{field} must be an object")
    payload = dict(value)
    assert_non_phi_marketing_payload(payload)  # raises MarketingDataPolicyError
    try:
        serialized = json.dumps(payload)
    except (TypeError, ValueError) as exc:
        raise ExperimentConfigError(
            f"{field} must be JSON-serializable"
        ) from exc
    if len(serialized) > MAX_JSON_CHARS:
        raise ExperimentConfigError(f"{field} exceeds max size")
    return payload


def validate_slug(value: Any) -> str:
    cleaned = _req_str(value, "slug", max_len=MAX_SLUG_LEN)
    if not _SLUG_RE.match(cleaned):
        raise ExperimentConfigError(
            "slug must be lowercase alphanumeric with - or _"
        )
    return cleaned


def validate_experiment_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    name = _req_str(payload.get("name"), "name", max_len=MAX_NAME_LEN)
    slug = validate_slug(payload.get("slug"))

    etype = payload.get("experiment_type")
    if not isinstance(etype, str) or etype.strip().lower() \
            not in EXPERIMENT_TYPES:
        raise ExperimentConfigError(
            f"invalid experiment_type: {etype!r}"
        )
    etype = etype.strip().lower()

    primary = str(payload.get("primary_metric", "conversion")).strip().lower()
    if primary not in PRIMARY_METRICS:
        raise ExperimentConfigError(f"invalid primary_metric: {primary!r}")

    exposure = str(payload.get("exposure_metric", "impression")).strip().lower()
    if exposure not in EXPOSURE_METRICS:
        raise ExperimentConfigError(f"invalid exposure_metric: {exposure!r}")

    hypothesis = _opt_str(
        payload.get("hypothesis"), "hypothesis", max_len=MAX_HYPOTHESIS_LEN
    )

    return {
        "name": name,
        "slug": slug,
        "experiment_type": etype,
        "primary_metric": primary,
        "exposure_metric": exposure,
        "hypothesis": hypothesis,
        "config": _bounded_json(payload.get("config", {}), "config"),
    }


def validate_variant_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    key = _req_str(payload.get("variant_key"), "variant_key",
                   max_len=MAX_KEY_LEN)
    if not _KEY_RE.match(key):
        raise ExperimentConfigError(
            "variant_key must be lowercase alphanumeric with - or _"
        )
    name = _req_str(payload.get("name"), "name", max_len=MAX_NAME_LEN)

    alloc = payload.get("allocation_pct", 0)
    if isinstance(alloc, bool) or not isinstance(alloc, int):
        raise ExperimentConfigError("allocation_pct must be an integer")
    if alloc < 0 or alloc > 100:
        raise ExperimentConfigError("allocation_pct must be 0..100")

    is_control = payload.get("is_control", False)
    if not isinstance(is_control, bool):
        raise ExperimentConfigError("is_control must be a boolean")

    return {
        "variant_key": key,
        "name": name,
        "allocation_pct": alloc,
        "is_control": is_control,
        "offer_id": _opt_str(payload.get("offer_id"), "offer_id", max_len=64),
        "funnel_step_id": _opt_str(
            payload.get("funnel_step_id"), "funnel_step_id", max_len=64
        ),
        "config": _bounded_json(payload.get("config", {}), "config"),
    }


def assert_can_transition(current: str, target: str) -> None:
    current = str(current or "").strip().lower()
    target = str(target or "").strip().lower()
    if target not in EXPERIMENT_STATUSES:
        raise ExperimentConfigError(f"invalid status: {target!r}")
    allowed = STATUS_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise ExperimentConfigError(
            f"cannot transition from {current} to {target}"
        )


def validate_activation(variants: list[Mapping[str, Any]]) -> None:
    """Variants must be well-formed to activate (fail-closed)."""
    if len(variants) < 2:
        raise ExperimentConfigError(
            "an experiment needs at least 2 variants to activate"
        )
    if len(variants) > MAX_VARIANTS:
        raise ExperimentConfigError("too many variants")
    controls = [v for v in variants if v.get("is_control")]
    if len(controls) != 1:
        raise ExperimentConfigError("exactly one control variant is required")
    total = sum(int(v.get("allocation_pct", 0)) for v in variants)
    if total != 100:
        raise ExperimentConfigError(
            f"variant allocation_pct must sum to 100 (got {total})"
        )


# --------------------------------------------------------------------------- #
# Deterministic assignment
# --------------------------------------------------------------------------- #

def _bucket(experiment_id: str, subject_id: str) -> int:
    """Stable 0.._HASH_SPACE-1 bucket for (experiment, subject)."""
    digest = hashlib.sha256(
        f"{experiment_id}:{subject_id}".encode("utf-8")
    ).hexdigest()
    return int(digest[:8], 16) % _HASH_SPACE


def assign_variant(experiment_id: str, subject_id: str,
                   variants: Iterable[Mapping[str, Any]]
                   ) -> Optional[dict[str, Any]]:
    """Deterministically pick a variant. Stable across calls.

    Variants are ordered by ``variant_key`` for determinism. Allocation is by
    ``allocation_pct`` (must sum to 100). Returns the chosen variant dict or
    None if there are no variants.
    """
    ordered = sorted(
        (dict(v) for v in variants),
        key=lambda v: str(v.get("variant_key", "")),
    )
    if not ordered:
        return None

    bucket = _bucket(experiment_id, subject_id)
    cumulative = 0
    for v in ordered:
        cumulative += int(v.get("allocation_pct", 0)) * (_HASH_SPACE // 100)
        if bucket < cumulative:
            return v
    return ordered[-1]  # deterministic fallback (rounding safety)


# --------------------------------------------------------------------------- #
# Deterministic reporting
# --------------------------------------------------------------------------- #

def _f(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def safe_ratio(numer: float, denom: float) -> Optional[float]:
    if not denom:
        return None
    return round(numer / denom, 6)


def _normal_cdf(z: float) -> float:
    """Deterministic standard-normal CDF via erf (documented approximation)."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def two_proportion_z(c_conv: int, c_exp: int,
                     v_conv: int, v_exp: int) -> dict[str, Any]:
    """Documented deterministic two-proportion z-test.

    Returns z, two-sided p-value, significant flag, and insufficient_sample
    flag. Never fabricates confidence: if either arm has fewer than
    MIN_EXPOSURES_FOR_SIGNIFICANCE exposures, significant is False and
    insufficient_sample is True.
    """
    result: dict[str, Any] = {
        "z": None, "p_value": None, "significant": False,
        "insufficient_sample": True,
        "min_exposures_required": MIN_EXPOSURES_FOR_SIGNIFICANCE,
    }
    if c_exp < MIN_EXPOSURES_FOR_SIGNIFICANCE or \
            v_exp < MIN_EXPOSURES_FOR_SIGNIFICANCE:
        return result
    if c_exp == 0 or v_exp == 0:
        return result

    p1 = c_conv / c_exp
    p2 = v_conv / v_exp
    pool = (c_conv + v_conv) / (c_exp + v_exp)
    denom = math.sqrt(pool * (1 - pool) * (1 / c_exp + 1 / v_exp))
    if denom == 0:
        return result
    z = (p2 - p1) / denom
    p_value = round(2.0 * (1.0 - _normal_cdf(abs(z))), 6)
    result.update({
        "z": round(z, 6),
        "p_value": p_value,
        "significant": abs(z) >= Z_SIGNIFICANCE,
        "insufficient_sample": False,
    })
    return result


def aggregate_variant(metric_rows: Iterable[Mapping[str, Any]],
                      assignments: int) -> dict[str, Any]:
    """Aggregate raw outcome rows for a single variant deterministically.

    metric_rows: iterable of {"metric_type": str, "cnt": int, "sum": number}.
    """
    counts = {m: 0 for m in METRIC_TYPES}
    revenue = 0.0
    spend = 0.0
    for row in metric_rows:
        mt = row.get("metric_type")
        cnt = int(row.get("cnt", 0) or 0)
        total = _f(row.get("sum"))
        if mt in counts:
            counts[mt] += cnt
        if mt == "conversion":
            revenue += total
        elif mt == "spend":
            spend += total
    return {"counts": counts, "revenue": round(revenue, 4),
            "spend": round(spend, 4), "assignments": int(assignments)}


def build_report(experiment: Mapping[str, Any],
                 variants: list[Mapping[str, Any]],
                 per_variant: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    """Deterministic conversion report + advisory winner recommendation.

    ``per_variant`` maps variant_id -> aggregate_variant() output.
    """
    primary = experiment.get("primary_metric", "conversion")
    exposure = experiment.get("exposure_metric", "impression")

    rows: list[dict[str, Any]] = []
    control_row: Optional[dict[str, Any]] = None

    for v in sorted(variants, key=lambda x: str(x.get("variant_key", ""))):
        agg = per_variant.get(v["id"], {
            "counts": {m: 0 for m in METRIC_TYPES},
            "revenue": 0.0, "spend": 0.0, "assignments": 0,
        })
        counts = agg["counts"]
        conversions = counts.get(primary, 0)
        if exposure == "assignment":
            exposures = agg["assignments"]
        else:
            exposures = counts.get(exposure, 0)
        leads = counts.get("lead", 0)
        revenue = agg["revenue"]
        spend = agg["spend"]

        row = {
            "variant_id": v["id"],
            "variant_key": v.get("variant_key"),
            "name": v.get("name"),
            "is_control": bool(v.get("is_control")),
            "allocation_pct": v.get("allocation_pct"),
            "assignments": agg["assignments"],
            "counts": counts,
            "exposures": exposures,
            "conversions": conversions,
            "leads": leads,
            "revenue": round(revenue, 4),
            "spend": round(spend, 4),
            "conversion_rate": safe_ratio(conversions, exposures),
            "cpl": safe_ratio(spend, leads),
            "cpa": safe_ratio(spend, conversions),
            "revenue_per_exposure": safe_ratio(revenue, exposures),
            "roas": safe_ratio(revenue, spend),
            "lift_vs_control": None,
            "significance": None,
        }
        rows.append(row)
        if row["is_control"]:
            control_row = row

    # Lift + significance vs control.
    if control_row is not None:
        base = control_row["conversion_rate"]
        for row in rows:
            if row["variant_id"] == control_row["variant_id"]:
                continue
            if base is not None and base > 0 and \
                    row["conversion_rate"] is not None:
                row["lift_vs_control"] = round(
                    (row["conversion_rate"] - base) / base, 6
                )
            row["significance"] = two_proportion_z(
                control_row["conversions"], control_row["exposures"],
                row["conversions"], row["exposures"],
            )

    recommendation = recommend_winner(rows, control_row)

    return {
        "experiment_id": experiment.get("id"),
        "primary_metric": primary,
        "exposure_metric": exposure,
        "variants": rows,
        "recommendation": recommendation,
    }


def recommend_winner(rows: list[dict[str, Any]],
                     control_row: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic ADVISORY winner. Never publishes or mutates anything.

    A winner is recommended only when a non-control variant beats control on
    conversion_rate AND its significance test is significant (and sample is
    sufficient). Otherwise returns a documented no-winner reason.
    """
    advisory = {
        "advisory_only": True,
        "auto_publish": False,
        "winner_variant_id": None,
        "reason": "no_significant_winner",
    }
    if control_row is None:
        advisory["reason"] = "no_control_defined"
        return advisory

    candidates = []
    for row in rows:
        if row["variant_id"] == control_row["variant_id"]:
            continue
        sig = row.get("significance") or {}
        if sig.get("insufficient_sample", True):
            continue
        if not sig.get("significant"):
            continue
        if row["conversion_rate"] is None or control_row["conversion_rate"] \
                is None:
            continue
        if row["conversion_rate"] > control_row["conversion_rate"]:
            candidates.append(row)

    if not candidates:
        # Distinguish "not enough data" from "no lift".
        any_sufficient = any(
            not (r.get("significance") or {}).get("insufficient_sample", True)
            for r in rows if r["variant_id"] != control_row["variant_id"]
        )
        advisory["reason"] = (
            "no_significant_winner" if any_sufficient
            else "insufficient_sample"
        )
        return advisory

    winner = sorted(
        candidates,
        key=lambda r: (r["conversion_rate"], str(r["variant_key"])),
        reverse=True,
    )[0]
    advisory["winner_variant_id"] = winner["variant_id"]
    advisory["winner_variant_key"] = winner["variant_key"]
    advisory["reason"] = "significant_lift_over_control"
    return advisory
