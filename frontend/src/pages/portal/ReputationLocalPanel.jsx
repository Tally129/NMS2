import React from "react";

import api from "../../lib/api";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "../../components/ui/select";
import {
  MapPin, Loader2, RefreshCw, ShieldCheck, Star, TrendingUp,
} from "lucide-react";

const pct = (v) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`);

function Stat({ label, value }) {
  return (
    <div className="rounded-xl border border-[#d8cba9] bg-white p-3">
      <div className="text-[10px] uppercase tracking-widest text-[#8a6a3c]">
        {label}
      </div>
      <div className="mt-1 text-xl font-semibold text-[#3f3320]">{value}</div>
    </div>
  );
}

const SEV = {
  high: "bg-rose-100 text-rose-800",
  medium: "bg-amber-100 text-amber-800",
  low: "bg-slate-200 text-slate-700",
};

export default function ReputationLocalPanel() {
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [locations, setLocations] = React.useState([]);
  const [selected, setSelected] = React.useState("");
  const [health, setHealth] = React.useState(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get("/marketing-os/local/locations");
      const locs = r.data?.locations || [];
      setLocations(locs);
      if (locs.length && !selected) setSelected(locs[0].id);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to load locations");
    } finally {
      setLoading(false);
    }
  }, [selected]);

  React.useEffect(() => { load(); }, [load]);

  const loadHealth = React.useCallback(async (id) => {
    if (!id) return;
    try {
      const r = await api.get(`/marketing-os/local/locations/${id}/health`);
      setHealth(r.data);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to load health");
    }
  }, []);

  React.useEffect(() => { loadHealth(selected); }, [selected, loadHealth]);

  return (
    <section
      className="rounded-2xl border border-[#d8cba9] bg-[#fbf7ee] p-5"
      data-testid="reputation-local-panel"
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="rounded-xl border border-[#d8cba9] bg-white p-2 text-[#8a6a3c]">
            <MapPin size={18} />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-[#3f3320]">
              Reputation &amp; Local Growth
            </h3>
            <p className="mt-1 max-w-3xl text-sm text-[#806837]">
              Location reputation health, listing consistency, and local SEO
              opportunities.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {locations.length ? (
            <Select value={selected} onValueChange={setSelected}>
              <SelectTrigger data-testid="location-select" className="w-56">
                <SelectValue placeholder="Select location" />
              </SelectTrigger>
              <SelectContent>
                {locations.map((l) => (
                  <SelectItem key={l.id} value={l.id}>{l.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : null}
          <Button type="button" variant="outline"
            onClick={() => { load(); loadHealth(selected); }}>
            <RefreshCw size={16} className="mr-1" /> Refresh
          </Button>
        </div>
      </div>

      <div
        className="mb-4 flex flex-wrap items-center gap-2 rounded-xl border border-[#d8cba9] bg-white px-4 py-3 text-xs text-[#5f5330]"
        data-testid="local-safety"
      >
        <ShieldCheck size={16} className="text-emerald-700" />
        <span className="font-medium">
          Read-only intelligence — no automatic listing or review changes.
        </span>
        <span>No posting/replies/edits · human approval required · no PHI · no SMS.</span>
      </div>

      {error ? (
        <div className="mb-3 rounded-lg bg-rose-50 px-4 py-2 text-sm text-rose-700">
          {typeof error === "string" ? error : JSON.stringify(error)}
        </div>
      ) : null}

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-[#806837]">
          <Loader2 size={16} className="animate-spin" /> Loading…
        </div>
      ) : locations.length === 0 ? (
        <div className="rounded-lg border border-dashed border-[#c9b98e] px-4 py-6 text-center text-sm text-[#806837]">
          No locations yet. Add a location to see reputation and local growth
          intelligence.
        </div>
      ) : !health ? (
        <div className="text-sm text-[#806837]">Select a location…</div>
      ) : (
        <div className="grid gap-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Health score" value={`${health.health_score}/100`} />
            <Stat label="Rating"
              value={health.best_rating ? (
                <span className="flex items-center gap-1">
                  <Star size={16} className="text-amber-500" />
                  {health.best_rating}
                </span>
              ) : "—"} />
            <Stat label="Reviews" value={health.total_reviews} />
            <Stat label="Velocity (30d)"
              value={`${health.review_velocity} (${health.review_velocity_class})`} />
            <Stat label="Listing completeness"
              value={pct(health.listing_completeness)} />
            <Stat label="NAP consistency" value={pct(health.nap_consistency)} />
            <Stat label="Response rate" value={pct(health.best_response_rate)} />
            <Stat label="Source coverage"
              value={pct(health.source_coverage?.coverage)} />
          </div>

          {health.source_coverage?.missing?.length ? (
            <div className="text-xs text-[#806837]">
              Missing directories:{" "}
              {health.source_coverage.missing.join(", ")}
            </div>
          ) : null}

          <div>
            <h4 className="mb-2 flex items-center gap-1 text-sm font-semibold text-[#3f3320]">
              <TrendingUp size={15} className="text-[#8a6a3c]" />
              Prioritized local growth opportunities
            </h4>
            {(health.opportunities || []).length === 0 ? (
              <div className="rounded-lg border border-dashed border-[#c9b98e] px-4 py-5 text-center text-sm text-[#806837]">
                No opportunities — this location looks healthy.
              </div>
            ) : (
              <div className="grid gap-2" data-testid="opportunity-list">
                {health.opportunities.map((o) => (
                  <div
                    key={o.opportunity_key}
                    className="flex items-start justify-between gap-3 rounded-xl border border-[#e2dac5] bg-white px-4 py-3"
                    data-testid="opportunity-row"
                  >
                    <div>
                      <div className="text-sm font-medium text-[#3f3320]">
                        {o.title}
                      </div>
                      <div className="text-[11px] text-[#806837]">{o.detail}</div>
                    </div>
                    <div className="flex flex-shrink-0 items-center gap-2">
                      <span className="text-[10px] text-[#8a6a3c]">
                        P{o.priority}
                      </span>
                      <span className={"rounded-full px-2 py-0.5 text-[11px] font-medium " + (SEV[o.severity] || SEV.low)}>
                        {o.severity}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="text-[11px] text-[#806837]">
            <Badge variant="outline">advisory</Badge> Recommendations are
            deterministic and read-only; any external change requires human
            approval.
          </div>
        </div>
      )}
    </section>
  );
}
