import React from "react";

import {
  AlertTriangle,
  BarChart3,
  CircleDollarSign,
  RefreshCw,
  ShieldCheck,
  Target,
  TrendingUp,
  Users,
} from "lucide-react";

import api from "../../lib/api";
import { Button } from "../../components/ui/button";


function asArray(value) {
  return Array.isArray(value) ? value : [];
}


function money(value) {
  if (value === null || value === undefined) {
    return "—";
  }

  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "—";
  }

  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(number);
}


function numberValue(value) {
  if (value === null || value === undefined) {
    return "—";
  }

  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "—";
  }

  return new Intl.NumberFormat("en-US").format(number);
}


function percent(value) {
  if (value === null || value === undefined) {
    return "—";
  }

  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "—";
  }

  return `${(number * 100).toFixed(1)}%`;
}


function ratio(value) {
  if (value === null || value === undefined) {
    return "—";
  }

  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "—";
  }

  return `${number.toFixed(2)}x`;
}


function humanize(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}


function statusTone(status) {
  switch (status) {
    case "critical":
      return "border-red-200 bg-red-50 text-red-700";

    case "needs_attention":
      return "border-amber-200 bg-amber-50 text-amber-700";

    case "healthy":
      return "border-emerald-200 bg-emerald-50 text-emerald-700";

    case "monitor":
      return "border-blue-200 bg-blue-50 text-blue-700";

    default:
      return "border-[#ded6c3] bg-[#f7f3e9] text-[#6c6c67]";
  }
}


function priorityTone(priority) {
  const value = Number(priority || 0);

  if (value >= 80) {
    return "border-red-200 bg-red-50 text-red-700";
  }

  if (value >= 60) {
    return "border-amber-200 bg-amber-50 text-amber-700";
  }

  return "border-[#ded6c3] bg-[#f7f3e9] text-[#6c6c67]";
}


function KpiCard({
  label,
  value,
  icon: Icon,
}) {
  return (
    <div className="rounded-xl border border-[#e7dfc9] bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-[#8a6a3c]">
          {label}
        </div>

        <Icon
          size={17}
          className="text-[#466653]"
        />
      </div>

      <div className="mt-3 text-2xl font-semibold text-[#1f2a22]">
        {value}
      </div>
    </div>
  );
}


function FunnelStep({
  label,
  value,
  rateLabel,
  rate,
}) {
  return (
    <div className="rounded-xl border border-[#e7dfc9] bg-white p-4">
      <div className="text-xs uppercase tracking-wide text-[#8a6a3c]">
        {label}
      </div>

      <div className="mt-2 text-2xl font-semibold text-[#1f2a22]">
        {numberValue(value)}
      </div>

      {rateLabel && (
        <div className="mt-2 text-xs text-[#777870]">
          {rateLabel}: {percent(rate)}
        </div>
      )}
    </div>
  );
}


export default function ExecutiveMarketingCommandCenter() {
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [brief, setBrief] = React.useState(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const response = await api.get(
        "/marketing-os/director/brief"
      );

      setBrief(response?.data || response || {});
    } catch (err) {
      setError(
        err?.response?.data?.detail?.message ||
        err?.response?.data?.detail ||
        err?.message ||
        "Unable to load executive marketing data."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  const commandCenter =
    brief?.executive_command_center || {};

  const kpis =
    commandCenter?.executive_kpis || {};

  const funnel =
    commandCenter?.growth_funnel || {};

  const channels =
    asArray(commandCenter?.channel_health);

  const pipeline =
    commandCenter?.pipeline_health || {};

  const director =
    commandCenter?.marketing_director || {};

  const topActions =
    asArray(director?.top_actions);

  return (
    <section
      className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5"
      data-testid="executive-marketing-command-center"
    >
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-widest text-[#8a6a3c]">
            Phase 13
          </div>

          <div className="flex items-center gap-2 font-display text-xl text-[#1f2a22]">
            <BarChart3
              size={20}
              className="text-[#466653]"
            />
            Executive Marketing Command Center
          </div>

          <div className="mt-1 max-w-3xl text-sm leading-6 text-[#6a6a6a]">
            Unified performance, funnel, channel, pipeline,
            and Marketing Director intelligence.
          </div>
        </div>

        <Button
          type="button"
          variant="outline"
          disabled={loading}
          onClick={load}
        >
          <RefreshCw
            size={15}
            className={
              loading
                ? "mr-2 animate-spin"
                : "mr-2"
            }
          />
          Refresh
        </Button>
      </div>

      <div className="mb-5 flex items-start gap-3 rounded-xl border border-[#d8cba9] bg-[#f7f1e4] p-4">
        <ShieldCheck
          size={19}
          className="mt-0.5 shrink-0 text-[#2f6a4a]"
        />

        <div>
          <div className="font-semibold text-[#1f2a22]">
            Executive view — read only
          </div>

          <div className="mt-1 text-sm leading-6 text-[#6a6a6a]">
            This dashboard summarizes connected marketing data.
            It does not publish, send, modify budgets, change
            campaigns, edit listings, or execute Director actions.
          </div>
        </div>
      </div>

      {error && (
        <div className="mb-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {String(error)}
        </div>
      )}

      {loading ? (
        <div className="py-12 text-center text-sm text-[#6a6a6a]">
          Loading executive marketing data...
        </div>
      ) : (
        <>
          <div className="mb-3 text-sm font-semibold text-[#1f2a22]">
            Executive KPIs
          </div>

          <div className="mb-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard
              label="Spend"
              value={money(kpis.spend)}
              icon={CircleDollarSign}
            />

            <KpiCard
              label="Leads"
              value={numberValue(kpis.leads)}
              icon={Users}
            />

            <KpiCard
              label="CPL"
              value={money(kpis.cpl)}
              icon={Target}
            />

            <KpiCard
              label="CPA"
              value={money(kpis.cac_cpa)}
              icon={Target}
            />

            <KpiCard
              label="Conversions"
              value={numberValue(kpis.conversions)}
              icon={TrendingUp}
            />

            <KpiCard
              label="Revenue"
              value={money(kpis.revenue)}
              icon={CircleDollarSign}
            />

            <KpiCard
              label="ROAS"
              value={ratio(kpis.roas)}
              icon={TrendingUp}
            />

            <KpiCard
              label="High Priority"
              value={numberValue(
                director.high_priority_count
              )}
              icon={AlertTriangle}
            />
          </div>

          <div className="mb-3 text-sm font-semibold text-[#1f2a22]">
            Growth Funnel
          </div>

          <div className="mb-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            <FunnelStep
              label="Leads"
              value={funnel.leads}
            />

            <FunnelStep
              label="Appointment Requests"
              value={funnel.appointment_requests}
              rateLabel="Lead → request"
              rate={funnel.lead_to_request_rate}
            />

            <FunnelStep
              label="Booked"
              value={funnel.booked}
              rateLabel="Request → booking"
              rate={funnel.request_to_booking_rate}
            />

            <FunnelStep
              label="Completed"
              value={funnel.completed}
              rateLabel="Booking → completed"
              rate={funnel.booking_to_completion_rate}
            />

            <FunnelStep
              label="No Show"
              value={funnel.no_show}
            />
          </div>

          <div className="mb-6 grid gap-4 lg:grid-cols-3">
            <div className="rounded-xl border border-[#e7dfc9] bg-white p-4">
              <div className="mb-3 font-semibold text-[#1f2a22]">
                Pipeline Health
              </div>

              <div className="space-y-3">
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-[#666962]">
                    Needs attention
                  </span>

                  <strong className="text-[#1f2a22]">
                    {numberValue(
                      pipeline.needs_attention
                    )}
                  </strong>
                </div>

                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-[#666962]">
                    Overdue follow-ups
                  </span>

                  <strong className="text-[#1f2a22]">
                    {numberValue(
                      pipeline.overdue_followups
                    )}
                  </strong>
                </div>

                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-[#666962]">
                    No-show recovery
                  </span>

                  <strong className="text-[#1f2a22]">
                    {numberValue(
                      pipeline.no_show_recovery
                    )}
                  </strong>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-[#e7dfc9] bg-white p-4 lg:col-span-2">
              <div className="mb-3 font-semibold text-[#1f2a22]">
                Marketing Director Summary
              </div>

              <div className="text-sm leading-7 text-[#60635d]">
                {director.executive_summary ||
                  "No Director summary is currently available."}
              </div>

              <div className="mt-3 text-xs text-[#777870]">
                Source:{" "}
                {humanize(
                  director.summary_source ||
                  "deterministic"
                )}
              </div>
            </div>
          </div>

          <div className="mb-3 text-sm font-semibold text-[#1f2a22]">
            Channel Health
          </div>

          <div className="mb-6 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {channels.length ? (
              channels.map((channel, index) => (
                <div
                  key={`${channel.channel}-${index}`}
                  className="rounded-xl border border-[#e7dfc9] bg-white p-4"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="font-semibold text-[#1f2a22]">
                      {humanize(channel.channel)}
                    </div>

                    <div
                      className={
                        "rounded-full border px-2.5 py-1 " +
                        "text-[11px] font-semibold " +
                        statusTone(channel.status)
                      }
                    >
                      {humanize(channel.status)}
                    </div>
                  </div>

                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-[#6d7069]">
                    {channel.spend !== undefined && (
                      <div>
                        Spend: {money(channel.spend)}
                      </div>
                    )}

                    {channel.ctr !== undefined && (
                      <div>
                        CTR: {percent(channel.ctr)}
                      </div>
                    )}

                    {channel.cpc !== undefined && (
                      <div>
                        CPC: {money(channel.cpc)}
                      </div>
                    )}

                    {channel.cpl !== undefined && (
                      <div>
                        CPL: {money(channel.cpl)}
                      </div>
                    )}

                    {channel.cpa !== undefined && (
                      <div>
                        CPA: {money(channel.cpa)}
                      </div>
                    )}

                    {channel.roas !== undefined && (
                      <div>
                        ROAS: {ratio(channel.roas)}
                      </div>
                    )}
                  </div>

                  <div className="mt-3 text-xs text-[#777870]">
                    {numberValue(channel.signal_count)} signal(s)
                    {Number(channel.highest_priority || 0) > 0
                      ? ` • priority ${channel.highest_priority}`
                      : ""}
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-xl border border-dashed border-[#d8cba9] p-6 text-sm text-[#6a6a6a]">
                No connected channel health data is currently available.
              </div>
            )}
          </div>

          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="text-sm font-semibold text-[#1f2a22]">
              Top Recommended Actions
            </div>

            <div className="text-xs text-[#777870]">
              Human approval required
            </div>
          </div>

          {topActions.length ? (
            <div className="space-y-3">
              {topActions.map((action) => (
                <div
                  key={action.signal_key}
                  className="rounded-xl border border-[#e7dfc9] bg-white p-4"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="font-semibold text-[#1f2a22]">
                        {action.title}
                      </div>

                      <div className="mt-1 text-xs text-[#777870]">
                        {humanize(action.category)}
                        {" • "}
                        {humanize(action.severity)}
                        {" • "}
                        confidence{" "}
                        {humanize(
                          action.confidence ||
                          "unknown"
                        )}
                      </div>
                    </div>

                    <div
                      className={
                        "rounded-full border px-2.5 py-1 " +
                        "text-xs font-semibold " +
                        priorityTone(action.priority)
                      }
                    >
                      Priority {action.priority}
                    </div>
                  </div>

                  {action.recommended_action && (
                    <div className="mt-3 rounded-lg bg-[#fbf7ee] p-3 text-sm leading-6 text-[#5e625d]">
                      {action.recommended_action}
                    </div>
                  )}

                  {action.data_quality && (
                    <div className="mt-2 text-xs text-[#7a7d78]">
                      Data quality:{" "}
                      {humanize(action.data_quality)}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-[#d8cba9] p-6 text-sm text-[#6a6a6a]">
              No Director actions currently require review.
            </div>
          )}
        </>
      )}
    </section>
  );
}
