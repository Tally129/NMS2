import asyncio
from datetime import datetime, timezone

from sqlalchemy import text

from postgres_db import AsyncSessionLocal
from marketing_os.services.persistence import (
    persist_conversion_and_attribution,
)


def test_transactional_persistence_and_idempotency():

    async def run():

        async with AsyncSessionLocal() as session:

            transaction = await session.begin()

            try:

                payload = {
                    "event_type":
                        "appointment_intent",

                    "session_id":
                        "anonymous-session-test-57cc",

                    "source":
                        "google",

                    "medium":
                        "organic",

                    "campaign":
                        "hyperbaric-therapy",

                    "value":
                        "125.00",

                    "currency":
                        "USD",

                    "properties": {
                        "page_path":
                            "/services/hyperbaric",

                        "cta":
                            "request-appointment",

                        "test_marker":
                            "57cc",
                    },
                }

                first = await (
                    persist_conversion_and_attribution(
                        session,
                        payload=payload,
                        idempotency_key=(
                            "57cc-"
                            "appointment-intent-001"
                        ),
                        occurred_at=datetime.now(
                            timezone.utc
                        ),
                        provider="organic_search",
                    )
                )

                await session.flush()

                assert (
                    first["conversion_inserted"]
                    is True
                )

                assert (
                    first["attribution_inserted"]
                    is True
                )

                second = await (
                    persist_conversion_and_attribution(
                        session,
                        payload=payload,
                        idempotency_key=(
                            "57cc-"
                            "appointment-intent-001"
                        ),
                        occurred_at=datetime.now(
                            timezone.utc
                        ),
                        provider="organic_search",
                    )
                )

                await session.flush()

                assert (
                    second["conversion_event_id"]
                    == first["conversion_event_id"]
                )

                assert (
                    second["attribution_id"]
                    == first["attribution_id"]
                )

                assert (
                    second["conversion_inserted"]
                    is False
                )

                assert (
                    second["attribution_inserted"]
                    is False
                )

                event_count = (
                    await session.execute(
                        text(
                            """
                            SELECT COUNT(*)
                            FROM marketing_conversion_events
                            WHERE id = :id
                            """
                        ),
                        {
                            "id":
                                first[
                                    "conversion_event_id"
                                ]
                        },
                    )
                ).scalar_one()

                attribution_count = (
                    await session.execute(
                        text(
                            """
                            SELECT COUNT(*)
                            FROM marketing_attributions
                            WHERE id = :id
                            """
                        ),
                        {
                            "id":
                                first[
                                    "attribution_id"
                                ]
                        },
                    )
                ).scalar_one()

                assert event_count == 1
                assert attribution_count == 1

            finally:

                await transaction.rollback()

    asyncio.run(run())


def test_phi_rejection_reaches_persistence_boundary():

    async def run():

        async with AsyncSessionLocal() as session:

            transaction = await session.begin()

            try:

                try:

                    await (
                        persist_conversion_and_attribution(
                            session,
                            payload={
                                "event_type":
                                    "lead_submit",

                                "properties": {
                                    "patient_id":
                                        "DO-NOT-STORE",
                                },
                            },
                            idempotency_key=(
                                "57cc-phi-rejection"
                            ),
                        )
                    )

                except ValueError:
                    pass

                else:
                    raise AssertionError(
                        "PHI payload was not rejected"
                    )

            finally:

                await transaction.rollback()

    asyncio.run(run())
