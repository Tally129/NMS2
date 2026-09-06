import React from "react";
import api from "../../../lib/api";
import Phase3Section from "../Phase3Section";
import { DataTable, Pager, PanelHeader, StateBlock, fmtDate, fmtInt, fmtNum, useCachedQuery } from "./shared";

const COLUMNS = [
  { key: "domain", label: "Competitor domain", sortable: false },
  { key: "intersections", label: "Common keywords", sortable: false },
  { key: "avg_position", label: "Avg. competitor position", sortable: false },
  { key: "competitor_organic_keywords", label: "Competitor keywords", sortable: false },
  { key: "competitor_estimated_traffic", label: "Est. traffic", sortable: false },
  { key: "captured_date", label: "Captured", sortable: false },
  { key: "gap", label: "Keyword gap", sortable: false },
];

/* DataForSEO competitors_domain snapshot (cached). Rows are unique per
 * normalized domain (www.example.com and example.com collapse). */
export default function CompetitorsSection({ onOpenGap }) {
  const [page, setPage] = React.useState({ offset: 0, limit: 25 });
  const q = useCachedQuery(async () => {
    const res = await api.get("/marketing-os/search/seo/competitors", { params: page });
    return res.data;
  }, [page.offset, page.limit]);
  const items = q.data?.items || [];
  const gapped = new Set(q.data?.gapped || []);
  return (
    <>
      <div className="mb-6 rounded-xl border border-[#d8cba9] bg-white p-4" data-testid="competitors-section">
        <PanelHeader
          title="Organic Competitors"
          subtitle={`Third-party competitor intelligence from the cached DataForSEO Labs snapshot${q.data?.captured_date ? ` (captured ${fmtDate(q.data.captured_date)})` : ""}. Common keywords = keywords both domains rank for. Not Google Search Console data.`}
        />
        <StateBlock loading={q.loading} error={q.error} empty={!q.data?.has_snapshot || items.length === 0} testPrefix="comp"
          emptyText="No cached competitor snapshot yet. Run a governed competitors_domain refresh from Provider / Sync.">
          <DataTable columns={COLUMNS} rows={items} testPrefix="comp" rowKey={(r) => r.id || r.normalized_domain}
            renderCell={(c, r) => {
              switch (c.key) {
                case "domain": return <span className="font-medium text-[#3f3320]">{r.normalized_domain || r.domain}</span>;
                case "intersections": return fmtInt(r.intersections);
                case "avg_position": return fmtNum(r.avg_position, 1);
                case "competitor_organic_keywords": return fmtInt(r.competitor_organic_keywords);
                case "competitor_estimated_traffic": return fmtNum(r.competitor_estimated_traffic, 0);
                case "captured_date": return fmtDate(r.captured_date);
                case "gap": return (
                  <button type="button" className="text-xs underline decoration-[#d8cba9] text-[#8a6a3c] hover:text-[#3f3320]"
                    onClick={() => onOpenGap && onOpenGap(r.normalized_domain || r.domain)} data-testid="comp-open-gap">
                    {gapped.has(r.normalized_domain) ? "View gap" : "Open in Keyword Gap"}
                  </button>
                );
                default: return r[c.key] ?? "—";
              }
            }} />
          <Pager offset={page.offset} limit={page.limit} total={q.data?.total || 0} hasMore={Boolean(q.data?.has_more)} onChange={setPage} testPrefix="comp" />
        </StateBlock>
      </div>
      <details className="mb-6 rounded-xl border border-dashed border-[#d8cba9] bg-[#fdfbf5] p-3" data-testid="manual-competitors">
        <summary className="cursor-pointer text-sm font-medium text-[#6b5836]">First-party manual competitor tracking (legacy Phase 3)</summary>
        <div className="mt-3"><Phase3Section /></div>
      </details>
    </>
  );
}
