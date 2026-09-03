"""Deterministic pre-LLM safety rules for the NMS public Concierge."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


SafetyAction = Literal[
    "allow",
    "emergency",
    "diagnosis",
    "prescribing",
    "sensitive_intake",
    "appointment",
]


@dataclass(frozen=True)
class SafetyDecision:
    action: SafetyAction
    answer: str | None = None
    handoff_recommended: bool = False


# High-confidence current-emergency constructions.
#
# Do not classify bare medical topic words as emergencies. These patterns
# require language indicating that the event is happening now to the visitor
# or another person. General educational, historical, and explicitly negated
# questions therefore remain available to the public Concierge.
EMERGENCY_PATTERNS = (
    re.compile(
        r"\b("
        r"i (?:have|am having|feel|am experiencing) "
        r"(?:severe )?chest pain|"
        r"i(?:'m| am) having (?:severe )?chest pain|"
        r"my chest (?:hurts|is hurting)|"
        r"i can't breathe|i cannot breathe|"
        r"i(?:'m| am) (?:having difficulty|having trouble|struggling to) "
        r"breathe|"
        r"i(?:'m| am) short of breath|"
        r"i have shortness of breath|"
        r"i(?:'m| am) bleeding (?:badly|heavily|severely)|"
        r"i have severe bleeding|"
        r"i (?:just )?(?:collapsed|passed out)|"
        r"i think i(?:'m| am) having (?:a )?(?:heart attack|stroke)|"
        r"i(?:'m| am) having (?:a )?(?:heart attack|stroke|seizure)|"
        r"i overdosed|i took an overdose|"
        r"i(?:'m| am) suicidal|"
        r"i want to kill myself|"
        r"i(?:'m| am) going to kill myself|"
        r"i want to hurt myself|"
        r"i(?:'m| am) going to hurt myself"
        r")\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b("
        r"my (?:husband|wife|spouse|partner|"
        r"child|son|daughter|baby|mother|mom|father|dad|"
        r"friend|brother|sister|family member) "
        r"(?:(?:is )(?:currently |now )?|"
        r"(?:suddenly |just ))?"
        r"(?:"
        r"having (?:severe )?chest pain|"
        r"having (?:a )?(?:heart attack|stroke|seizure)|"
        r"having (?:difficulty|trouble) breathing|"
        r"struggling to breathe|"
        r"can't breathe|cannot breathe|"
        r"is short of breath|"
        r"collapsed|"
        r"passed out|"
        r"is unconscious|"
        r"unconscious|"
        r"is unresponsive|"
        r"unresponsive|"
        r"is not responding|"
        r"not responding"
        r")"
        r")\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b("
        r"someone (?:here |near me )?"
        r"(?:"
        r"is having (?:severe )?chest pain|"
        r"is having (?:a )?(?:heart attack|stroke|seizure)|"
        r"is having (?:difficulty|trouble) breathing|"
        r"is struggling to breathe|"
        r"can't breathe|cannot breathe|"
        r"collapsed(?: in front of me)?|"
        r"passed out|"
        r"is unconscious|"
        r"is unresponsive|"
        r"unresponsive|"
        r"is not responding|"
        r"not responding"
        r")|"
        r"there is someone unconscious here|"
        r"someone is unconscious here"
        r")\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bhelp[,:! ]+(?:"
        r"(?:i(?:'m| am) )?"
        r"(?:having )?(?:severe )?chest pain|"
        r"(?:i |someone )?(?:can't|cannot) breathe|"
        r"someone is having (?:a )?(?:heart attack|stroke|seizure)|"
        r"(?:i(?:'m| am) )?having (?:a )?(?:heart attack|stroke|seizure)"
        r")\b",
        re.IGNORECASE,
    ),
)


DIAGNOSIS_PATTERNS = (
    re.compile(
        r"\b("
        r"diagnose me|"
        r"what do i have|"
        r"what(?:'s| is) wrong with me|"
        r"do i have [a-z]|"
        r"could i have [a-z]|"
        r"what could be causing my|"
        r"what (?:disease|condition|illness) do i have|"
        r"based on my symptoms.{0,80}"
        r"(?:what|which).{0,40}"
        r"(?:disease|condition|illness|diagnosis)"
        r")",
        re.IGNORECASE,
    ),
)

# Intercept individualized prescribing requests, not general questions
# about whether the practice provides medication-related services.
PRESCRIBING_PATTERNS = (
    re.compile(
        r"\b("
        r"can you prescribe (?:me|for me)|"
        r"will you prescribe (?:me|for me)|"
        r"prescribe me|"
        r"write me (?:a )?prescription|"
        r"give me (?:a )?prescription|"
        r"what medication should i take|"
        r"what medicine should i take|"
        r"which medication should i take|"
        r"which medicine should i take|"
        r"which prescription medication should i start taking|"
        r"which prescription medicine should i start taking|"
        r"what dose should i take|"
        r"change my dose|"
        r"increase my dose|"
        r"decrease my dose|"
        r"should i (?:increase|decrease|change|stop|start) "
        r"(?:taking )?(?:my )?(?:medication|medicine|prescription)|"
        r"tell me which (?:medication|medicine) i need|"
        r"tell me what (?:medication|medicine) i need|"
        r"what prescription should i ask for|"
        r"what prescription should i ask my doctor for|"
        r"can you tell me what prescription i should ask for|"
        r"can you tell me what prescription i should ask my doctor for|"
        r"what should my doctor prescribe (?:me|for me)"
        r")\b",
        re.IGNORECASE,
    ),
)


# Sensitive intake requires evidence that the visitor is trying to
# submit/disclose personal information through the public Concierge.
#
# Merely asking whether NMS reviews labs, records, medications, or
# insurance-related information is not itself sensitive intake.
SENSITIVE_SUBMISSION_PATTERNS = (
    re.compile(
        r"\b("
        r"send|upload|attach|paste|share|give|provide|"
        r"submit|enter|type|post"
        r")\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b("
        r"here (?:is|are)|"
        r"these are"
        r")\b",
        re.IGNORECASE,
    ),
)

SENSITIVE_MATERIAL_PATTERNS = (
    re.compile(
        r"\b("
        r"(?:my )?(?:lab|test) results?|"
        r"(?:my )?blood ?work|"
        r"(?:my )?medical records?|"
        r"(?:my )?health records?|"
        r"(?:my )?(?:medical )?chart|"
        r"(?:my )?diagnos(?:is|es)|"
        r"(?:my )?medication(?: list|s)?|"
        r"(?:my )?medicine(?: list|s)?|"
        r"(?:my )?insurance "
        r"(?:information|info|member id|policy number)|"
        r"insurance member id|"
        r"policy number|"
        r"social security number|"
        r"\bssn\b"
        r")\b",
        re.IGNORECASE,
    ),
)

# Some content is sensitive enough to intercept directly when the
# visitor appears to be supplying the value itself.
SENSITIVE_VALUE_PATTERNS = (
    re.compile(
        r"\b\d{3}-\d{2}-\d{4}\b"
    ),
    re.compile(
        r"\bi take \d+(?:\.\d+)?\s*"
        r"(?:mg|mcg|g|ml)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bmy diagnosis is\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bi was diagnosed with\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bmy medication is\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bmy medications are\b",
        re.IGNORECASE,
    ),
)


def _is_sensitive_intake(
    text: str,
) -> bool:
    """Detect attempted disclosure, not general service questions."""

    if _matches(
        text,
        SENSITIVE_VALUE_PATTERNS,
    ):
        return True

    return (
        _matches(
            text,
            SENSITIVE_SUBMISSION_PATTERNS,
        )
        and _matches(
            text,
            SENSITIVE_MATERIAL_PATTERNS,
        )
    )


APPOINTMENT_PATTERNS = (
    re.compile(
        r"\b("
        r"book (an |a )?appointment|"
        r"schedule (an |a )?appointment|"
        r"request (an |a )?appointment|"
        r"make (an |a )?appointment|"
        r"set up (an |a )?appointment|"
        r"i want (an |a )?appointment|"
        r"i need (an |a )?appointment|"
        r"see (a |the )?(doctor|provider|practitioner)"
        r")\b",
        re.IGNORECASE,
    ),
)


EMERGENCY_ANSWER = (
    "This may need urgent medical attention. "
    "If you or someone with you may be experiencing a medical emergency, "
    "call 911 or go to the nearest emergency department now. "
    "The NMS website Concierge cannot evaluate or manage emergencies."
)

DIAGNOSIS_ANSWER = (
    "I can explain Natural Medical Solutions services and general "
    "published health information, but I can't diagnose a condition "
    "or determine what is causing personal symptoms. A clinician can "
    "evaluate your individual situation."
)

PRESCRIBING_ANSWER = (
    "I can't prescribe medication, recommend a personal medication "
    "change, or determine a dose. Please discuss medication decisions "
    "with a licensed clinician who can evaluate your individual care."
)

SENSITIVE_INTAKE_ANSWER = (
    "For your privacy, please don't send personal medical records, "
    "lab results, medication details, insurance identifiers, or other "
    "sensitive health information through the public website Concierge. "
    "Existing patients should use the secure patient portal or contact "
    "the office."
)

APPOINTMENT_ANSWER = (
    "You can request an appointment with Natural Medical Solutions "
    "using the appointment link."
)


def _matches(
    text: str,
    patterns: tuple[re.Pattern[str], ...],
) -> bool:
    return any(
        pattern.search(text)
        for pattern in patterns
    )


def evaluate_message(message: str) -> SafetyDecision:
    """Evaluate high-priority public-chat rules before any LLM call."""

    text = str(message or "").strip()

    if _matches(text, EMERGENCY_PATTERNS):
        return SafetyDecision(
            action="emergency",
            answer=EMERGENCY_ANSWER,
            handoff_recommended=False,
        )

    if _is_sensitive_intake(text):
        return SafetyDecision(
            action="sensitive_intake",
            answer=SENSITIVE_INTAKE_ANSWER,
            handoff_recommended=False,
        )

    if _matches(text, PRESCRIBING_PATTERNS):
        return SafetyDecision(
            action="prescribing",
            answer=PRESCRIBING_ANSWER,
            handoff_recommended=False,
        )

    if _matches(text, DIAGNOSIS_PATTERNS):
        return SafetyDecision(
            action="diagnosis",
            answer=DIAGNOSIS_ANSWER,
            handoff_recommended=True,
        )

    if _matches(text, APPOINTMENT_PATTERNS):
        return SafetyDecision(
            action="appointment",
            answer=APPOINTMENT_ANSWER,
            handoff_recommended=True,
        )

    return SafetyDecision(action="allow")
