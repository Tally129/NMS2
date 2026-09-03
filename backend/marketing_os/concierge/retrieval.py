"""Bounded approved knowledge retrieval for Concierge generation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from marketing_os.concierge.app_sync import (
    APP_SNAPSHOT_PATH,
)
from marketing_os.concierge.knowledge import (
    KnowledgeResult,
    load_knowledge,
    search_knowledge,
)


TOKEN_RE = re.compile(
    r"[a-zA-Z0-9][a-zA-Z0-9'-]{1,}"
)

# Low-information conversational words must not dominate
# lexical retrieval. These are removed from the query only;
# source content is never altered.
QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "can",
    "could",
    "do",
    "does",
    "for",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "please",
    "tell",
    "that",
    "the",
    "to",
    "what",
    "which",
    "with",
    "you",
    "your",
}

# Terms that are useful for navigation/service discovery and
# therefore must not be discarded as generic language.
KEEP_TERMS = {
    "appointment",
    "consultation",
    "service",
    "services",
    "offer",
    "offers",
    "treatment",
    "treatments",
}

# These words may help rank or route a query, but when a
# visitor also names a specific subject they cannot establish
# grounding by themselves.
GENERIC_DISCOVERY_TERMS = {
    "appointment",
    "consultation",
    "service",
    "services",
    "offer",
    "offers",
    "treatment",
    "treatments",
}


@dataclass(frozen=True)
class GroundedContext:
    text: str
    source_pages: tuple[str, ...]
    website_results: tuple[KnowledgeResult, ...]
    app_treatments: tuple[dict[str, Any], ...]


def _tokens(value: Any) -> set[str]:
    return {
        match.group(0).lower()
        for match in TOKEN_RE.finditer(
            str(value or "").replace("-", " ")
        )
    }


def _ordered_tokens(value: Any) -> list[str]:
    return [
        match.group(0).lower()
        for match in TOKEN_RE.finditer(
            str(value or "").replace("-", " ")
        )
    ]


# Retrieval and model input intentionally have separate trust semantics.
# These patterns identify clauses whose subject is control of the assistant
# rather than Natural Medical Solutions. Only the retrieval copy is altered.
# The original visitor message remains unchanged for safety evaluation and
# model input.
INSTRUCTION_CONTROL_PATTERNS = (
    re.compile(
        r"\bignore\b.{0,80}\b("
        r"instruction|instructions|prompt|prompts|system|rules"
        r")\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b("
        r"override|bypass"
        r")\b.{0,80}\b("
        r"instruction|instructions|prompt|prompts|rules|system"
        r")\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b("
        r"reveal|disclose|show|print|repeat"
        r")\b.{0,80}\b("
        r"system prompt|hidden prompt|prompt|"
        r"internal instructions|system instructions"
        r")\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bnew\s+(?:system\s+)?instruction\b",
        re.IGNORECASE,
    ),
)


def _is_instruction_control_clause(
    clause: str,
) -> bool:
    """Return True only for clear assistant-control clauses."""

    value = str(clause or "").strip()

    if not value:
        return False

    return any(
        pattern.search(value)
        for pattern in INSTRUCTION_CONTROL_PATTERNS
    )


def _retrieval_query(
    message: str,
) -> str:
    """Return the lexical retrieval copy of a visitor message.

    Sentence-like clauses that clearly attempt to control the assistant
    are excluded from retrieval. The original visitor message is never
    modified and remains authoritative as the user's actual message.

    If every clause would be removed, return the original text so the
    normal strict grounding gate still fails closed rather than turning
    an injection-only message into generic discovery.
    """

    original = str(message or "").strip()

    if not original:
        return original

    clauses = [
        part.strip()
        for part in re.split(
            r"(?<=[.!?])\s+|[\r\n]+",
            original,
        )
        if part.strip()
    ]

    if not clauses:
        return original

    retained = [
        clause
        for clause in clauses
        if not _is_instruction_control_clause(
            clause
        )
    ]

    if not retained:
        return original

    return " ".join(retained)


def _clean_query(query: str) -> str:
    """Remove conversational filler without inventing synonyms."""

    original = _ordered_tokens(query)

    useful = [
        token
        for token in original
        if (
            token not in QUERY_STOPWORDS
            or token in KEEP_TERMS
        )
    ]

    # Fail safely back to the original lexical query if every
    # token was filtered.
    if not useful:
        useful = original

    return " ".join(useful)


SUBJECT_FILLER_TERMS = {
    # Question / conversational structure.
    "at",
    "be",
    "explain",
    "help",
    "how",
    "reviewed",
    "virtually",
    "who",
    "won",

    # Generic actions that do not identify the visitor's subject.
    "change",
    "write",
    "replace",
    "done",
    "through",
}



def _expand_retrieval_query(query: str) -> str:
    """
    Add narrow public-information synonyms for retrieval only.

    This does not change the visitor's message, safety classification,
    model prompt, or approved knowledge. It only helps lexical retrieval
    locate the correct approved website material for common natural
    language descriptions of telehealth and at-home testing.
    """
    cleaned = _clean_query(query)
    additions: list[str] = []

    telehealth_patterns = (
        r"\b(?:treated|treatment|care|visit|appointment|consultation|consult)"
        r"\s+(?:entirely\s+)?from\s+home\b",
        r"\b(?:see|meet|talk|speak)\s+(?:with\s+)?(?:a\s+|the\s+)?"
        r"(?:doctor|provider|practitioner|clinician)\s+"
        r"(?:from\s+home|online|remotely|virtually)\b",
        r"\bwithout\s+(?:coming|going)\s+(?:in|into|to)\b",
        r"\b(?:remote|virtual|online)\s+"
        r"(?:care|visit|appointment|consultation|consult)\b",
    )

    testing_patterns = (
        r"\b(?:test|testing|lab|labs)\s+(?:at|from)\s+home\b",
        r"\b(?:at[\s-]?home|home)\s+"
        r"(?:test|testing|lab|labs|test\s+kit|test\s+kits)\b",
        r"\b(?:ship|send|mail|deliver)\b.{0,40}\b"
        r"(?:test|tests|testing|kit|kits|lab|labs)\b",
        r"\b(?:test|tests|testing|kit|kits|lab|labs)\b.{0,40}\b"
        r"(?:ship|send|mail|deliver)\b",
    )

    if any(re.search(pattern, cleaned) for pattern in telehealth_patterns):
        additions.extend(
            (
                "telehealth",
                "virtual appointment",
                "remote care",
                "online consultation",
            )
        )

    if any(re.search(pattern, cleaned) for pattern in testing_patterns):
        additions.extend(
            (
                "telehealth",
                "at-home testing",
                "test kits",
                "specialty lab testing",
                "shipping",
            )
        )

    if not additions:
        return query

    unique: list[str] = []
    seen: set[str] = set()

    for value in additions:
        if value not in seen:
            seen.add(value)
            unique.append(value)

    return f"{query} {' '.join(unique)}"


def _intent_grounding_query(
    original_query: str,
    expanded_query: str,
) -> str:
    """
    Return a narrow canonical subject for locally recognized
    Telehealth / at-home-testing intents.

    The canonical subject is used only by the deterministic
    subject-grounding gate. Unrecognized queries retain their
    original subject requirements.
    """
    if expanded_query == original_query:
        return original_query

    expanded = _tokens(
        _clean_query(expanded_query)
    )

    original = _tokens(
        _clean_query(original_query)
    )

    # Testing / kit / shipping intent.
    testing_markers = {
        "test",
        "testing",
        "lab",
        "labs",
        "kit",
        "kits",
        "ship",
        "shipping",
        "send",
        "mail",
        "deliver",
    }

    if original & testing_markers:
        return "telehealth testing"

    # The only other expansion currently produced by
    # _expand_retrieval_query is remote Telehealth care.
    if "telehealth" in expanded:
        return "telehealth"

    return original_query


def _subject_tokens(query: str) -> set[str]:
    """Return meaningful subject terms that must be grounded."""

    cleaned = _tokens(
        _clean_query(query)
    )

    return {
        token
        for token in cleaned
        if (
            token not in GENERIC_DISCOVERY_TERMS
            and token not in SUBJECT_FILLER_TERMS
        )
    }


def _filter_subject_grounded_results(
    query: str,
    results: list[KnowledgeResult],
) -> list[KnowledgeResult]:
    """Apply a deterministic query-level subject grounding gate.

    Generic service-discovery queries intentionally retain their
    existing behavior.

    For a specific query, at least one approved source must cover
    every meaningful subject token before any website grounding is
    allowed. This prevents incidental lexical overlap from admitting
    unrelated domains such as vehicle repair or sports.

    Once the query passes that gate, partially matching approved
    sources may still be retained as useful supporting context.
    """

    subjects = _subject_tokens(
        query
    )

    if not subjects:
        return results

    matched_by_result: list[
        tuple[KnowledgeResult, set[str]]
    ] = []

    has_full_subject_grounding = False

    for result in results:
        matched = {
            str(term).lower()
            for term in result.matched_terms
        }

        subject_matches = (
            matched & subjects
        )

        matched_by_result.append(
            (
                result,
                subject_matches,
            )
        )

        if subject_matches == subjects:
            has_full_subject_grounding = True

    if not has_full_subject_grounding:
        return []

    return [
        result
        for result, subject_matches
        in matched_by_result
        if subject_matches
    ]


def _load_app_snapshot() -> dict[str, Any]:
    if not APP_SNAPSHOT_PATH.exists():
        return {
            "count": 0,
            "treatments": [],
        }

    data = json.loads(
        APP_SNAPSHOT_PATH.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(data, dict):
        return {
            "count": 0,
            "treatments": [],
        }

    treatments = data.get("treatments")

    if not isinstance(treatments, list):
        treatments = []

    return {
        "count": len(treatments),
        "treatments": treatments,
    }


def _search_app_treatments(
    query: str,
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    query_tokens = _tokens(
        _clean_query(query)
    )

    if not query_tokens:
        return []

    subjects = _subject_tokens(query)

    snapshot = _load_app_snapshot()

    ranked: list[
        tuple[int, str, dict[str, Any]]
    ] = []

    for treatment in snapshot["treatments"]:
        if not isinstance(treatment, dict):
            continue

        searchable = " ".join(
            str(
                treatment.get(key) or ""
            )
            for key in (
                "name",
                "category",
                "description",
            )
        )

        searchable_tokens = _tokens(
            searchable
        )

        metadata = " ".join(
            str(
                treatment.get(key) or ""
            )
            for key in (
                "name",
                "category",
            )
        )

        metadata_tokens = _tokens(
            metadata
        )

        overlap = len(
            query_tokens & searchable_tokens
        )

        if overlap <= 0:
            continue

        # Generic service-discovery queries intentionally retain
        # their existing lexical ranking behavior.
        #
        # Specific queries must satisfy BOTH conditions:
        #
        # 1. Every meaningful query subject must be represented
        #    inside this one explicitly public treatment.
        #
        # 2. At least one meaningful subject must occur in strong
        #    treatment metadata (name/category), rather than only
        #    incidental descriptive prose.
        #
        # This prevents unrelated queries such as "car oil" from
        # grounding merely because a wellness description mentions
        # cooking oil.
        if subjects:
            if not subjects.issubset(
                searchable_tokens
            ):
                continue

            if not (
                subjects
                & metadata_tokens
            ):
                continue

        ranked.append(
            (
                overlap,
                str(
                    treatment.get("name")
                    or ""
                ).lower(),
                treatment,
            )
        )

    ranked.sort(
        key=lambda item: (
            item[0],
            item[1],
        ),
        reverse=True,
    )

    return [
        item[2]
        for item in ranked[
            :max(1, min(limit, 5))
        ]
    ]


def _knowledge_document_map() -> dict[str, dict[str, Any]]:
    """Index only already-approved website snapshot documents."""

    data = load_knowledge()

    result: dict[
        str,
        dict[str, Any],
    ] = {}

    for doc in data.get(
        "documents",
        [],
    ):
        if not isinstance(doc, dict):
            continue

        path = str(
            doc.get("path")
            or ""
        )

        url = str(
            doc.get("canonical_url")
            or ""
        )

        if path:
            result[
                f"path:{path}"
            ] = doc

        if url:
            result[
                f"url:{url}"
            ] = doc

    return result


def _paragraph_score(
    paragraph: str,
    query_tokens: set[str],
) -> tuple[int, int]:
    tokens = _tokens(
        paragraph
    )

    overlap = len(
        query_tokens & tokens
    )

    # Prefer a compact paragraph when overlap ties.
    length_penalty = min(
        len(paragraph),
        4000,
    )

    return (
        overlap,
        -length_penalty,
    )


def _matched_excerpt(
    result: KnowledgeResult,
    *,
    query: str,
    documents: dict[str, dict[str, Any]],
) -> str:
    """Return the most query-relevant approved paragraph."""

    doc = documents.get(
        f"path:{result.path}"
    )

    if doc is None:
        doc = documents.get(
            f"url:{result.canonical_url}"
        )

    if not doc:
        return result.summary

    query_tokens = _tokens(
        _clean_query(query)
    )

    candidates: list[str] = []

    for key in (
        "paragraphs",
        "list_items",
    ):
        for value in (
            doc.get(key)
            or []
        ):
            text = " ".join(
                str(value or "").split()
            ).strip()

            # Skip tiny labels/headings. They may contain the
            # keyword but do not provide enough factual context
            # for grounded generation.
            if (
                text
                and len(text) >= 60
                and len(_tokens(text)) >= 8
            ):
                candidates.append(
                    text
                )

    if not candidates:
        return result.summary

    ranked = sorted(
        candidates,
        key=lambda paragraph:
            _paragraph_score(
                paragraph,
                query_tokens,
            ),
        reverse=True,
    )

    best = ranked[0]

    # If no paragraph actually contains a useful query term,
    # the approved page summary is safer/more representative.
    if (
        _paragraph_score(
            best,
            query_tokens,
        )[0]
        <= 0
    ):
        return result.summary

    return best[:1200]


def _untrusted_source_text(
    value: Any,
) -> str:
    """Serialize retrieved source data without allowing it to forge
    Concierge trust-boundary markers.

    Retrieved content remains visible to the model as data. Only the
    structural marker syntax reserved by this module is neutralized.
    """

    text = str(value or "")

    return (
        text
        .replace("<<<", "‹‹‹")
        .replace(">>>", "›››")
    )


CONTEXT_CHAR_LIMIT = 12_000
WEBSITE_TITLE_CHAR_LIMIT = 500
WEBSITE_URL_CHAR_LIMIT = 2_048
WEBSITE_EXCERPT_CHAR_LIMIT = 1_200
APP_NAME_CHAR_LIMIT = 500
APP_CATEGORY_CHAR_LIMIT = 500
APP_SCALAR_CHAR_LIMIT = 100
APP_DESCRIPTION_CHAR_LIMIT = 2_000


def _bounded_untrusted_source_text(
    value: Any,
    *,
    limit: int,
) -> str:
    """Escape source text and cap one untrusted field safely."""

    return _untrusted_source_text(
        value
    )[:limit]


def _website_records(
    results: list[KnowledgeResult],
    *,
    query: str,
) -> list[tuple[KnowledgeResult, str]]:
    """Serialize complete website records only."""

    documents = _knowledge_document_map()
    records: list[
        tuple[KnowledgeResult, str]
    ] = []

    for index, item in enumerate(
        results,
        start=1,
    ):
        excerpt = _matched_excerpt(
            item,
            query=query,
            documents=documents,
        )

        record = "\n".join(
            (
                (
                    "<<< BEGIN UNTRUSTED WEBSITE "
                    f"DOCUMENT {index} >>>"
                ),
                (
                    "Title: "
                    f"{_bounded_untrusted_source_text(item.title, limit=WEBSITE_TITLE_CHAR_LIMIT)}"
                ),
                (
                    "URL: "
                    f"{_bounded_untrusted_source_text(item.canonical_url, limit=WEBSITE_URL_CHAR_LIMIT)}"
                ),
                (
                    "Relevant excerpt: "
                    f"{_bounded_untrusted_source_text(excerpt, limit=WEBSITE_EXCERPT_CHAR_LIMIT)}"
                ),
                (
                    "<<< END UNTRUSTED WEBSITE "
                    f"DOCUMENT {index} >>>"
                ),
            )
        )

        records.append(
            (item, record)
        )

    return records


def _app_records(
    treatments: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], str]]:
    """Serialize complete public-app records only."""

    records: list[
        tuple[dict[str, Any], str]
    ] = []

    for index, item in enumerate(
        treatments,
        start=1,
    ):
        lines = [
            (
                "<<< BEGIN UNTRUSTED PUBLIC APP "
                f"SERVICE {index} >>>"
            ),
            (
                "Name: "
                f"{_bounded_untrusted_source_text(item.get('name'), limit=APP_NAME_CHAR_LIMIT)}"
            ),
            (
                "Category: "
                f"{_bounded_untrusted_source_text(item.get('category'), limit=APP_CATEGORY_CHAR_LIMIT)}"
            ),
        ]

        if (
            item.get("duration_min")
            is not None
        ):
            lines.append(
                "Duration minutes: "
                f"{_bounded_untrusted_source_text(item.get('duration_min'), limit=APP_SCALAR_CHAR_LIMIT)}"
            )

        if (
            item.get("price")
            is not None
        ):
            lines.append(
                "Price: "
                f"{_bounded_untrusted_source_text(item.get('price'), limit=APP_SCALAR_CHAR_LIMIT)}"
            )

        if item.get("description"):
            lines.append(
                "Description: "
                f"{_bounded_untrusted_source_text(item.get('description'), limit=APP_DESCRIPTION_CHAR_LIMIT)}"
            )

        lines.append(
            (
                "<<< END UNTRUSTED PUBLIC APP "
                f"SERVICE {index} >>>"
            )
        )

        records.append(
            (
                item,
                "\n".join(lines),
            )
        )

    return records


def _website_section(
    results: list[KnowledgeResult],
    *,
    query: str,
) -> str:
    if not results:
        return (
            "No matching approved website "
            "pages were found."
        )

    return "\n\n".join(
        record
        for _, record in _website_records(
            results,
            query=query,
        )
    )


def _app_section(
    treatments: list[dict[str, Any]],
) -> str:
    if not treatments:
        return (
            "No matching explicitly public "
            "app services were found."
        )

    return "\n\n".join(
        record
        for _, record in _app_records(
            treatments
        )
    )


def _budget_grounded_context(
    website: list[KnowledgeResult],
    app: list[dict[str, Any]],
    *,
    query: str,
) -> tuple[
    str,
    list[KnowledgeResult],
    list[dict[str, Any]],
]:
    """Build model context from complete records within budget."""

    website_header = (
        "APPROVED WEBSITE KNOWLEDGE\n"
        "==========================\n"
    )

    app_header = (
        "\n\n"
        "APPROVED PUBLIC APP SERVICE KNOWLEDGE\n"
        "=====================================\n"
    )

    website_empty = (
        "No matching approved website "
        "pages were found."
    )

    app_empty = (
        "No matching explicitly public "
        "app services were found."
    )

    website_records = _website_records(
        website,
        query=query,
    )

    app_records = _app_records(
        app
    )

    selected_website: list[
        KnowledgeResult
    ] = []

    selected_app: list[
        dict[str, Any]
    ] = []

    website_texts: list[str] = []
    app_texts: list[str] = []

    base = (
        website_header
        + website_empty
        + app_header
        + app_empty
    )

    if len(base) > CONTEXT_CHAR_LIMIT:
        raise RuntimeError(
            "Concierge context headers exceed hard limit"
        )

    current_length = len(base)

    for item, record in website_records:
        separator = (
            2
            if website_texts
            else 0
        )

        replacement_credit = (
            len(website_empty)
            if not website_texts
            else 0
        )

        delta = (
            separator
            + len(record)
            - replacement_credit
        )

        if (
            current_length + delta
            > CONTEXT_CHAR_LIMIT
        ):
            break

        website_texts.append(record)
        selected_website.append(item)
        current_length += delta

    for item, record in app_records:
        separator = (
            2
            if app_texts
            else 0
        )

        replacement_credit = (
            len(app_empty)
            if not app_texts
            else 0
        )

        delta = (
            separator
            + len(record)
            - replacement_credit
        )

        if (
            current_length + delta
            > CONTEXT_CHAR_LIMIT
        ):
            break

        app_texts.append(record)
        selected_app.append(item)
        current_length += delta

    website_body = (
        "\n\n".join(website_texts)
        if website_texts
        else website_empty
    )

    app_body = (
        "\n\n".join(app_texts)
        if app_texts
        else app_empty
    )

    context = (
        website_header
        + website_body
        + app_header
        + app_body
    )

    if len(context) > CONTEXT_CHAR_LIMIT:
        raise RuntimeError(
            "Concierge context exceeded hard limit"
        )

    return (
        context,
        selected_website,
        selected_app,
    )


def retrieve_context(
    query: str,
) -> GroundedContext:
    """Return tightly bounded approved public context."""

    retrieval_query = _expand_retrieval_query(query)
    cleaned_query = _clean_query(query)
    cleaned_retrieval_query = _clean_query(
        retrieval_query
    )

    # Preserve the strict all-subject grounding gate while
    # translating only locally recognized Telehealth intent into
    # a small canonical subject vocabulary.
    subject_grounding_query = _clean_query(
        _intent_grounding_query(
            query,
            retrieval_query,
        )
    )

    website = search_knowledge(
        cleaned_retrieval_query,
        limit=10,
    )

    website = _filter_subject_grounded_results(
        subject_grounding_query,
        website,
    )[:5]

    app = _search_app_treatments(
        cleaned_retrieval_query,
        limit=3,
    )

    (
        context,
        included_website,
        included_app,
    ) = _budget_grounded_context(
        website,
        app,
        query=cleaned_query,
    )

    source_pages: list[str] = []

    for item in included_website:
        if (
            item.canonical_url
            and item.canonical_url
            not in source_pages
        ):
            source_pages.append(
                item.canonical_url
            )

    return GroundedContext(
        text=context,
        source_pages=tuple(
            source_pages[:5]
        ),
        website_results=tuple(
            included_website
        ),
        app_treatments=tuple(
            included_app
        ),
    )
