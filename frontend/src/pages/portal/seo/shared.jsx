import React from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Database, Loader2 } from "lucide-react";
import { Button } from "../../../components/ui/button";

/* Shared primitives for the SEO Command Center workspace.
 * Every number rendered here comes from CACHED PostgreSQL routes; nothing in
 * this folder calls a paid provider directly. */

export const SOURCE_LABELS = {
  google_search_console: "Google Search Console",
  dataforseo: "DataForSEO Labs (cached)",
  dataforseo_serp: "DataForSEO SERP (cached)",
  rank_provider: "Rank provider",
  rank_tracking: "Rank tracking",
  site_audit: "Site audit",
  marketing_search_keywords: "Tracked keywords",
  backlink_provider: "Backlink provider",
  not_connected: "Not connected",
};

export const SOURCE_STYLES = {
  google_search_console: "bg-blue-50 text-blue-800",
  dataforseo: "bg-emerald-50 text-emerald-800",
  dataforseo_serp: "bg-teal-50 text-teal-800",
  site_audit: "bg-amber-50 text-amber-800",
  marketing_search_keywords: "bg-[#faf6ec] text-[#8a6a3c]",
};

export function fmtInt(v) {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  return Number.isNaN(n) ? String(v) : n.toLocaleString();
}
export function fmtNum(v, digits = 2) {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  return Number.isNaN(n) ? String(v) : n.toLocaleString(undefined, { maximumFractionDigits: digits });
}
export function fmtMoney(v) {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  return Number.isNaN(n) ? String(v) : `$${n.toFixed(2)}`;
}
export function fmtDate(v) {
  return v ? String(v).slice(0, 10) : "—";
}
export function fmtDateTime(v) {
  return v ? String(v).slice(0, 16).replace("T", " ") : "—";
}

export function SourceBadge({ source, className = "" }) {
  if (!source) return null;
  return (
    <span
      className={
        "inline-block w-fit rounded-full px-2 py-0.5 text-[10px] font-medium " +
        (SOURCE_STYLES[source] || "bg-gray-100 text-gray-600") + " " + className
      }
      data-testid="source-badge"
    >
      {SOURCE_LABELS[source] || source}
    </span>
  );
}

export function Kpi({ label, value, source, hint, testId }) {
  return (
    <div className="flex flex-col gap-1 rounded-2xl border border-[#d8cba9] bg-white p-4" data-testid={testId}>
      <span className="text-xs font-medium uppercase tracking-wide text-[#8a6a3c]">{label}</span>
      <span className="text-xl font-semibold text-[#3f3320]">{value}</span>
      {source ? <SourceBadge source={source} className="mt-1" /> : null}
      {hint ? <span className="text-[11px] text-[#a99b7d]">{hint}</span> : null}
    </div>
  );
}

export function PanelHeader({ title, subtitle, right, badge = "Cached read" }) {
  return (
    <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
      <div>
        <h4 className="font-semibold text-[#3f3320]">{title}</h4>
        {subtitle ? <p className="max-w-3xl text-xs text-[#8a6a3c]">{subtitle}</p> : null}
      </div>
      <div className="flex items-center gap-2">
        {badge ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-[#faf6ec] px-2 py-0.5 text-xs text-[#8a6a3c]">
            <Database size={12} /> {badge}
          </span>
        ) : null}
        {right}
      </div>
    </div>
  );
}

export function StateBlock({ loading, error, empty, emptyText, children, testPrefix = "tbl" }) {
  if (loading) {
    return (
      <div className="flex items-center gap-2 py-6 text-sm text-[#8a6a3c]" data-testid={`${testPrefix}-loading`}>
        <Loader2 size={16} className="animate-spin" /> Loading cached data…
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700" data-testid={`${testPrefix}-error`}>
        {error}
      </div>
    );
  }
  if (empty) {
    return (
      <div className="rounded-lg bg-[#faf6ec] p-4 text-sm text-[#8a6a3c]" data-testid={`${testPrefix}-empty`}>
        {emptyText || "No cached data yet. A governed provider sync must run before this view populates."}
      </div>
    );
  }
  return children;
}

function SortIcon({ active, dir }) {
  if (!active) return <ArrowUpDown size={12} className="opacity-50" />;
  return dir === "asc" ? <ArrowUp size={12} /> : <ArrowDown size={12} />;
}

/* Server-paginated table. `sort` is forwarded to the caller (server-side when
 * the endpoint supports it). */
export function DataTable({ columns, rows, sort, onSort, rowKey, testPrefix = "tbl", renderCell }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-[#8a6a3c]">
          <tr className="border-b border-[#e7dcc2]">
            {columns.map((c) => (
              <th
                key={c.key}
                className={"py-2 pr-3 " + (c.sortable ? "cursor-pointer select-none" : "")}
                onClick={() => c.sortable && onSort && onSort(c.key)}
                data-testid={`${testPrefix}-col-${c.key}`}
              >
                <span className="inline-flex items-center gap-1">
                  {c.label}
                  {c.sortable ? <SortIcon active={sort?.key === c.key} dir={sort?.dir} /> : null}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody data-testid={`${testPrefix}-body`}>
          {rows.map((row, i) => (
            <tr key={rowKey ? rowKey(row, i) : i} className="border-b border-[#f0e8d5]" data-testid={`${testPrefix}-row`}>
              {columns.map((c) => (
                <td key={c.key} className={"py-2 pr-3 " + (c.className || "")}>
                  {renderCell ? renderCell(c, row) : row[c.key] ?? "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Pager({ offset, limit, total, hasMore, onChange, testPrefix = "tbl", pageSizes = [25, 50, 100] }) {
  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(offset + limit, total);
  return (
    <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-[#6b5836]">
      <span data-testid={`${testPrefix}-range`}>
        Showing {fmtInt(start)}–{fmtInt(end)} of {fmtInt(total)}
      </span>
      <div className="flex items-center gap-2">
        <select
          value={limit}
          onChange={(e) => onChange({ offset: 0, limit: Number(e.target.value) })}
          className="h-8 rounded-md border border-[#d8cba9] bg-white px-2"
          data-testid={`${testPrefix}-page-size`}
        >
          {pageSizes.map((n) => (
            <option key={n} value={n}>{n} / page</option>
          ))}
        </select>
        <Button type="button" variant="outline" disabled={offset <= 0} className="h-8 rounded-full border-[#d8cba9]"
          onClick={() => onChange({ offset: Math.max(0, offset - limit), limit })} data-testid={`${testPrefix}-prev`}>
          <ChevronLeft size={14} /> Prev
        </Button>
        <Button type="button" variant="outline" disabled={!hasMore} className="h-8 rounded-full border-[#d8cba9]"
          onClick={() => onChange({ offset: offset + limit, limit })} data-testid={`${testPrefix}-next`}>
          Next <ChevronRight size={14} />
        </Button>
      </div>
    </div>
  );
}

export function IntentPill({ intent }) {
  const styles = {
    informational: "bg-blue-100 text-blue-800", navigational: "bg-purple-100 text-purple-800",
    commercial: "bg-amber-100 text-amber-800", transactional: "bg-green-100 text-green-800",
  };
  const i = String(intent || "unknown");
  return <span className={"rounded-full px-2 py-0.5 text-xs font-medium capitalize " + (styles[i] || "bg-gray-100 text-gray-600")}>{i}</span>;
}

export function Change({ value }) {
  if (value === null || value === undefined) return <span className="text-[#a99b7d]">—</span>;
  const n = Number(value);
  if (n === 0) return <span className="text-[#a99b7d]">0</span>;
  return (
    <span className={n > 0 ? "text-emerald-700" : "text-red-700"}>
      {n > 0 ? "▲" : "▼"} {Math.abs(n)}
    </span>
  );
}

export function useCachedQuery(fetcher, deps) {
  const [state, setState] = React.useState({ loading: true, error: "", data: null });
  const load = React.useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: "" }));
    try {
      const data = await fetcher();
      setState({ loading: false, error: "", data });
    } catch (err) {
      setState({ loading: false, error: err?.response?.data?.detail || "Failed to load cached data", data: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  React.useEffect(() => { load(); }, [load]);
  return { ...state, reload: load };
}
