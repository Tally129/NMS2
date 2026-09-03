"""Automatic reconciliation for approved app business knowledge."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from marketing_os.concierge.app_knowledge import (
    public_app_knowledge_snapshot,
)


DATA_DIR = Path(__file__).resolve().parent / "data"

APP_SNAPSHOT_PATH = (
    DATA_DIR / "app_public_knowledge.json"
)

APP_STATE_PATH = (
    DATA_DIR / "app_public_knowledge_state.json"
)


def _utcnow_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def _atomic_json(
    path: Path,
    value: Any,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    tmp = path.with_name(
        f".{path.name}.{os.getpid()}.tmp"
    )

    tmp.write_text(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )

    os.replace(tmp, path)


def _read_json(
    path: Path,
) -> dict:
    if not path.exists():
        return {}

    try:
        value = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        return (
            value
            if isinstance(value, dict)
            else {}
        )

    except Exception:
        return {}


async def reconcile_app_knowledge(
    *,
    trigger: str = "scheduler",
) -> dict:
    candidate = (
        await public_app_knowledge_snapshot()
    )

    fingerprint = candidate["fingerprint"]

    current = _read_json(
        APP_SNAPSHOT_PATH
    )

    current_fp = current.get(
        "fingerprint"
    )

    changed = (
        fingerprint != current_fp
    )

    now = _utcnow_iso()

    if changed:
        active = {
            "generated_at": now,
            "fingerprint": fingerprint,
            "count": candidate["count"],
            "treatments":
                candidate["treatments"],
        }

        _atomic_json(
            APP_SNAPSHOT_PATH,
            active,
        )

    state = {
        "status":
            "updated"
            if changed
            else "unchanged",
        "trigger": trigger,
        "checked_at": now,
        "fingerprint": fingerprint,
        "public_treatments":
            candidate["count"],
    }

    _atomic_json(
        APP_STATE_PATH,
        state,
    )

    return state


def app_sync_status() -> dict:
    state = _read_json(
        APP_STATE_PATH
    )

    snapshot = _read_json(
        APP_SNAPSHOT_PATH
    )

    return {
        "status":
            state.get(
                "status",
                "not_initialized",
            ),
        "checked_at":
            state.get("checked_at"),
        "fingerprint":
            snapshot.get("fingerprint"),
        "public_treatments":
            snapshot.get("count", 0),
        "snapshot_available":
            APP_SNAPSHOT_PATH.exists(),
    }
