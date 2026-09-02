"""Phase 5 LIVE HTTP tests with SEEDED marketing-safe conversion events.

Seeds TEST_ prefixed rows into marketing_conversion_events and
marketing_daily_metrics, exercises deterministic first/last-touch
attribution, real purchase-only revenue and channel economics over HTTP,
then removes every seeded row.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone

import pytest
import requests

sys.path.insert(0, "/app/backend")

from tests.test_marketing_attribution_phase5_http import (  # noqa: E402
    API,
    ATTR,
    _login,
)

SUBJ_A = "TEST_subj_attr_a"
SUBJ_B = "TEST_subj_attr_b"
T0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def _events():
    return [
        # Subject A: google lead -> meta booked -> meta completed -> purchase
        ("TEST_ev_a1", "lead_submit", T0, SUBJ_A, "google", "cpc",
         "TEST_camp_g", None),
        ("TEST_ev_a2", "appointment_booked", T0 + timedelta(days=1), SUBJ_A,
         "facebook", "paid_social", "TEST_camp_f", None),
        ("TEST_ev_a3", "appointment_completed", T0 + timedelta(days=2), SUBJ_A,
         "facebook", "paid_social", "TEST_camp_f", None),
        ("TEST_ev_a4", "purchase", T0 + timedelta(days=3), SUBJ_A,
         None, None, None, 500),
        # Subject B: bing lead -> request -> booked -> no_show
        ("TEST_ev_b1", "lead_submit", T0, SUBJ_B, "bing", "cpc",
         "TEST_camp_b", None),
        ("TEST_ev_b2", "appointment_request", T0 + timedelta(hours=1), SUBJ_B,
         "bing", "cpc", "TEST_camp_b", None),
        ("TEST_ev_b3", "appointment_booked", T0 + timedelta(hours=2), SUBJ_B,
         "bing", "cpc", "TEST_camp_b", None),
        ("TEST_ev_b4", "appointment_no_show", T0 + timedelta(days=2), SUBJ_B,
         "bing", "cpc", "TEST_camp_b", None),
    ]


async def _seed():
    from sqlalchemy import text

    from postgres_db import AsyncSessionLocal

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            for (eid, etype, occurred, subj, source, medium, campaign,
                 value) in _events():
                await pg.execute(
                    text(
                        """
                        INSERT INTO marketing_conversion_events
                          (id, event_type, occurred_at, marketing_subject_id,
                           source, medium, campaign, value, properties,
                           created_at, updated_at)
                        VALUES
                          (:id, :etype, :occurred, :subj, :source, :medium,
                           :campaign, :value, '{}'::jsonb, now(), now())
                        ON CONFLICT (id) DO NOTHING
                        """
                    ),
                    {"id": eid, "etype": etype, "occurred": occurred,
                     "subj": subj, "source": source, "medium": medium,
                     "campaign": campaign, "value": value},
                )
            for mid, provider, spend in (
                ("TEST_dm_google", "google_ads", 250),
                ("TEST_dm_meta", "meta_ads", 100),
            ):
                await pg.execute(
                    text(
                        """
                        INSERT INTO marketing_daily_metrics
                          (id, metric_date, provider, spend, impressions,
                           clicks, leads, conversions, raw_metrics,
                           created_at, updated_at)
                        VALUES
                          (:id, :d, :provider, :spend, 0, 0, 0, 0,
                           '{}'::jsonb, now(), now())
                        ON CONFLICT (id) DO NOTHING
                        """
                    ),
                    {"id": mid, "d": T0.date(), "provider": provider,
                     "spend": spend},
                )


async def _cleanup():
    from sqlalchemy import text

    from postgres_db import AsyncSessionLocal

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            await pg.execute(text(
                "DELETE FROM marketing_conversion_events WHERE id LIKE 'TEST_%'"
            ))
            await pg.execute(text(
                "DELETE FROM marketing_daily_metrics WHERE id LIKE 'TEST_%'"
            ))


@pytest.fixture(scope="module", autouse=True)
def seeded():
    asyncio.run(_seed())
    yield
    asyncio.run(_cleanup())


@pytest.fixture(scope="module")
def headers():
    return {"Authorization":
            f"Bearer {_login('admin@natmedsol.local', 'Admin!2345')}"}


def _get(path, headers, **params):
    r = requests.get(path, headers=headers, params=params or None, timeout=90)
    assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:400]}"
    return r.json()


def _credited(block):
    return {c["key"]: c["attributed_count"] for c in block["credited"]}


class TestSeededFunnel:
    def test_stage_counts_and_null_untracked(self, headers):
        f = _get(f"{ATTR}/funnel", headers)
        s = f["stages"]
        assert s["lead"] == 2, s
        assert s["appointment_request"] == 1, s
        assert s["appointment_booked"] == 2, s
        assert s["appointment_completed"] == 1, s
        assert s["no_show"] == 1, s
        # appointment_intent has no events anywhere -> honest null, not 0
        assert s["appointment_intent"] is None, s

    def test_rates(self, headers):
        rates = _get(f"{ATTR}/funnel", headers)["rates"]
        assert rates["lead_to_booking_rate"] == pytest.approx(1.0)
        assert rates["booking_to_show_rate"] == pytest.approx(0.5)
        assert rates["lead_to_show_rate"] == pytest.approx(0.5)
        assert rates["request_to_booking_rate"] == pytest.approx(2.0)
        assert rates["no_show_rate"] == pytest.approx(0.5)


class TestSeededAttributionModels:
    def test_last_touch_booked(self, headers):
        d = _get(f"{ATTR}/overview", headers, model="last_touch")
        credited = _credited(d["booked_attribution"])
        assert credited.get("meta_ads") == 1, credited
        assert credited.get("microsoft_ads") == 1, credited

    def test_first_touch_booked_differs(self, headers):
        d = _get(f"{ATTR}/overview", headers, model="first_touch")
        credited = _credited(d["booked_attribution"])
        assert credited.get("google_ads") == 1, credited
        assert credited.get("microsoft_ads") == 1, credited
        assert "meta_ads" not in credited, credited

    def test_completed_attribution(self, headers):
        last = _credited(_get(f"{ATTR}/overview", headers,
                              model="last_touch")["completed_attribution"])
        first = _credited(_get(f"{ATTR}/overview", headers,
                               model="first_touch")["completed_attribution"])
        assert last.get("meta_ads") == 1, last
        assert first.get("google_ads") == 1, first

    def test_campaign_dimension(self, headers):
        d = _get(f"{ATTR}/campaigns", headers, model="first_touch")
        booked = _credited(d["booked"])
        assert booked.get("TEST_camp_g") == 1, booked
        assert booked.get("TEST_camp_b") == 1, booked


class TestSeededRevenue:
    def test_purchase_only_revenue_last_touch(self, headers):
        d = _get(f"{ATTR}/revenue", headers, model="last_touch")
        assert d["revenue_available"] is True
        assert d["purchase_count"] == 1, d
        assert d["total_attributed_revenue"] == pytest.approx(500.0)
        by_channel = {r["key"]: r["attributed_revenue"]
                      for r in d["by_channel"]}
        assert by_channel.get("meta_ads") == pytest.approx(500.0), by_channel

    def test_revenue_first_touch(self, headers):
        d = _get(f"{ATTR}/revenue", headers, model="first_touch")
        by_channel = {r["key"]: r["attributed_revenue"]
                      for r in d["by_channel"]}
        assert by_channel.get("google_ads") == pytest.approx(500.0), by_channel

    def test_no_estimated_revenue_from_appointments(self, headers):
        """Only the single purchase (500) counts; 4 appointment events must
        contribute nothing."""
        d = _get(f"{ATTR}/revenue", headers, model="last_touch")
        assert d["total_attributed_revenue"] == pytest.approx(500.0)
        assert d["attribution_source"] == "first_party_purchase_events"


class TestSeededChannelEconomics:
    def test_cost_per_appointment_and_roas_first_touch(self, headers):
        d = _get(f"{ATTR}/channels", headers, model="first_touch")
        assert d["revenue_available"] is True
        rows = {r["channel"]: r for r in d["channels"]}
        g = rows["google_ads"]
        assert g["spend"] == pytest.approx(250.0)
        assert g["booked_appointments"] == 1
        assert g["completed_appointments"] == 1
        assert g["cost_per_booked_appointment"] == pytest.approx(250.0)
        assert g["cost_per_completed_appointment"] == pytest.approx(250.0)
        assert g["attributed_revenue"] == pytest.approx(500.0)
        assert g["roas"] == pytest.approx(2.0)

        # meta_ads has spend but zero first-touch credit -> nulls, not fake 0
        m = rows["meta_ads"]
        assert m["spend"] == pytest.approx(100.0)
        assert m["booked_appointments"] == 0
        assert m["cost_per_booked_appointment"] is None, m
        assert m["attributed_revenue"] == pytest.approx(0.0)
        assert m["roas"] == pytest.approx(0.0)

    def test_channel_without_spend_has_null_spend(self, headers):
        d = _get(f"{ATTR}/channels", headers, model="first_touch")
        rows = {r["channel"]: r for r in d["channels"]}
        ms = rows.get("microsoft_ads")
        assert ms is not None, list(rows)
        assert ms["spend"] is None, ms
        assert ms["cost_per_booked_appointment"] is None, ms
        assert ms["booked_appointments"] == 1, ms


class TestSeededJourneys:
    def test_journeys_contain_seeded_subjects(self, headers):
        d = _get(f"{ATTR}/journeys", headers, limit=500)
        journeys = {j["marketing_subject_id"]: j for j in d["journeys"]}
        a = journeys.get(SUBJ_A)
        assert a is not None, list(journeys)
        assert a["first_touch"]["channel"] == "google_ads"
        assert a["last_touch"]["channel"] == "meta_ads"
        assert a["stages_reached"] == [
            "lead", "appointment_booked", "appointment_completed"], a
        assert a["event_count"] == 4
        b = journeys[SUBJ_B]
        assert b["stages_reached"] == [
            "lead", "appointment_request", "appointment_booked", "no_show"], b

    def test_journey_limit_respected(self, headers):
        d = _get(f"{ATTR}/journeys", headers, limit=1)
        assert len(d["journeys"]) == 1
        assert d["count"] >= 2


class TestSeededDirectorBrief:
    def test_journey_outcomes_reflect_seed(self, headers):
        r = requests.get(f"{API}/marketing-os/director/brief",
                         headers=headers, timeout=180)
        assert r.status_code == 200, r.text[:400]
        jo = r.json()["journey_outcomes"]
        assert jo["funnel"]["stages"]["lead"] == 2, jo["funnel"]
        assert jo["revenue"]["revenue_available"] is True, jo["revenue"]
        assert jo["revenue"]["total_attributed_revenue"] == pytest.approx(500.0)
        assert jo["channel_economics"]["channels"], jo["channel_economics"]
