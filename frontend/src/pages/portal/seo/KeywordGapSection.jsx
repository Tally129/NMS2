import React from "react";
import api from "../../../lib/api";
import { Input } from "../../../components/ui/input";
import { DataTable, IntentPill, Pager, PanelHeader, StateBlock, fmtDate, fmtInt, fmtMoney, fmtNum, useCachedQuery } from "./shared";

const GAP_TABS = [
  ["", "All"], ["missing", "Missing"], ["weak", "Weak"], ["strong", "Strong"], ["shared", "Shared"], ["untapped", "Untapped"],
];
const GAP_HELP = {
  missing: "Competitor ranks, NMS does not", weak: "Both rank, competitor is better", strong: "Both rank, NMS is better",
  shared: "Both rank at the same position", untapped: "NMS ranks, competitor does not",
};
const COLUMNS = [
  { key: "keyword", label: "Keyword", sortable: true },
  { key: "gap_type", label: "Bucket", sortable: false },
  { key: "target_rank", label: "NMS pos.", sortable: true },
  { key: "competitor_rank", label: "Competitor pos.", sortable: true },
  { key: "search_volume", label: "Volume", sortable: true },
  { key: "cpc", label: "CPC", sortable: true },
  { key: "intent", label: "Intent", sortable: false },
  { key: "keyword_difficulty", label: "KD", sortable: true },
  { key: "competitor_etv", label: "Competitor est. traffic", sortable: true },
  { key: "url", label: "Ranking URLs", sortable: false },
];

export default function KeywordGapSection({ initialCompetitor }) {
  const [competitor, setCompetitor] = React.useState(initialCompetitor || "");
  const [gapType, setGapType] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [debounced, setDebounced] = React.useState("");
  const [sort, setSort] = React.useState({ key: "search_volume", dir: "desc" });
  const [page, setPage] = React.useState({ offset: 0, limit: 25 });
  React.useEffect(() => { const t = setTimeout(() => setDebounced(search), 350); return () => clearTimeout(t); }, [search]);
  React.useEffect(() => { if (initialCompetitor) setCompetitor(initialCompetitor); }, [initialCompetitor]);

  const comps = useCachedQuery(async () => (await api.get("/marketing-os/search/seo/keyword-gap/competitors")).data, []);
  React.useEffect(() => {
    if (!competitor && comps.data?.items?.length) setCompetitor(comps.data.items[0].competitor_domain);
  }, [comps.data, competitor]);

  const gap = useCachedQuery(async () => {
    if (!competitor) return null;
    const res = await api.get("/marketing-os/search/seo/keyword-gap", { params: {
      competitor_domain: competitor, gap_type: gapType || undefined, search: debounced || undefined,
      sort: sort.key, direction: sort.dir, limit: page.limit, offset: page.offset } });
    return res.data;
  }, [competitor, gapType, debounced, sort.key, sort.dir, page.offset, page.limit]);

  const onSort = (key) => { setSort((s) => ({ key, dir: s.key === key && s.dir === "desc" ? "asc" : "desc" })); setPage((p) => ({ ...p, offset: 0 })); };
  const items = gap.data?.items || [];
  const counts = gap.data?.counts || {};
  const options = [...(comps.data?.items || []).map((c) => c.competitor_domain), ...(comps.data?.candidates || []).map((c) => c.competitor_domain)];

  return (
    <div className="mb-6 rounded-xl border border-[#d8cba9] bg-white p-4" data-testid="keyword-gap-section">
      <PanelHeader title="Keyword Gap"
        subtitle={`Domain vs. competitor keyword intersection from the cached DataForSEO Labs snapshot${gap.data?.captured_date ? ` (captured ${fmtDate(gap.data.captured_date)})` : ""}. Buckets are derived only from the two provider ranks. Opening this page never triggers a provider request.`}
        right={
          <select value={competitor} onChange={(e) => { setCompetitor(e.target.value); setPage((p) => ({ ...p, offset: 0 })); }}
            className="h-9 rounded-md border border-[#d8cba9] bg-white px-2 text-sm" data-testid="gap-competitor-select">
            {options.length === 0 ? <option value="">No competitors cached</option> : null}
            {options.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        } />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {GAP_TABS.map(([v, label]) => (
          <button key={v} type="button" onClick={() => { setGapType(v); setPage((p) => ({ ...p, offset: 0 })); }} title={GAP_HELP[v]}
            className={"rounded-full border px-3 py-1 text-xs " + (gapType === v ? "border-[#c19a4b] bg-[#c19a4b] text-white" : "border-[#d8cba9] text-[#6b5836]")}
            data-testid={`gap-tab-${v || "all"}`}>
            {label}{v ? ` (${fmtInt(counts[v] ?? 0)})` : ""}
          </button>
        ))}
        <Input value={search} onChange={(e) => { setSearch(e.target.value); setPage((p) => ({ ...p, offset: 0 })); }} placeholder="Search keywords…"
          className="h-8 w-56 border-[#d8cba9]" data-testid="gap-search" />
        {gapType ? <span className="text-xs text-[#a99b7d]">{GAP_HELP[gapType]}</span> : null}
      </div>
      <StateBlock loading={comps.loading || gap.loading} error={comps.error || gap.error} testPrefix="gap"
        empty={!competitor || !gap.data?.has_snapshot || (items.length === 0 && !debounced && !gapType)}
        emptyText={!competitor ? "No competitor selected. Run a governed keyword_gap refresh from Provider / Sync for a competitor domain." : `No cached keyword-gap snapshot for ${competitor} yet. Run a governed keyword_gap refresh (modes: shared, missing).`}>
        <DataTable columns={COLUMNS} rows={items} sort={sort} onSort={onSort} testPrefix="gap" rowKey={(r) => r.id}
          renderCell={(c, r) => {
            switch (c.key) {
              case "keyword": return <span className="font-medium text-[#3f3320]">{r.keyword}</span>;
              case "gap_type": return <span className="rounded bg-[#faf6ec] px-1.5 py-0.5 text-[10px] uppercase text-[#6b5836]">{r.gap_type}</span>;
              case "target_rank": return fmtInt(r.target_rank);
              case "competitor_rank": return fmtInt(r.competitor_rank);
              case "search_volume": return fmtInt(r.search_volume);
              case "cpc": return fmtMoney(r.cpc);
              case "intent": return <IntentPill intent={r.intent} />;
              case "keyword_difficulty": return fmtInt(r.keyword_difficulty);
              case "competitor_etv": return fmtNum(r.competitor_etv, 1);
              case "url": return (
                <div className="max-w-[260px] truncate text-xs text-[#6b5836]" title={`${r.target_url || ""}\n${r.competitor_url || ""}`}>
                  {r.target_url ? <div className="truncate">NMS: {r.target_url}</div> : null}
                  {r.competitor_url ? <div className="truncate">Comp: {r.competitor_url}</div> : null}
                  {!r.target_url && !r.competitor_url ? "—" : null}
                </div>
              );
              default: return r[c.key] ?? "—";
            }
          }} />
        {items.length === 0 ? <div className="py-4 text-center text-sm text-[#8a6a3c]" data-testid="gap-filter-empty">No keywords match this filter.</div> : null}
        <Pager offset={page.offset} limit={page.limit} total={gap.data?.total || 0} hasMore={Boolean(gap.data?.has_more)} onChange={setPage} testPrefix="gap" />
      </StateBlock>
    </div>
  );
}
