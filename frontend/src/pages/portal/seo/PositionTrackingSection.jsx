import React from "react";
import api from "../../../lib/api";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Change, DataTable, Kpi, PanelHeader, StateBlock, fmtDateTime, fmtInt, fmtNum, useCachedQuery } from "./shared";

const COLUMNS = [
  { key: "keyword", label: "Tracked keyword" }, { key: "device", label: "Device / location" },
  { key: "latest_position", label: "Position" }, { key: "position_change", label: "Change" },
  { key: "latest_url", label: "Ranking URL" }, { key: "latest_serp_features", label: "SERP features" },
  { key: "latest_observed_at", label: "Last observed" }, { key: "observation_count", label: "Obs." }, { key: "actions", label: "" },
];

function Sparkline({ points }) {
  const vals = points.map((p) => (p.position === null || p.position === undefined ? null : Number(p.position)));
  const known = vals.filter((v) => v !== null);
  if (known.length < 2) return <span className="text-xs text-[#a99b7d]">Not enough observations to graph yet.</span>;
  const max = Math.max(...known), min = Math.min(...known), w = 320, h = 60;
  const x = (i) => (i / (vals.length - 1)) * (w - 8) + 4;
  const y = (v) => (max === min ? h / 2 : 4 + ((v - min) / (max - min)) * (h - 8)); // lower position = higher on chart
  const d = vals.map((v, i) => (v === null ? null : `${x(i)},${y(v)}`)).filter(Boolean).join(" ");
  return (
    <svg width={w} height={h} className="block" data-testid="rt-sparkline">
      <polyline fill="none" stroke="#c19a4b" strokeWidth="2" points={d} />
      {vals.map((v, i) => (v === null ? null : <circle key={i} cx={x(i)} cy={y(v)} r="3" fill="#3f3320" />))}
    </svg>
  );
}

export default function PositionTrackingSection({ isAdmin }) {
  const [keyword, setKeyword] = React.useState("");
  const [device, setDevice] = React.useState("desktop");
  const [busy, setBusy] = React.useState(false);
  const [formError, setFormError] = React.useState("");
  const [openId, setOpenId] = React.useState(null);
  const q = useCachedQuery(async () => (await api.get("/marketing-os/search/seo/tracked-keywords")).data, []);
  const hist = useCachedQuery(async () => (openId ? (await api.get(`/marketing-os/search/seo/tracked-keywords/${openId}/history`)).data : null), [openId]);
  const s = q.data?.summary || {};
  const items = q.data?.items || [];
  const src = "dataforseo_serp";

  const add = async () => {
    setBusy(true); setFormError("");
    try { await api.post("/marketing-os/search/seo/tracked-keywords", { keyword, device }); setKeyword(""); q.reload(); }
    catch (err) { setFormError(err?.response?.data?.detail || "Failed to add tracked keyword"); }
    finally { setBusy(false); }
  };
  const remove = async (id) => { try { await api.delete(`/marketing-os/search/seo/tracked-keywords/${id}`); q.reload(); } catch (err) { setFormError(err?.response?.data?.detail || "Failed"); } };

  return (
    <div className="mb-6 rounded-xl border border-[#d8cba9] bg-white p-4" data-testid="position-tracking-section">
      <PanelHeader title="Position Tracking"
        subtitle="Exact live Google rankings for selected keywords (DataForSEO SERP, cached observations). Only tracked keywords are checked, on the governed schedule or via an admin refresh — never the whole keyword universe, never on page load." />
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
        <Kpi label="Tracked" value={fmtInt(s.tracked)} source={src} testId="rt-kpi-tracked" />
        <Kpi label="Top 3" value={fmtInt(s.top_3)} source={src} />
        <Kpi label="Top 10" value={fmtInt(s.top_10)} source={src} />
        <Kpi label="Top 20" value={fmtInt(s.top_20)} source={src} />
        <Kpi label="Improved" value={fmtInt(s.improved)} source={src} hint="vs. previous observation" />
        <Kpi label="Declined" value={fmtInt(s.declined)} source={src} hint="vs. previous observation" />
        <Kpi label="Avg. position" value={fmtNum(s.average_position, 1)} source={src} />
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Input value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="Add keyword to track…" className="h-9 w-72 border-[#d8cba9]" data-testid="rt-add-input" />
        <select value={device} onChange={(e) => setDevice(e.target.value)} className="h-9 rounded-md border border-[#d8cba9] bg-white px-2 text-sm" data-testid="rt-add-device">
          <option value="desktop">Desktop</option><option value="mobile">Mobile</option>
        </select>
        <Button type="button" disabled={busy || !keyword.trim()} onClick={add} className="h-9 rounded-full bg-[#c19a4b] text-white" data-testid="rt-add-btn">Track keyword</Button>
        <span className="text-xs text-[#a99b7d]">Adding a keyword stores it only; no SERP request is made until a governed refresh runs.</span>
        {formError ? <span className="text-xs text-red-700" data-testid="rt-form-error">{formError}</span> : null}
      </div>
      <StateBlock loading={q.loading} error={q.error} empty={items.length === 0} testPrefix="rt" emptyText="No tracked keywords yet. Add the keywords that matter and run a governed serp_rank refresh.">
        <DataTable columns={COLUMNS} rows={items} testPrefix="rt" rowKey={(r) => r.id}
          renderCell={(c, r) => {
            switch (c.key) {
              case "keyword": return <span className="font-medium text-[#3f3320]">{r.keyword}</span>;
              case "device": return <span className="text-xs text-[#6b5836]">{r.device} · {r.location}</span>;
              case "latest_position": return r.latest_found === false ? <span className="text-xs text-[#a99b7d]">not in top {fmtInt(100)}</span> : fmtInt(r.latest_position);
              case "position_change": return <Change value={r.position_change} />;
              case "latest_url": return <span className="block max-w-[220px] truncate text-xs text-[#6b5836]" title={r.latest_url || ""}>{r.latest_url || "—"}</span>;
              case "latest_serp_features": return Array.isArray(r.latest_serp_features) && r.latest_serp_features.length ? <span className="text-[10px] text-[#6b5836]">{r.latest_serp_features.slice(0, 3).join(", ")}</span> : "—";
              case "latest_observed_at": return <span className="text-xs">{fmtDateTime(r.latest_observed_at)}</span>;
              case "observation_count": return fmtInt(r.observation_count);
              case "actions": return (
                <span className="flex gap-2 text-xs">
                  <button type="button" className="underline decoration-[#d8cba9] text-[#8a6a3c]" onClick={() => setOpenId(openId === r.id ? null : r.id)} data-testid="rt-history">History</button>
                  <button type="button" className="text-red-700 underline decoration-red-200" onClick={() => remove(r.id)} data-testid="rt-remove">Stop</button>
                </span>
              );
              default: return r[c.key] ?? "—";
            }
          }} />
        {openId ? (
          <div className="mt-3 rounded-lg bg-[#faf6ec] p-3" data-testid="rt-history-panel">
            <div className="mb-1 text-xs font-medium text-[#6b5836]">Position history (newest right; lower is better)</div>
            {hist.loading ? <span className="text-xs">Loading…</span> : <Sparkline points={[...(hist.data?.items || [])].reverse()} />}
            <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-[#6b5836]">
              {(hist.data?.items || []).slice(0, 12).map((o) => <span key={o.id} className="rounded bg-white px-1.5 py-0.5">{fmtDateTime(o.observed_at)}: {o.found ? `#${o.position}` : "not found"}</span>)}
            </div>
          </div>
        ) : null}
      </StateBlock>
    </div>
  );
}
