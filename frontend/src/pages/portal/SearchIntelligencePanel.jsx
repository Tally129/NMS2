import React from "react";

import api from "../../lib/api";

import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";

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


function asArray(value, keys = []) {
  if (Array.isArray(value)) return value;
  for (const key of keys) {
    if (Array.isArray(value?.[key])) return value[key];
  }
  return [];
}


function metricValue(overview, name) {
  const metric = overview?.metrics?.[name];
  if (!metric) return { text: "—", connected: false };
  if (!metric.connected) return { text: "Not connected", connected: false };
  if (metric.value === null || metric.value === undefined) {
    return { text: "—", connected: true };
  }
  return { text: String(metric.value), connected: true };
}


function MetricCard({ label, name, overview, icon: Icon }) {
  const { text, connected } = metricValue(overview, name);
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
              label="Organic Keywords"
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
              label="Avg. Position"
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
                {issues.slice(0, 30).map((issue, idx) => (
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
        </>
      )}
    </SectionCard>
  );
}
