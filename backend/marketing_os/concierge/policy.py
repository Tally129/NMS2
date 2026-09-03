"""Safety policy for the public NMS AI Concierge.

The Concierge is a public marketing/navigation assistant.

It is deliberately separated from clinical AI systems and must not
behave as a diagnostic, prescribing, or emergency-care system.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ConciergePolicy:
    public_enabled: bool = False

    medical_diagnosis_enabled: bool = False
    prescribing_enabled: bool = False
    clinical_record_access_enabled: bool = False
    patient_chart_access_enabled: bool = False

    appointment_handoff_enabled: bool = True

    sensitive_medical_intake_enabled: bool = False

    content_gap_tracking_enabled: bool = True
    conversation_analytics_enabled: bool = True

    max_message_chars: int = 2000
    max_history_messages: int = 12


DEFAULT_CONCIERGE_POLICY = ConciergePolicy()
