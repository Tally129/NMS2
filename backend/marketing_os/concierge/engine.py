"""Internal grounded response engine for the NMS AI Concierge."""

from __future__ import annotations

from urllib.parse import urlparse

import uuid
from dataclasses import dataclass

from llm_client import run_template

from marketing_os.concierge.knowledge import (
    ALLOWED_PUBLIC_HOSTS,
    load_knowledge,
)
from marketing_os.concierge.prompt import (
    CONCIERGE_TEMPLATE,
)
from marketing_os.concierge.retrieval import (
    _retrieval_query,
    retrieve_context,
)
from marketing_os.concierge.safety import (
    SafetyDecision,
    evaluate_message,
)


APPOINTMENT_URL = (
    "https://app.natmedsol.org/request-appointment"
)


@dataclass(frozen=True)
class AppointmentAction:
    offered: bool
    inline_request_enabled: bool
    appointment_url: str | None


@dataclass(frozen=True)
class ConciergeEngineResult:
    session_id: str
    answer: str
    source_pages: tuple[str, ...]
    handoff_recommended: bool
    appointment_url: str | None
    appointment_action: AppointmentAction
    safety_action: str
    used_llm: bool


def _session_id(value: str | None) -> str:
    cleaned = str(value or "").strip()

    if cleaned:
        return cleaned[:128]

    return uuid.uuid4().hex


APPOINTMENT_RECOMMENDATION_PATTERNS = (
    r"\bschedule (?:an? )?(?:appointment|consultation|visit)\b",
    r"\bbook (?:an? )?(?:appointment|consultation|visit)\b",
    r"\brequest (?:an? )?(?:appointment|consultation|visit)\b",
    r"\bmake (?:an? )?appointment\b",
    r"\bset up (?:an? )?(?:appointment|consultation|visit)\b",
    r"\bconsider scheduling (?:an? )?(?:appointment|consultation|visit)\b",
    r"\brecommend scheduling (?:an? )?(?:appointment|consultation|visit)\b",
    r"\brecommend (?:an? )?(?:appointment|consultation)\b",
    r"\bconsultation may be (?:a |the )?(?:good|best|helpful|appropriate) next step\b",
    r"\bappointment may be (?:a |the )?(?:good|best|helpful|appropriate) next step\b",
    r"\bwould you like to (?:schedule|book|request) (?:an? )?(?:appointment|consultation|visit)\b",
)


def _answer_recommends_appointment(
    answer: str,
) -> bool:
    """
    Detect a clear scheduling recommendation in the final answer.

    This only controls whether appointment UI is offered.
    It never creates an appointment.
    """
    import re

    normalized = " ".join(
        str(answer or "").split()
    ).lower()

    if not normalized:
        return False

    return any(
        re.search(
            pattern,
            normalized,
            flags=re.IGNORECASE,
        )
        for pattern
        in APPOINTMENT_RECOMMENDATION_PATTERNS
    )


def _appointment_action(
    offered: bool,
) -> AppointmentAction:
    return AppointmentAction(
        offered=bool(offered),
        inline_request_enabled=bool(offered),
        appointment_url=(
            APPOINTMENT_URL
            if offered
            else None
        ),
    )


def _intercepted_result(
    decision: SafetyDecision,
    *,
    session_id: str,
) -> ConciergeEngineResult:
    return ConciergeEngineResult(
        session_id=session_id,
        answer=str(
            decision.answer or ""
        ),
        source_pages=(),
        handoff_recommended=(
            decision.handoff_recommended
        ),
        appointment_url=(
            APPOINTMENT_URL
            if decision.handoff_recommended
            else None
        ),
        appointment_action=_appointment_action(
            decision.handoff_recommended
        ),
        safety_action=decision.action,
        used_llm=False,
    )


def _trusted_page_context(
    page_url: str | None,
) -> tuple[str, str] | None:
    """Resolve a browser page hint against approved server knowledge.

    The caller-provided URL is used only to identify an approved
    Natural Medical Solutions page. The canonical URL and title
    returned to the prompt come exclusively from the server-owned
    knowledge snapshot.
    """

    raw = str(page_url or "").strip()

    if not raw:
        return None

    try:
        parsed = urlparse(raw)
    except (TypeError, ValueError):
        return None

    if parsed.scheme.lower() != "https":
        return None

    # A browser page hint never needs URL credentials or an
    # explicit port. Reject both before using hostname/path identity.
    # Accessing parsed.port is intentional: urllib raises ValueError
    # for malformed ports, which must fail closed rather than being
    # silently accepted.
    if (
        parsed.username is not None
        or parsed.password is not None
    ):
        return None

    try:
        explicit_port = parsed.port
    except ValueError:
        return None

    if explicit_port is not None:
        return None

    host = (
        parsed.hostname or ""
    ).lower()

    if host not in ALLOWED_PUBLIC_HOSTS:
        return None

    # Browser query strings/fragments never participate in page
    # identity. Normalize the path to the site's trailing-slash form.
    page_path = parsed.path or "/"

    if not page_path.startswith("/"):
        return None

    if page_path != "/" and not page_path.endswith("/"):
        page_path += "/"

    try:
        data = load_knowledge()
    except (OSError, ValueError):
        return None

    for doc in data.get("documents", []):
        if not isinstance(doc, dict):
            continue

        doc_path = str(
            doc.get("path") or ""
        )

        if doc_path != page_path:
            continue

        canonical = str(
            doc.get("canonical_url") or ""
        ).strip()

        title = " ".join(
            str(
                doc.get("title") or ""
            ).split()
        ).strip()

        if not canonical:
            return None

        return (
            canonical,
            title[:300],
        )

    return None


async def generate_concierge_response(
    message: str,
    *,
    session_id: str | None = None,
    page_url: str | None = None,
    page_title: str | None = None,
) -> ConciergeEngineResult:
    """Generate one grounded internal Concierge answer.

    This function is intentionally not exposed through a public route.
    """

    clean_message = str(
        message or ""
    ).strip()

    if not clean_message:
        raise ValueError(
            "message_required"
        )

    if len(clean_message) > 2000:
        raise ValueError(
            "message_too_long"
        )

    sid = _session_id(
        session_id
    )

    decision = evaluate_message(
        clean_message
    )

    if decision.action != "allow":
        return _intercepted_result(
            decision,
            session_id=sid,
        )

    # Retrieval receives a deterministic copy with clear
    # assistant-control clauses excluded. clean_message itself remains
    # unchanged for the eventual model payload.
    retrieval_message = _retrieval_query(
        clean_message
    )

    context = retrieve_context(
        retrieval_message
    )

    if (
        not context.website_results
        and not context.app_treatments
    ):
        return ConciergeEngineResult(
            session_id=sid,
            answer=(
                "I don't have enough published Natural Medical "
                "Solutions information to answer that confidently. "
                "You can contact the office or request an appointment "
                "for help with that question."
            ),
            source_pages=(),
            handoff_recommended=True,
            appointment_url=APPOINTMENT_URL,
            appointment_action=_appointment_action(True),
            safety_action="allow",
            used_llm=False,
        )

    # page_url is an untrusted browser hint only. page_title is
    # deliberately ignored: page identity must come from the approved
    # server-side knowledge snapshot.
    trusted_page = _trusted_page_context(
        page_url
    )

    page_context: list[str] = []

    if trusted_page:
        canonical_url, trusted_title = (
            trusted_page
        )

        if trusted_title:
            page_context.append(
                "Approved current page title: "
                f"{trusted_title}"
            )

        page_context.append(
            "Approved current page URL: "
            f"{canonical_url}"
        )

    user_payload = (
        "VISITOR QUESTION\n"
        "================\n"
        f"{clean_message}\n\n"
    )

    if page_context:
        user_payload += (
            "PAGE CONTEXT\n"
            "============\n"
            + "\n".join(
                page_context
            )
            + "\n\n"
        )

    user_payload += context.text

    try:
        answer = await run_template(
            CONCIERGE_TEMPLATE,
            user_payload,
            session_id=(
                "concierge."
                f"{sid}"
            ),
        )

    except RuntimeError:
        # Fail closed without exposing provider/AWS details.
        return ConciergeEngineResult(
            session_id=sid,
            answer=(
                "I'm unable to generate an answer right now. "
                "You can still request an appointment or contact "
                "Natural Medical Solutions directly."
            ),
            source_pages=context.source_pages,
            handoff_recommended=True,
            appointment_url=APPOINTMENT_URL,
            appointment_action=_appointment_action(True),
            safety_action="allow",
            used_llm=False,
        )

    answer = str(
        answer or ""
    ).strip()

    if not answer:
        return ConciergeEngineResult(
            session_id=sid,
            answer=(
                "I don't have enough published information to "
                "answer that confidently. Please contact the office "
                "or request an appointment."
            ),
            source_pages=context.source_pages,
            handoff_recommended=True,
            appointment_url=APPOINTMENT_URL,
            appointment_action=_appointment_action(True),
            safety_action="allow",
            used_llm=False,
        )

    recommended_handoff = (
        _answer_recommends_appointment(
            answer
        )
    )

    return ConciergeEngineResult(
        session_id=sid,
        answer=answer[:5000],
        source_pages=context.source_pages,
        handoff_recommended=recommended_handoff,
        appointment_url=(
            APPOINTMENT_URL
            if recommended_handoff
            else None
        ),
        appointment_action=_appointment_action(
            recommended_handoff
        ),
        safety_action="allow",
        used_llm=True,
    )
