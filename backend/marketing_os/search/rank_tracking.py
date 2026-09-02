"""Deterministic rank-history math for tracked search terms.

Works for any ordered series of position snapshots. The metric_type and
source are ALWAYS carried explicitly so a GSC average position is never
conflated with a dedicated SERP rank.
"""

from __future__ import annotations

from typing import Any, Optional


def classify_movement(change: Optional[float]) -> str:
    if change is None:
        return "new"
    if change > 0:
        return "gain"      # position number decreased -> improved
    if change < 0:
        return "loss"
    return "unchanged"


def compute_rank_history(
    snapshots: list[dict],
    *,
    source: str,
    metric_type: str,
) -> dict[str, Any]:
    """Compute current/previous/best/change from ordered snapshots.

    `snapshots`: list of {captured_date, position}. Sorted ascending by
    captured_date internally. Lower position is better. `change` is
    previous_position - current_position (positive == improvement).
    """
    series = [
        s for s in snapshots
        if s.get("position") is not None
    ]
    series.sort(key=lambda s: str(s.get("captured_date")))

    if not series:
        return {
            "source": source,
            "metric_type": metric_type,
            "current_position": None,
            "previous_position": None,
            "best_position": None,
            "change": None,
            "movement": "unranked",
            "last_checked": None,
            "history": [],
        }

    current = series[-1]["position"]
    previous = series[-2]["position"] if len(series) > 1 else None
    best = min(s["position"] for s in series)
    change = (previous - current) if previous is not None else None

    return {
        "source": source,
        "metric_type": metric_type,
        "current_position": current,
        "previous_position": previous,
        "best_position": best,
        "change": (round(change, 3) if change is not None else None),
        "movement": classify_movement(change),
        "last_checked": str(series[-1].get("captured_date")),
        "history": [
            {
                "captured_date": str(s.get("captured_date")),
                "position": s["position"],
            }
            for s in series
        ],
    }


def summarize_movements(items: list[dict]) -> dict[str, int]:
    """Count gains / losses / unchanged / new across rank-history items."""
    gains = losses = unchanged = new = unranked = 0
    for item in items:
        movement = item.get("movement")
        if movement == "gain":
            gains += 1
        elif movement == "loss":
            losses += 1
        elif movement == "unchanged":
            unchanged += 1
        elif movement == "new":
            new += 1
        else:
            unranked += 1
    return {
        "gains": gains,
        "losses": losses,
        "unchanged": unchanged,
        "new": new,
        "unranked": unranked,
    }
