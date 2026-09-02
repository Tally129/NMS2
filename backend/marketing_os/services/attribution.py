"""Marketing attribution service.

No PHI should be required by this service.

The attribution layer should operate on marketing-safe identifiers and
conversion events rather than clinical records.
"""


def attribution_health() -> dict:
    return {
        "status": "foundation",
        "phi_required": False,
    }
