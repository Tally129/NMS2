import React from "react";
import api from "../../../lib/api";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { DataTable, PanelHeader, StateBlock, fmtDateTime, fmtInt, fmtNum, useCachedQuery } from "./shared";

const RUN_COLS = [
  { key: "report_type", label: "Report" }, { key: "status", label: "Status" }, { key: "requested_offset", label: "Offset" },
  { key: "requested_limit", label: "Limit" }, { key: "provider_items_count", label: "Items consumed" }, { key: "rows_normalized", label: "Rows normalized" },
  { key: "provider_total_count", label: "Provider total" }, { key: "complete", label: "Complete" }, { key: "next_offset", label: "Next offset" },
  { key: "provider_cost", label: "Cost" }, { key: "finished_at", label: "Finished" },
];
const REPORT_HELP = {
  domain_rank_overview: "Domain overview (1 request)", ranked_keywords: "Organic ranking keywords (paged)", competitors_domain: "Organic competitors (paged)",
  keyword_gap: "Keyword gap — requires options.competitor_domain + mode", backlinks_summary: "Backlink summary (1 request)", backlinks: "Backlink rows (paged)", serp_rank: "Live SERP check per tracked keyword",
};

export default function ProviderStatusSection({ isAdmin }) {
  const runs = useCachedQuery(async () => (await api.get("/marketing-os/search/seo/provider-runs", { params: { limit: 25 } })).data, []);
  const sched = useCachedQuery(async () => (await api.get("/marketing-os/search/seo/schedules")).data, []);
  const gsc = useCachedQuery(async () => (await api.get("/marketing-os/search/search-console/runs", { params: { limit: 10 } })).data, []);
  const ready = useCachedQuery(async () => (await api.get("/marketing-os/search/seo/refresh/readiness")).data, []);

  const [form, setForm] = React.useState({ report_type: "ranked_keywords", start_offset: 0, limit: 1000, max_pages: 1, max_total_cost: 0.25, competitor_domain: "", mode: "shared", tracked_keyword_id: "" });
  const [plan, setPlan] = React.useState(null);
  const [result, setResult] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState("");
  const options = () => {
    const o = {};
    if (form.report_type === "keyword_gap") { o.competitor_domain = form.competitor_domain; o.mode = form.mode; }
    if (form.report_type === "serp_rank") o.tracked_keyword_id = form.tracked_keyword_id;
    return o;
  };
  const submit = async (live) => {
    setBusy(true); setErr("");
    try {
      const res = await api.post("/marketing-os/search/seo/refresh", {
        report_type: form.report_type, start_offset: Number(form.start_offset), limit: Number(form.limit), max_pages: Number(form.max_pages),
        max_total_cost: Number(form.max_total_cost), options: options(), dry_run: !live, confirm: live });
      if (live) { setResult(res.data); setPlan(null); runs.reload(); } else { setPlan(res.data.plan); setResult(null); }
    } catch (e) { setErr(e?.response?.data?.detail || "Request failed"); }
    finally { setBusy(false); }
  };
  const saveSchedule = async (row, patch) => {
    try {
      await api.put(`/marketing-os/search/seo/schedules/${row.report_type}`, {
        enabled: row.enabled, cadence_hours: row.cadence_hours, max_pages: row.max_pages, max_requests: row.max_requests,
        max_total_cost: Number(row.max_total_cost), retry_ceiling: row.retry_ceiling, limit_per_page: row.limit_per_page, options: row.options, ...patch });
      sched.reload();
    } catch (e) { setErr(e?.response?.data?.detail || "Failed to save schedule"); }
  };
  const providerReady = ready.data?.status === "connected";

  return (
    <>
      <div className="mb-6 rounded-xl border border-[#d8cba9] bg-white p-4" data-testid="provider-status-section">
        <PanelHeader title="Provider / Sync Status" badge="Ledger"
          subtitle="Every DataForSEO request NMS has made, with the provider metadata actually returned (items consumed, provider total, completeness, next offset, cost). Offsets advance by items consumed, never by rows stored." />
        <div className="mb-3 flex flex-wrap gap-2 text-xs" data-testid="provider-readiness">
          <span className={"rounded-full px-2 py-0.5 " + (providerReady ? "bg-emerald-50 text-emerald-800" : "bg-gray-100 text-gray-600")}>DataForSEO credentials: {ready.data?.status || "…"}</span>
          <span className={"rounded-full px-2 py-0.5 " + (sched.data?.scheduler_enabled ? "bg-emerald-50 text-emerald-800" : "bg-gray-100 text-gray-600")}>Automatic refresh: {sched.data?.scheduler_enabled ? "enabled (SEO_PROVIDER_REFRESH_ENABLED)" : "disabled (kill switch off)"}</span>
        </div>
        <StateBlock loading={runs.loading} error={runs.error} empty={(runs.data?.items || []).length === 0} testPrefix="runs" emptyText="No provider runs recorded yet.">
          <DataTable columns={RUN_COLS} rows={runs.data?.items || []} testPrefix="runs" rowKey={(r) => r.id}
            renderCell={(c, r) => {
              switch (c.key) {
                case "status": return <span className={r.status === "completed" ? "text-emerald-700" : "text-red-700"}>{r.status}</span>;
                case "complete": return r.complete === true ? "yes" : r.complete === false ? <span className="text-amber-700">no</span> : "—";
                case "provider_cost": return r.provider_cost === null || r.provider_cost === undefined ? "—" : `$${fmtNum(r.provider_cost, 4)}`;
                case "finished_at": return <span className="text-xs">{fmtDateTime(r.finished_at)}</span>;
                case "report_type": return <span className="text-xs font-medium">{r.report_type}<div className="text-[10px] text-[#a99b7d]">{r.target}</div></span>;
                default: return fmtInt(r[c.key]);
              }
            }} />
        </StateBlock>
      </div>

      <div className="mb-6 rounded-xl border border-[#d8cba9] bg-white p-4" data-testid="gsc-runs-section">
        <PanelHeader title="Search Console Sync Runs" badge="Ledger" subtitle="Completeness is derived from the pagination the sync actually performed (start_row paging until a short page). Historical runs recorded before this field existed show 'unknown'." />
        <StateBlock loading={gsc.loading} error={gsc.error} empty={(gsc.data?.items || []).length === 0} testPrefix="gscruns" emptyText="No Search Console sync runs recorded in this environment.">
          <DataTable columns={[{ key: "status", label: "Status" }, { key: "start_date", label: "From" }, { key: "end_date", label: "To" }, { key: "rows_synced", label: "Rows" }, { key: "completeness", label: "Completeness" }, { key: "pages_consumed", label: "Pages" }, { key: "safety_ceiling_reached", label: "Ceiling hit" }, { key: "finished_at", label: "Finished" }]}
            rows={gsc.data?.items || []} testPrefix="gscruns" rowKey={(r) => r.id}
            renderCell={(c, r) => c.key === "finished_at" ? fmtDateTime(r.finished_at) : c.key === "safety_ceiling_reached" ? (r.safety_ceiling_reached === null ? "—" : String(r.safety_ceiling_reached)) : c.key === "completeness" ? <span className={r.completeness === "complete" ? "text-emerald-700" : r.completeness === "incomplete" ? "text-amber-700" : "text-[#a99b7d]"}>{r.completeness}</span> : (typeof r[c.key] === "number" ? fmtInt(r[c.key]) : (r[c.key] ?? "—"))} />
        </StateBlock>
      </div>

      <div className="mb-6 rounded-xl border border-[#d8cba9] bg-white p-4" data-testid="schedules-section">
        <PanelHeader title="Automatic Refresh Schedules" badge={null} subtitle="Conservative, opt-in cadences (minimum daily; defaults weekly/fortnightly). A schedule only runs when it is enabled here AND the server kill switch is on AND provider credentials exist. First run is never immediate." />
        <StateBlock loading={sched.loading} error={sched.error} empty={false} testPrefix="sched">
          <DataTable columns={[{ key: "report_type", label: "Report" }, { key: "enabled", label: "Enabled" }, { key: "cadence_hours", label: "Cadence (h)" }, { key: "max_pages", label: "Max pages" }, { key: "max_requests", label: "Max requests" }, { key: "max_total_cost", label: "Max cost" }, { key: "last_status", label: "Last run" }, { key: "next_run_at", label: "Next run" }]}
            rows={sched.data?.items || []} testPrefix="sched" rowKey={(r) => r.report_type}
            renderCell={(c, r) => {
              switch (c.key) {
                case "report_type": return <span className="text-xs font-medium">{r.report_type}<div className="text-[10px] text-[#a99b7d]">{REPORT_HELP[r.report_type]}</div></span>;
                case "enabled": return isAdmin ? <input type="checkbox" checked={Boolean(r.enabled)} onChange={(e) => saveSchedule(r, { enabled: e.target.checked })} data-testid={`sched-toggle-${r.report_type}`} /> : (r.enabled ? "yes" : "no");
                case "max_total_cost": return `$${fmtNum(r.max_total_cost, 2)}`;
                case "last_status": return <span className="text-xs">{r.last_status || "never"}{r.last_error ? <div className="text-[10px] text-red-700">{r.last_error}</div> : null}<div className="text-[10px] text-[#a99b7d]">{fmtDateTime(r.last_run_at)}</div></span>;
                case "next_run_at": return <span className="text-xs">{r.enabled ? fmtDateTime(r.next_run_at) : "—"}</span>;
                default: return fmtInt(r[c.key]);
              }
            }} />
        </StateBlock>
      </div>

      {isAdmin ? (
        <div className="mb-6 rounded-xl border border-[#c19a4b] bg-[#fdfbf5] p-4" data-testid="refresh-section">
          <PanelHeader title="Governed Provider Refresh (admin)" badge="Paid provider call" subtitle="Preview first: the plan shows the exact endpoint scope, offset, page/cost bounds and tables written. Live execution requires explicit confirmation and is audit-logged." />
          <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6 text-xs">
            <label className="flex flex-col gap-1">Report
              <select value={form.report_type} onChange={(e) => setForm({ ...form, report_type: e.target.value })} className="h-9 rounded-md border border-[#d8cba9] bg-white px-2" data-testid="refresh-report">
                {(ready.data?.supported_reports || Object.keys(REPORT_HELP)).map((r) => <option key={r} value={r}>{r}</option>)}
              </select></label>
            <label className="flex flex-col gap-1">Start offset<Input type="number" min="0" value={form.start_offset} onChange={(e) => setForm({ ...form, start_offset: e.target.value })} className="h-9 border-[#d8cba9]" data-testid="refresh-offset" /></label>
            <label className="flex flex-col gap-1">Limit / page<Input type="number" min="1" max="1000" value={form.limit} onChange={(e) => setForm({ ...form, limit: e.target.value })} className="h-9 border-[#d8cba9]" /></label>
            <label className="flex flex-col gap-1">Max pages<Input type="number" min="1" max="20" value={form.max_pages} onChange={(e) => setForm({ ...form, max_pages: e.target.value })} className="h-9 border-[#d8cba9]" /></label>
            <label className="flex flex-col gap-1">Max cost ($)<Input type="number" step="0.05" min="0.05" max="5" value={form.max_total_cost} onChange={(e) => setForm({ ...form, max_total_cost: e.target.value })} className="h-9 border-[#d8cba9]" /></label>
            {form.report_type === "keyword_gap" ? (<>
              <label className="flex flex-col gap-1">Competitor domain<Input value={form.competitor_domain} onChange={(e) => setForm({ ...form, competitor_domain: e.target.value })} className="h-9 border-[#d8cba9]" data-testid="refresh-competitor" /></label>
              <label className="flex flex-col gap-1">Mode<select value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })} className="h-9 rounded-md border border-[#d8cba9] bg-white px-2"><option value="shared">shared (both rank)</option><option value="missing">missing (competitor only)</option><option value="untapped">untapped (NMS only)</option></select></label>
            </>) : null}
            {form.report_type === "serp_rank" ? <label className="flex flex-col gap-1">Tracked keyword id<Input value={form.tracked_keyword_id} onChange={(e) => setForm({ ...form, tracked_keyword_id: e.target.value })} className="h-9 border-[#d8cba9]" /></label> : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" disabled={busy} onClick={() => submit(false)} className="h-9 rounded-full border-[#c19a4b] text-[#8a6a3c]" data-testid="refresh-preview">Preview plan (no call)</Button>
            <Button type="button" disabled={busy || !plan || !providerReady} onClick={() => submit(true)} className="h-9 rounded-full bg-[#c19a4b] text-white" data-testid="refresh-execute">Execute live refresh</Button>
            {!providerReady ? <span className="text-xs text-[#a99b7d]">Live execution disabled: provider credentials not configured on this server.</span> : null}
            {err ? <span className="text-xs text-red-700" data-testid="refresh-error">{err}</span> : null}
          </div>
          {plan ? <pre className="mt-3 overflow-x-auto rounded-lg bg-white p-3 text-[11px] text-[#3f3320]" data-testid="refresh-plan">{JSON.stringify(plan, null, 2)}</pre> : null}
          {result ? <pre className="mt-3 overflow-x-auto rounded-lg bg-white p-3 text-[11px] text-[#3f3320]" data-testid="refresh-result">{JSON.stringify({ status: result.status, error: result.error, pages: result.pages, stop_reason: result.stop_reason, complete: result.complete, next_offset: result.next_offset, total_cost: result.total_cost, rows_normalized: result.rows_normalized, rows_persisted: result.rows_persisted, provider_run_ids: result.provider_run_ids }, null, 2)}</pre> : null}
        </div>
      ) : null}
    </>
  );
}
