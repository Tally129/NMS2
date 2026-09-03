"""Automatic knowledge synchronization for NMS AI Concierge.

Responsibilities:
- detect source changes;
- rebuild website knowledge only when necessary;
- preserve the last known-good snapshot;
- write sync metadata atomically;
- expose non-secret synchronization status.

No LLM calls.
No patient/clinical data.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"

KNOWLEDGE_PATH = (
    DATA_DIR
    / "website_knowledge.json"
)

LAST_GOOD_PATH = (
    DATA_DIR
    / "website_knowledge.last_good.json"
)

SYNC_STATE_PATH = (
    DATA_DIR
    / "knowledge_sync_state.json"
)

SITEMAP_URL = (
    "https://preview.natmedsol.org/sitemap.xml"
)

USER_AGENT = (
    "NMS-MarketingOS-KnowledgeSync/1.0"
)

REQUEST_TIMEOUT = 15

MAX_SITEMAP_BYTES = 1024 * 1024


def utcnow_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def sha256_bytes(
    value: bytes,
) -> str:
    return hashlib.sha256(
        value
    ).hexdigest()


def sha256_file(
    path: Path,
) -> str | None:
    if not path.exists():
        return None

    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def atomic_write_json(
    path: Path,
    payload: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
        prefix=path.name + ".",
        suffix=".tmp",
    ) as handle:
        json.dump(
            payload,
            handle,
            indent=2,
            ensure_ascii=False,
        )

        handle.write("\n")

        temp_path = Path(
            handle.name
        )

    temp_path.replace(path)


def read_sync_state() -> dict[str, Any]:
    if not SYNC_STATE_PATH.exists():
        return {
            "version": 1,
            "status": "never_run",
        }

    try:
        data = json.loads(
            SYNC_STATE_PATH.read_text(
                encoding="utf-8"
            )
        )

        if isinstance(
            data,
            dict,
        ):
            return data

    except Exception:
        pass

    return {
        "version": 1,
        "status": "state_unreadable",
    }


def fetch_sitemap_bytes() -> bytes:
    request = Request(
        SITEMAP_URL,
        headers={
            "User-Agent":
                USER_AGENT,
            "Accept":
                "application/xml,text/xml,*/*",
        },
    )

    with urlopen(
        request,
        timeout=REQUEST_TIMEOUT,
    ) as response:
        raw = response.read(
            MAX_SITEMAP_BYTES + 1
        )

    if len(raw) > MAX_SITEMAP_BYTES:
        raise RuntimeError(
            "Sitemap exceeded maximum allowed size."
        )

    return raw


def validate_snapshot(
    path: Path,
) -> dict[str, Any]:
    data = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(
        data,
        dict,
    ):
        raise RuntimeError(
            "Knowledge snapshot must be an object."
        )

    documents = data.get(
        "documents"
    )

    failures = data.get(
        "failures",
        [],
    )

    if not isinstance(
        documents,
        list,
    ):
        raise RuntimeError(
            "Knowledge snapshot documents must be a list."
        )

    if not documents:
        raise RuntimeError(
            "Knowledge snapshot contains no documents."
        )

    if not isinstance(
        failures,
        list,
    ):
        raise RuntimeError(
            "Knowledge snapshot failures must be a list."
        )

    failure_ratio = (
        len(failures)
        / max(
            len(documents)
            + len(failures),
            1,
        )
    )

    if failure_ratio > 0.05:
        raise RuntimeError(
            "Knowledge snapshot failure ratio exceeded 5%."
        )

    return data


def preserve_last_good() -> None:
    if not KNOWLEDGE_PATH.exists():
        return

    validate_snapshot(
        KNOWLEDGE_PATH
    )

    shutil.copy2(
        KNOWLEDGE_PATH,
        LAST_GOOD_PATH,
    )


def restore_last_good() -> bool:
    if not LAST_GOOD_PATH.exists():
        return False

    validate_snapshot(
        LAST_GOOD_PATH
    )

    shutil.copy2(
        LAST_GOOD_PATH,
        KNOWLEDGE_PATH,
    )

    return True


def current_snapshot_fingerprint() -> str | None:
    return sha256_file(
        KNOWLEDGE_PATH
    )


def knowledge_content_fingerprint(
    snapshot: dict[str, Any],
) -> str:
    """Fingerprint deterministic Concierge-visible knowledge.

    generated_at, fetch metadata, failures, and JSON formatting are
    intentionally excluded so identical public knowledge produces
    the same fingerprint across sync runs.
    """

    documents = snapshot.get(
        "documents",
        [],
    )

    normalized_documents = []

    for document in documents:
        normalized_documents.append(
            {
                "path":
                    document.get(
                        "path",
                        "",
                    ),
                "title":
                    document.get(
                        "title",
                        "",
                    ),
                "description":
                    document.get(
                        "description",
                        "",
                    ),
                "canonical_url":
                    document.get(
                        "canonical_url",
                        "",
                    ),
                "h1":
                    document.get(
                        "h1",
                        "",
                    ),
                "headings":
                    document.get(
                        "headings",
                        [],
                    ),
                "paragraphs":
                    document.get(
                        "paragraphs",
                        [],
                    ),
                "list_items":
                    document.get(
                        "list_items",
                        [],
                    ),
            }
        )

    normalized_documents.sort(
        key=lambda item: (
            item["path"],
            item["canonical_url"],
        )
    )

    canonical = json.dumps(
        normalized_documents,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return sha256_bytes(
        canonical
    )


def run_sync(
    *,
    force: bool = False,
    trigger: str = "scheduled",
) -> dict[str, Any]:
    """Reconcile live public website knowledge.

    A candidate snapshot is crawled separately, validated, and
    content-fingerprinted before the active snapshot is replaced.
    """

    started_at = utcnow_iso()
    previous_state = read_sync_state()

    candidate_path = (
        DATA_DIR
        / "website_knowledge.candidate.json"
    )

    try:
        sitemap_bytes = fetch_sitemap_bytes()

        sitemap_fingerprint = sha256_bytes(
            sitemap_bytes
        )

        active_snapshot = validate_snapshot(
            KNOWLEDGE_PATH
        )

        active_content_fingerprint = (
            knowledge_content_fingerprint(
                active_snapshot
            )
        )

        if candidate_path.exists():
            candidate_path.unlink()

        command = [
            sys.executable,
            "-m",
            "marketing_os.concierge.sync_website_knowledge",
        ]

        env = dict(
            __import__("os").environ
        )

        env[
            "NMS_CONCIERGE_KNOWLEDGE_OUTPUT"
        ] = str(candidate_path)

        completed = subprocess.run(
            command,
            cwd=str(
                BASE_DIR.parent.parent
            ),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )

        if completed.returncode != 0:
            raise RuntimeError(
                "Candidate knowledge crawl failed. "
                f"stderr={completed.stderr[-1200:]}"
            )

        candidate_snapshot = validate_snapshot(
            candidate_path
        )

        candidate_content_fingerprint = (
            knowledge_content_fingerprint(
                candidate_snapshot
            )
        )

        documents = len(
            candidate_snapshot.get(
                "documents",
                [],
            )
        )

        failures = len(
            candidate_snapshot.get(
                "failures",
                [],
            )
        )

        changed = (
            force
            or candidate_content_fingerprint
                != active_content_fingerprint
        )

        if not changed:
            candidate_path.unlink(
                missing_ok=True
            )

            result = {
                "version": 2,
                "status": "unchanged",
                "trigger": trigger,
                "started_at": started_at,
                "completed_at": utcnow_iso(),
                "sitemap_fingerprint":
                    sitemap_fingerprint,
                "content_fingerprint":
                    active_content_fingerprint,
                "knowledge_fingerprint":
                    current_snapshot_fingerprint(),
                "documents": documents,
                "failures": failures,
                "last_success_at":
                    previous_state.get(
                        "last_success_at"
                    )
                    or utcnow_iso(),
            }

            atomic_write_json(
                SYNC_STATE_PATH,
                result,
            )

            return result

        preserve_last_good()

        candidate_path.replace(
            KNOWLEDGE_PATH
        )

        activated_snapshot = validate_snapshot(
            KNOWLEDGE_PATH
        )

        activated_content_fingerprint = (
            knowledge_content_fingerprint(
                activated_snapshot
            )
        )

        if (
            activated_content_fingerprint
            != candidate_content_fingerprint
        ):
            restored = restore_last_good()

            raise RuntimeError(
                "Activated knowledge fingerprint mismatch. "
                f"last_good_restored={restored}"
            )

        new_fingerprint = (
            current_snapshot_fingerprint()
        )

        success_at = utcnow_iso()

        result = {
            "version": 2,
            "status": "updated",
            "trigger": trigger,
            "started_at": started_at,
            "completed_at": success_at,
            "sitemap_fingerprint":
                sitemap_fingerprint,
            "content_fingerprint":
                activated_content_fingerprint,
            "knowledge_fingerprint":
                new_fingerprint,
            "documents": documents,
            "failures": failures,
            "last_success_at":
                success_at,
        }

        atomic_write_json(
            SYNC_STATE_PATH,
            result,
        )

        preserve_last_good()

        return result

    except Exception as exc:
        if candidate_path.exists():
            candidate_path.unlink(
                missing_ok=True
            )

        result = {
            "version": 2,
            "status": "failed",
            "trigger": trigger,
            "started_at": started_at,
            "completed_at": utcnow_iso(),
            "error": str(exc)[:2000],
            "knowledge_fingerprint":
                current_snapshot_fingerprint(),
            "last_success_at":
                previous_state.get(
                    "last_success_at"
                ),
        }

        atomic_write_json(
            SYNC_STATE_PATH,
            result,
        )

        return result


def sync_status() -> dict[str, Any]:
    state = read_sync_state()

    return {
        "status":
            state.get(
                "status",
                "unknown",
            ),
        "last_success_at":
            state.get(
                "last_success_at"
            ),
        "completed_at":
            state.get(
                "completed_at"
            ),
        "documents":
            state.get(
                "documents"
            ),
        "failures":
            state.get(
                "failures"
            ),
        "knowledge_fingerprint":
            state.get(
                "knowledge_fingerprint"
            ),
        "content_fingerprint":
            state.get(
                "content_fingerprint"
            ),
    }
