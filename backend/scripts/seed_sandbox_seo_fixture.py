"""SANDBOX-ONLY synthetic SEO provider fixture.

Seeds the LOCAL sandbox PostgreSQL with a synthetic (clearly fake) cached
DataForSEO-shaped dataset so the SEO Command Center UI can be exercised
without any paid provider call:

* 1 marketing site (natmedsol.com)
* 1 domain snapshot (organic_keywords / ETV / new-up-down-lost)
* 1 ranked-keyword provider run: offset 0, limit 1000, items 1000,
  total 1017, complete=false, next_offset=1000  (mirrors the recorded
  production state so the completeness indicator can be verified)
* 1000 organic keyword snapshot rows (synthetic keywords)

It reuses the EXISTING persistence layer (no duplicate schema/logic) and
therefore also exercises that layer against a real PostgreSQL.

Safety:
* refuses to run unless CONFIRM_SANDBOX_SEO_FIXTURE=YES
* refuses to run unless DATABASE_URL points at 127.0.0.1 / localhost
* makes NO network calls of any kind
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from sqlalchemy import text  # noqa: E402

from postgres_db import AsyncSessionLocal  # noqa: E402
from marketing_os.search.seo_provider_persistence import (  # noqa: E402
    persist_domain_snapshot,
    persist_organic_keyword_snapshots,
    persist_provider_run,
)

TARGET = "natmedsol.com"
SITE_URL = "https://www.natmedsol.com/"
CAPTURED = date(2026, 9, 5)

TOPICS = [
    "naturopathic doctor", "iv therapy", "hormone replacement therapy",
    "functional medicine", "thyroid specialist", "peptide therapy",
    "weight loss clinic", "bioidentical hormones", "acupuncture",
    "vitamin b12 injection", "nad iv", "glutathione iv", "ozone therapy",
    "prp therapy", "adrenal fatigue treatment", "gut health doctor",
    "integrative medicine", "menopause clinic", "testosterone therapy",
    "lyme disease doctor", "food sensitivity testing", "hair loss treatment",
    "chelation therapy", "myers cocktail", "hyperbaric oxygen therapy",
]
MODIFIERS = [
    "", "near me", "scottsdale", "phoenix", "arizona", "cost", "reviews",
    "benefits", "side effects", "for women", "for men", "clinic",
    "specialist", "natural", "best", "what is", "how much is",
    "does insurance cover", "before and after", "vs",
]
INTENTS = ["informational", "commercial", "transactional", "navigational"]
FEATURES = [[], [], ["featured_snippet"], ["people_also_ask"],
            ["local_pack"], ["video"], ["images", "people_also_ask"]]


def _guard() -> None:
    if os.environ.get("CONFIRM_SANDBOX_SEO_FIXTURE") != "YES":
        raise SystemExit(
            "Refusing: set CONFIRM_SANDBOX_SEO_FIXTURE=YES (sandbox only)"
        )
    url = os.environ.get("DATABASE_URL", "")
    host = urlparse(url.replace("postgresql+psycopg", "postgresql")).hostname
    if host not in {"127.0.0.1", "localhost"}:
        raise SystemExit(
            f"Refusing: DATABASE_URL host {host!r} is not local sandbox"
        )


def _keywords(n: int) -> list[dict]:
    rng = random.Random(20260905)
    seen: set[str] = set()
    rows: list[dict] = []
    i = 0
    while len(rows) < n:
        i += 1
        topic = TOPICS[i % len(TOPICS)]
        mod = MODIFIERS[(i * 7) % len(MODIFIERS)]
        kw = f"{mod} {topic}".strip() if i % 3 else f"{topic} {mod}".strip()
        if i > len(TOPICS) * len(MODIFIERS):
            kw = f"{kw} {i}"
        norm = " ".join(kw.lower().split())
        if norm in seen:
            kw = f"{kw} {i}"
            norm = " ".join(kw.lower().split())
        seen.add(norm)
        rank = min(100, 1 + int(rng.expovariate(1 / 18)))
        rows.append(
            {
                "keyword": kw,
                "normalized_keyword": norm,
                "intent": INTENTS[(i * 5) % len(INTENTS)],
                "search_volume": int(rng.choice([10, 20, 30, 50, 70, 90,
                                                 110, 140, 170, 210, 260,
                                                 320, 390, 480, 590, 720,
                                                 880, 1000, 1300, 1600,
                                                 1900, 2400, 2900, 3600,
                                                 4400, 5400, 6600, 8100])),
                "keyword_difficulty": int(rng.randint(3, 78)),
                "cpc": round(rng.uniform(0.4, 14.0), 2),
                "current_rank": rank,
                "ranking_url": (
                    f"https://www.natmedsol.com/"
                    f"{topic.replace(' ', '-')}/"
                ),
                "serp_features": FEATURES[i % len(FEATURES)],
                "source": "dataforseo",
                "metric_type": "organic_serp_rank",
            }
        )
    return rows


async def main() -> None:
    _guard()
    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            res = await pg.execute(
                text(
                    "SELECT id FROM marketing_search_sites "
                    "WHERE normalized_url = :n"
                ),
                {"n": TARGET},
            )
            row = res.first()
            if row:
                site_id = row._mapping["id"]
            else:
                import uuid

                site_id = uuid.uuid4().hex
                await pg.execute(
                    text(
                        "INSERT INTO marketing_search_sites "
                        "(id, site_url, normalized_url, label, is_active) "
                        "VALUES (:id, :u, :n, :l, true)"
                    ),
                    {"id": site_id, "u": SITE_URL, "n": TARGET,
                     "l": "Natural Medical Solutions (sandbox fixture)"},
                )

            existing = await pg.execute(
                text(
                    "SELECT COUNT(*) AS c FROM marketing_seo_provider_runs "
                    "WHERE site_id = :s"
                ),
                {"s": site_id},
            )
            if int(existing.first()._mapping["c"]) > 0:
                print("Fixture already present; nothing written.")
                return

            # --- domain overview (single request in real life) ---
            run_overview = await persist_provider_run(
                pg,
                site_id=site_id,
                report_type="domain_rank_overview",
                target=TARGET,
                metadata={"status_code": 20000, "task_status_code": 20000,
                          "cost": 0.0101, "task_cost": 0.0101,
                          "total_count": 1, "items_count": 1},
                rows_normalized=1,
                complete=True,
            )
            await persist_domain_snapshot(
                pg,
                site_id=site_id,
                provider_run_id=run_overview["id"],
                captured_date=CAPTURED,
                overview={
                    "target": TARGET,
                    "organic_keywords": 1017,
                    "estimated_organic_traffic": 455.1282,
                    "estimated_paid_traffic_cost": 1832.55,
                    "positions": {"pos_1": 12, "pos_2_3": 44, "pos_4_10": 190,
                                  "pos_11_20": 260, "pos_21_30": 180,
                                  "pos_31_40": 120, "pos_41_50": 90,
                                  "pos_51_60": 50, "pos_61_70": 30,
                                  "pos_71_80": 20, "pos_81_90": 13,
                                  "pos_91_100": 8},
                    "new": 41,
                    "up": 120,
                    "down": 98,
                    "lost": 33,
                    "source": "dataforseo",
                },
            )

            # --- ranked keywords page 1 (incomplete; mirrors prod state) ---
            keywords = _keywords(1000)
            run_kw = await persist_provider_run(
                pg,
                site_id=site_id,
                report_type="ranked_keywords",
                target=TARGET,
                metadata={"status_code": 20000, "task_status_code": 20000,
                          "cost": 0.1102, "task_cost": 0.1102,
                          "total_count": 1017, "items_count": 1000},
                rows_normalized=len(keywords),
                requested_limit=1000,
                requested_offset=0,
                complete=False,
                next_offset=1000,
            )
            stored = await persist_organic_keyword_snapshots(
                pg,
                site_id=site_id,
                keywords=keywords,
                provider_run_id=run_kw["id"],
                captured_date=CAPTURED,
            )
    print(
        f"Sandbox SEO fixture seeded: site={site_id} "
        f"keywords_stored={stored} (provider total 1017, next_offset 1000)"
    )


if __name__ == "__main__":
    asyncio.run(main())
