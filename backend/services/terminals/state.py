"""
Normalize terminal/provider states into NMS states.
"""


APPROVED = "approved"
PROCESSING = "processing"
WAITING = "waiting_for_terminal"
DECLINED = "declined"
CANCELED = "canceled"
FAILED = "failed"
TIMED_OUT = "timed_out"


def may_mark_transaction_paid(
    normalized_status: str,
) -> bool:
    return normalized_status == APPROVED
