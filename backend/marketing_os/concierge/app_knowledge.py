"""Approved app business knowledge for the NMS AI Concierge.

This adapter intentionally exposes only explicitly public treatment
catalog fields. It must never expose client IDs, treatment plans,
clinical records, notes, messages, labs, billing data, or arbitrary
database payloads.
"""

from __future__ import annotations

from typing import Any

from deps import db


PUBLIC_TREATMENT_FIELDS = (
    "id",
    "name",
    "category",
    "duration_min",
    "price",
    "description",
)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None

    value = str(value).strip()

    return value or None


async def load_public_treatments() -> list[dict]:
    records = (
        await db.treatments.find(
            {
                "active": True,
                "concierge_public": True,
            }
        )
        .sort("name", 1)
        .to_list(500)
    )

    result: list[dict] = []

    for record in records:
        item = {
            "id": str(record.get("id") or ""),
            "name": _clean_text(record.get("name")),
            "category": _clean_text(
                record.get("category")
            ),
            "duration_min": record.get(
                "duration_min"
            ),
            "price": record.get("price"),
            "description": _clean_text(
                record.get("description")
            ),
        }

        if not item["id"] or not item["name"]:
            continue

        result.append(item)

    return result


async def public_app_knowledge_status() -> dict:
    treatments = await load_public_treatments()

    return {
        "available": True,
        "public_treatments": len(treatments),
        "allowed_fields": list(
            PUBLIC_TREATMENT_FIELDS
        ),
        "contains_patient_data": False,
        "contains_clinical_records": False,
    }


def canonical_public_treatments(
    treatments: list[dict],
) -> list[dict]:
    """Return deterministic, public-only catalog content."""

    allowed = set(PUBLIC_TREATMENT_FIELDS)

    normalized: list[dict] = []

    for treatment in treatments:
        item = {
            key: treatment.get(key)
            for key in PUBLIC_TREATMENT_FIELDS
            if key in allowed
        }

        normalized.append(item)

    normalized.sort(
        key=lambda item: (
            str(item.get("name") or "").lower(),
            str(item.get("id") or ""),
        )
    )

    return normalized


def public_treatments_fingerprint(
    treatments: list[dict],
) -> str:
    """Fingerprint meaningful public catalog content only."""

    import hashlib
    import json

    canonical = canonical_public_treatments(
        treatments
    )

    payload = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")

    return hashlib.sha256(payload).hexdigest()


async def public_app_knowledge_snapshot() -> dict:
    treatments = await load_public_treatments()

    canonical = canonical_public_treatments(
        treatments
    )

    return {
        "treatments": canonical,
        "fingerprint":
            public_treatments_fingerprint(canonical),
        "count": len(canonical),
    }
