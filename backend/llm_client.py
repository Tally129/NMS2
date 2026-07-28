"""
NatMedSol AI client — Amazon Bedrock ONLY.

This module is the single AI entry point for every existing and future AI
feature in the application. Every route (SOAP drafting, forms transcription,
protocol generation, document classification, lab review, marketing drafts,
etc.) must call `complete_text()` from here instead of importing an SDK
directly.

Design goals:
  1. One provider only: Amazon Bedrock (accessed via the EC2 instance
     IAM role — never static AWS keys, never a browser call).
  2. Fail closed. If AI is disabled or Bedrock is misconfigured, we raise a
     safe RuntimeError; we do NOT silently reroute prompts elsewhere.
  3. Preserve the `complete_text()` signature so no existing caller has to be
     rewritten during this migration.
  4. Never log system prompts, user prompts, model responses, or PHI. Only
     safe metadata (feature id, model id, latency, char count, outcome).
  5. Future AI features must be able to plug in by adding a prompt template,
     not by adding new AI infrastructure. See `PromptTemplate` / `render()`.

Environment variables (non-secret; AWS credentials come from the EC2 IAM role):

    AI_ENABLED=true|false                # kill switch
    AI_PROVIDER=bedrock                  # only accepted value
    AWS_REGION=us-east-1                 # Bedrock region
    BEDROCK_MODEL_ID=...                 # e.g. anthropic.claude-sonnet-4-5-20250929-v1:0
                                         # or an inference-profile ARN
    AI_REQUEST_TIMEOUT_SECONDS=90        # per-request timeout (int)

The module deliberately imports boto3 lazily inside the Bedrock call so that
unit tests can patch `_invoke_bedrock` without needing the SDK on the path
and so that a misconfigured environment still allows the FastAPI process to
import cleanly.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nms.llm")

# --- Public constants ------------------------------------------------------ #
# Kept as an alias for backwards compatibility with existing callers that
# import `DEFAULT_ANTHROPIC_MODEL` (e.g. telehealth SOAP draft response).
# The value is whatever BEDROCK_MODEL_ID is configured to; both names now
# resolve to the same Bedrock identifier.
BEDROCK_MODEL_ID: str = os.environ.get("BEDROCK_MODEL_ID", "") or ""
DEFAULT_ANTHROPIC_MODEL: str = BEDROCK_MODEL_ID  # legacy alias — do not rename

_ALLOWED_PROVIDER = "bedrock"


# --- Provider / health reporting ------------------------------------------ #
def provider() -> str:
    """Return a safe status string for `/api/health`.

    Valid values:
        - "bedrock"        : enabled and configuration is present
        - "disabled"       : AI_ENABLED is false
        - "misconfigured"  : AI_PROVIDER != bedrock or BEDROCK_MODEL_ID missing
        - "unavailable"    : boto3 missing (deployment problem)

    Callers must NOT surface any AWS account details, IAM info, or errors
    beyond this string.
    """
    if not _ai_enabled():
        return "disabled"
    if os.environ.get("AI_PROVIDER", _ALLOWED_PROVIDER).strip().lower() != _ALLOWED_PROVIDER:
        return "misconfigured"
    if not (os.environ.get("BEDROCK_MODEL_ID") or "").strip():
        return "misconfigured"
    try:
        import boto3  # noqa: F401
    except ImportError:
        return "unavailable"
    return "bedrock"


def _ai_enabled() -> bool:
    val = os.environ.get("AI_ENABLED", "true").strip().lower()
    return val in {"1", "true", "yes", "on"}


def _request_timeout_seconds() -> int:
    try:
        return max(5, int(os.environ.get("AI_REQUEST_TIMEOUT_SECONDS", "90")))
    except (TypeError, ValueError):
        return 90


def _aws_region() -> str:
    return (os.environ.get("AWS_REGION") or "us-east-1").strip()


# --- Public entry point ---------------------------------------------------- #
async def complete_text(
    system_prompt: str,
    user_message: str,
    *,
    session_id: str = "nms",
    max_tokens: int = 4096,
    temperature: float = 0.2,
) -> str:
    """Return the assistant text for a single-turn prompt.

    Sends the request through Amazon Bedrock (Converse API) using the EC2
    instance IAM role. Never falls back to another provider. Never logs the
    prompt or the response.

    Raises:
        RuntimeError with a safe category token as its message, e.g.
            "ai_disabled", "bedrock_misconfigured", "bedrock_unavailable",
            "model_access_denied", "request_timeout", "invalid_model_response".
        The caller is expected to translate this into an HTTP error without
        exposing the underlying AWS exception to the client.
    """
    status = provider()
    if status == "disabled":
        raise RuntimeError("ai_disabled")
    if status == "misconfigured":
        raise RuntimeError("bedrock_misconfigured")
    if status == "unavailable":
        raise RuntimeError("bedrock_unavailable")

    request_id = uuid.uuid4().hex[:12]
    started = time.monotonic()
    try:
        text = await asyncio.wait_for(
            asyncio.to_thread(
                _invoke_bedrock,
                system_prompt,
                user_message,
                max_tokens,
                temperature,
            ),
            timeout=_request_timeout_seconds(),
        )
    except asyncio.TimeoutError:
        logger.warning(
            "llm.timeout req=%s feature=%s model=%s",
            request_id, session_id, BEDROCK_MODEL_ID,
        )
        raise RuntimeError("request_timeout")
    except RuntimeError:
        # Already a safe category — re-raise untouched.
        raise
    except Exception as exc:  # boto3 ClientError etc. — never surface raw
        category = _classify_bedrock_error(exc)
        logger.warning(
            "llm.error req=%s feature=%s model=%s category=%s exc=%s",
            request_id, session_id, BEDROCK_MODEL_ID,
            category, type(exc).__name__,
        )
        raise RuntimeError(category)

    latency_ms = int((time.monotonic() - started) * 1000)
    # SAFE metadata only. Never log prompts or responses.
    logger.info(
        "llm.ok req=%s feature=%s provider=bedrock model=%s latency_ms=%d chars_out=%d",
        request_id, session_id, BEDROCK_MODEL_ID, latency_ms, len(text or ""),
    )
    return text


# --- Bedrock invocation (synchronous — runs in a thread) ------------------ #
def _invoke_bedrock(
    system_prompt: str,
    user_message: str,
    max_tokens: int,
    temperature: float,
) -> str:
    """Synchronous Bedrock Converse call. Runs inside `asyncio.to_thread`.

    Uses the EC2 instance IAM role (boto3 default credential chain). Do not
    pass access keys here — none should ever exist in the process env.
    """
    try:
        import boto3
        from botocore.config import Config as BotoConfig
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("bedrock_unavailable") from exc

    region = _aws_region()
    timeout = _request_timeout_seconds()
    boto_config = BotoConfig(
        region_name=region,
        connect_timeout=min(30, timeout),
        read_timeout=timeout,
        retries={"max_attempts": 2, "mode": "standard"},
    )
    client = boto3.client("bedrock-runtime", config=boto_config)

    # Prefer the Converse API when available (boto3 >= 1.34). It normalises
    # the request/response shape across supported Bedrock models.
    if hasattr(client, "converse"):
        response = client.converse(
            modelId=BEDROCK_MODEL_ID,
            system=[{"text": system_prompt}] if system_prompt else [],
            messages=[{"role": "user", "content": [{"text": user_message}]}],
            inferenceConfig={
                "maxTokens": int(max_tokens),
                "temperature": float(temperature),
            },
        )
        return _extract_converse_text(response)

    # Fallback: legacy invoke_model path (Anthropic-native message schema).
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
        "system": system_prompt or "",
        "messages": [{"role": "user", "content": user_message}],
    }
    raw = client.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )
    payload = raw.get("body")
    if hasattr(payload, "read"):
        payload = payload.read()
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError("invalid_model_response") from exc
    return _extract_invoke_text(payload)


def _extract_converse_text(response: Dict[str, Any]) -> str:
    """Concatenate every text content block returned by the Converse API."""
    parts: List[str] = []
    try:
        message = (response.get("output") or {}).get("message") or {}
        for block in message.get("content") or []:
            text = block.get("text")
            if text:
                parts.append(text)
    except AttributeError:
        pass
    return "".join(parts).strip()


def _extract_invoke_text(payload: Dict[str, Any]) -> str:
    """Concatenate every text block from a legacy Anthropic-on-Bedrock body."""
    parts: List[str] = []
    for block in payload.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if text:
                parts.append(text)
    return "".join(parts).strip()


def _classify_bedrock_error(exc: Exception) -> str:
    """Map a boto3/botocore exception onto a safe category token."""
    name = type(exc).__name__
    text = str(exc).lower()
    if "accessdenied" in name.lower() or "access denied" in text or "not authorized" in text:
        return "model_access_denied"
    if "throttl" in name.lower() or "throttl" in text or "too many requests" in text:
        return "bedrock_unavailable"
    if "resourcenotfound" in name.lower() or "modelnotready" in name.lower():
        return "bedrock_misconfigured"
    if "validation" in name.lower():
        return "bedrock_misconfigured"
    if "timeout" in name.lower() or "timed out" in text:
        return "request_timeout"
    if "credentials" in name.lower() or "nocredentials" in name.lower():
        return "bedrock_misconfigured"
    return "bedrock_unavailable"


# --- Future-feature helper: prompt templates ------------------------------ #
# Kept intentionally tiny. Feature routers add a template and call
# `run_template()`; they never touch Bedrock directly.
@dataclass(frozen=True)
class PromptTemplate:
    """Describes one AI feature's system prompt.

    Only a system prompt lives here. The user-facing payload is built by the
    feature router because it varies (minimum-necessary rules, JSON envelope,
    guardrails, etc.). Keeping the template dataclass immutable means all
    routers share one AI entry point without wrapping Bedrock in per-feature
    services.
    """
    feature: str
    system: str
    max_tokens: int = 4096
    temperature: float = 0.2


async def run_template(
    template: PromptTemplate,
    user_message: str,
    *,
    session_id: Optional[str] = None,
) -> str:
    """Convenience wrapper. New AI features should call this."""
    return await complete_text(
        template.system,
        user_message,
        session_id=session_id or f"{template.feature}",
        max_tokens=template.max_tokens,
        temperature=template.temperature,
    )


def safe_extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort JSON extraction for structured-output features.

    Bedrock models sometimes wrap JSON in markdown fences or add leading
    prose. This helper strips fences and parses the first top-level object.
    Returns None on failure — callers must translate that into a safe
    `invalid_model_response` / `output_validation_failed` error.
    """
    if not text:
        return None
    trimmed = text.strip()
    # Strip ``` and ```json fences
    if trimmed.startswith("```"):
        trimmed = trimmed[3:]
        if trimmed[:4].lower() == "json":
            trimmed = trimmed[4:]
        # Everything up to the closing fence is our candidate JSON.
        closing = trimmed.rfind("```")
        if closing >= 0:
            trimmed = trimmed[:closing]
        trimmed = trimmed.strip()
    # Direct parse
    try:
        obj = json.loads(trimmed)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    # Fallback: extract the first {...} block
    start = trimmed.find("{")
    end = trimmed.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(trimmed[start:end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None
