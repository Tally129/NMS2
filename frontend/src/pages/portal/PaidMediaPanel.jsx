import React from "react";

import api from "../../lib/api";

import { Button } from "../../components/ui/button";

import {
  BadgeDollarSign,
  Loader2,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";


const PROVIDER_ORDER = ["google_ads", "meta_ads", "microsoft_ads"];

const METRICS = [
  { key: "spend", label: "Spend", kind: "money" },
  { key: "impressions", label: "Impressions", kind: "int" },
  { key: "clicks", label: "Clicks", kind: "int" },
  { key: "ctr", label: "CTR", kind: "percent" },
  { key: "conversions", label: "Conversions", kind: "float" },
  { key: "cpa", label: "CPA", kind: "money" },
  { key: "roas", label: "ROAS", kind: "roas" },
];


function statusTone(status) {
  const normalized = String(status || "").toLowerCase();
  if (normalized === "connected") {
    return "border-[#b9d2bf] bg-[#edf5ef] text-[#2f6a4a]";
  }
  if (normalized === "configuration_incomplete") {
    return "border-[#d8cba9] bg-[#f7f1e4] text-[#8a6a3c]";
  }
  return "border-[#e7dfc9] bg-[#fbf7ee] text-[#6a6a6a]";
}


function statusLabel(status) {
  const map = {
    connected: "Connected",
    not_connected: "Not connected",
    configuration_incomplete: "Configuration incomplete",
    unknown_provider: "Unknown",
  };
  return map[String(status || "").toLowerCase()] || "Not connected";
}


function formatMetric(kind, value) {
  // Null / undefined stays unknown ("—"), never rendered as zero.
  if (value === null || value === undefined) {
    return "—";
  }
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "—";
  }
  if (kind === "money") {
    return number.toLocaleString(undefined, {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 2,
    });
  }
  if (kind === "int") {
    return Math.round(number).toLocaleString();
  }
  if (kind === "float") {
    return number.toLocaleString(undefined, {
      maximumFractionDigits: 2,
    });
  }
  if (kind === "percent") {
    return `${(number * 100).toFixed(2)}%`;
  }
  if (kind === "roas") {
    return `${number.toFixed(2)}x`;
  }
  return String(value);
}


function ProviderCard({ entry }) {
  const provider = entry?.provider;
  const metrics = entry?.metrics || null;
  const readiness = entry?.readiness || {};
  const status = readiness.status;

  return (
    <div
      className="rounded-xl border border-[#e7dfc9] bg-white p-4"
      data-testid={`paid-media-provider-${provider}`}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="font-medium text-[#1f2a22]">
          {entry?.display_name || provider}
        </div>
        <span
          className={
            "inline-flex items-center rounded-full border px-2.5 py-1 " +
            "text-[11px] font-semibold " +
            statusTone(status)
          }
          data-testid={`paid-media-status-${provider}`}
        >
          {statusLabel(status)}
        </span>
      </div>

      {!entry?.has_data ? (
        <div
          className={
            "mt-3 rounded-lg border border-dashed border-[#d8cba9] " +
            "bg-[#fbf7ee] px-3 py-4 text-xs text-[#6a6a6a]"
          }
          data-testid={`paid-media-empty-${provider}`}
        >
          {entry?.note ||
            "No performance data available — metrics are unknown, not zero."}
        </div>
      ) : null}

      <div
        className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4"
      >
        {METRICS.map((metric) => (
          <div key={metric.key}>
            <div
              className={
                "text-[10px] uppercase tracking-widest text-[#8a6a3c]"
              }
            >
              {metric.label}
            </div>
            <div
              className="mt-1 font-semibold text-[#1f2a22]"
              data-testid={`paid-media-metric-${provider}-${metric.key}`}
            >
              {formatMetric(metric.kind, metrics ? metrics[metric.key] : null)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}


export default function PaidMediaPanel() {
  const [loading, setLoading] = React.useState(true);
  const [refreshing, setRefreshing] = React.useState(false);
  const [error, setError] = React.useState("");
  const [overview, setOverview] = React.useState(null);

  const load = React.useCallback(async ({ manual = false } = {}) => {
    if (manual) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError("");
    try {
      const response = await api.get("/marketing-os/paid/performance");
      setOverview(response.data || null);
    } catch (loadError) {
      setError(
        loadError?.response?.data?.detail ||
          loadError?.message ||
          "Could not load paid media channels."
      );
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  const providers = React.useMemo(() => {
    const list = Array.isArray(overview?.providers)
      ? overview.providers
      : [];
    const byProvider = new Map(list.map((item) => [item.provider, item]));
    return PROVIDER_ORDER.map((key) => byProvider.get(key)).filter(Boolean);
  }, [overview]);

  return (
    <section
      className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5"
      data-testid="paid-media-panel"
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div
            className={
              "mb-1 text-[11px] uppercase tracking-widest text-[#8a6a3c]"
            }
          >
            Read-only • Google · Meta · Microsoft
          </div>
          <div
            className={
              "flex items-center gap-2 font-display text-xl text-[#1f2a22]"
            }
          >
            <BadgeDollarSign size={18} className="text-[#2f4a3a]" />
            Paid Media Channels
          </div>
        </div>

        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => load({ manual: true })}
          disabled={refreshing || loading}
          data-testid="paid-media-refresh"
        >
          {refreshing ? (
            <Loader2 size={14} className="mr-2 animate-spin" />
          ) : (
            <RefreshCw size={14} className="mr-2" />
          )}
          Refresh
        </Button>
      </div>

      <div
        className={
          "mb-4 flex items-center gap-2 rounded-lg border " +
          "border-[#b9d2bf] bg-[#edf5ef] px-3 py-2 text-xs text-[#2f6a4a]"
        }
        data-testid="paid-media-safety-note"
      >
        <ShieldCheck size={14} />
        Read-only. No external writes, budget changes, or campaign creation.
        All actions require human approval.
      </div>

      {loading ? (
        <div
          className="flex items-center gap-2 px-1 py-6 text-sm text-[#6a6a6a]"
          data-testid="paid-media-loading"
        >
          <Loader2 size={16} className="animate-spin" />
          Loading paid media channels…
        </div>
      ) : error ? (
        <div
          className={
            "rounded-xl border border-[#d9b7b7] bg-[#f9eeee] px-4 py-6 " +
            "text-sm text-[#7a2a2a]"
          }
          data-testid="paid-media-error"
        >
          {error}
        </div>
      ) : (
        <div className="space-y-3">
          {providers.map((entry) => (
            <ProviderCard key={entry.provider} entry={entry} />
          ))}
        </div>
      )}
    </section>
  );
}
