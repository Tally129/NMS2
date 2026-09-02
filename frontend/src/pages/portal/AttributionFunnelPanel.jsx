import React from "react";

import api from "../../lib/api";

import { Button } from "../../components/ui/button";

import {
  GitBranch,
  Loader2,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";


const FUNNEL_STAGES = [
  { key: "lead", label: "Leads" },
  { key: "appointment_intent", label: "Appt. Intents" },
  { key: "appointment_request", label: "Requests" },
  { key: "appointment_booked", label: "Booked" },
  { key: "appointment_completed", label: "Completed" },
  { key: "no_show", label: "No-shows" },
];

const FUNNEL_RATES = [
  { key: "lead_to_booking_rate", label: "Lead → Booking" },
  { key: "booking_to_show_rate", label: "Booking → Show" },
  { key: "lead_to_show_rate", label: "Lead → Show" },
  { key: "request_to_booking_rate", label: "Request → Booking" },
  { key: "no_show_rate", label: "No-show Rate" },
];

const CHANNEL_COLS = [
  { key: "spend", label: "Spend", kind: "money" },
  { key: "booked_appointments", label: "Booked", kind: "int" },
  { key: "completed_appointments", label: "Completed", kind: "int" },
  { key: "cost_per_booked_appointment", label: "Cost / Booked", kind: "money" },
  {
    key: "cost_per_completed_appointment",
    label: "Cost / Completed",
    kind: "money",
  },
  { key: "attributed_revenue", label: "Revenue", kind: "money" },
  { key: "roas", label: "ROAS", kind: "roas" },
];


// Null/undefined stays unknown ("—"), never rendered as a fabricated zero.
function fmt(kind, value) {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  if (kind === "money") {
    return n.toLocaleString(undefined, {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 2,
    });
  }
  if (kind === "int") return Math.round(n).toLocaleString();
  if (kind === "percent") return `${(n * 100).toFixed(1)}%`;
  if (kind === "roas") return `${n.toFixed(2)}x`;
  return String(value);
}


function StatTile({ label, value, kind, testid }) {
  return (
    <div className="rounded-xl border border-[#e7dfc9] bg-white p-3">
      <div className="text-[10px] uppercase tracking-widest text-[#8a6a3c]">
        {label}
      </div>
      <div
        className="mt-1 text-lg font-semibold text-[#1f2a22]"
        data-testid={testid}
      >
        {fmt(kind, value)}
      </div>
    </div>
  );
}


export default function AttributionFunnelPanel() {
  const [loading, setLoading] = React.useState(true);
  const [refreshing, setRefreshing] = React.useState(false);
  const [error, setError] = React.useState("");
  const [model, setModel] = React.useState("last_touch");
  const [overview, setOverview] = React.useState(null);
  const [campaigns, setCampaigns] = React.useState(null);

  const load = React.useCallback(
    async (nextModel, { manual = false } = {}) => {
      if (manual) setRefreshing(true);
      else setLoading(true);
      setError("");
      try {
        const [ov, cmp] = await Promise.all([
          api.get(`/marketing-os/attribution/overview?model=${nextModel}`),
          api.get(`/marketing-os/attribution/campaigns?model=${nextModel}`),
        ]);
        setOverview(ov.data || null);
        setCampaigns(cmp.data || null);
      } catch (err) {
        setError(
          err?.response?.data?.detail ||
            err?.message ||
            "Could not load attribution data."
        );
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    []
  );

  React.useEffect(() => {
    load(model);
  }, [load, model]);

  const funnel = overview?.funnel || null;
  const channels = overview?.channels?.channels || [];
  const revenue = overview?.revenue || null;
  const revenueAvailable = Boolean(revenue?.revenue_available);
  const campaignRows = campaigns?.booked?.credited || [];

  return (
    <section
      className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5"
      data-testid="attribution-panel"
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-widest text-[#8a6a3c]">
            Deterministic • Lead → Appointment → Revenue
          </div>
          <div className="flex items-center gap-2 font-display text-xl text-[#1f2a22]">
            <GitBranch size={18} className="text-[#2f4a3a]" />
            Attribution & Funnel
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div
            className="flex rounded-full border border-[#e7dfc9] bg-white p-0.5"
            data-testid="attribution-model-toggle"
          >
            {["last_touch", "first_touch"].map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setModel(m)}
                data-testid={`attribution-model-${m}`}
                className={
                  "rounded-full px-3 py-1 text-xs font-semibold transition-colors " +
                  (model === m
                    ? "bg-[#2f4a3a] text-white"
                    : "text-[#6a6a6a] hover:text-[#1f2a22]")
                }
              >
                {m === "last_touch" ? "Last-touch" : "First-touch"}
              </button>
            ))}
          </div>

          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => load(model, { manual: true })}
            disabled={refreshing || loading}
            data-testid="attribution-refresh"
          >
            {refreshing ? (
              <Loader2 size={14} className="mr-2 animate-spin" />
            ) : (
              <RefreshCw size={14} className="mr-2" />
            )}
            Refresh
          </Button>
        </div>
      </div>

      <div
        className="mb-4 flex items-center gap-2 rounded-lg border border-[#b9d2bf] bg-[#edf5ef] px-3 py-2 text-xs text-[#2f6a4a]"
        data-testid="attribution-safety-note"
      >
        <ShieldCheck size={14} />
        Deterministic, privacy-safe attribution. No PHI. Advisory only — no
        budget changes or provider execution. Unavailable stages show "—",
        never zero.
      </div>

      {loading ? (
        <div
          className="flex items-center gap-2 px-1 py-6 text-sm text-[#6a6a6a]"
          data-testid="attribution-loading"
        >
          <Loader2 size={16} className="animate-spin" />
          Loading attribution…
        </div>
      ) : error ? (
        <div
          className="rounded-xl border border-[#d9b7b7] bg-[#f9eeee] px-4 py-6 text-sm text-[#7a2a2a]"
          data-testid="attribution-error"
        >
          {error}
        </div>
      ) : (
        <div className="space-y-6">
          {/* Funnel */}
          <div>
            <div className="mb-2 text-sm font-semibold text-[#1f2a22]">
              Lead → Appointment Funnel
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              {FUNNEL_STAGES.map((s) => (
                <StatTile
                  key={s.key}
                  label={s.label}
                  value={funnel?.stages?.[s.key]}
                  kind="int"
                  testid={`funnel-stage-${s.key}`}
                />
              ))}
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              {FUNNEL_RATES.map((r) => (
                <StatTile
                  key={r.key}
                  label={r.label}
                  value={funnel?.rates?.[r.key]}
                  kind="percent"
                  testid={`funnel-rate-${r.key}`}
                />
              ))}
            </div>
          </div>

          {/* Channel economics */}
          <div>
            <div className="mb-2 text-sm font-semibold text-[#1f2a22]">
              Source / Channel Performance
            </div>
            {channels.length === 0 ? (
              <div
                className="rounded-xl border border-dashed border-[#d8cba9] bg-white px-4 py-6 text-sm text-[#6a6a6a]"
                data-testid="attribution-channels-empty"
              >
                No channel outcome or spend data available yet.
              </div>
            ) : (
              <div className="overflow-x-auto rounded-xl border border-[#e7dfc9] bg-white">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[#e7dfc9] text-left text-[10px] uppercase tracking-widest text-[#8a6a3c]">
                      <th className="p-3">Channel</th>
                      {CHANNEL_COLS.map((c) => (
                        <th key={c.key} className="p-3">
                          {c.label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {channels.map((row) => (
                      <tr
                        key={row.channel}
                        className="border-b border-[#f0eaDB] last:border-0"
                        data-testid={`attribution-channel-row-${row.channel}`}
                      >
                        <td className="p-3 font-medium text-[#1f2a22]">
                          {row.channel}
                        </td>
                        {CHANNEL_COLS.map((c) => (
                          <td
                            key={c.key}
                            className="p-3 text-[#1f2a22]"
                            data-testid={`attribution-channel-${row.channel}-${c.key}`}
                          >
                            {fmt(c.kind, row[c.key])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Revenue + campaigns */}
          <div className="grid gap-4 lg:grid-cols-2">
            <div>
              <div className="mb-2 text-sm font-semibold text-[#1f2a22]">
                Attributed Revenue
              </div>
              {!revenueAvailable ? (
                <div
                  className="rounded-xl border border-dashed border-[#d8cba9] bg-white px-4 py-6 text-sm text-[#6a6a6a]"
                  data-testid="attribution-revenue-empty"
                >
                  No first-party revenue data available. Revenue is recognized
                  only from real paid purchases, never appointment estimates.
                </div>
              ) : (
                <div className="rounded-xl border border-[#e7dfc9] bg-white p-4">
                  <StatTile
                    label="Total Attributed Revenue"
                    value={revenue?.total_attributed_revenue}
                    kind="money"
                    testid="attribution-revenue-total"
                  />
                  <div className="mt-3 space-y-1">
                    {(revenue?.by_channel || []).map((r) => (
                      <div
                        key={r.key}
                        className="flex items-center justify-between text-sm"
                        data-testid={`attribution-revenue-channel-${r.key}`}
                      >
                        <span className="text-[#6a6a6a]">{r.key}</span>
                        <span className="font-semibold text-[#1f2a22]">
                          {fmt("money", r.attributed_revenue)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div>
              <div className="mb-2 text-sm font-semibold text-[#1f2a22]">
                Booked by Campaign
              </div>
              {campaignRows.length === 0 ? (
                <div
                  className="rounded-xl border border-dashed border-[#d8cba9] bg-white px-4 py-6 text-sm text-[#6a6a6a]"
                  data-testid="attribution-campaigns-empty"
                >
                  No campaign-attributed bookings yet.
                </div>
              ) : (
                <div className="rounded-xl border border-[#e7dfc9] bg-white p-4">
                  <div className="space-y-1">
                    {campaignRows.map((r) => (
                      <div
                        key={r.key}
                        className="flex items-center justify-between text-sm"
                        data-testid={`attribution-campaign-row-${r.key}`}
                      >
                        <span className="text-[#6a6a6a]">{r.key}</span>
                        <span className="font-semibold text-[#1f2a22]">
                          {fmt("int", r.attributed_count)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
