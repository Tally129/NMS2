import React from "react";

import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Target,
  TrendingUp,
} from "lucide-react";

import api from "../../lib/api";
import { Button } from "../../components/ui/button";


function asArray(value) {
  return Array.isArray(value) ? value : [];
}


function priorityTone(priority) {
  const value = Number(priority || 0);

  if (value >= 80) {
    return "border-red-200 bg-red-50 text-red-700";
  }

  if (value >= 60) {
    return "border-amber-200 bg-amber-50 text-amber-700";
  }

  return "border-[#d8cba9] bg-[#f7f1e4] text-[#6a6a6a]";
}


function SummaryList({
  title,
  icon: Icon,
  items,
}) {
  const rows = asArray(items);

  return (
    <div className="rounded-xl border border-[#e7dfc9] bg-white p-4">
      <div className="mb-3 flex items-center gap-2">
        <Icon
          size={17}
          className="text-[#2f4a3a]"
        />
        <div className="font-semibold text-[#1f2a22]">
          {title}
        </div>
      </div>

      {rows.length ? (
        <div className="space-y-2">
          {rows.map((item, index) => (
            <div
              key={`${title}-${index}`}
              className="text-sm leading-6 text-[#5f625e]"
            >
              {item}
            </div>
          ))}
        </div>
      ) : (
        <div className="text-sm text-[#7a7d78]">
          Nothing requiring attention from the connected data.
        </div>
      )}
    </div>
  );
}


export default function AIMarketingDirectorPanel() {
  const [loading, setLoading] = React.useState(true);
  const [aiLoading, setAiLoading] = React.useState(false);
  const [error, setError] = React.useState("");
  const [brief, setBrief] = React.useState(null);

  const load = React.useCallback(async ({
    ai = false,
  } = {}) => {
    if (ai) {
      setAiLoading(true);
    } else {
      setLoading(true);
    }

    setError("");

    try {
      const response = await api.get(
        `/marketing-os/director/brief${
          ai ? "?ai_summary=true" : ""
        }`
      );

      setBrief(response?.data || response || {});
    } catch (err) {
      setError(
        err?.response?.data?.detail?.message ||
        err?.response?.data?.detail ||
        err?.message ||
        "Unable to load Marketing Director."
      );
    } finally {
      setLoading(false);
      setAiLoading(false);
    }
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  const director = brief?.director_summary || {};
  const signalEnvelope = brief?.director_signals || {};
  const signals = asArray(signalEnvelope?.signals);
  const signalSummary = signalEnvelope?.summary || {};
  const aiStatus = brief?.director_ai_status || "not_requested";

  return (
    <section
      className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5"
      data-testid="ai-marketing-director-panel"
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-widest text-[#8a6a3c]">
            Phase 12
          </div>

          <div className="flex items-center gap-2 font-display text-xl text-[#1f2a22]">
            <Brain
              size={19}
              className="text-[#2f4a3a]"
            />
            AI Marketing Director
          </div>

          <div className="mt-1 max-w-3xl text-sm leading-6 text-[#6a6a6a]">
            Cross-channel marketing intelligence, deterministic
            prioritization, and optional AI executive summarization.
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={loading || aiLoading}
            onClick={() => load()}
          >
            <RefreshCw
              size={15}
              className={loading ? "mr-2 animate-spin" : "mr-2"}
            />
            Refresh
          </Button>

          <Button
            type="button"
            disabled={loading || aiLoading}
            onClick={() => load({ ai: true })}
            data-testid="director-ai-summary-button"
          >
            <Sparkles
              size={15}
              className="mr-2"
            />
            {aiLoading
              ? "Generating..."
              : "Generate AI Summary"}
          </Button>
        </div>
      </div>

      <div className="mb-5 flex items-start gap-3 rounded-xl border border-[#d8cba9] bg-[#f7f1e4] p-4">
        <ShieldCheck
          size={19}
          className="mt-0.5 shrink-0 text-[#2f6a4a]"
        />

        <div>
          <div className="font-semibold text-[#1f2a22]">
            Advisory only — no autonomous actions
          </div>

          <div className="mt-1 text-sm leading-6 text-[#6a6a6a]">
            Signals, priorities, and evidence are deterministic.
            AI may summarize them, but it cannot publish content,
            send messages, change budgets, modify campaigns or
            listings, alter experiments, or book appointments.
            Human review remains required.
          </div>
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {String(error)}
        </div>
      )}

      {loading ? (
        <div className="py-10 text-center text-sm text-[#6a6a6a]">
          Loading Marketing Director...
        </div>
      ) : (
        <>
          <div className="mb-5 grid gap-3 md:grid-cols-4">
            <div className="rounded-xl border border-[#e7dfc9] bg-white p-4">
              <div className="text-xs uppercase tracking-wide text-[#8a6a3c]">
                Signals
              </div>
              <div className="mt-2 text-2xl font-semibold text-[#1f2a22]">
                {Number(signalSummary?.total || signals.length)}
              </div>
            </div>

            <div className="rounded-xl border border-[#e7dfc9] bg-white p-4">
              <div className="text-xs uppercase tracking-wide text-[#8a6a3c]">
                High Priority
              </div>
              <div className="mt-2 text-2xl font-semibold text-[#1f2a22]">
                {Number(signalSummary?.high_priority || 0)}
              </div>
            </div>

            <div className="rounded-xl border border-[#e7dfc9] bg-white p-4">
              <div className="text-xs uppercase tracking-wide text-[#8a6a3c]">
                Summary Source
              </div>
              <div className="mt-2 text-sm font-semibold text-[#1f2a22]">
                {director?.source || "deterministic"}
              </div>
            </div>

            <div className="rounded-xl border border-[#e7dfc9] bg-white p-4">
              <div className="text-xs uppercase tracking-wide text-[#8a6a3c]">
                AI Status
              </div>
              <div className="mt-2 text-sm font-semibold text-[#1f2a22]">
                {aiStatus}
              </div>
            </div>
          </div>

          <div className="mb-5 rounded-xl border border-[#e7dfc9] bg-white p-5">
            <div className="mb-2 flex items-center gap-2">
              <TrendingUp
                size={18}
                className="text-[#2f4a3a]"
              />
              <div className="font-semibold text-[#1f2a22]">
                Executive Summary
              </div>
            </div>

            <div className="text-sm leading-7 text-[#5f625e]">
              {director?.executive_summary ||
                "No Director summary is currently available."}
            </div>
          </div>

          <div className="mb-5 grid gap-4 lg:grid-cols-3">
            <SummaryList
              title="Urgent Issues"
              icon={AlertTriangle}
              items={director?.urgent_issues}
            />

            <SummaryList
              title="Top Opportunities"
              icon={Target}
              items={director?.top_opportunities}
            />

            <SummaryList
              title="Recommended Focus"
              icon={CheckCircle2}
              items={director?.recommended_focus}
            />
          </div>

          <div>
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="font-semibold text-[#1f2a22]">
                Supporting Evidence
              </div>

              <div className="text-xs text-[#7a7d78]">
                Deterministically ranked
              </div>
            </div>

            {signals.length ? (
              <div className="space-y-3">
                {signals.slice(0, 12).map((signal) => (
                  <div
                    key={signal.signal_key}
                    className="rounded-xl border border-[#e7dfc9] bg-white p-4"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="font-semibold text-[#1f2a22]">
                          {signal.title}
                        </div>

                        <div className="mt-1 text-sm leading-6 text-[#6a6a6a]">
                          {signal.summary}
                        </div>
                      </div>

                      <div
                        className={
                          "rounded-full border px-2.5 py-1 " +
                          "text-xs font-semibold " +
                          priorityTone(signal.priority)
                        }
                      >
                        Priority {signal.priority}
                      </div>
                    </div>

                    <div className="mt-3 flex flex-wrap gap-2 text-xs text-[#7a7d78]">
                      <span>
                        {signal.category}
                      </span>
                      <span>•</span>
                      <span>
                        Phase {signal.source_phase}
                      </span>
                      <span>•</span>
                      <span>
                        {signal.severity}
                      </span>
                      <span>•</span>
                      <span>
                        confidence {signal.confidence || "unknown"}
                      </span>
                    </div>

                    {signal.recommended_action && (
                      <div className="mt-3 rounded-lg bg-[#fbf7ee] p-3 text-sm leading-6 text-[#5f625e]">
                        <strong>Recommended action: </strong>
                        {signal.recommended_action}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-[#d8cba9] px-4 py-8 text-center text-sm text-[#6a6a6a]">
                No deterministic Director signals are currently available.
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}
