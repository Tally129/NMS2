import React from "react";

import api from "../../lib/api";

import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import SearchConsoleSection from "./SearchConsoleSection";
import OrganicResearchSection from "./OrganicResearchSection";
import CompetitorsSection from "./seo/CompetitorsSection";
import KeywordGapSection from "./seo/KeywordGapSection";
import PositionTrackingSection from "./seo/PositionTrackingSection";
import BacklinksSection from "./seo/BacklinksSection";
import ProviderStatusSection from "./seo/ProviderStatusSection";
import { useAuth } from "../../lib/auth";

const SEO_TABS = [
  ["overview", "Overview"],
  ["organic", "Organic Research"],
  ["competitors", "Competitors"],
  ["gap", "Keyword Gap"],
  ["tracking", "Position Tracking"],
  ["backlinks", "Backlinks"],
  ["gsc", "Search Console"],
  ["provider", "Provider / Sync"],
];

import {
  AlertTriangle,
  FileSearch,
  Gauge,
  Globe,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { normalizeArray } from "../../lib/collections";


function asArray(value, keys = []) {
  if (Array.isArray(value)) return value;
  for (const key of keys) {
    if (Array.isArray(value?.[key])) return value[key];
  }
  return [];
}


function metricValue(overview, name, format) {
  const metric = overview?.metrics?.[name];
  if (!metric) return { text: "—", connected: false, source: null };
  if (!metric.connected) {
    return { text: "Not connected", connected: false, source: metric.source };
  }
  if (metric.value === null || metric.value === undefined) {
    return { text: "—", connected: true, source: metric.source };
  }
  const value = metric.value;
  let text;
  if (typeof format === "function") text = format(value);
  else if (typeof value === "number") {
    text = Number.isInteger(value)
      ? value.toLocaleString()
      : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  } else text = String(value);
  return { text, connected: true, source: metric.source };
}


// Human labels for the `source` reported by the backend on every metric so
// the card always tells the reader what the number actually represents.
const SOURCE_LABELS = {
  google_search_console: "Google Search Console",
  dataforseo: "DataForSEO Labs (cached)",
  dataforseo_serp: "DataForSEO SERP (cached)",
  rank_tracking: "Rank tracking",
  rank_provider: "Rank provider",
  site_audit: "Site audit",
  marketing_search_keywords: "Tracked keywords",
  backlink_provider: "Backlink provider",
  not_connected: "Not connected",
};

const SOURCE_STYLES = {
  google_search_console: "bg-blue-50 text-blue-800",
  dataforseo: "bg-emerald-50 text-emerald-800",
  dataforseo_serp: "bg-teal-50 text-teal-800",
  rank_provider: "bg-gray-100 text-gray-600",
  site_audit: "bg-amber-50 text-amber-800",
  marketing_search_keywords: "bg-[#faf6ec] text-[#8a6a3c]",
  backlink_provider: "bg-gray-100 text-gray-600",
  not_connected: "bg-gray-100 text-gray-500",
};


function MetricCard({ label, name, overview, icon: Icon, format }) {
  const { text, connected, source } = metricValue(overview, name, format);
  const sourceLabel = source ? SOURCE_LABELS[source] || source : null;
  return (
    <div
      className={
        "rounded-2xl border border-[#d8cba9] bg-white p-4 " +
        "flex flex-col gap-1"
      }
      data-testid={`si-metric-${name}`}
    >
      <div className="flex items-center gap-2 text-[#8a6a3c]">
        {Icon ? <Icon size={14} /> : null}
        <span className="text-xs font-medium uppercase tracking-wide">
          {label}
        </span>
      </div>
      <div
        className={
          "text-xl font-semibold " +
          (connected ? "text-[#3f3320]" : "text-[#a99b7d]")
        }
      >
        {text}
      </div>
      {sourceLabel ? (
        <span
          className={
            "mt-1 inline-block w-fit rounded-full px-2 py-0.5 text-[10px] " +
            "font-medium " +
            (SOURCE_STYLES[source] || "bg-gray-100 text-gray-600")
          }
          data-testid={`si-metric-${name}-source`}
        >
          {sourceLabel}
        </span>
      ) : null}
    </div>
  );
}


const DATASET_STYLES = {
  complete: "border-emerald-200 bg-emerald-50 text-emerald-900",
  incomplete: "border-amber-200 bg-amber-50 text-amber-900",
  unknown: "border-gray-200 bg-gray-50 text-gray-700",
  not_connected: "border-dashed border-[#d8cba9] bg-[#fdfbf5] text-[#6b5836]",
};

const DATASET_TITLES = {
  complete: "Provider dataset complete",
  incomplete: "Provider dataset incomplete",
  unknown: "Provider completeness unknown",
  not_connected: "Rank provider not synced",
};


function fmtNum(value) {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  return Number.isNaN(n) ? String(value) : n.toLocaleString();
}


/*
 * Completeness indicator for the CACHED rank-provider keyword dataset.
 * Derived by the backend from the persisted provider-run ledger
 * (complete / next_offset / provider_total_count). Nothing here is
 * computed from Search Console, and nothing here triggers a provider call.
 */
function ProviderDatasetStatus({ dataset }) {
  if (!dataset) return null;
  const status = dataset.status || "unknown";
  const showCounts =
    dataset.keyword_rows_stored !== null &&
    dataset.keyword_rows_stored !== undefined;
  return (
    <div
      className={
        "rounded-xl border p-3 text-sm " +
        (DATASET_STYLES[status] || DATASET_STYLES.unknown)
      }
      data-testid="si-provider-dataset"
      data-status={status}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-medium" data-testid="si-provider-dataset-title">
          {DATASET_TITLES[status] || DATASET_TITLES.unknown}
        </div>
        {showCounts && status !== "not_connected" ? (
          <div className="text-xs" data-testid="si-provider-dataset-counts">
            {fmtNum(dataset.keyword_rows_stored)} keyword rows cached
            {dataset.provider_total_count !== null &&
            dataset.provider_total_count !== undefined
              ? ` · provider reports ${fmtNum(dataset.provider_total_count)}`
              : ""}
            {dataset.percent_complete !== null &&
            dataset.percent_complete !== undefined
              ? ` · ${dataset.percent_complete}% synced`
              : ""}
            {dataset.next_offset !== null && dataset.next_offset !== undefined
              ? ` · next offset ${fmtNum(dataset.next_offset)}`
              : ""}
          </div>
        ) : null}
      </div>
      <p className="mt-1 text-xs" data-testid="si-provider-dataset-message">
        {dataset.message}
      </p>
      {dataset.last_error ? (
        <p className="mt-1 text-xs text-red-700" data-testid="si-provider-dataset-error">
          Last provider run reported: {dataset.last_error}
        </p>
      ) : null}
      {dataset.snapshot_captured_date || dataset.keyword_captured_date ? (
        <p className="mt-1 text-[11px] opacity-80">
          Snapshot date:{" "}
          {String(
            dataset.snapshot_captured_date || dataset.keyword_captured_date
          ).slice(0, 10)}
          {dataset.latest_completed_run?.finished_at
            ? ` · last completed run ${String(
                dataset.latest_completed_run.finished_at
              ).slice(0, 19).replace("T", " ")}`
            : ""}
        </p>
      ) : null}
    </div>
  );
}


function SectionCard({ title, subtitle, actions, children }) {
  return (
    <section
      className={
        "mb-6 rounded-2xl border border-[#d8cba9] bg-[#fbf7ee] p-5"
      }
    >
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-[#3f3320]">{title}</h3>
          {subtitle ? (
            <p className="text-sm text-[#8a6a3c]">{subtitle}</p>
          ) : null}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}


function MovementBadge({ movement, change }) {
  const map = {
    gain: {
      cls: "bg-green-100 text-green-800",
      icon: <TrendingUp size={12} />,
      label: `+${change}`,
    },
    loss: {
      cls: "bg-red-100 text-red-800",
      icon: <TrendingDown size={12} />,
      label: `${change}`,
    },
    flat: { cls: "bg-gray-100 text-gray-700", icon: null, label: "0" },
    new: { cls: "bg-blue-100 text-blue-800", icon: null, label: "new" },
    unranked: {
      cls: "bg-gray-100 text-gray-500",
      icon: null,
      label: "unranked",
    },
  };
  const cfg = map[movement] || map.unranked;
  return (
    <span
      className={
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 " +
        "text-xs font-medium " +
        cfg.cls
      }
    >
      {cfg.icon}
      {cfg.label}
    </span>
  );
}


const SEVERITY_STYLES = {
  critical: "bg-red-100 text-red-800",
  warning: "bg-amber-100 text-amber-800",
  opportunity: "bg-blue-100 text-blue-800",
  informational: "bg-gray-100 text-gray-700",
};


export default function SearchIntelligencePanel() {
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const [overview, setOverview] = React.useState(null);
  const [tracked, setTracked] = React.useState(null);
  const [audit, setAudit] = React.useState(null);
  const [issues, setIssues] = React.useState([]);

  const [siteUrl, setSiteUrl] = React.useState("");
  const [keywordInput, setKeywordInput] = React.useState("");
  const [tab, setTab] = React.useState("overview");
  const [gapCompetitor, setGapCompetitor] = React.useState("");
  const auth = useAuth();
  const isAdmin = (auth?.user?.role || "") === "admin";
  const openGap = (domain) => {
    setGapCompetitor(domain);
    setTab("gap");
  };

  const load = React.useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [overviewRes, trackedRes, auditRes] = await Promise.all([
        api.get("/marketing-os/search/overview"),
        api.get("/marketing-os/search/keywords/tracked"),
        api.get("/marketing-os/search/site-audit"),
      ]);
      setOverview(overviewRes.data || null);
      setTracked(trackedRes.data || null);
      setAudit(auditRes.data || null);

      if (auditRes.data?.has_run) {
        const issuesRes = await api.get(
          "/marketing-os/search/site-audit/issues"
        );
        setIssues(asArray(issuesRes.data, ["issues"]));
      } else {
        setIssues([]);
      }
    } catch (err) {
      setError(
        err?.response?.data?.detail || "Failed to load Search Intelligence"
      );
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  const connectAndAudit = async () => {
    if (!siteUrl.trim()) return;
    setBusy(true);
    setError("");
    try {
      await api.post("/marketing-os/search/sites", {
        site_url: siteUrl.trim(),
      });
      await api.post("/marketing-os/search/site-audit/run", {
        site_url: siteUrl.trim(),
        max_pages: 5,
      });
      setSiteUrl("");
      await load();
    } catch (err) {
      setError(
        err?.response?.data?.detail || "Unable to connect / run audit"
      );
    } finally {
      setBusy(false);
    }
  };

  const trackKeyword = async () => {
    if (!keywordInput.trim()) return;
    setBusy(true);
    setError("");
    try {
      await api.post("/marketing-os/search/keywords", {
        keyword: keywordInput.trim(),
      });
      setKeywordInput("");
      await load();
    } catch (err) {
      setError(err?.response?.data?.detail || "Unable to track keyword");
    } finally {
      setBusy(false);
    }
  };

  const connected = overview?.connected;
  const keywords = asArray(tracked?.keywords);
  const summary = tracked?.summary || {};

  return (
    <SectionCard
      title="Search Intelligence"
      subtitle={
        "Read-only SEO overview, keyword tracking, and technical site " +
        "audit. Recommendations are advisory."
      }
      actions={
        <Button
          type="button"
          variant="outline"
          disabled={loading || busy}
          onClick={load}
          className="h-9 rounded-full border-[#c19a4b] text-[#8a6a3c]"
          data-testid="si-refresh"
        >
          <RefreshCw
            size={14}
            className={"mr-2 " + (loading ? "animate-spin" : "")}
          />
          Refresh
        </Button>
      }
    >
      {error ? (
        <div
          className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700"
          data-testid="si-error"
        >
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="flex items-center gap-2 text-[#8a6a3c]">
          <Loader2 size={16} className="animate-spin" />
          Loading Search Intelligence…
        </div>
      ) : (
        <>
          {!connected ? (
            <div
              className={
                "mb-5 rounded-xl border border-dashed border-[#c19a4b] " +
                "bg-[#fdfbf5] p-4 text-sm text-[#6b5836]"
              }
              data-testid="si-not-connected"
            >
              <div className="mb-2 flex items-center gap-2 font-medium">
                <Globe size={16} /> No marketing site connected yet
              </div>
              Connect a public marketing website to run a read-only
              technical audit and start tracking search performance.
            </div>
          ) : null}

          {/* Connect + audit action */}
          <div className="mb-6 flex flex-wrap items-center gap-2">
            <Input
              value={siteUrl}
              onChange={(e) => setSiteUrl(e.target.value)}
              placeholder="https://your-marketing-site.com"
              className="h-9 w-72 border-[#d8cba9]"
              data-testid="si-site-input"
            />
            <Button
              type="button"
              disabled={busy || !siteUrl.trim()}
              onClick={connectAndAudit}
              className="h-9 rounded-full bg-[#c19a4b] text-white"
              data-testid="si-run-audit"
            >
              {busy ? (
                <Loader2 size={14} className="mr-2 animate-spin" />
              ) : (
                <FileSearch size={14} className="mr-2" />
              )}
              Connect &amp; Run Audit
            </Button>
          </div>

          {/* Workspace navigation */}
          <nav
            className="mb-5 flex flex-wrap gap-1 border-b border-[#e7dcc2]"
            data-testid="seo-tabs"
          >
            {SEO_TABS.map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setTab(key)}
                className={
                  "-mb-px rounded-t-lg border-b-2 px-3 py-2 text-sm " +
                  (tab === key
                    ? "border-[#c19a4b] font-semibold text-[#3f3320]"
                    : "border-transparent text-[#8a6a3c] hover:text-[#3f3320]")
                }
                data-testid={`seo-tab-${key}`}
                aria-current={tab === key ? "page" : undefined}
              >
                {label}
              </button>
            ))}
          </nav>

          {tab === "overview" ? (<>
          {/* SEO overview cards */}
          <div
            className={
              "mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4"
            }
          >
            <MetricCard
              label="Indexed Pages"
              name="indexed_pages"
              overview={overview}
              icon={FileSearch}
            />
            <MetricCard
              label="GSC Search Queries"
              name="gsc_search_queries"
              overview={overview}
              icon={Search}
            />
            <MetricCard
              label="GSC Organic Clicks"
              name="organic_clicks"
              overview={overview}
              icon={TrendingUp}
            />
            <MetricCard
              label="GSC Impressions"
              name="organic_impressions"
              overview={overview}
            />
            <MetricCard
              label="GSC CTR"
              name="organic_ctr"
              overview={overview}
              format={(v) => `${(Number(v) * 100).toFixed(2)}%`}
            />
            <MetricCard
              label="GSC Avg. Position"
              name="average_organic_position"
              overview={overview}
              icon={Gauge}
            />
            <MetricCard
              label="Organic Ranking Keywords"
              name="organic_keywords"
              overview={overview}
              icon={Search}
            />
            <MetricCard
              label="Est. Organic Traffic"
              name="estimated_organic_traffic"
              overview={overview}
              icon={TrendingUp}
            />
            <MetricCard
              label="Tracked Keywords"
              name="tracked_keywords"
              overview={overview}
              icon={Search}
            />
            <MetricCard
              label="Avg. Tracked Position"
              name="average_tracked_position"
              overview={overview}
              icon={Gauge}
            />
            <MetricCard
              label="Top 3"
              name="keywords_in_top_3"
              overview={overview}
            />
            <MetricCard
              label="Top 10"
              name="keywords_in_top_10"
              overview={overview}
            />
            <MetricCard
              label="Top 20"
              name="keywords_in_top_20"
              overview={overview}
            />
            <MetricCard
              label="Ranking Gains"
              name="ranking_gains"
              overview={overview}
              icon={TrendingUp}
            />
            <MetricCard
              label="Ranking Losses"
              name="ranking_losses"
              overview={overview}
              icon={TrendingDown}
            />
            <MetricCard
              label="Technical Issues"
              name="technical_issue_count"
              overview={overview}
              icon={AlertTriangle}
            />
            <MetricCard
              label="Backlinks"
              name="backlink_count"
              overview={overview}
            />
            <MetricCard
              label="Referring Domains"
              name="referring_domain_count"
              overview={overview}
            />
          </div>

          {/* Rank-provider (DataForSEO Labs) keyword-universe movement.
              Cached snapshot only — distinct from Search Console above. */}
          <div
            className="mb-6 rounded-xl border border-[#d8cba9] bg-white p-4"
            data-testid="si-provider-block"
          >
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                <h4 className="font-semibold text-[#3f3320]">
                  Organic Ranking Intelligence
                </h4>
                <p className="text-xs text-[#8a6a3c]">
                  Third-party keyword-universe estimates from the cached{" "}
                  {overview?.provider_snapshot?.provider || "rank provider"}{" "}
                  domain snapshot
                  {overview?.provider_snapshot?.captured_date
                    ? ` (captured ${String(
                        overview.provider_snapshot.captured_date
                      ).slice(0, 10)}, ${
                        overview.provider_snapshot.location || ""
                      } · ${overview.provider_snapshot.device || ""})`
                    : ""}
                  . These are not Google Search Console metrics.
                </p>
              </div>
            </div>
            <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <MetricCard
                label="New Keywords"
                name="provider_new_keywords"
                overview={overview}
                icon={Plus}
              />
              <MetricCard
                label="Improved Keywords"
                name="provider_up_keywords"
                overview={overview}
                icon={TrendingUp}
              />
              <MetricCard
                label="Declined Keywords"
                name="provider_down_keywords"
                overview={overview}
                icon={TrendingDown}
              />
              <MetricCard
                label="Lost Keywords"
                name="provider_lost_keywords"
                overview={overview}
                icon={AlertTriangle}
              />
            </div>
            <ProviderDatasetStatus dataset={overview?.provider_dataset} />
          </div>

          {/* Competitor intelligence / Backlinks / Rank tracking KPI groups */}
          <div className="mb-6 grid gap-4 lg:grid-cols-3" data-testid="si-intel-groups">
            <div className="rounded-xl border border-[#d8cba9] bg-white p-4" data-testid="si-competitor-group">
              <h4 className="mb-2 font-semibold text-[#3f3320]">Competitor Intelligence</h4>
              <div className="grid grid-cols-3 gap-2">
                <MetricCard label="Organic Competitors" name="organic_competitors" overview={overview} />
                <MetricCard label="Common Keywords" name="competitor_common_keywords" overview={overview} />
                <MetricCard label="Keyword Opportunities" name="keyword_opportunities" overview={overview} />
              </div>
              <p className="mt-2 text-[11px] text-[#a99b7d]">Common keywords = sum of provider intersections across cached competitors. Opportunities = distinct missing/weak gap keywords in the latest gap snapshot.</p>
            </div>
            <div className="rounded-xl border border-[#d8cba9] bg-white p-4" data-testid="si-backlink-group">
              <h4 className="mb-2 font-semibold text-[#3f3320]">Backlinks</h4>
              <div className="grid grid-cols-2 gap-2">
                <MetricCard label="Backlinks" name="backlink_count" overview={overview} />
                <MetricCard label="Referring Domains" name="referring_domain_count" overview={overview} />
                <MetricCard label="New Links (sampled)" name="backlink_new_links_sampled" overview={overview} />
                <MetricCard label="Lost Links (sampled)" name="backlink_lost_links_sampled" overview={overview} />
              </div>
            </div>
            <div className="rounded-xl border border-[#d8cba9] bg-white p-4" data-testid="si-tracking-group">
              <h4 className="mb-2 font-semibold text-[#3f3320]">Rank Tracking</h4>
              <div className="grid grid-cols-3 gap-2">
                <MetricCard label="Tracked" name="rt_tracked_keywords" overview={overview} />
                <MetricCard label="Top 3" name="rt_top_3" overview={overview} />
                <MetricCard label="Top 10" name="rt_top_10" overview={overview} />
                <MetricCard label="Top 20" name="rt_top_20" overview={overview} />
                <MetricCard label="Improved" name="rt_improved" overview={overview} />
                <MetricCard label="Declined" name="rt_declined" overview={overview} />
              </div>
            </div>
          </div>
          </>) : null}

          {tab === "organic" ? <OrganicResearchSection overview={overview} /> : null}
          {tab === "competitors" ? <CompetitorsSection onOpenGap={openGap} /> : null}
          {tab === "gap" ? <KeywordGapSection initialCompetitor={gapCompetitor} /> : null}
          {tab === "tracking" ? <PositionTrackingSection isAdmin={isAdmin} /> : null}
          {tab === "backlinks" ? <BacklinksSection /> : null}
          {tab === "provider" ? <ProviderStatusSection isAdmin={isAdmin} /> : null}

          {tab === "overview" ? (<>
          {/* Technical audit summary */}
          <div className="mb-6 rounded-xl border border-[#d8cba9] bg-white p-4">
            <div className="mb-3 flex items-center justify-between">
              <h4 className="font-semibold text-[#3f3320]">
                Technical Audit
              </h4>
              <span className="text-xs text-[#8a6a3c]">
                {audit?.has_run
                  ? `Last run: ${
                      audit.finished_at || audit.created_at || "—"
                    } · ${audit.pages_scanned || 0} pages`
                  : "No audit run yet"}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {["critical", "warning", "opportunity", "informational"].map(
                (sev) => (
                  <div
                    key={sev}
                    className="rounded-lg bg-[#faf6ec] p-3 text-center"
                    data-testid={`si-sev-${sev}`}
                  >
                    <div className="text-2xl font-semibold text-[#3f3320]">
                      {audit?.[`${sev}_count`] ?? 0}
                    </div>
                    <div
                      className={
                        "mt-1 inline-block rounded-full px-2 py-0.5 " +
                        "text-xs font-medium capitalize " +
                        (SEVERITY_STYLES[sev] || "")
                      }
                    >
                      {sev}
                    </div>
                  </div>
                )
              )}
            </div>
          </div>

          {/* Keyword performance table */}
          <div className="mb-6 rounded-xl border border-[#d8cba9] bg-white p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h4 className="font-semibold text-[#3f3320]">
                Tracked Keywords
              </h4>
              <div className="flex items-center gap-2">
                <Input
                  value={keywordInput}
                  onChange={(e) => setKeywordInput(e.target.value)}
                  placeholder="Track a keyword"
                  className="h-9 w-56 border-[#d8cba9]"
                  data-testid="si-keyword-input"
                />
                <Button
                  type="button"
                  disabled={busy || !keywordInput.trim()}
                  onClick={trackKeyword}
                  className="h-9 rounded-full bg-[#c19a4b] text-white"
                  data-testid="si-track-keyword"
                >
                  <Plus size={14} className="mr-1" />
                  Track
                </Button>
              </div>
            </div>

            <div className="mb-3 flex gap-4 text-sm text-[#6b5836]">
              <span>
                Gains:{" "}
                <b className="text-green-700">
                  {summary.ranking_gains ?? 0}
                </b>
              </span>
              <span>
                Losses:{" "}
                <b className="text-red-700">{summary.ranking_losses ?? 0}</b>
              </span>
              <span>
                Avg. position: <b>{summary.average_position ?? "—"}</b>
              </span>
            </div>

            {keywords.length === 0 ? (
              <div
                className="rounded-lg bg-[#faf6ec] p-4 text-sm text-[#8a6a3c]"
                data-testid="si-keywords-empty"
              >
                No tracked keywords yet.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="text-[#8a6a3c]">
                    <tr className="border-b border-[#e7dcc2]">
                      <th className="py-2 pr-3">Keyword</th>
                      <th className="py-2 pr-3">Intent</th>
                      <th className="py-2 pr-3">Rank</th>
                      <th className="py-2 pr-3">Change</th>
                      <th className="py-2 pr-3">Volume</th>
                      <th className="py-2 pr-3">Difficulty</th>
                    </tr>
                  </thead>
                  <tbody data-testid="si-keywords-table">
                    {keywords.map((kw, idx) => (
                      <tr
                        key={`${kw.normalized_keyword}-${idx}`}
                        className="border-b border-[#f0e8d5]"
                      >
                        <td className="py-2 pr-3 font-medium text-[#3f3320]">
                          {kw.keyword}
                        </td>
                        <td className="py-2 pr-3 capitalize text-[#6b5836]">
                          {kw.intent}
                        </td>
                        <td className="py-2 pr-3">
                          {kw.current_rank ?? "—"}
                        </td>
                        <td className="py-2 pr-3">
                          <MovementBadge
                            movement={kw.movement}
                            change={kw.rank_change}
                          />
                        </td>
                        <td className="py-2 pr-3">
                          {kw.search_volume ?? "—"}
                        </td>
                        <td className="py-2 pr-3">
                          {kw.keyword_difficulty ?? "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Issue list */}
          {issues.length > 0 ? (
            <div className="rounded-xl border border-[#d8cba9] bg-white p-4">
              <h4 className="mb-3 font-semibold text-[#3f3320]">
                Audit Findings
              </h4>
              <div className="space-y-2" data-testid="si-issues">
                {normalizeArray(issues).slice(0, 30).map((issue, idx) => (
                  <div
                    key={`${issue.issue_code}-${idx}`}
                    className="rounded-lg border border-[#f0e8d5] p-3"
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={
                          "rounded-full px-2 py-0.5 text-xs font-medium " +
                          "capitalize " +
                          (SEVERITY_STYLES[issue.severity] || "")
                        }
                      >
                        {issue.severity}
                      </span>
                      <span className="text-sm font-medium text-[#3f3320]">
                        {issue.issue_code}
                      </span>
                      <span className="text-xs text-[#8a6a3c]">
                        {issue.category}
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-[#6b5836]">
                      {issue.description}
                    </p>
                    <p className="mt-1 text-xs text-[#8a6a3c]">
                      Recommended: {issue.recommended_action}
                    </p>
                    <p className="mt-1 break-all text-xs text-[#a99b7d]">
                      {issue.url}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          </>) : null}

          {tab === "gsc" ? <SearchConsoleSection /> : null}
        </>
      )}
    </SectionCard>
  );
}
