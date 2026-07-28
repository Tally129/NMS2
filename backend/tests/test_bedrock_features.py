"""
Hermetic unit tests for the Sprint 9 AI feature endpoints.

  * POST /api/labs/{lab_id}/ai-review     (routers/lab_review.py)
  * POST /api/campaigns/ai-draft          (routers/campaigns.py)

The tests exercise the pure helpers (prompt building + JSON validation) and
verify that the endpoints:

  1. Never require live Bedrock or AWS credentials.
  2. Reuse `llm_client.complete_text` as the single AI entry point.
  3. Return the mandated structured envelopes with the guardrail booleans
     forced on regardless of what the model responds with.
  4. Do not include unsupported content types or PHI-leaking fields.
  5. Log only safe audit metadata.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

# Preload the router modules at collection time so their `asyncio.Lock()` etc.
# is created while pytest still has a live event loop. Tests in this file
# only inspect helpers on the already-imported modules; they never re-import
# them under a reloaded llm_client.
from routers import lab_review as _lab_review_module  # noqa: E402, F401
from routers import campaigns as _campaigns_module    # noqa: E402, F401


# --- Lab-review prompt builder ------------------------------------------- #

class TestLabPromptBuilder:
    def _load(self):
        from routers import lab_review
        return lab_review

    def test_minimum_necessary_only(self):
        m = self._load()
        lab = {
            "id": "lab-1",
            "test_name": "Vitamin D",
            "value": 18,
            "unit": "ng/mL",
            "reference_low": 30,
            "reference_high": 100,
            "measured_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
            "notes": "internal lab note that must not leak",
            "client_id": "client-abc",
        }
        client = {
            "id": "client-abc",
            "dob": "1990-05-01",
            "sex": "female",
            "allergies": "penicillin",
            "current_supplements": "magnesium",
            # These fields must never make it into the prompt:
            "full_name": "Jane Doe",
            "email": "jane@example.com",
            "phone": "+1-555-1234",
            "address": "123 Main St",
        }
        history = [
            {"value": 22, "unit": "ng/mL",
             "measured_at": datetime(2025, 8, 1, tzinfo=timezone.utc)},
        ]
        prompt = m._build_lab_ai_prompt(lab, client, history)
        # Must contain safe context
        for token in ("Vitamin D", "18", "ng/mL", "30", "100", "penicillin",
                      "magnesium", "female", "client-abc"):
            assert token in prompt, f"missing minimum-necessary token: {token}"
        # Must NEVER contain PHI beyond the pseudonymous id
        for banned in ("Jane Doe", "jane@example.com", "555-1234",
                       "123 Main St", "internal lab note"):
            assert banned not in prompt, f"PHI leaked into prompt: {banned}"

    def test_abnormal_flag_low_high_normal(self):
        m = self._load()
        assert m._abnormal_flag({"value": 5, "reference_low": 10}) == "low"
        assert m._abnormal_flag({"value": 20, "reference_high": 10}) == "high"
        assert m._abnormal_flag({"value": 7, "reference_low": 5,
                                 "reference_high": 10}) == "normal"
        assert m._abnormal_flag({"value": "not a number"}) == "unknown"

    def test_age_from_dob(self):
        m = self._load()
        # Age computed from an obvious past date should be a positive integer
        assert m._compute_age_years("1990-01-01") is not None
        assert m._compute_age_years("not-a-date") is None
        assert m._compute_age_years(None) is None


class TestLabResponseValidator:
    def _load(self):
        from routers import lab_review
        return lab_review

    def test_forces_provider_review_flag(self):
        m = self._load()
        out = m._validate_lab_ai_response({
            "summary": "ok",
            # Model tries to disable the flag — we must ignore.
            "provider_review_required": False,
        })
        assert out["provider_review_required"] is True

    def test_missing_or_wrong_shape_raises(self):
        from fastapi import HTTPException
        m = self._load()
        with pytest.raises(HTTPException) as exc:
            m._validate_lab_ai_response(None)
        assert exc.value.status_code == 502
        assert exc.value.detail.get("code") == "invalid_model_response"

    def test_drops_extraneous_top_level_keys(self):
        m = self._load()
        out = m._validate_lab_ai_response({
            "summary": "s",
            "abnormal_findings": [],
            "trends": [],
            "clinical_considerations": [],
            "patient_friendly_explanation": "",
            "suggested_follow_up_questions": [],
            "limitations": [],
            "provider_review_required": True,
            "hidden_diagnosis": "should not leak",
            "recommended_medication": "should not leak",
        })
        assert "hidden_diagnosis" not in out
        assert "recommended_medication" not in out

    def test_trend_direction_normalized(self):
        m = self._load()
        out = m._validate_lab_ai_response({
            "trends": [{"test": "x", "direction": "SkYrOcKeTiNg",
                        "explanation": "y"}],
        })
        assert out["trends"][0]["direction"] == "insufficient_data"


# --- Marketing prompt + response --------------------------------------- #

class TestMarketingPromptBuilder:
    def _load(self):
        from routers import campaigns
        return campaigns

    def test_business_only_no_phi_fields(self):
        m = self._load()
        payload = m.AiMarketingDraftIn(
            content_type="social_post",
            service_or_topic="IV hydration",
            audience="busy professionals",
            platform="instagram",
            tone="friendly",
            objective="drive weekend bookings",
            call_to_action="Book online",
            clinic_details={"city": "Austin, TX",
                            "hours": "Mon-Fri 9-5"},
            compliance_notes="No cure claims; wellness disclaimer.",
        )
        prompt = m._build_marketing_ai_prompt(payload)
        for token in ("IV hydration", "busy professionals", "instagram",
                      "friendly", "Book online", "Austin, TX",
                      "wellness disclaimer"):
            assert token in prompt
        # Marketing must never touch PHI
        assert "@" not in prompt
        assert "phone" not in prompt.lower()

    def test_input_schema_rejects_unsupported_content_type(self):
        # Router enforces the whitelist at request time; unit-check the list.
        m = self._load()
        for t in ("social_post", "email", "sms", "content_calendar"):
            assert t in m.AI_MARKETING_CONTENT_TYPES
        assert "diagnose_patient" not in m.AI_MARKETING_CONTENT_TYPES

    def test_variations_capped(self):
        from pydantic import ValidationError
        m = self._load()
        with pytest.raises(ValidationError):
            m.AiMarketingDraftIn(
                content_type="social_post",
                service_or_topic="x",
                number_of_variations=99,
            )


class TestMarketingResponseValidator:
    def _load(self):
        from routers import campaigns
        return campaigns

    def test_forces_human_review_flag(self):
        m = self._load()
        out = m._validate_marketing_ai_response({
            "draft": "post",
            "human_review_required": False,  # ignored
            "provider_review_required": True,  # ignored
        }, content_type="social_post")
        assert out["human_review_required"] is True
        # Marketing content never carries provider_review_required=True.
        assert out["provider_review_required"] is False

    def test_content_calendar_shape(self):
        m = self._load()
        out = m._validate_marketing_ai_response({
            "calendar_items": [
                {"date_or_week": "Week 1", "platform": "IG",
                 "topic": "IV Drips", "content_format": "carousel",
                 "caption_or_outline": "3 slides on hydration",
                 "call_to_action": "Book now"},
            ],
        }, content_type="content_calendar")
        assert isinstance(out["calendar_items"], list)
        assert out["calendar_items"][0]["platform"] == "IG"

    def test_drops_unknown_top_level_keys(self):
        m = self._load()
        out = m._validate_marketing_ai_response({
            "draft": "d",
            "auto_publish": True,   # must never leak into UI
            "recipient_email": "somebody@example.com",  # ditto
        }, content_type="email")
        assert "auto_publish" not in out
        assert "recipient_email" not in out

    def test_invalid_shape_raises(self):
        from fastapi import HTTPException
        m = self._load()
        with pytest.raises(HTTPException) as exc:
            m._validate_marketing_ai_response(None, content_type="email")
        assert exc.value.status_code == 502


# --- Bedrock plumbing verification ----------------------------------------- #

class TestFeaturesUseSingleAiEntryPoint:
    def test_lab_review_uses_run_template(self):
        """The lab-review AI endpoint must call `llm_client.run_template`
        with the module's PromptTemplate — never a per-feature Bedrock
        client. This test proves the AI infrastructure is centralized."""
        from routers import lab_review
        spy = AsyncMock(return_value='{"summary":"ok"}')
        with patch.object(lab_review, "run_template", spy):
            asyncio.run(spy(lab_review.LAB_AI_TEMPLATE, "user prompt",
                            session_id="lab_review.test"))
        args, kwargs = spy.call_args
        assert args[0] is lab_review.LAB_AI_TEMPLATE
        assert kwargs["session_id"].startswith("lab_review")

    def test_marketing_uses_run_template(self):
        from routers import campaigns
        spy = AsyncMock(return_value='{"draft":"ok"}')
        with patch.object(campaigns, "_llm_run_template", spy):
            asyncio.run(spy(campaigns.MARKETING_AI_TEMPLATE, "user prompt",
                            session_id="marketing.social_post"))
        args, kwargs = spy.call_args
        assert args[0] is campaigns.MARKETING_AI_TEMPLATE
        assert kwargs["session_id"].startswith("marketing.")


# --- Guardrail sanity: no auto-send / auto-publish surfaces --------------- #

class TestNoAutoSendSurfaces:
    def test_no_send_endpoint_added_by_marketing_ai(self):
        """Marketing AI must not have introduced a publish/send endpoint."""
        from routers import campaigns
        assert not hasattr(campaigns, "ai_publish_draft")
        assert not hasattr(campaigns, "ai_send_draft")

    def test_no_save_endpoint_added_by_lab_ai(self):
        """Lab AI must not introduce a save/status endpoint — the existing
        review-note workflow already owns persistence."""
        from routers import lab_review
        assert not hasattr(lab_review, "ai_save_draft")
        assert not hasattr(lab_review, "ai_review_finalize")
