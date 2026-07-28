"""
Sprint: Standardize on Amazon Bedrock
Unit tests for `backend/llm_client.py`.

These tests are hermetic — they never talk to AWS. They patch the Bedrock
invocation inside `llm_client` to verify:

  * Bedrock is the ONLY supported provider (no Anthropic/Emergent code path).
  * `AI_PROVIDER` values other than `bedrock` fail closed.
  * The `complete_text()` signature is preserved for existing callers.
  * boto3 calls run through `asyncio.to_thread` (event loop stays free).
  * Static AWS keys are never required for import or invocation.
  * Prompts and responses are never written to the application logger.
  * Bedrock errors are mapped onto safe category tokens — no raw AWS text.
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import os
import sys
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest


BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


@contextmanager
def env(**overrides):
    """Temporarily replace env vars, then reload llm_client so its module-level
    `BEDROCK_MODEL_ID` alias picks up the new value."""
    saved = {k: os.environ.get(k) for k in overrides}
    for k, v in overrides.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    # Ensure static AWS creds are absent — IAM role only.
    for banned in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        saved.setdefault(banned, os.environ.get(banned))
        os.environ.pop(banned, None)
    if "llm_client" in sys.modules:
        importlib.reload(sys.modules["llm_client"])
    try:
        yield importlib.import_module("llm_client")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if "llm_client" in sys.modules:
            importlib.reload(sys.modules["llm_client"])


# ---------------------------------------------------------------- provider() #

class TestProviderReporting:
    def test_bedrock_when_configured(self):
        with env(AI_ENABLED="true", AI_PROVIDER="bedrock",
                 BEDROCK_MODEL_ID="anthropic.claude-sonnet-4-5-20250929-v1:0",
                 AWS_REGION="us-east-1") as m:
            assert m.provider() == "bedrock"

    def test_disabled_when_kill_switch(self):
        with env(AI_ENABLED="false", AI_PROVIDER="bedrock",
                 BEDROCK_MODEL_ID="x") as m:
            assert m.provider() == "disabled"

    def test_misconfigured_when_no_model(self):
        with env(AI_ENABLED="true", AI_PROVIDER="bedrock",
                 BEDROCK_MODEL_ID="") as m:
            assert m.provider() == "misconfigured"

    def test_misconfigured_when_wrong_provider_string(self):
        # Any value other than 'bedrock' must fail closed.
        for bad in ("anthropic", "emergent", "openai", "azure", "fallback"):
            with env(AI_ENABLED="true", AI_PROVIDER=bad,
                     BEDROCK_MODEL_ID="x") as m:
                assert m.provider() == "misconfigured", bad


# ------------------------------------------------------------- complete_text #

class TestCompleteTextRouting:
    def test_signature_preserved(self):
        """`complete_text` keeps its documented keyword args so the existing
        SOAP / forms / protocol routes do not need to be rewritten."""
        with env(AI_ENABLED="true", AI_PROVIDER="bedrock",
                 BEDROCK_MODEL_ID="x") as m:
            import inspect
            sig = inspect.signature(m.complete_text)
            names = list(sig.parameters.keys())
            assert names[:2] == ["system_prompt", "user_message"]
            for kw in ("session_id", "max_tokens", "temperature"):
                assert kw in sig.parameters, kw

    def test_disabled_raises_ai_disabled(self):
        with env(AI_ENABLED="false", AI_PROVIDER="bedrock",
                 BEDROCK_MODEL_ID="x") as m:
            with pytest.raises(RuntimeError) as exc:
                asyncio.run(m.complete_text("sys", "hi"))
            assert str(exc.value) == "ai_disabled"

    def test_misconfigured_raises_bedrock_misconfigured(self):
        with env(AI_ENABLED="true", AI_PROVIDER="bedrock",
                 BEDROCK_MODEL_ID="") as m:
            with pytest.raises(RuntimeError) as exc:
                asyncio.run(m.complete_text("sys", "hi"))
            assert str(exc.value) == "bedrock_misconfigured"

    def test_wrong_provider_string_fails_closed(self):
        with env(AI_ENABLED="true", AI_PROVIDER="anthropic",
                 BEDROCK_MODEL_ID="x") as m:
            with pytest.raises(RuntimeError) as exc:
                asyncio.run(m.complete_text("sys", "hi"))
            assert str(exc.value) == "bedrock_misconfigured"

    def test_happy_path_calls_bedrock_only(self):
        """A successful call must invoke `_invoke_bedrock` exactly once and
        return the text unchanged. No other provider must ever be reached."""
        with env(AI_ENABLED="true", AI_PROVIDER="bedrock",
                 BEDROCK_MODEL_ID="x") as m:
            with patch.object(m, "_invoke_bedrock",
                              return_value="hello from bedrock") as spy:
                out = asyncio.run(m.complete_text("sys", "hi"))
            assert out == "hello from bedrock"
            spy.assert_called_once()

    def test_runs_in_thread_not_blocking_loop(self):
        """`_invoke_bedrock` is synchronous; verify the wrapper dispatches it
        via `asyncio.to_thread` so the FastAPI event loop is never blocked."""
        with env(AI_ENABLED="true", AI_PROVIDER="bedrock",
                 BEDROCK_MODEL_ID="x") as m:
            with patch("llm_client.asyncio.to_thread",
                       wraps=asyncio.to_thread) as spy, \
                 patch.object(m, "_invoke_bedrock", return_value="ok"):
                asyncio.run(m.complete_text("sys", "hi"))
            assert spy.called, "complete_text must dispatch through asyncio.to_thread"

    def test_bedrock_client_error_returns_safe_category(self):
        with env(AI_ENABLED="true", AI_PROVIDER="bedrock",
                 BEDROCK_MODEL_ID="x") as m:
            class AccessDeniedException(Exception):
                pass

            def boom(*a, **kw):
                raise AccessDeniedException("User is not authorized to invoke model")

            with patch.object(m, "_invoke_bedrock", side_effect=boom):
                with pytest.raises(RuntimeError) as exc:
                    asyncio.run(m.complete_text("sys", "hi"))
            # Safe token, no AWS internals leaked
            assert str(exc.value) == "model_access_denied"


# --------------------------------------------------------------- no old code #

class TestNoLegacyProviders:
    def test_module_source_has_no_anthropic_or_emergent(self):
        with env(AI_ENABLED="true", AI_PROVIDER="bedrock",
                 BEDROCK_MODEL_ID="x") as m:
            src = open(m.__file__, "r", encoding="utf-8").read().lower()
        assert "anthropic_api_key" not in src
        assert "emergent_llm_key" not in src
        assert "emergentintegrations" not in src
        assert "from anthropic" not in src
        assert "asyncanthropic" not in src

    def test_no_static_aws_credentials_required(self):
        """Import + invocation must succeed with NO AWS_ACCESS_KEY_ID etc."""
        with env(AI_ENABLED="true", AI_PROVIDER="bedrock",
                 BEDROCK_MODEL_ID="x") as m:
            for banned in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
                           "AWS_SESSION_TOKEN"):
                assert banned not in os.environ
            with patch.object(m, "_invoke_bedrock", return_value="ok"):
                assert asyncio.run(m.complete_text("sys", "hi")) == "ok"


# ------------------------------------------------------- safe-logging checks #

class TestSafeLogging:
    def test_no_prompt_or_response_in_logs(self, caplog):
        """The client is allowed to log latency + char count but MUST NOT log
        the system prompt, the user message, or the model response."""
        secret_prompt = "PATIENT NAME: Jane Doe, DOB 1980-01-01 SOAP notes ..."
        secret_user = "SSN 123-45-6789 lab result 987"
        secret_reply = "Confidential clinical answer for Jane Doe"

        with env(AI_ENABLED="true", AI_PROVIDER="bedrock",
                 BEDROCK_MODEL_ID="x") as m:
            with caplog.at_level(logging.DEBUG, logger="nms.llm"), \
                 patch.object(m, "_invoke_bedrock", return_value=secret_reply):
                asyncio.run(m.complete_text(secret_prompt, secret_user,
                                            session_id="feature.test"))

        for rec in caplog.records:
            msg = rec.getMessage()
            assert "Jane Doe" not in msg
            assert "SSN" not in msg
            assert "123-45-6789" not in msg
            assert "Confidential" not in msg
            assert secret_prompt not in msg
            assert secret_user not in msg
            assert secret_reply not in msg
        # Confirm at least one metadata line landed.
        assert any("llm.ok" in r.getMessage() for r in caplog.records)


# --------------------------------------------------- safe JSON extract helper #

class TestSafeJsonExtract:
    def test_plain_json(self):
        with env(AI_ENABLED="true", AI_PROVIDER="bedrock",
                 BEDROCK_MODEL_ID="x") as m:
            assert m.safe_extract_json('{"a": 1}') == {"a": 1}

    def test_markdown_fence(self):
        with env(AI_ENABLED="true", AI_PROVIDER="bedrock",
                 BEDROCK_MODEL_ID="x") as m:
            wrapped = '```json\n{"summary": "ok"}\n```'
            assert m.safe_extract_json(wrapped) == {"summary": "ok"}

    def test_invalid_returns_none(self):
        with env(AI_ENABLED="true", AI_PROVIDER="bedrock",
                 BEDROCK_MODEL_ID="x") as m:
            assert m.safe_extract_json("not json at all") is None
            assert m.safe_extract_json("") is None


# ----------------------------------------------- prompt-template convenience #

class TestPromptTemplateHelper:
    def test_run_template_uses_complete_text(self):
        with env(AI_ENABLED="true", AI_PROVIDER="bedrock",
                 BEDROCK_MODEL_ID="x") as m:
            tmpl = m.PromptTemplate(
                feature="lab_review",
                system="You are a lab review assistant.",
                max_tokens=1024,
                temperature=0.1,
            )
            spy = AsyncMock(return_value="draft-json")
            with patch.object(m, "complete_text", spy):
                out = asyncio.run(m.run_template(tmpl, "user context"))
            assert out == "draft-json"
            spy.assert_called_once()
            kwargs = spy.call_args.kwargs
            assert kwargs["max_tokens"] == 1024
            assert kwargs["temperature"] == 0.1
            assert kwargs["session_id"] == "lab_review"


async def _coro_impl(value):
    return value


def _coroutine(value):
    return _coro_impl(value)
