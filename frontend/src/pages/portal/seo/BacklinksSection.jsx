import React from "react";
import api from "../../../lib/api";
import { Input } from "../../../components/ui/input";
import { DataTable, Kpi, Pager, PanelHeader, StateBlock, fmtDate, fmtDateTime, fmtInt, useCachedQuery } from "./shared";

const COLUMNS = [
  { key: "source_url", label: "Source page", sortable: false },
  { key: "anchor", label: "Anchor", sortable: false },
  { key: "target_url", label: "Target URL", sortable: false },
  { key: "dofollow", label: "Follow", sortable: false },
  { key: "domain_from_rank", label: "Domain rank", sortable: true },
  { key: "page_from_rank", label: "Page rank", sortable: true },
  { key: "backlink_spam_score", label: "Spam", sortable: true },
  { key: "first_seen", label: "First seen", sortable: true },
  { key: "last_seen", label: "Last seen", sortable: true },
  { key: "status", label: "Status", sortable: false },
];

export default function BacklinksSection() {
  const [status, setStatus] = React.useState("");
  const [follow, setFollow] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [debounced, setDebounced] = React.useState("");
  const [sort, setSort] = React.useState({ key: "domain_from_rank", dir: "desc" });
  const [page, setPage] = React.useState({ offset: 0, limit: 25 });
  React.useEffect(() => { const t = setTimeout(() => setDebounced(search), 350); return () => clearTimeout(t); }, [search]);

  const summary = useCachedQuery(async () => (await api.get("/marketing-os/search/seo/backlinks/summary")).data, []);
  const list = useCachedQuery(async () => (await api.get("/marketing-os/search/seo/backlinks", { params: {
    status: status || undefined, dofollow: follow === "" ? undefined : follow === "dofollow", search: debounced || undefined,
    sort: sort.key, direction: sort.dir, limit: page.limit, offset: page.offset } })).data,
  [status, follow, debounced, sort.key, sort.dir, page.offset, page.limit]);

  const s = summary.data?.summary;
  const items = list.data?.items || [];
  const onSort = (key) => { setSort((x) => ({ key, dir: x.key === key && x.dir === "desc" ? "asc" : "desc" })); setPage((p) => ({ ...p, offset: 0 })); };
  const src = s?.provider || "dataforseo";

  return (
    <div className="mb-6 rounded-xl border border-[#d8cba9] bg-white p-4" data-testid="backlinks-section">
      <PanelHeader title="Backlinks"
        subtitle={`Backlink profile from the cached DataForSEO Backlinks snapshot${s ? ` (captured ${fmtDate(s.captured_date)}, target ${s.target})` : ""}. Totals come from the provider summary; new/lost counts are derived from the sampled backlink rows stored for the same date and are labelled as sampled.`} />
      <StateBlock loading={summary.loading} error={summary.error} empty={!s} testPrefix="bl-summary"
        emptyText="No cached backlink summary yet. Run a governed backlinks_summary refresh (1 request) from Provider / Sync.">
        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Kpi label="Backlinks" value={fmtInt(s?.backlinks)} source={src} testId="bl-kpi-backlinks" />
          <Kpi label="Referring domains" value={fmtInt(s?.referring_domains)} source={src} />
          <Kpi label="Referring pages" value={fmtInt(s?.referring_pages)} source={src} />
          <Kpi label="Dofollow / Nofollow" value={`${fmtInt(s?.dofollow_links)} / ${fmtInt(s?.nofollow_links)}`} source={src} hint="Derived from provider attribute counts" />
          <Kpi label="New links (sampled)" value={fmtInt(s?.sampled?.new_sampled)} source={src} hint={`of ${fmtInt(s?.sampled?.sampled_rows)} sampled rows`} />
          <Kpi label="Lost links (sampled)" value={fmtInt(s?.sampled?.lost_sampled)} source={src} hint="Provider is_lost flag" />
        </div>
      </StateBlock>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {[["", "All"], ["new", "New"], ["lost", "Lost"], ["broken", "Broken"]].map(([v, label]) => (
          <button key={v} type="button" onClick={() => { setStatus(v); setPage((p) => ({ ...p, offset: 0 })); }}
            className={"rounded-full border px-3 py-1 text-xs " + (status === v ? "border-[#c19a4b] bg-[#c19a4b] text-white" : "border-[#d8cba9] text-[#6b5836]")}
            data-testid={`bl-status-${v || "all"}`}>{label}</button>
        ))}
        <select value={follow} onChange={(e) => { setFollow(e.target.value); setPage((p) => ({ ...p, offset: 0 })); }}
          className="h-8 rounded-md border border-[#d8cba9] bg-white px-2 text-xs" data-testid="bl-follow">
          <option value="">Follow: any</option><option value="dofollow">Dofollow</option><option value="nofollow">Nofollow</option>
        </select>
        <Input value={search} onChange={(e) => { setSearch(e.target.value); setPage((p) => ({ ...p, offset: 0 })); }} placeholder="Search source, anchor, domain…"
          className="h-8 w-64 border-[#d8cba9]" data-testid="bl-search" />
      </div>
      <StateBlock loading={list.loading} error={list.error} empty={!list.data?.has_snapshot} testPrefix="bl"
        emptyText="No cached backlink rows yet. Run a governed backlinks refresh (paged, cost-bounded) from Provider / Sync.">
        <DataTable columns={COLUMNS} rows={items} sort={sort} onSort={onSort} testPrefix="bl" rowKey={(r) => r.id}
          renderCell={(c, r) => {
            switch (c.key) {
              case "source_url": return <a href={r.source_url} target="_blank" rel="noreferrer" className="block max-w-[240px] truncate text-xs underline decoration-[#d8cba9]" title={r.source_url}>{r.source_domain || r.source_url}</a>;
              case "anchor": return <span className="block max-w-[180px] truncate text-xs" title={r.anchor || ""}>{r.anchor || "—"}</span>;
              case "target_url": return <span className="block max-w-[200px] truncate text-xs text-[#6b5836]" title={r.target_url || ""}>{r.target_url || "—"}</span>;
              case "dofollow": return r.dofollow === null || r.dofollow === undefined ? "—" : (r.dofollow ? <span className="text-emerald-700">dofollow</span> : <span className="text-[#a99b7d]">nofollow</span>);
              case "first_seen": return fmtDateTime(r.first_seen);
              case "last_seen": return fmtDateTime(r.last_seen);
              case "status": return (
                <span className="flex gap-1 text-[10px]">
                  {r.is_new ? <span className="rounded bg-emerald-50 px-1 text-emerald-800">new</span> : null}
                  {r.is_lost ? <span className="rounded bg-red-50 px-1 text-red-800">lost</span> : null}
                  {r.is_broken ? <span className="rounded bg-amber-50 px-1 text-amber-800">broken</span> : null}
                  {!r.is_new && !r.is_lost && !r.is_broken ? <span className="text-[#a99b7d]">live</span> : null}
                </span>
              );
              default: return fmtInt(r[c.key]);
            }
          }} />
        {items.length === 0 ? <div className="py-4 text-center text-sm text-[#8a6a3c]" data-testid="bl-filter-empty">No backlinks match this filter.</div> : null}
        <Pager offset={page.offset} limit={page.limit} total={list.data?.total || 0} hasMore={Boolean(list.data?.has_more)} onChange={setPage} testPrefix="bl" />
      </StateBlock>
    </div>
  );
}
