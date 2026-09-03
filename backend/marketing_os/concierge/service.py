"""Core NMS AI Concierge service.

This foundation module contains no LLM invocation and no persistence yet.
Those layers will be added deliberately after the public safety boundary,
knowledge contract, and persistence schema are defined.
"""

from __future__ import annotations

from typing import Any

from marketing_os.concierge.policy import (
    DEFAULT_CONCIERGE_POLICY,
)

from marketing_os.concierge.app_sync import app_sync_status
from marketing_os.concierge.knowledge import (
    knowledge_status,
)

from marketing_os.concierge.sync_manager import (
    sync_status,
)


APPOINTMENT_URL = (
    "https://app.natmedsol.org/request-appointment"
)


def concierge_status() -> dict[str, Any]:
    """Return non-secret Concierge capability state."""

    policy = DEFAULT_CONCIERGE_POLICY

    return {
        "module": "marketing_os.concierge",
        "status": "grounded_engine_ready",
        "public_enabled": policy.public_enabled,
        "appointment_handoff_enabled":
            policy.appointment_handoff_enabled,
        "appointment_url": APPOINTMENT_URL,
        "clinical_record_access_enabled":
            policy.clinical_record_access_enabled,
        "medical_diagnosis_enabled":
            policy.medical_diagnosis_enabled,
        "sensitive_medical_intake_enabled":
            policy.sensitive_medical_intake_enabled,
        "conversation_analytics_enabled":
            policy.conversation_analytics_enabled,
        "content_gap_tracking_enabled":
            policy.content_gap_tracking_enabled,
        "knowledge": knowledge_status(),
        "knowledge_sync": sync_status(),
        "app_knowledge_sync": app_sync_status(),
    }
