"""Shared AI lab-report transcription and extraction service.

This service accepts text extracted from an uploaded lab report and returns:
- full report transcription;
- report metadata;
- structured analytes;
- AI confidence and verification warnings.

It never creates verified lab values, assigns a patient, approves a report,
or releases results to the patient portal.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from llm_client import PromptTemplate, run_template, safe_extract_json


LAB_REPORT_EXTRACTION_TEMPLATE = PromptTemplate(
    feature="lab_report_extraction",
    system=(
        "You are a laboratory-report transcription assistant. Extract only "
        "information visibly present in the supplied report text. Never infer, "
        "calculate, diagnose, interpret clinically, or invent missing values. "
        "Preserve the full report text and extract every identifiable analyte. "
        "A licensed provider must review all extracted data before it is added "
        "to a patient chart.\n\n"

        "Return STRICT JSON only, without markdown fences, using exactly this "
        "top-level structure:\n"
        "{\n"
        '  "report_title": "",\n'
        '  "laboratory_name": "",\n'
        '  "patient_name_on_report": "",\n'
        '  "patient_dob_on_report": "",\n'
        '  "ordering_provider": "",\n'
        '  "accession_number": "",\n'
        '  "collection_date": "",\n'
        '  "reported_date": "",\n'
        '  "full_report_text": "",\n'
        '  "report_sections": [\n'
        '    {"title": "", "text": ""}\n'
        "  ],\n"
        '  "results": [\n'
        "    {\n"
        '      "panel_name": "",\n'
        '      "test_name": "",\n'
        '      "value_text": "",\n'
        '      "numeric_value": null,\n'
        '      "unit": "",\n'
        '      "reference_low": null,\n'
        '      "reference_high": null,\n'
        '      "reference_text": "",\n'
        '      "flag": "high|low|normal|abnormal|critical|unknown",\n'
        '      "status": "",\n'
        '      "comments": "",\n'
        '      "source_page": null,\n'
        '      "confidence": 0.0\n'
        "    }\n"
        "  ],\n"
        '  "critical_or_abnormal_text": [],\n'
        '  "unparsed_lines": [],\n'
        '  "document_confidence": 0.0,\n'
        '  "warnings": [],\n'
        '  "provider_review_required": true\n'
        "}\n\n"

        "Rules:\n"
        "1. Include every visible test result, including normal values.\n"
        "2. Keep value_text exactly as represented when possible.\n"
        "3. numeric_value must be a JSON number only when clearly numeric; "
        "otherwise use null.\n"
        "4. Reference limits must be numbers only when clearly represented; "
        "preserve the original range in reference_text.\n"
        "5. Do not classify a result as normal when no reference range or flag "
        "is present; use unknown.\n"
        "6. Preserve laboratory comments, footnotes, specimen information, and "
        "interpretive text in report_sections or comments.\n"
        "7. Put unreadable, ambiguous, or unmatched text into unparsed_lines.\n"
        "8. Confidence values must be between 0 and 1.\n"
        "9. provider_review_required must always be true.\n"
        "10. Do not provide treatment recommendations or medical diagnoses."
    ),
    max_tokens=8192,
    temperature=0.0,
)


def _clean_text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None

    if isinstance(value, bool):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _confidence(value: Any) -> float:
    parsed = _optional_float(value)

    if parsed is None:
        return 0.0

    return max(0.0, min(parsed, 1.0))


def _optional_page(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None

    return parsed if parsed > 0 else None


def _string_list(value: Any, *, item_limit: int = 1000,
                 max_items: int = 300) -> List[str]:
    if not isinstance(value, list):
        return []

    output: List[str] = []

    for item in value[:max_items]:
        text = _clean_text(item, item_limit)
        if text:
            output.append(text)

    return output


def validate_lab_report_extraction(
    data: Optional[Dict[str, Any]],
    *,
    extracted_text: str,
) -> Dict[str, Any]:
    """Coerce the model response into the approved extraction envelope."""
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "invalid_lab_extraction",
                "message": "The AI lab transcription could not be parsed.",
            },
        )

    sections = []

    for row in data.get("report_sections") or []:
        if not isinstance(row, dict):
            continue

        title = _clean_text(row.get("title"), 300)
        text = _clean_text(row.get("text"), 12000)

        if title or text:
            sections.append({
                "title": title,
                "text": text,
            })

    allowed_flags = {
        "high",
        "low",
        "normal",
        "abnormal",
        "critical",
        "unknown",
    }

    results = []

    for row in data.get("results") or []:
        if not isinstance(row, dict):
            continue

        test_name = _clean_text(row.get("test_name"), 300)

        if not test_name:
            continue

        flag = _clean_text(row.get("flag"), 30).lower()

        if flag not in allowed_flags:
            flag = "unknown"

        results.append({
            "id": f"result-{len(results) + 1}",
            "panel_name": _clean_text(row.get("panel_name"), 300),
            "test_name": test_name,
            "value_text": _clean_text(row.get("value_text"), 300),
            "numeric_value": _optional_float(row.get("numeric_value")),
            "unit": _clean_text(row.get("unit"), 100),
            "reference_low": _optional_float(row.get("reference_low")),
            "reference_high": _optional_float(row.get("reference_high")),
            "reference_text": _clean_text(
                row.get("reference_text"),
                300,
            ),
            "flag": flag,
            "status": _clean_text(row.get("status"), 120),
            "comments": _clean_text(row.get("comments"), 3000),
            "source_page": _optional_page(row.get("source_page")),
            "confidence": _confidence(row.get("confidence")),
            "provider_verified": False,
        })

    model_full_text = _clean_text(
        data.get("full_report_text"),
        100000,
    )

    # The deterministic extraction remains the source of truth. The AI can
    # improve formatting, but it must not remove the original extracted text.
    full_report_text = model_full_text or extracted_text[:100000]

    warnings = _string_list(
        data.get("warnings"),
        item_limit=1000,
        max_items=100,
    )

    warnings.extend([
        "AI transcription is unverified.",
        "Confirm patient identity before assignment.",
        "A practitioner must verify every result before chart release.",
    ])

    return {
        "report_title": _clean_text(data.get("report_title"), 500),
        "laboratory_name": _clean_text(data.get("laboratory_name"), 500),
        "patient_name_on_report": _clean_text(
            data.get("patient_name_on_report"),
            500,
        ),
        "patient_dob_on_report": _clean_text(
            data.get("patient_dob_on_report"),
            100,
        ),
        "ordering_provider": _clean_text(
            data.get("ordering_provider"),
            500,
        ),
        "accession_number": _clean_text(
            data.get("accession_number"),
            300,
        ),
        "collection_date": _clean_text(
            data.get("collection_date"),
            100,
        ),
        "reported_date": _clean_text(
            data.get("reported_date"),
            100,
        ),
        "full_report_text": full_report_text,
        "raw_extracted_text": extracted_text[:100000],
        "report_sections": sections,
        "results": results,
        "critical_or_abnormal_text": _string_list(
            data.get("critical_or_abnormal_text"),
            item_limit=2000,
            max_items=200,
        ),
        "unparsed_lines": _string_list(
            data.get("unparsed_lines"),
            item_limit=2000,
            max_items=500,
        ),
        "document_confidence": _confidence(
            data.get("document_confidence")
        ),
        "warnings": list(dict.fromkeys(warnings)),
        "provider_review_required": True,
        "verified": False,
        "extraction_status": "ai_transcribed",
        "extracted_at": datetime.utcnow().isoformat() + "Z",
    }


async def transcribe_lab_report(
    *,
    extracted_text: str,
    source_filename: str,
    session_id: str,
) -> Dict[str, Any]:
    """Transcribe a complete lab report from deterministic extracted text."""
    text = str(extracted_text or "").strip()

    if len(text) < 30:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "insufficient_report_text",
                "message": (
                    "The report did not contain enough readable text. "
                    "A scanned report may require OCR."
                ),
            },
        )

    if len(text) > 100000:
        text = text[:100000]

    prompt = f"""SOURCE FILE
{source_filename or "uploaded-lab-report"}

EXTRACTED LAB REPORT TEXT
{text}

Transcribe the full report and extract every visible laboratory result.
Return strict JSON only.
"""

    try:
        raw = await run_template(
            LAB_REPORT_EXTRACTION_TEMPLATE,
            prompt,
            session_id=session_id,
        )
    except RuntimeError as exc:
        code = str(exc)

        status = 503 if code in {
            "ai_disabled",
            "bedrock_misconfigured",
            "bedrock_unavailable",
            "model_access_denied",
            "request_timeout",
        } else 502

        raise HTTPException(
            status_code=status,
            detail={"code": code},
        )

    return validate_lab_report_extraction(
        safe_extract_json(raw),
        extracted_text=text,
    )
