"""AWS HealthScribe integration for telehealth clinical documentation.

The service starts and polls Medical Scribe jobs. It does not finalize
clinical documentation; generated material remains provider-reviewable.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Dict, Optional
async def normalize_recording_to_flac(
    contents: bytes,
) -> bytes:
    """Convert browser MediaRecorder WebM/Opus to finalized FLAC.

    The source and converted audio remain in memory. No temporary
    PHI-bearing audio file is written to the local filesystem.
    """
    if not contents:
        raise RuntimeError("empty_recording")

    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "48000",
        "-c:a",
        "flac",
        "-f",
        "flac",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await process.communicate(
        input=contents,
    )

    if process.returncode != 0:
        error = stderr.decode(
            "utf-8",
            errors="replace",
        ).strip()

        raise RuntimeError(
            f"recording_normalization_failed: {error[:1000]}"
        )

    if not stdout:
        raise RuntimeError(
            "recording_normalization_empty_output"
        )

    return stdout

def _region() -> str:
    return (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or "us-east-1"
    )


def _config() -> Dict[str, str]:
    enabled = (
        os.environ.get("HEALTHSCRIBE_ENABLED", "")
        .strip()
        .lower()
        in {"1", "true", "yes", "on"}
    )

    if not enabled:
        raise RuntimeError("healthscribe_disabled")

    role_arn = os.environ.get(
        "HEALTHSCRIBE_DATA_ACCESS_ROLE_ARN", ""
    ).strip()

    output_bucket = os.environ.get(
        "HEALTHSCRIBE_OUTPUT_BUCKET", ""
    ).strip()

    kms_key = os.environ.get(
        "HEALTHSCRIBE_OUTPUT_KMS_KEY_ID", ""
    ).strip()

    if not role_arn or not output_bucket:
        raise RuntimeError("healthscribe_misconfigured")

    return {
        "role_arn": role_arn,
        "output_bucket": output_bucket,
        "kms_key": kms_key,
    }


def _client():
    try:
        import boto3
    except Exception as exc:
        raise RuntimeError(
            "healthscribe_unavailable"
        ) from exc

    return boto3.client(
        "transcribe",
        region_name=_region(),
    )


def build_job_name(
    appointment_id: str,
    recording_id: str,
) -> str:
    raw = (
        f"nms-{appointment_id}-{recording_id}"
    )

    # HealthScribe job names only allow
    # letters, digits, period, underscore and hyphen.
    cleaned = re.sub(
        r"[^0-9A-Za-z._-]",
        "-",
        raw,
    )

    return cleaned[:200]


async def start_job(
    *,
    appointment_id: str,
    recording_id: str,
    media_s3_uri: str,
) -> Dict[str, Any]:
    cfg = _config()
    job_name = build_job_name(
        appointment_id,
        recording_id,
    )

    request: Dict[str, Any] = {
        "MedicalScribeJobName": job_name,
        "Media": {
            "MediaFileUri": media_s3_uri,
        },
        "OutputBucketName": cfg["output_bucket"],
        "DataAccessRoleArn": cfg["role_arn"],
        "Settings": {
            "ShowSpeakerLabels": True,
            "MaxSpeakerLabels": 2,
            "ClinicalNoteGenerationSettings": {
                "NoteTemplate": "PHYSICAL_SOAP",
            },
        },
        "Tags": [
            {
                "Key": "Application",
                "Value": "NatMedSol",
            },
            {
                "Key": "Feature",
                "Value": "TelehealthSOAP",
            },
        ],
    }

    if cfg["kms_key"]:
        request[
            "OutputEncryptionKMSKeyId"
        ] = cfg["kms_key"]

    client = _client()

    try:
        response = await asyncio.to_thread(
            client.start_medical_scribe_job,
            **request,
        )
    except client.exceptions.ConflictException:
        # Idempotent behavior: if the same recording was
        # already submitted, return the existing job.
        response = await asyncio.to_thread(
            client.get_medical_scribe_job,
            MedicalScribeJobName=job_name,
        )

    job = response.get(
        "MedicalScribeJob", {}
    )

    return {
        "job_name": job_name,
        "status": job.get(
            "MedicalScribeJobStatus",
            "IN_PROGRESS",
        ),
        "media_s3_uri": media_s3_uri,
    }


async def get_job(
    job_name: str,
) -> Dict[str, Any]:
    _config()
    client = _client()

    response = await asyncio.to_thread(
        client.get_medical_scribe_job,
        MedicalScribeJobName=job_name,
    )

    job = response.get(
        "MedicalScribeJob", {}
    )

    output = job.get(
        "MedicalScribeOutput", {}
    ) or {}

    return {
        "job_name": job_name,
        "status": job.get(
            "MedicalScribeJobStatus",
            "UNKNOWN",
        ),
        "failure_reason": job.get(
            "FailureReason"
        ),
        "transcript_uri": output.get(
            "TranscriptFileUri"
        ),
        "clinical_document_uri": output.get(
            "ClinicalDocumentUri"
        ),
    }


def _parse_s3_uri(uri: str):
    """Parse HealthScribe S3 output references.

    AWS may return either:
      s3://bucket/key
    or:
      https://s3.REGION.amazonaws.com/bucket/key
      https://bucket.s3.REGION.amazonaws.com/key
    """
    if not uri:
        raise RuntimeError(
            "invalid_healthscribe_output_uri"
        )

    if uri.startswith("s3://"):
        remainder = uri[5:]
        bucket, _, key = remainder.partition("/")

        if not bucket or not key:
            raise RuntimeError(
                "invalid_healthscribe_output_uri"
            )

        return bucket, key

    if uri.startswith(
        ("https://", "http://")
    ):
        from urllib.parse import urlparse

        parsed = urlparse(uri)
        host = parsed.netloc
        path = parsed.path.lstrip("/")

        # Path-style S3 URL:
        # s3.REGION.amazonaws.com/bucket/key
        if (
            host == "s3.amazonaws.com"
            or host.startswith("s3.")
        ):
            bucket, _, key = path.partition("/")

            if bucket and key:
                return bucket, key

        # Virtual-hosted S3 URL:
        # bucket.s3.REGION.amazonaws.com/key
        if ".s3." in host:
            bucket = host.split(".s3.", 1)[0]

            if bucket and path:
                return bucket, path

    raise RuntimeError(
        "invalid_healthscribe_output_uri"
    )


async def read_json_from_s3(
    uri: str,
) -> Dict[str, Any]:
    bucket, key = _parse_s3_uri(uri)

    try:
        import boto3
    except Exception as exc:
        raise RuntimeError(
            "healthscribe_unavailable"
        ) from exc

    s3 = boto3.client(
        "s3",
        region_name=_region(),
    )

    response = await asyncio.to_thread(
        s3.get_object,
        Bucket=bucket,
        Key=key,
    )

    body = await asyncio.to_thread(
        response["Body"].read
    )

    return json.loads(
        body.decode("utf-8")
    )



def clinical_document_to_soap(
    clinical_document: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    """Normalize a HealthScribe PHYSICAL_SOAP document.

    AWS returns:
      ClinicalDocumentation -> Sections -> Summary ->
      SummarizedSegment

    Keep this AWS-specific parsing in the backend so the
    React client receives a stable SOAP contract.
    """
    soap = {
        "subjective": "",
        "objective": "",
        "assessment": "",
        "plan": "",
    }

    if not isinstance(clinical_document, dict):
        return soap

    documentation = (
        clinical_document.get(
            "ClinicalDocumentation"
        )
        or {}
    )

    sections = documentation.get("Sections") or []

    mapping = {
        "SUBJECTIVE": "subjective",
        "OBJECTIVE": "objective",
        "ASSESSMENT": "assessment",
        "PLAN": "plan",
    }

    for section in sections:
        if not isinstance(section, dict):
            continue

        section_name = str(
            section.get("SectionName") or ""
        ).upper()

        target = mapping.get(section_name)

        if not target:
            continue

        pieces = []

        for summary in (
            section.get("Summary") or []
        ):
            if not isinstance(summary, dict):
                continue

            segment = str(
                summary.get(
                    "SummarizedSegment"
                )
                or ""
            ).strip()

            if segment:
                pieces.append(segment)

        soap[target] = "\n".join(pieces)[:4000]

    return soap


async def get_completed_outputs(
    job_name: str,
) -> Dict[str, Any]:
    job = await get_job(job_name)

    if job["status"] != "COMPLETED":
        return {
            **job,
            "transcript": None,
            "clinical_document": None,
            "soap_draft": None,
        }

    transcript = None
    clinical_document = None

    if job.get("transcript_uri"):
        transcript = await read_json_from_s3(
            job["transcript_uri"]
        )

    if job.get("clinical_document_uri"):
        clinical_document = (
            await read_json_from_s3(
                job["clinical_document_uri"]
            )
        )

    soap_draft = clinical_document_to_soap(
        clinical_document
    )

    return {
        **job,
        "transcript": transcript,
        "clinical_document": clinical_document,
        "soap_draft": soap_draft,
    }
