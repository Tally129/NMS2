"""Shared AI SOAP drafting service.

Produces editable drafts only. It never saves, signs, or finalizes notes.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from llm_client import DEFAULT_ANTHROPIC_MODEL, complete_text, provider


def _compact(value: Any, limit: int = 1800) -> str:
    if value in (None, "", {}, []):
        return ""

    if isinstance(value, str):
        return value[:limit]

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            default=str,
        )[:limit]
    except Exception:
        return str(value)[:limit]


def _intake_summary(
    intake: Optional[Dict[str, Any]],
) -> str:
    if not intake:
        return ""

    sections = []

    for key, label in (
        ("demographics", "Demographics"),
        ("health_history", "Health history"),
        ("symptoms", "Symptoms"),
        ("lifestyle", "Lifestyle"),
        ("consent", "Consent"),
    ):
        value = intake.get(key)

        if value:
            sections.append(
                f"{label}: {_compact(value, 1400)}"
            )

    return "\n".join(sections)[:5000]


async def generate_soap_draft(
    *,
    client: Dict[str, Any],
    intake: Optional[Dict[str, Any]] = None,
    last_note: Optional[Dict[str, Any]] = None,
    encounter_text: str = "",
    template: Optional[Dict[str, Any]] = None,
    session_id: str,
) -> Dict[str, Any]:
    """Generate an editable SOAP draft from supplied chart context."""
    encounter_text = str(encounter_text or "").strip()

    if not encounter_text:
        raise ValueError("Encounter notes are required")

    encounter_text = encounter_text[:12000]

    system_message = (
        "You are a clinical-documentation assistant helping an authorized "
        "wellness practitioner prepare an editable SOAP-note draft. "
        "Output strict JSON only with exactly these keys: "
        "subjective, objective, assessment, and plan. "
        "Keep each section under 350 words. "
        "Use only facts supplied in the prompt. "
        "Do not invent vitals, medications, examination findings, diagnoses, "
        "test results, or patient statements. "
        "Clearly identify information that needs clinician verification. "
        "The responsible practitioner must review this draft before it is "
        "saved or finalized."
    )

    patient_summary = (
        f"Patient name: {client.get('full_name') or 'Not provided'}\n"
        f"MRN: {client.get('mrn') or 'Not provided'}\n"
        f"Pronouns: {client.get('pronouns') or 'Not provided'}\n"
        f"Primary concern: "
        f"{client.get('primary_concern') or 'Not provided'}\n"
        f"Wellness goals: "
        f"{client.get('wellness_goals') or 'Not provided'}\n"
        f"Allergies: {client.get('allergies') or 'Not provided'}\n"
        f"Current supplements: "
        f"{client.get('current_supplements') or 'Not provided'}"
    )

    previous_note = ""
    if last_note:
        previous_note = (
            f"Subjective: "
            f"{(last_note.get('subjective') or '')[:1000]}\n"
            f"Objective: "
            f"{(last_note.get('objective') or '')[:1000]}\n"
            f"Assessment: "
            f"{(last_note.get('assessment') or '')[:1000]}\n"
            f"Plan: "
            f"{(last_note.get('plan') or '')[:1000]}"
        )

    template_summary = ""
    if template:
        template_summary = (
            f"Template title: {template.get('title') or ''}\n"
            f"Subjective guidance: "
            f"{(template.get('subjective') or '')[:800]}\n"
            f"Objective guidance: "
            f"{(template.get('objective') or '')[:800]}\n"
            f"Assessment guidance: "
            f"{(template.get('assessment') or '')[:800]}\n"
            f"Plan guidance: "
            f"{(template.get('plan') or '')[:800]}"
        )

    prompt = f"""PATIENT SUMMARY
{patient_summary}

STRUCTURED INTAKE
{_intake_summary(intake) or "No structured intake is available."}

PREVIOUS SOAP NOTE
{previous_note or "No previous SOAP note is available."}

SELECTED SOAP TEMPLATE
{template_summary or "No SOAP template was selected."}

TODAY'S ENCOUNTER NOTES OR TRANSCRIPT
{encounter_text}

Create an editable SOAP-note draft as strict JSON only.
"""

    response = await complete_text(
        system_message,
        prompt,
        session_id=session_id,
    )

    match = re.search(r"\{.*\}", response, re.DOTALL)

    if not match:
        raise ValueError("AI returned no JSON object")

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError("AI returned invalid JSON") from exc

    return {
        "subjective": str(
            data.get("subjective") or ""
        )[:6000],
        "objective": str(
            data.get("objective") or ""
        )[:6000],
        "assessment": str(
            data.get("assessment") or ""
        )[:6000],
        "plan": str(
            data.get("plan") or ""
        )[:6000],
        "source": "ai_draft",
        "model": DEFAULT_ANTHROPIC_MODEL,
        "provider": provider(),
        "requires_clinician_review": True,
    }
