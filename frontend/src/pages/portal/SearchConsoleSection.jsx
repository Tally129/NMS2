import React from "react";

import api from "../../lib/api";
import { Button } from "../../components/ui/button";

import {
  BarChart3,
  Loader2,
  MousePointerClick,
  Percent,
  RefreshCw,
  Search,
  TrendingDown,
  TrendingUp,
} from "lucide-react";

const READINESS_STYLES = {
  connected: { cls: "bg-green-100 text-green-800", label: "Connected" },
  configuration_incomplete: {
    cls: "bg-amber-100 text-amber-800",
    label: "Configuration incomplete",
  },
  not_connected: {
    cls: "bg-gray-100 text-gray-700",
    label: "Not connected",
  },
  read_error: { cls: "bg-red-100 text-red-800", label: "Read error" },
};

function fmt(n) {
  if (n === null || n === undefined) return "—";
  return typeof n === "number" ? n.toLocaleString() : String(n);
}

function pct(n) {
  if (n === null || n === undefined) return "—";
  return `${(n * 100).toFixed(2)}%`;
}

function GscMovementBadge({ item }) {
  const m = item?.movement;
  if (m === "gain") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800">
        <TrendingUp size={12} /> +{item.change}
      </span>
    );
  }
  if (m === "loss") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">
        <TrendingDown size={12} /> {item.change}
      </span>
    );
  }
  const label = m === "new" ? "new" : m === "unchanged" ? "0" : "—";
  return (
    <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
      {label}
    </span>
  );
}

export default function SearchConsoleSection() {
  const [loading, setLoading] = React.useState(true);
  const [syncing, setSyncing] = React.useState(false);
  const [error, setError] = React.useState("");
  const [readiness, setReadiness] = React.useState(null);
  const [perf, setPerf] = React.useState(null);
  const [queries, setQueries] = React.useState([]);
  const [pages, setPages] = React.useState([]);
  const [rank, setRank] = React.useState(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [rRes, pRes, qRes, pgRes, rankRes] = await Promise.all([
        api.get("/marketing-os/search/search-console/readiness"),
        api.get("/marketing-os/search/search-console/performance"),
        api.get("/marketing-os/search/search-console/queries"),
        api.get("/marketing-os/search/search-console/pages"),
        api.get("/marketing-os/search/rank-tracking"),
      ]);
      setReadiness(rRes.data || null);
      setPerf(pRes.data || null);
      setQueries(qRes.data?.queries || []);
      setPages(pgRes.data?.pages || []);
      setRank(rankRes.data || null);
    } catch (err) {
      setError(
        err?.response?.data?.detail || "Failed to load Search Console data"
      );
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  const runSync = async () => {
    setSyncing(true);
    setError("");
    try {
      const res = await api.post(
        "/marketing-os/search/search-console/sync",
        {}
      );
      if (res.data?.started === false) {
        setError(
          `Search Console not connected (${res.data.reason}). Configure ` +
            "GOOGLE_SEARCH_CONSOLE_PROPERTY and GOOGLE_SERVICE_ACCOUNT_JSON."
        );
      }
      await load();
    } catch (err) {
      setError(err?.response?.data?.detail || "Sync failed");
    } finally {
      setSyncing(false);
    }
  };

  const status =
    (readiness?.runtime_state === "read_error" && "read_error") ||
    readiness?.status ||
    "not_connected";
  const style = READINESS_STYLES[status] || READINESS_STYLES.not_connected;
  const totals = perf?.totals || {};
  const lastSync = readiness?.last_sync;
  const rankKeywords = rank?.keywords || [];
  const rankSummary = rank?.summary || {};

  return (
    <div
      className="mt-6 rounded-xl border border-[#d8cba9] bg-white p-4"
      data-testid="gsc-section"
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <BarChart3 size={16} className="text-[#8a6a3c]" />
          <h4 className="font-semibold text-[#3f3320]">
            Google Search Console
          </h4>
          <span
            className={
              "rounded-full px-2 py-0.5 text-xs font-medium " + style.cls
            }
            data-testid="gsc-readiness"
          >
            {style.label}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {lastSync?.finished_at ? (
            <span className="text-xs text-[#8a6a3c]">
              Last synced: {lastSync.finished_at}
            </span>
          ) : null}
          <Button
            type="button"
            variant="outline"
            disabled={loading || syncing}
            onClick={runSync}
            className="h-9 rounded-full border-[#c19a4b] text-[#8a6a3c]"
            data-testid="gsc-sync"
          >
            {syncing ? (
              <Loader2 size={14} className="mr-2 animate-spin" />
            ) : (
              <RefreshCw size={14} className="mr-2" />
            )}
            Sync
          </Button>
        </div>
      </div>

      {error ? (
        <div
          className="mb-3 rounded-lg bg-red-50 p-3 text-sm text-red-700"
          data-testid="gsc-error"
        >
          {error}
        </div>
      ) : null}

      {status !== "connected" ? (
        <div
          className="mb-3 rounded-lg border border-dashed border-[#c19a4b] bg-[#fdfbf5] p-3 text-sm text-[#6b5836]"
          data-testid="gsc-not-connected"
        >
          Search Console is <b>{style.label.toLowerCase()}</b>. Organic
          metrics below stay empty until a read-only Search Console property
          is configured. No data is fabricated.
        </div>
      ) : null}

      {loading ? (
        <div className="flex items-center gap-2 text-[#8a6a3c]">
          <Loader2 size={16} className="animate-spin" /> Loading…
        </div>
      ) : (
        <>
          {/* Organic performance cards */}
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              {
                label: "Organic Clicks",
                value: fmt(totals.clicks),
                icon: MousePointerClick,
              },
              {
                label: "Impressions",
                value: fmt(totals.impressions),
                icon: Search,
              },
              { label: "CTR", value: pct(totals.ctr), icon: Percent },
              {
                label: "Avg. Position",
                value:
                  totals.average_position === null ||
                  totals.average_position === undefined
                    ? "—"
                    : totals.average_position,
                icon: BarChart3,
              },
            ].map((c) => (
              <div
                key={c.label}
                className="rounded-2xl border border-[#d8cba9] bg-[#fbf7ee] p-4"
              >
                <div className="flex items-center gap-2 text-[#8a6a3c]">
                  <c.icon size={14} />
                  <span className="text-xs font-medium uppercase tracking-wide">
                    {c.label}
                  </span>
                </div>
                <div className="text-xl font-semibold text-[#3f3320]">
                  {c.value}
                </div>
              </div>
            ))}
          </div>
          <p className="mb-4 text-xs text-[#a99b7d]">
            Average position is a Search Console average position, not a
            dedicated SERP rank.
          </p>

          {/* Top queries + pages */}
          <div className="mb-4 grid gap-4 md:grid-cols-2">
            <div>
              <h5 className="mb-2 text-sm font-semibold text-[#3f3320]">
                Top Queries
              </h5>
              {queries.length === 0 ? (
                <div className="rounded-lg bg-[#faf6ec] p-3 text-sm text-[#8a6a3c]">
                  No query data.
                </div>
              ) : (
                <table className="w-full text-left text-xs" data-testid="gsc-queries">
                  <thead className="text-[#8a6a3c]">
                    <tr>
                      <th className="py-1 pr-2">Query</th>
                      <th className="py-1 pr-2">Clicks</th>
                      <th className="py-1 pr-2">Impr.</th>
                      <th className="py-1 pr-2">Pos.</th>
                    </tr>
                  </thead>
                  <tbody>
                    {queries.slice(0, 10).map((q, i) => (
                      <tr key={i} className="border-t border-[#f0e8d5]">
                        <td className="py-1 pr-2 text-[#3f3320]">{q.query}</td>
                        <td className="py-1 pr-2">{fmt(q.clicks)}</td>
                        <td className="py-1 pr-2">{fmt(q.impressions)}</td>
                        <td className="py-1 pr-2">{q.position ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <div>
              <h5 className="mb-2 text-sm font-semibold text-[#3f3320]">
                Top Landing Pages
              </h5>
              {pages.length === 0 ? (
                <div className="rounded-lg bg-[#faf6ec] p-3 text-sm text-[#8a6a3c]">
                  No page data.
                </div>
              ) : (
                <table className="w-full text-left text-xs" data-testid="gsc-pages">
                  <thead className="text-[#8a6a3c]">
                    <tr>
                      <th className="py-1 pr-2">Page</th>
                      <th className="py-1 pr-2">Clicks</th>
                      <th className="py-1 pr-2">Impr.</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pages.slice(0, 10).map((p, i) => (
                      <tr key={i} className="border-t border-[#f0e8d5]">
                        <td className="py-1 pr-2 break-all text-[#3f3320]">
                          {p.page}
                        </td>
                        <td className="py-1 pr-2">{fmt(p.clicks)}</td>
                        <td className="py-1 pr-2">{fmt(p.impressions)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          {/* Tracked keyword rank history */}
          <div>
            <div className="mb-2 flex items-center justify-between">
              <h5 className="text-sm font-semibold text-[#3f3320]">
                Tracked Keyword History (GSC position)
              </h5>
              <span className="text-xs text-[#6b5836]">
                Gains <b className="text-green-700">{rankSummary.gains ?? 0}</b>{" "}
                · Losses{" "}
                <b className="text-red-700">{rankSummary.losses ?? 0}</b> ·
                Unchanged {rankSummary.unchanged ?? 0}
              </span>
            </div>
            {rankKeywords.length === 0 ? (
              <div className="rounded-lg bg-[#faf6ec] p-3 text-sm text-[#8a6a3c]">
                No tracked-keyword history yet.
              </div>
            ) : (
              <table className="w-full text-left text-xs" data-testid="gsc-rank">
                <thead className="text-[#8a6a3c]">
                  <tr>
                    <th className="py-1 pr-2">Keyword</th>
                    <th className="py-1 pr-2">Current</th>
                    <th className="py-1 pr-2">Previous</th>
                    <th className="py-1 pr-2">Best</th>
                    <th className="py-1 pr-2">Change</th>
                    <th className="py-1 pr-2">Source</th>
                  </tr>
                </thead>
                <tbody>
                  {rankKeywords.map((k, i) => {
                    const g = k.gsc_average_position || {};
                    return (
                      <tr key={i} className="border-t border-[#f0e8d5]">
                        <td className="py-1 pr-2 text-[#3f3320]">{k.keyword}</td>
                        <td className="py-1 pr-2">{g.current_position ?? "—"}</td>
                        <td className="py-1 pr-2">
                          {g.previous_position ?? "—"}
                        </td>
                        <td className="py-1 pr-2">{g.best_position ?? "—"}</td>
                        <td className="py-1 pr-2">
                          <GscMovementBadge item={g} />
                        </td>
                        <td className="py-1 pr-2 text-[#a99b7d]">
                          {g.metric_type}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}
