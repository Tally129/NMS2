"""Grounded public-website knowledge for the NMS AI Concierge.

The Concierge is allowed to answer from an approved snapshot of the
Natural Medical Solutions public website.

Important:
- content is fetched from the staging/production-candidate website;
- public canonical URLs are preserved for visitor-facing links;
- no patient, chart, billing, appointment, or clinical database data
  is accessed here;
- this module performs no LLM calls.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


KNOWLEDGE_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "website_knowledge.json"
)

ALLOWED_PUBLIC_HOSTS = {
    "www.natmedsol.com",
    "natmedsol.com",
}

ALLOWED_SOURCE_HOSTS = {
    "preview.natmedsol.org",
}

TOKEN_RE = re.compile(
    r"[a-zA-Z0-9][a-zA-Z0-9'-]{1,}"
)

SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class KnowledgeResult:
    title: str
    canonical_url: str
    path: str
    summary: str
    score: float
    matched_terms: tuple[str, ...]


def normalize_text(value: Any) -> str:
    return SPACE_RE.sub(
        " ",
        str(value or ""),
    ).strip()


def tokenize(value: Any) -> list[str]:
    return [
        match.group(0).lower()
        for match in TOKEN_RE.finditer(
            normalize_text(value)
        )
    ]


def validate_public_url(url: str) -> str:
    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise ValueError(
            "Knowledge canonical URL must use HTTPS"
        )

    host = (
        parsed.hostname or ""
    ).lower()

    if host not in ALLOWED_PUBLIC_HOSTS:
        raise ValueError(
            f"Unapproved public knowledge host: {host}"
        )

    return url


def validate_source_url(url: str) -> str:
    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise ValueError(
            "Knowledge source URL must use HTTPS"
        )

    host = (
        parsed.hostname or ""
    ).lower()

    if host not in ALLOWED_SOURCE_HOSTS:
        raise ValueError(
            f"Unapproved knowledge source host: {host}"
        )

    return url


def load_knowledge(
    path: Path = KNOWLEDGE_PATH,
) -> dict[str, Any]:
    if not path.exists():
        return {
            "version": 1,
            "documents": [],
        }

    data = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(data, dict):
        raise ValueError(
            "Knowledge snapshot must be an object"
        )

    docs = data.get("documents")

    if not isinstance(docs, list):
        raise ValueError(
            "Knowledge snapshot documents must be a list"
        )

    for doc in docs:
        if not isinstance(doc, dict):
            raise ValueError(
                "Knowledge document must be an object"
            )

        validate_public_url(
            str(doc.get("canonical_url") or "")
        )

        source_url = str(
            doc.get("source_url") or ""
        )

        if source_url:
            validate_source_url(source_url)

    return data


def document_search_text(
    document: dict[str, Any],
) -> str:
    parts: list[str] = [
        str(document.get("title") or ""),
        str(document.get("description") or ""),
        str(document.get("h1") or ""),
    ]

    for key in (
        "headings",
        "paragraphs",
        "list_items",
    ):
        value = document.get(key) or []

        if isinstance(value, list):
            parts.extend(
                str(item)
                for item in value
            )

    return normalize_text(
        " ".join(parts)
    )


def _term_frequency(
    tokens: Iterable[str],
) -> dict[str, int]:
    result: dict[str, int] = {}

    for token in tokens:
        result[token] = (
            result.get(token, 0) + 1
        )

    return result


def _score_document(
    query_tokens: list[str],
    document: dict[str, Any],
) -> tuple[float, tuple[str, ...]]:
    if not query_tokens:
        return 0.0, ()

    title_tokens = tokenize(
        document.get("title")
    )

    h1_tokens = tokenize(
        document.get("h1")
    )

    path_tokens = tokenize(
        document.get("path")
    )

    body_tokens = tokenize(
        document_search_text(document)
    )

    title_tf = _term_frequency(title_tokens)
    h1_tf = _term_frequency(h1_tokens)
    path_tf = _term_frequency(path_tokens)
    body_tf = _term_frequency(body_tokens)

    unique_query = sorted(
        set(query_tokens)
    )

    score = 0.0
    matched: list[str] = []

    for term in unique_query:
        term_score = 0.0

        term_score += (
            title_tf.get(term, 0) * 8.0
        )

        term_score += (
            h1_tf.get(term, 0) * 6.0
        )

        term_score += (
            path_tf.get(term, 0) * 5.0
        )

        body_count = body_tf.get(
            term,
            0,
        )

        if body_count:
            term_score += (
                1.0
                + math.log1p(body_count)
            )

        if term_score > 0:
            matched.append(term)
            score += term_score

    if matched:
        coverage = (
            len(matched)
            / len(unique_query)
        )

        score *= (
            1.0 + coverage
        )

    return (
        round(score, 4),
        tuple(matched),
    )


def search_knowledge(
    query: str,
    *,
    limit: int = 5,
    knowledge: dict[str, Any] | None = None,
) -> list[KnowledgeResult]:
    query_tokens = tokenize(query)

    if not query_tokens:
        return []

    data = (
        knowledge
        if knowledge is not None
        else load_knowledge()
    )

    results: list[KnowledgeResult] = []

    for document in data.get(
        "documents",
        [],
    ):
        score, matched = _score_document(
            query_tokens,
            document,
        )

        if score <= 0:
            continue

        paragraphs = (
            document.get("paragraphs")
            or []
        )

        summary = (
            document.get("description")
            or (
                paragraphs[0]
                if paragraphs
                else ""
            )
        )

        results.append(
            KnowledgeResult(
                title=normalize_text(
                    document.get("title")
                ),
                canonical_url=str(
                    document.get(
                        "canonical_url"
                    )
                    or ""
                ),
                path=str(
                    document.get("path")
                    or ""
                ),
                summary=normalize_text(
                    summary
                )[:700],
                score=score,
                matched_terms=matched,
            )
        )

    results.sort(
        key=lambda item: (
            item.score,
            item.title,
        ),
        reverse=True,
    )

    safe_limit = max(
        1,
        min(int(limit), 10),
    )

    return results[:safe_limit]


def knowledge_status() -> dict[str, Any]:
    data = load_knowledge()

    docs = data.get(
        "documents",
        [],
    )

    return {
        "available": bool(docs),
        "documents": len(docs),
        "generated_at":
            data.get("generated_at"),
        "source_sitemap":
            data.get("source_sitemap"),
    }
