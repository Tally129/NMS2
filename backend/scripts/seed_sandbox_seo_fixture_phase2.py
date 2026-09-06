"""SANDBOX-ONLY synthetic phase-2 SEO fixture (keyword gap, backlinks, rank
tracking). Drives the REAL bounded sync + persistence code with a fake
provider adapter, so the pipelines are exercised end-to-end against
PostgreSQL without any paid DataForSEO call.

Guards: CONFIRM_SANDBOX_SEO_FIXTURE=YES and local DATABASE_URL only.
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from sqlalchemy import text  # noqa: E402

from postgres_db import AsyncSessionLocal  # noqa: E402
from marketing_os.integrations.dataforseo import (  # noqa: E402
    normalize_backlink_summary, normalize_backlinks, normalize_domain_intersection,
    normalize_serp_rank,
)
from marketing_os.search.seo_intel_store import create_tracked_keyword  # noqa: E402
from marketing_os.search.seo_provider_persistence import persist_competitor_snapshots, persist_provider_run  # noqa: E402
from marketing_os.search.seo_provider_sync import sync_seo_provider_report_bounded  # noqa: E402

TARGET = "natmedsol.com"
COMPETITORS = ["rival-naturopath.com", "desertwellnessclinic.com", "azivtherapy.com"]
TOPICS = ["iv therapy", "naturopathic doctor", "hormone therapy", "peptide therapy", "thyroid specialist",
          "functional medicine", "weight loss clinic", "nad iv", "glutathione iv", "acupuncture"]
MODS = ["scottsdale", "phoenix", "near me", "cost", "benefits", "arizona", "reviews", "clinic"]


def _guard():
    if os.environ.get("CONFIRM_SANDBOX_SEO_FIXTURE") != "YES":
        raise SystemExit("Refusing: set CONFIRM_SANDBOX_SEO_FIXTURE=YES (sandbox only)")
    host = urlparse(os.environ.get("DATABASE_URL", "").replace("postgresql+psycopg", "postgresql")).hostname
    if host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Refusing: non-local DATABASE_URL")


def _env(items, total=None):
    return {"status_code": 20000, "cost": 0.0101, "tasks": [{"status_code": 20000, "cost": 0.0101, "result": [
        {"items": items, "items_count": len(items), "total_count": total if total is not None else len(items)}]}]}


class SyntheticAdapter:
    """Deterministic fake provider (clearly synthetic data)."""

    def __init__(self):
        self.rng = random.Random(7)

    def _meta(self, env, **extra):
        r = env["tasks"][0]["result"][0]
        return {"provider": "dataforseo", "status_code": 20000, "task_status_code": 20000, "cost": 0.0101,
                "task_cost": 0.0101, "items_count": r["items_count"], "total_count": r["total_count"], **extra}

    async def fetch_domain_intersection(self, *, target, competitor, limit, offset, intersections, target_is_first, **kw):
        items = []
        for i, t in enumerate(TOPICS):
            for j, m in enumerate(MODS):
                kw_text = f"{t} {m}"
                t_rank = self.rng.randint(1, 60)
                c_rank = self.rng.randint(1, 60)
                first = {"serp_item": {"rank_absolute": t_rank, "url": f"https://www.{TARGET}/{t.replace(' ', '-')}/", "etv": round(self.rng.uniform(1, 80), 2)}}
                second = {"serp_item": {"rank_absolute": c_rank, "url": f"https://{competitor}/{t.replace(' ', '-')}", "etv": round(self.rng.uniform(1, 80), 2)}}
                if not intersections:
                    second = None if target_is_first else second
                    first = first if target_is_first else None
                    if not target_is_first:
                        first, second = second, None  # target1=competitor slot only
                items.append({"keyword_data": {"keyword": kw_text, "keyword_info": {"search_volume": self.rng.choice([20, 50, 90, 140, 320, 590, 1300]), "cpc": round(self.rng.uniform(0.5, 12), 2)},
                                               "keyword_properties": {"keyword_difficulty": self.rng.randint(5, 70)},
                                               "search_intent_info": {"main_intent": self.rng.choice(["informational", "commercial", "transactional"])}},
                              "first_domain_serp_element": first, "second_domain_serp_element": second})
        items = items[: limit]
        env = _env(items)
        return {**self._meta(env), "report": "keyword_gap", "target": target, "limit": limit, "offset": offset,
                "gap_rows": normalize_domain_intersection(env, target=target, competitor=competitor, target_is_first=target_is_first)}

    async def fetch_backlinks_summary(self, *, target, **kw):
        env = _env([{"target": target, "rank": 187, "backlinks": 1842, "referring_domains": 263, "referring_main_domains": 251,
                     "referring_pages": 1105, "referring_ips": 240, "referring_domains_nofollow": 61, "broken_backlinks": 17,
                     "broken_pages": 4, "backlinks_spam_score": 9, "crawled_pages": 412, "first_seen": "2019-03-12 00:00:00 +00:00",
                     "referring_links_types": {"anchor": 1650, "image": 140, "redirect": 52},
                     "referring_links_attributes": {"nofollow": 402, "sponsored": 12}}])
        return {**self._meta(env), "report": "backlinks_summary", "target": target, "summary": normalize_backlink_summary(env, target=target)}

    async def fetch_backlinks(self, *, target, limit, offset, **kw):
        items = []
        for i in range(min(limit, 120)):
            d = f"site{i:03d}.example-{['blog', 'news', 'directory', 'health'][i % 4]}.com"
            items.append({"url_from": f"https://{d}/article-{i}", "domain_from": d, "url_to": f"https://www.{TARGET}/{TOPICS[i % len(TOPICS)].replace(' ', '-')}/",
                          "anchor": self.rng.choice(["Natural Medical Solutions", "naturopathic doctor scottsdale", "iv therapy", "click here", TARGET]),
                          "item_type": "anchor", "dofollow": i % 5 != 0, "attributes": None if i % 5 else ["nofollow"],
                          "is_new": i % 9 == 0, "is_lost": i % 17 == 0, "is_broken": i % 40 == 0,
                          "first_seen": f"2026-0{1 + i % 8}-1{i % 9} 10:00:00 +00:00", "last_seen": "2026-09-05 10:00:00 +00:00",
                          "domain_from_rank": self.rng.randint(20, 700), "page_from_rank": self.rng.randint(1, 300),
                          "backlink_spam_score": self.rng.randint(0, 40)})
        env = _env(items, total=1842)
        return {**self._meta(env), "report": "backlinks", "target": target, "limit": limit, "offset": offset,
                "backlinks": normalize_backlinks(env, target=target)}

    async def fetch_serp_rank(self, *, keyword, target, device="desktop", **kw):
        pos = self.rng.randint(1, 25)
        items = [{"type": "people_also_ask", "rank_absolute": 1}] + [
            {"type": "organic", "rank_group": r, "rank_absolute": r + 1, "domain": (f"www.{TARGET}" if r == pos else f"other{r}.com"),
             "url": f"https://www.{TARGET}/{keyword.replace(' ', '-')}/" if r == pos else f"https://other{r}.com/"} for r in range(1, 31)]
        env = {"tasks": [{"result": [{"se_results_count": 8_400_000, "check_url": "https://www.google.com/search?q=" + keyword.replace(" ", "+"),
                                      "datetime": "2026-09-06 00:00:00 +00:00", "items": items}]}]}
        return {"provider": "dataforseo", "status_code": 20000, "task_status_code": 20000, "cost": 0.002, "task_cost": 0.002,
                "items_count": len(items), "total_count": len(items), "report": "serp_rank", "target": target, "device": device,
                "observation": normalize_serp_rank(env, keyword=keyword, target_domain=target)}


async def main():
    _guard()
    adapter = SyntheticAdapter()
    async with AsyncSessionLocal() as pg:
        site_id = (await pg.execute(text("SELECT id FROM marketing_search_sites WHERE normalized_url = :n"), {"n": TARGET})).scalar()
        if not site_id:
            raise SystemExit("Run seed_sandbox_seo_fixture.py first")
        if (await pg.execute(text("SELECT COUNT(*) FROM marketing_seo_keyword_gap_snapshots WHERE site_id = :s"), {"s": site_id})).scalar():
            print("Phase-2 fixture already present; nothing written."); return
        if True:
            # Competitor snapshots (DataForSEO competitors_domain shape) so the UI has entities.
            run = await persist_provider_run(pg, site_id=site_id, report_type="competitors_domain", target=TARGET,
                                             metadata={"status_code": 20000, "task_status_code": 20000, "cost": 0.0101, "task_cost": 0.0101,
                                                       "total_count": len(COMPETITORS), "items_count": len(COMPETITORS)},
                                             rows_normalized=len(COMPETITORS), requested_limit=1000, requested_offset=0, complete=True)
            comps = [{"domain": c, "normalized_domain": c, "avg_position": round(random.Random(i).uniform(8, 30), 1), "sum_position": 1000 + i,
                      "intersections": 400 - i * 90, "competitor_organic_keywords": 900 + i * 300, "competitor_estimated_traffic": 300 + i * 120,
                      "competitor_estimated_paid_traffic_cost": 1000 + i * 250, "source": "dataforseo"} for i, c in enumerate(COMPETITORS)]
            await persist_competitor_snapshots(pg, site_id=site_id, competitors=comps, provider_run_id=run["id"])
            # Keyword gap for two competitors (shared + missing), via the real bounded sync.
            for comp in COMPETITORS[:2]:
                for mode in ("shared", "missing"):
                    await sync_seo_provider_report_bounded(pg, site_id=site_id, target=TARGET, adapter=adapter, report="keyword_gap",
                                                           limit=1000, max_pages=1, max_total_cost=0.25, options={"competitor_domain": comp, "mode": mode})
            await sync_seo_provider_report_bounded(pg, site_id=site_id, target=TARGET, adapter=adapter, report="backlinks_summary", limit=1, max_pages=1)
            await sync_seo_provider_report_bounded(pg, site_id=site_id, target=TARGET, adapter=adapter, report="backlinks", limit=500, max_pages=1, max_total_cost=0.25)
            for kw, dev in [("iv therapy scottsdale", "desktop"), ("naturopathic doctor phoenix", "desktop"), ("nad iv near me", "mobile"),
                            ("hormone replacement therapy scottsdale", "desktop"), ("peptide therapy arizona", "mobile")]:
                tk = await create_tracked_keyword(pg, site_id=site_id, keyword=kw, target_domain=TARGET, device=dev)
                for _ in range(3):  # three historical observations
                    await sync_seo_provider_report_bounded(pg, site_id=site_id, target=TARGET, adapter=adapter, report="serp_rank", limit=100,
                                                           max_pages=1, options={"tracked_keyword_id": tk["id"]})
        await pg.commit()
    print("Phase-2 sandbox fixture seeded.")


if __name__ == "__main__":
    asyncio.run(main())
