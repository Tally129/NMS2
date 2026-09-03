"""Scheduled Concierge knowledge reconciliation."""

from __future__ import annotations

import asyncio
import logging

from marketing_os.concierge.app_sync import (
    reconcile_app_knowledge,
)
from marketing_os.concierge.sync_manager import (
    run_sync,
)


logger = logging.getLogger(__name__)


def reconcile_concierge_knowledge() -> None:
    """Reconcile website and approved app knowledge."""

    try:
        website = run_sync(
            force=False,
            trigger="scheduler",
        )

        logger.info(
            "Concierge website knowledge sync: %s",
            website.get("status"),
        )

    except Exception:
        logger.exception(
            "Concierge website knowledge sync failed"
        )

    try:
        app = asyncio.run(
            reconcile_app_knowledge(
                trigger="scheduler"
            )
        )

        logger.info(
            "Concierge app knowledge sync: %s",
            app.get("status"),
        )

    except Exception:
        logger.exception(
            "Concierge app knowledge sync failed"
        )
