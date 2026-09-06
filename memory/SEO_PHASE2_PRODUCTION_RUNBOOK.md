# SEO Phase 2 — Production Runbook (EC2 `/opt/natmedsol`)

These operations could NOT be executed from the Emergent sandbox: it has no
route to the production host, no production `DATABASE_URL`, and no
DataForSEO / Google Search Console / Google Ads credentials. Run them on the
production host in this order. Every step is idempotent or bounded.

## 0. Pre-flight (read-only)
```bash
cd /opt/natmedsol && git fetch origin && git status --short
git log --oneline -1                      # record current production commit
cd backend && alembic current             # expect f5a7b9c1d3e5 before upgrade
alembic heads                             # expect a7c9e1f3b5d7 (single head)
alembic upgrade head --sql | grep -iE "drop|truncate|delete" ; echo "(must print nothing)"
```

## 1. Backup / checkpoint (required before migration)
```bash
pg_dump "$DATABASE_URL" -Fc -f /var/backups/nms/pre_seo_phase2_$(date +%F_%H%M).dump
```

## 2. Deploy code + migrate (additive only)
```bash
cd /opt/natmedsol && git checkout handoff/marketing-os-seo-current && git pull --ff-only
./bin/deploy                              # existing deployment script (builds frontend, restarts services)
cd backend && alembic upgrade head        # adds 4 GSC columns, 3 keyword columns, 6 tables
alembic current                           # expect a7c9e1f3b5d7
```
Rollback path: `git checkout <previous commit> && ./bin/deploy`; the new
columns/tables are nullable/unused by old code, so no downgrade is required.
Keep `SEO_PROVIDER_REFRESH_ENABLED=false` (default) until schedules are reviewed.

## 3. Finish the organic-keyword ingestion (1 paid DataForSEO request)
Verify persisted state first (read-only):
```sql
SELECT report_type,status,requested_offset,requested_limit,provider_items_count,
       provider_total_count,rows_normalized,complete,next_offset,finished_at
FROM marketing_seo_provider_runs WHERE report_type='ranked_keywords'
ORDER BY finished_at DESC LIMIT 5;
SELECT captured_date, COUNT(*) FROM marketing_seo_organic_keyword_snapshots GROUP BY 1 ORDER BY 1 DESC LIMIT 3;
```
Then, as admin, preview and execute through the governed route (dry-run first):
```bash
# dry run — zero provider calls
curl -s -X POST "$BASE/api/marketing-os/search/seo/refresh" -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"report_type":"ranked_keywords","start_offset":<next_offset from SQL, expected 1000>,"limit":1000,"max_pages":1,"max_total_cost":0.25}'
# live — exactly 1 request, writes marketing_seo_provider_runs + marketing_seo_organic_keyword_snapshots
curl -s -X POST "$BASE/api/marketing-os/search/seo/refresh" -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"report_type":"ranked_keywords","start_offset":1000,"limit":1000,"max_pages":1,"max_total_cost":0.25,"dry_run":false,"confirm":true}'
```
Expected: `complete: true`, `next_offset: null`, `rows_normalized ≈ 17`
(follow the provider's current `provider_total_count` if it changed). If the
run reports `complete:false`, repeat with the returned `next_offset`.

## 4. GSC production sync (paginated, historical snapshots preserved)
```bash
curl -s -X POST "$BASE/api/marketing-os/search/search-console/sync" -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"row_limit":25000}'     # default range; dimensions date / query / page
```
Verify: response `completeness: "complete"`, `pagination.queries.rows` well above 1,000,
`safety_ceiling_reached: false`; then `GET /api/marketing-os/search/search-console/runs`.

## 5. Minimal pipeline proofs (bounded, ~4 paid requests total)
```bash
# competitors (if not already cached)      -> competitors_domain, max_pages 1
# keyword gap for the top competitor       -> keyword_gap options {"competitor_domain":"<domain>","mode":"shared"} then "missing"
# backlink summary                         -> backlinks_summary (1 request)
# backlinks first page                     -> backlinks limit 500 max_pages 1
# rank tracking: add 3-5 keywords in UI (Position Tracking), then serp_rank per tracked_keyword_id
```
Each via the same `POST /seo/refresh` with `dry_run:true` first.

## 6. Enable conservative automatic refresh (optional)
Set `SEO_PROVIDER_REFRESH_ENABLED=true` in the server env, restart, then in
Provider / Sync enable only the schedules wanted (defaults: weekly overview /
ranked keywords / backlink summary / serp_rank; fortnightly competitors, gap,
backlinks). First automatic run is one cadence after enabling — never immediate.

## 7. Google Ads governed mutation (only if a safe test campaign exists)
Use the existing execution-request flow (submit → approve → dry-run → live) on a
non-critical PAUSED/ENABLED campaign: pause → readback → resume → readback.
Do not change budgets/bids/targeting. If no safe campaign exists, skip.
