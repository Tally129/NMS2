"""Seed/cleanup TEST_ attribution data to exercise data-present UI paths.

Usage: python seed_attribution_test_data.py [seed|cleanup]
Creates 2 leads / 3 booked (=> 150% lead_to_booking_rate data-quality artifact),
2 completed, 1 no-show, one real purchase ($500) and one spend row ($250).
"""
import asyncio
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

sys.path.insert(0, "/app/backend")

from sqlalchemy import text  # noqa: E402
from postgres_db import AsyncSessionLocal  # noqa: E402

BASE = datetime.now(timezone.utc) - timedelta(days=3)

EVENTS = [
    # (id, event_type, minutes_offset, subject, source, medium, campaign, value)
    ("TEST_ev_l1", "lead_submit", 0, "TEST_s1", "google", "cpc", "TEST_camp_a", None),
    ("TEST_ev_l2", "lead_submit", 5, "TEST_s2", "google", "cpc", "TEST_camp_a", None),
    ("TEST_ev_i1", "appointment_intent", 10, "TEST_s1", "google", "cpc", "TEST_camp_a", None),
    ("TEST_ev_r1", "appointment_request", 15, "TEST_s1", "google", "cpc", "TEST_camp_a", None),
    ("TEST_ev_b1", "appointment_booked", 20, "TEST_s1", "google", "cpc", "TEST_camp_a", None),
    ("TEST_ev_b2", "appointment_booked", 25, "TEST_s2", "google", "cpc", "TEST_camp_a", None),
    # out-of-order / lead-less booking -> pushes lead_to_booking_rate above 100%
    ("TEST_ev_b3", "appointment_booked", 30, "TEST_s3", "google", "cpc", "TEST_camp_b", None),
    ("TEST_ev_c1", "appointment_completed", 40, "TEST_s1", "google", "cpc", "TEST_camp_a", None),
    ("TEST_ev_c2", "appointment_completed", 45, "TEST_s2", "google", "cpc", "TEST_camp_a", None),
    ("TEST_ev_n1", "appointment_no_show", 50, "TEST_s3", "google", "cpc", "TEST_camp_b", None),
    ("TEST_ev_p1", "purchase", 60, "TEST_s1", "google", "cpc", "TEST_camp_a", 500.00),
]


async def seed():
    async with AsyncSessionLocal() as pg:
        for eid, etype, off, subj, src, med, camp, val in EVENTS:
            await pg.execute(
                text(
                    """
                    INSERT INTO marketing_conversion_events
                        (id, event_type, occurred_at, marketing_subject_id,
                         source, medium, campaign, value, currency,
                         properties, created_at, updated_at)
                    VALUES (:id, :et, :oa, :sub, :src, :med, :camp, :val,
                            'USD', '{}'::jsonb, now(), now())
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": eid,
                    "et": etype,
                    "oa": BASE + timedelta(minutes=off),
                    "sub": subj,
                    "src": src,
                    "med": med,
                    "camp": camp,
                    "val": val,
                },
            )
        await pg.execute(
            text(
                """
                INSERT INTO marketing_daily_metrics
                    (id, metric_date, provider, campaign_name, impressions,
                     clicks, spend, leads, conversions, conversion_value,
                     raw_metrics, created_at, updated_at)
                VALUES ('TEST_dm_1', :d, 'google_ads', 'TEST_camp_a', 1000,
                        100, 250.00, 2, 2, 0, '{}'::jsonb, now(), now())
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"d": BASE.date()},
        )
        await pg.commit()
    print("seeded")


async def cleanup():
    async with AsyncSessionLocal() as pg:
        await pg.execute(
            text("DELETE FROM marketing_conversion_events WHERE id LIKE 'TEST_%'")
        )
        await pg.execute(
            text("DELETE FROM marketing_daily_metrics WHERE id LIKE 'TEST_%'")
        )
        await pg.commit()
    print("cleaned")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "seed"
    asyncio.run(seed() if mode == "seed" else cleanup())
