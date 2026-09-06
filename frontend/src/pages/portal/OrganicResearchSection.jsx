import React from "react";

import api from "../../lib/api";

import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";

import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  Database,
  Loader2,
  RefreshCw,
  Search,
} from "lucide-react";

/*
 * Organic Research — Semrush-style ranked-keyword table.
 *
 * DATA SOURCE: the CACHED rank-provider (DataForSEO Labs) snapshot stored in
 * PostgreSQL, read via:
 *   GET /api/marketing-os/search/seo/organic-keywords
 *
 * This component NEVER triggers a paid provider request. Opening or
 * refreshing this page only re-reads the cache. Pagination is server-side
 * (limit/offset); sorting is applied client-side to the CURRENT PAGE only
 * (the cached endpoint returns rows ordered by rank), and the keyword
 * filter also applies to the current page — both are labeled as such so
 * the numbers are never misread as whole-dataset operations.
 *
 * These are third-party organic ranking keywords — NOT Google Search
 * Console queries.
 */

const PAGE_SIZES = [25, 50, 100];

const COLUMNS = [
  { key: "keyword", label: "Keyword", sortable: true },
  { key: "current_rank", label: "Position", sortable: true, numeric: true },
  { key: "search_volume", label: "Volume", sortable: true, numeric: true },
  { key: "cpc", label: "CPC", sortable: true, numeric: true },
  { key: "intent", label: "Intent", sortable: true },
  { key: "keyword_difficulty", label: "KD", sortable: true, numeric: true },
  { key: "ranking_url", label: "Ranking URL", sortable: false },
  { key: "serp_features", label: "SERP Features", sortable: false },
];

const INTENT_STYLES = {
  informational: "bg-blue-100 text-blue-800",
  navigational: "bg-purple-100 text-purple-800",
  commercial: "bg-amber-100 text-amber-800",
  transactional: "bg-green-100 text-green-800",
  unknown: "bg-gray-100 text-gray-600",
};

function fmtInt(value) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  return n.toLocaleString();
}

function fmtMoney(value) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  return `$${n.toFixed(2)}`;
}

function fmtDate(value) {
  if (!value) return "—";
  return String(value).slice(0, 10);
}

function compare(a, b, key, numeric) {
  const av = a?.[key];
  const bv = b?.[key];
  const aNull = av === null || av === undefined || av === "";
  const bNull = bv === null || bv === undefined || bv === "";
  if (aNull && bNull) return 0;
  if (aNull) return 1; // nulls last regardless of direction
  if (bNull) return -1;
  if (numeric) return Number(av) - Number(bv);
  return String(av).localeCompare(String(bv));
}

function SortIcon({ active, dir }) {
  if (!active) return <ArrowUpDown size={12} className="opacity-50" />;
  return dir === "asc" ? <ArrowUp size={12} /> : <ArrowDown size={12} />;
}

export default function OrganicResearchSection({ overview }) {
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [payload, setPayload] = React.useState(null);

  const [pageSize, setPageSize] = React.useState(25);
  const [offset, setOffset] = React.useState(0);

  const [sortKey, setSortKey] = React.useState("current_rank");
  const [sortDir, setSortDir] = React.useState("asc");
  const [filter, setFilter] = React.useState("");

  const load = React.useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      // CACHE READ ONLY — never calls DataForSEO.
      const res = await api.get("/marketing-os/search/seo/organic-keywords", {
        params: { limit: pageSize, offset },
      });
      setPayload(res.data || null);
    } catch (err) {
      setError(
        err?.response?.data?.detail ||
          "Failed to load cached organic ranking keywords"
      );
    } finally {
      setLoading(false);
    }
  }, [pageSize, offset]);

  React.useEffect(() => {
    load();
  }, [load]);

  const items = React.useMemo(
    () => (Array.isArray(payload?.items) ? payload.items : []),
    [payload]
  );
  const total = Number(payload?.total || 0);
  const hasSnapshot = Boolean(payload?.has_snapshot);
  const connected = Boolean(payload?.connected);

  const filtered = React.useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (row) =>
        String(row.keyword || "").toLowerCase().includes(q) ||
        String(row.ranking_url || "").toLowerCase().includes(q)
    );
  }, [items, filter]);

  const sorted = React.useMemo(() => {
    const col = COLUMNS.find((c) => c.key === sortKey);
    if (!col || !col.sortable) return filtered;
    const copy = [...filtered];
    copy.sort((a, b) => {
      const r = compare(a, b, col.key, col.numeric);
      return sortDir === "asc" ? r : -r;
    });
    return copy;
  }, [filtered, sortKey, sortDir]);

  const toggleSort = (col) => {
    if (!col.sortable) return;
    if (sortKey === col.key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(col.key);
      setSortDir(col.numeric ? "asc" : "asc");
    }
  };

  const pageStart = total === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + items.length, total);
  const canPrev = offset > 0;
  const canNext = Boolean(payload?.has_more);

  const dataset = overview?.provider_dataset || null;
  const providerLabel =
    (payload?.provider || dataset?.provider || "rank provider").toString();

  return (
    <div
      className="mb-6 rounded-xl border border-[#d8cba9] bg-white p-4"
      data-testid="organic-research-section"
    >
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h4 className="font-semibold text-[#3f3320]">Organic Research</h4>
          <p className="text-xs text-[#8a6a3c]" data-testid="or-source-note">
            Third-party organic ranking keywords from the cached{" "}
            <span className="font-medium">{providerLabel}</span> snapshot
            {payload?.captured_date
              ? ` (captured ${fmtDate(payload.captured_date)})`
              : ""}
            . Not Google Search Console queries. Reading this page never
            triggers a provider request.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={
              "inline-flex items-center gap-1 rounded-full bg-[#faf6ec] " +
              "px-2 py-0.5 text-xs text-[#8a6a3c]"
            }
            data-testid="or-cache-badge"
          >
            <Database size={12} /> Cached read
          </span>
          <Button
            type="button"
            variant="outline"
            disabled={loading}
            onClick={load}
            className="h-8 rounded-full border-[#c19a4b] text-[#8a6a3c]"
            data-testid="or-refresh"
          >
            <RefreshCw
              size={14}
              className={"mr-1 " + (loading ? "animate-spin" : "")}
            />
            Reload cache
          </Button>
        </div>
      </div>

      {dataset && dataset.status === "incomplete" ? (
        <div
          className={
            "mb-3 rounded-lg border border-amber-200 bg-amber-50 p-3 " +
            "text-sm text-amber-900"
          }
          data-testid="or-incomplete-note"
        >
          {dataset.message}
          {dataset.next_offset !== null && dataset.next_offset !== undefined
            ? ` Next provider offset: ${fmtInt(dataset.next_offset)}.`
            : ""}
        </div>
      ) : null}

      {error ? (
        <div
          className="mb-3 rounded-lg bg-red-50 p-3 text-sm text-red-700"
          data-testid="or-error"
        >
          {error}
        </div>
      ) : null}

      {loading ? (
        <div
          className="flex items-center gap-2 py-6 text-sm text-[#8a6a3c]"
          data-testid="or-loading"
        >
          <Loader2 size={16} className="animate-spin" />
          Loading cached organic keywords…
        </div>
      ) : !error && (!connected || !hasSnapshot || total === 0) ? (
        <div
          className="rounded-lg bg-[#faf6ec] p-4 text-sm text-[#8a6a3c]"
          data-testid="or-empty"
        >
          {!connected
            ? "No marketing site connected yet."
            : "No cached organic ranking keywords yet. A controlled " +
              "provider sync must be run (with approval) before this " +
              "table populates. Nothing is fetched automatically."}
        </div>
      ) : !error ? (
        <>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <div className="relative">
                <Search
                  size={14}
                  className="pointer-events-none absolute left-2 top-2.5 text-[#a99b7d]"
                />
                <Input
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  placeholder="Filter this page…"
                  className="h-9 w-60 border-[#d8cba9] pl-7"
                  data-testid="or-filter"
                />
              </div>
              <span className="text-xs text-[#a99b7d]">
                Filter and sort apply to the current page only.
              </span>
            </div>
            <div className="flex items-center gap-2 text-xs text-[#6b5836]">
              <span data-testid="or-range">
                Showing {fmtInt(pageStart)}–{fmtInt(pageEnd)} of{" "}
                {fmtInt(total)} cached keywords
              </span>
              <select
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value));
                  setOffset(0);
                }}
                className="h-8 rounded-md border border-[#d8cba9] bg-white px-2"
                data-testid="or-page-size"
              >
                {PAGE_SIZES.map((n) => (
                  <option key={n} value={n}>
                    {n} / page
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-[#8a6a3c]">
                <tr className="border-b border-[#e7dcc2]">
                  {COLUMNS.map((col) => (
                    <th
                      key={col.key}
                      className={
                        "py-2 pr-3 " +
                        (col.sortable ? "cursor-pointer select-none" : "")
                      }
                      onClick={() => toggleSort(col)}
                      data-testid={`or-col-${col.key}`}
                    >
                      <span className="inline-flex items-center gap-1">
                        {col.label}
                        {col.sortable ? (
                          <SortIcon
                            active={sortKey === col.key}
                            dir={sortDir}
                          />
                        ) : null}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody data-testid="or-table">
                {sorted.length === 0 ? (
                  <tr>
                    <td
                      colSpan={COLUMNS.length}
                      className="py-4 text-center text-[#8a6a3c]"
                      data-testid="or-filter-empty"
                    >
                      No keywords on this page match the filter.
                    </td>
                  </tr>
                ) : (
                  sorted.map((row, idx) => {
                    const feats = Array.isArray(row.serp_features)
                      ? row.serp_features
                      : [];
                    const intent = String(row.intent || "unknown");
                    return (
                      <tr
                        key={`${row.id || row.normalized_keyword}-${idx}`}
                        className="border-b border-[#f0e8d5]"
                        data-testid="or-row"
                      >
                        <td className="py-2 pr-3 font-medium text-[#3f3320]">
                          {row.keyword}
                        </td>
                        <td className="py-2 pr-3">{fmtInt(row.current_rank)}</td>
                        <td className="py-2 pr-3">{fmtInt(row.search_volume)}</td>
                        <td className="py-2 pr-3">{fmtMoney(row.cpc)}</td>
                        <td className="py-2 pr-3">
                          <span
                            className={
                              "rounded-full px-2 py-0.5 text-xs font-medium " +
                              "capitalize " +
                              (INTENT_STYLES[intent] || INTENT_STYLES.unknown)
                            }
                          >
                            {intent}
                          </span>
                        </td>
                        <td className="py-2 pr-3">
                          {fmtInt(row.keyword_difficulty)}
                        </td>
                        <td
                          className="max-w-[260px] truncate py-2 pr-3 text-xs text-[#6b5836]"
                          title={row.ranking_url || ""}
                        >
                          {row.ranking_url ? (
                            <a
                              href={row.ranking_url}
                              target="_blank"
                              rel="noreferrer"
                              className="underline decoration-[#d8cba9] hover:text-[#3f3320]"
                            >
                              {row.ranking_url}
                            </a>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="py-2 pr-3">
                          {feats.length === 0 ? (
                            <span className="text-[#a99b7d]">—</span>
                          ) : (
                            <div className="flex flex-wrap gap-1">
                              {feats.slice(0, 4).map((f) => (
                                <span
                                  key={f}
                                  className="rounded bg-[#faf6ec] px-1.5 py-0.5 text-[10px] text-[#6b5836]"
                                >
                                  {f}
                                </span>
                              ))}
                              {feats.length > 4 ? (
                                <span className="text-[10px] text-[#a99b7d]">
                                  +{feats.length - 4}
                                </span>
                              ) : null}
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          <div className="mt-3 flex items-center justify-between text-xs text-[#6b5836]">
            <span>
              Position change and per-keyword traffic are not yet persisted
              by the provider sync and are intentionally not shown.
            </span>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={!canPrev || loading}
                onClick={() => setOffset(Math.max(0, offset - pageSize))}
                className="h-8 rounded-full border-[#d8cba9]"
                data-testid="or-prev"
              >
                <ChevronLeft size={14} /> Prev
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={!canNext || loading}
                onClick={() => setOffset(offset + pageSize)}
                className="h-8 rounded-full border-[#d8cba9]"
                data-testid="or-next"
              >
                Next <ChevronRight size={14} />
              </Button>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
