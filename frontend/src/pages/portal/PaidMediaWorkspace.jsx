import React from "react";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { useAuth } from "../../lib/auth";
import { DataTable, Kpi, Pager, PanelHeader, StateBlock, fmtDateTime, fmtInt, fmtMoney, fmtNum, useCachedQuery } from "./seo/shared";

/* Cross-channel paid media workspace (Google · Meta · Microsoft).
 * Reads CACHED PostgreSQL routes only:
 *   GET /marketing-os/paid/campaigns      unified campaign table (normalized metrics; provider metrics kept per row)
 *   GET /marketing-os/paid/sync-status    connection / freshness per provider
 * The only provider call is the admin governed sync (dry-run first). */

const PROVIDERS = [["", "All providers"], ["google_ads", "Google Ads"], ["meta_ads", "Meta Ads"], ["microsoft_ads", "Microsoft Ads"]];
const PROVIDER_LABEL = { google_ads: "Google Ads", meta_ads: "Meta Ads", microsoft_ads: "Microsoft Ads" };
const PROVIDER_STYLE = { google_ads: "bg-blue-50 text-blue-800", meta_ads: "bg-indigo-50 text-indigo-800", microsoft_ads: "bg-teal-50 text-teal-800" };
const COLUMNS = [
  { key: "provider", label: "Provider" }, { key: "campaign_name", label: "Campaign" }, { key: "status", label: "Status" },
  { key: "campaign_type", label: "Objective / type" }, { key: "daily_budget", label: "Budget" }, { key: "spend", label: "Spend" },
  { key: "impressions", label: "Impr." }, { key: "clicks", label: "Clicks" }, { key: "ctr", label: "CTR" }, { key: "cpc", label: "CPC" },
  { key: "conversions", label: "Conv." }, { key: "cpa", label: "CPA" }, { key: "conversion_value", label: "Conv. value" }, { key: "roas", label: "ROAS" },
  { key: "last_updated", label: "Updated" },
];

function daysAgo(n) { const d = new Date(); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); }

export default function PaidMediaWorkspace() {
  const auth = useAuth();
  const isAdmin = (auth?.user?.role || "") === "admin";
  const [tab, setTab] = React.useState("campaigns");
  const [provider, setProvider] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [debounced, setDebounced] = React.useState("");
  const [range, setRange] = React.useState({ start: daysAgo(30), end: daysAgo(1) });
  const [page, setPage] = React.useState({ offset: 0, limit: 25 });
  React.useEffect(() => { const t = setTimeout(() => setDebounced(search), 350); return () => clearTimeout(t); }, [search]);

  const campaigns = useCachedQuery(async () => (await api.get("/marketing-os/paid/campaigns", { params: {
    provider: provider || undefined, status: status || undefined, search: debounced || undefined,
    start_date: range.start, end_date: range.end, limit: page.limit, offset: page.offset } })).data,
  [provider, status, debounced, range.start, range.end, page.offset, page.limit]);
  const syncStatus = useCachedQuery(async () => (await api.get("/marketing-os/paid/sync-status")).data, []);

  const items = React.useMemo(() => campaigns.data?.items || [], [campaigns.data]);
  const totals = React.useMemo(() => items.reduce((a, r) => ({ spend: a.spend + (r.spend || 0), clicks: a.clicks + (r.clicks || 0),
    impressions: a.impressions + (r.impressions || 0), conversions: a.conversions + (r.conversions || 0), value: a.value + (r.conversion_value || 0) }),
    { spend: 0, clicks: 0, impressions: 0, conversions: 0, value: 0 }), [items]);

  const [syncPlan, setSyncPlan] = React.useState(null);
  const [syncResult, setSyncResult] = React.useState(null);
  const [syncErr, setSyncErr] = React.useState("");
  const runSync = async (p, live) => {
    setSyncErr("");
    try {
      const res = await api.post(`/marketing-os/paid/${p}/sync`, { start_date: range.start, end_date: range.end, dry_run: !live, confirm: live });
      if (live) { setSyncResult(res.data); setSyncPlan(null); syncStatus.reload(); campaigns.reload(); } else { setSyncPlan(res.data.plan); setSyncResult(null); }
    } catch (e) { setSyncErr(e?.response?.data?.detail || "Sync request failed"); }
  };

  return (
    <section className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5" data-testid="paid-media-workspace">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="font-display text-xl text-[#1f2a22]">Cross-Channel Campaigns</div>
        <nav className="flex gap-1" data-testid="pm-tabs">
          {[["campaigns", "Campaigns"], ["sync", "Sync Status"]].map(([k, l]) => (
            <button key={k} type="button" onClick={() => setTab(k)} data-testid={`pm-tab-${k}`}
              className={"rounded-full px-3 py-1 text-xs " + (tab === k ? "bg-[#2f4a3a] text-white" : "border border-[#d8cba9] text-[#6b5836]")}>{l}</button>
          ))}
        </nav>
      </div>

      {tab === "campaigns" ? (
        <div className="rounded-xl border border-[#d8cba9] bg-white p-4" data-testid="pm-campaigns">
          <PanelHeader title="Unified campaign table" subtitle="Normalized spend / clicks / conversions across providers from cached daily metrics. Metrics that providers define differently (e.g. Meta results, Microsoft conversion rate) stay in each row's provider metrics and are not blended." />
          <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
            <Kpi label="Spend (page)" value={fmtMoney(totals.spend)} hint="sum of visible rows" testId="pm-kpi-spend" />
            <Kpi label="Impressions" value={fmtInt(totals.impressions)} />
            <Kpi label="Clicks" value={fmtInt(totals.clicks)} hint={totals.clicks ? `blended CPC ${fmtMoney(totals.spend / totals.clicks)}` : ""} />
            <Kpi label="Conversions" value={fmtNum(totals.conversions, 1)} hint={totals.conversions ? `blended CPA ${fmtMoney(totals.spend / totals.conversions)}` : ""} />
            <Kpi label="Conv. value / ROAS" value={`${fmtMoney(totals.value)}${totals.spend && totals.value ? ` · ${fmtNum(totals.value / totals.spend, 2)}x` : ""}`} hint="only where providers report value" />
          </div>
          <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
            <select value={provider} onChange={(e) => { setProvider(e.target.value); setPage((p) => ({ ...p, offset: 0 })); }} className="h-8 rounded-md border border-[#d8cba9] bg-white px-2" data-testid="pm-provider">
              {PROVIDERS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
            <Input value={status} onChange={(e) => { setStatus(e.target.value); setPage((p) => ({ ...p, offset: 0 })); }} placeholder="Status (e.g. ENABLED, PAUSED)" className="h-8 w-48 border-[#d8cba9]" data-testid="pm-status" />
            <Input value={search} onChange={(e) => { setSearch(e.target.value); setPage((p) => ({ ...p, offset: 0 })); }} placeholder="Search campaign…" className="h-8 w-52 border-[#d8cba9]" data-testid="pm-search" />
            <label className="flex items-center gap-1">From <Input type="date" value={range.start} onChange={(e) => setRange({ ...range, start: e.target.value })} className="h-8 border-[#d8cba9]" data-testid="pm-start" /></label>
            <label className="flex items-center gap-1">To <Input type="date" value={range.end} onChange={(e) => setRange({ ...range, end: e.target.value })} className="h-8 border-[#d8cba9]" data-testid="pm-end" /></label>
          </div>
          <StateBlock loading={campaigns.loading} error={campaigns.error} empty={items.length === 0} testPrefix="pm"
            emptyText="No cached campaign metrics for this range. Connect a provider and run a governed sync from Sync Status (providers are never called on page load).">
            <DataTable columns={COLUMNS} rows={items} testPrefix="pm" rowKey={(r) => `${r.provider}-${r.campaign_id}`}
              renderCell={(c, r) => {
                switch (c.key) {
                  case "provider": return <span className={"rounded-full px-2 py-0.5 text-[10px] font-medium " + (PROVIDER_STYLE[r.provider] || "")}>{PROVIDER_LABEL[r.provider] || r.provider}</span>;
                  case "campaign_name": return <span className="font-medium text-[#3f3320]">{r.campaign_name || r.campaign_id}</span>;
                  case "status": return <span className="text-xs">{r.status || "—"}</span>;
                  case "campaign_type": return <span className="text-xs text-[#6b5836]">{r.objective || r.campaign_type || "—"}</span>;
                  case "daily_budget": return r.daily_budget ? `${fmtMoney(r.daily_budget)}/day` : "—";
                  case "spend": case "cpc": case "cpa": case "conversion_value": return fmtMoney(r[c.key]);
                  case "ctr": return r.ctr === null || r.ctr === undefined ? "—" : `${(r.ctr * 100).toFixed(2)}%`;
                  case "roas": return r.roas === null || r.roas === undefined ? "—" : `${fmtNum(r.roas, 2)}x`;
                  case "conversions": return fmtNum(r.conversions, 1);
                  case "last_updated": return <span className="text-xs">{fmtDateTime(r.last_updated)}</span>;
                  default: return fmtInt(r[c.key]);
                }
              }} />
            <Pager offset={page.offset} limit={page.limit} total={campaigns.data?.total || 0} hasMore={Boolean(campaigns.data?.has_more)} onChange={setPage} testPrefix="pm" />
          </StateBlock>
        </div>
      ) : (
        <div className="rounded-xl border border-[#d8cba9] bg-white p-4" data-testid="pm-sync">
          <PanelHeader title="Provider sync status" badge="Cached" subtitle={`Automatic sync: ${syncStatus.data?.scheduler_enabled ? "enabled (daily, advisory-locked)" : "disabled (PAID_MEDIA_SYNC_ENABLED kill switch off)"}. Dashboards read cached data; a sync is an explicit, audited provider read.`} />
          <StateBlock loading={syncStatus.loading} error={syncStatus.error} empty={false} testPrefix="pm-sync">
            <div className="grid gap-3 lg:grid-cols-3">
              {(syncStatus.data?.items || []).map((p) => (
                <div key={p.provider} className="rounded-xl border border-[#e7dcc2] p-3 text-sm" data-testid={`pm-sync-${p.provider}`}>
                  <div className="mb-1 flex items-center justify-between"><span className="font-semibold">{PROVIDER_LABEL[p.provider]}</span>
                    <span className={"rounded-full px-2 py-0.5 text-[10px] " + (p.connected ? "bg-emerald-50 text-emerald-800" : "bg-gray-100 text-gray-600")}>{p.readiness}</span></div>
                  <div className="text-xs text-[#6b5836]">Last successful sync: {fmtDateTime(p.last_successful_sync)}</div>
                  <div className="text-xs text-[#6b5836]">Latest metric date: {p.latest_metric_date || "—"}{p.data_age_days !== null && p.data_age_days !== undefined ? ` (${p.data_age_days}d old)` : ""}</div>
                  <div className="text-xs text-[#6b5836]">Cached campaigns: {fmtInt(p.cached_campaigns)} · rows: {fmtInt(p.cached_rows)}</div>
                  {p.account ? <div className="text-[11px] text-[#a99b7d]">Account {p.account.external_account_id} · write {p.account.write_enabled ? "enabled" : "disabled"}</div> : <div className="text-[11px] text-[#a99b7d]">No channel account registered</div>}
                  {isAdmin ? (
                    <div className="mt-2 flex gap-2">
                      <Button type="button" variant="outline" className="h-7 rounded-full border-[#d8cba9] text-xs" onClick={() => runSync(p.provider, false)} data-testid={`pm-sync-preview-${p.provider}`}>Preview sync</Button>
                      <Button type="button" className="h-7 rounded-full bg-[#2f4a3a] text-xs text-white" disabled={!p.connected || !syncPlan || syncPlan.provider !== p.provider} onClick={() => runSync(p.provider, true)} data-testid={`pm-sync-run-${p.provider}`}>Run sync</Button>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
            {syncErr ? <div className="mt-3 text-xs text-red-700" data-testid="pm-sync-error">{syncErr}</div> : null}
            {syncPlan ? <pre className="mt-3 overflow-x-auto rounded-lg bg-[#faf6ec] p-3 text-[11px]" data-testid="pm-sync-plan">{JSON.stringify(syncPlan, null, 2)}</pre> : null}
            {syncResult ? <pre className="mt-3 overflow-x-auto rounded-lg bg-[#faf6ec] p-3 text-[11px]" data-testid="pm-sync-result">{JSON.stringify(syncResult, null, 2)}</pre> : null}
          </StateBlock>
        </div>
      )}
    </section>
  );
}
