import React from "react";

import api from "../../lib/api";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../components/ui/select";
import {
  FlaskConical,
  Loader2,
  Play,
  Pause,
  CheckCircle2,
  RefreshCw,
  ShieldCheck,
  Plus,
  Trophy,
} from "lucide-react";

function StatusBadge({ status }) {
  const tone = {
    draft: "bg-slate-200 text-slate-700",
    active: "bg-emerald-100 text-emerald-800",
    paused: "bg-amber-100 text-amber-800",
    completed: "bg-sky-100 text-sky-800",
    archived: "bg-slate-200 text-slate-500",
  }[status] || "bg-slate-200 text-slate-700";
  return (
    <span className={"rounded-full px-2 py-0.5 text-[11px] font-medium " + tone}>
      {status}
    </span>
  );
}

const fmtRate = (v) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(2)}%`);
const fmtNum = (v) => (v === null || v === undefined ? "—" : v);

export default function ExperimentsPanel() {
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [success, setSuccess] = React.useState("");

  const [experiments, setExperiments] = React.useState([]);
  const [overview, setOverview] = React.useState(null);
  const [selectedId, setSelectedId] = React.useState("");
  const [detail, setDetail] = React.useState(null);
  const [report, setReport] = React.useState(null);

  const [newExp, setNewExp] = React.useState({
    name: "", slug: "", experiment_type: "landing_page",
  });
  const [newVar, setNewVar] = React.useState({
    variant_key: "", name: "", role: "variant", allocation_pct: "50",
  });

  const flash = (setter, v) => {
    setter(v);
    window.setTimeout(() => setter(""), 10000);
  };

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const [ov, list] = await Promise.all([
        api.get("/marketing-os/experiments/overview"),
        api.get("/marketing-os/experiments"),
      ]);
      setOverview(ov.data);
      setExperiments(list.data?.experiments || []);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to load experiments");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const openDetail = async (id) => {
    setSelectedId(id);
    setReport(null);
    try {
      const [d, r] = await Promise.all([
        api.get(`/marketing-os/experiments/${id}`),
        api.get(`/marketing-os/experiments/${id}/report`),
      ]);
      setDetail(d.data);
      setReport(r.data);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to load experiment");
    }
  };

  const createExperiment = async () => {
    setBusy(true); setError("");
    try {
      await api.post("/marketing-os/experiments", {
        name: newExp.name, slug: newExp.slug,
        experiment_type: newExp.experiment_type,
      });
      setNewExp({ name: "", slug: "", experiment_type: "landing_page" });
      flash(setSuccess, "Experiment created (draft)");
      await load();
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not create experiment");
    } finally { setBusy(false); }
  };

  const addVariant = async () => {
    if (!selectedId) { setError("Open an experiment first"); return; }
    setBusy(true); setError("");
    try {
      await api.post(`/marketing-os/experiments/${selectedId}/variants`, {
        variant_key: newVar.variant_key,
        name: newVar.name,
        is_control: newVar.role === "control",
        allocation_pct: Number(newVar.allocation_pct) || 0,
      });
      setNewVar({ variant_key: "", name: "", role: "variant",
        allocation_pct: "50" });
      flash(setSuccess, "Variant added");
      await openDetail(selectedId);
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not add variant");
    } finally { setBusy(false); }
  };

  const transition = async (id, action) => {
    setBusy(true); setError("");
    try {
      await api.post(`/marketing-os/experiments/${id}/transition`, { action });
      flash(setSuccess, `Experiment ${action}d`);
      await load();
      if (selectedId === id) await openDetail(id);
    } catch (err) {
      setError(err?.response?.data?.detail || `Could not ${action}`);
    } finally { setBusy(false); }
  };

  const rec = report?.recommendation;

  return (
    <section
      className="rounded-2xl border border-[#d8cba9] bg-[#fbf7ee] p-5"
      data-testid="experiments-panel"
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="rounded-xl border border-[#d8cba9] bg-white p-2 text-[#8a6a3c]">
            <FlaskConical size={18} />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-[#3f3320]">
              Conversion Experiments
            </h3>
            <p className="mt-1 max-w-3xl text-sm text-[#806837]">
              Deterministic A/B testing for landing pages, offers, and funnel
              steps. Reporting and winner recommendations are advisory only.
            </p>
          </div>
        </div>
        <Button type="button" variant="outline" onClick={load} disabled={busy}>
          <RefreshCw size={16} className="mr-1" /> Refresh
        </Button>
      </div>

      <div
        className="mb-4 flex flex-wrap items-center gap-2 rounded-xl border border-[#d8cba9] bg-white px-4 py-3 text-xs text-[#5f5330]"
        data-testid="experiments-safety"
      >
        <ShieldCheck size={16} className="text-emerald-700" />
        <span className="font-medium">No autonomous publishing.</span>
        <span>Winner selection is advisory only · human approval required for any external change · no ad-platform writes · no budget changes · no PHI.</span>
      </div>

      {error ? (
        <div className="mb-3 rounded-lg bg-rose-50 px-4 py-2 text-sm text-rose-700">
          {typeof error === "string" ? error : JSON.stringify(error)}
        </div>
      ) : null}
      {success ? (
        <div className="mb-3 rounded-lg bg-emerald-50 px-4 py-2 text-sm text-emerald-700">
          {success}
        </div>
      ) : null}

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-[#806837]">
          <Loader2 size={16} className="animate-spin" /> Loading…
        </div>
      ) : (
        <div className="grid gap-5 lg:grid-cols-2">
          {/* Left: list + create */}
          <div className="grid gap-4">
            <div className="rounded-xl border border-[#e2dac5] bg-white p-4">
              <h4 className="mb-3 text-sm font-semibold text-[#3f3320]">
                Experiments
              </h4>
              {experiments.length === 0 ? (
                <div className="rounded-lg border border-dashed border-[#c9b98e] px-4 py-5 text-center text-sm text-[#806837]">
                  No experiments yet.
                </div>
              ) : (
                <div className="grid gap-2">
                  {experiments.map((e) => (
                    <div
                      key={e.id}
                      className="flex items-center justify-between gap-2 rounded-lg border border-[#eee3ca] px-3 py-2"
                      data-testid="experiment-row"
                    >
                      <button
                        type="button"
                        onClick={() => openDetail(e.id)}
                        className="text-left"
                        data-testid="experiment-open"
                      >
                        <div className="text-sm font-medium text-[#3f3320]">
                          {e.name}
                        </div>
                        <div className="text-[11px] text-[#806837]">
                          {e.slug} · {e.experiment_type}
                        </div>
                      </button>
                      <div className="flex items-center gap-1">
                        <StatusBadge status={e.status} />
                        {e.status === "draft" ? (
                          <Button type="button" size="sm" variant="outline"
                            data-testid="experiment-start"
                            onClick={() => transition(e.id, "activate")}
                            disabled={busy}>
                            <Play size={13} className="mr-1" /> Start
                          </Button>
                        ) : null}
                        {e.status === "active" ? (
                          <>
                            <Button type="button" size="sm" variant="outline"
                              onClick={() => transition(e.id, "pause")}
                              disabled={busy}>
                              <Pause size={13} className="mr-1" /> Pause
                            </Button>
                            <Button type="button" size="sm" variant="outline"
                              data-testid="experiment-complete"
                              onClick={() => transition(e.id, "complete")}
                              disabled={busy}>
                              <CheckCircle2 size={13} className="mr-1" /> Complete
                            </Button>
                          </>
                        ) : null}
                        {e.status === "paused" ? (
                          <Button type="button" size="sm" variant="outline"
                            onClick={() => transition(e.id, "activate")}
                            disabled={busy}>
                            <Play size={13} className="mr-1" /> Resume
                          </Button>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="rounded-xl border border-[#e2dac5] bg-white p-4">
              <h4 className="mb-3 text-sm font-semibold text-[#3f3320]">
                Create experiment
              </h4>
              <Label>Name</Label>
              <Input value={newExp.name} data-testid="experiment-name"
                onChange={(e) => setNewExp({ ...newExp, name: e.target.value })} />
              <Label className="mt-2">Slug</Label>
              <Input value={newExp.slug} data-testid="experiment-slug"
                placeholder="homepage-hero-test"
                onChange={(e) => setNewExp({ ...newExp, slug: e.target.value })} />
              <Label className="mt-2">Type</Label>
              <Select value={newExp.experiment_type}
                onValueChange={(v) => setNewExp({ ...newExp, experiment_type: v })}>
                <SelectTrigger data-testid="experiment-type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="landing_page">landing_page</SelectItem>
                  <SelectItem value="offer">offer</SelectItem>
                  <SelectItem value="funnel_step">funnel_step</SelectItem>
                </SelectContent>
              </Select>
              <Button type="button" className="mt-3" onClick={createExperiment}
                disabled={busy} data-testid="experiment-create">
                <Plus size={16} className="mr-1" /> Create draft
              </Button>
            </div>
          </div>

          {/* Right: detail + report */}
          <div className="rounded-xl border border-[#e2dac5] bg-white p-4">
            {!detail ? (
              <div className="text-sm text-[#806837]">
                Select an experiment to view variants, allocation, and results.
              </div>
            ) : (
              <div className="grid gap-3">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-semibold text-[#3f3320]">
                      {detail.name}
                    </div>
                    <div className="text-[11px] text-[#806837]">
                      {detail.experiment_type} · primary: {detail.primary_metric}
                      {" "}· exposure: {detail.exposure_metric}
                    </div>
                  </div>
                  <StatusBadge status={detail.status} />
                </div>

                {detail.status === "draft" ? (
                  <div className="rounded-lg border border-[#eee3ca] p-3">
                    <div className="mb-2 text-xs font-semibold text-[#3f3320]">
                      Add variant (need control + &ge;1 variant, allocations sum 100)
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <Input placeholder="variant_key" value={newVar.variant_key}
                        data-testid="variant-key"
                        onChange={(e) => setNewVar({ ...newVar, variant_key: e.target.value })} />
                      <Input placeholder="Name" value={newVar.name}
                        data-testid="variant-name"
                        onChange={(e) => setNewVar({ ...newVar, name: e.target.value })} />
                      <Select value={newVar.role}
                        onValueChange={(v) => setNewVar({ ...newVar, role: v })}>
                        <SelectTrigger data-testid="variant-role">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="control">control</SelectItem>
                          <SelectItem value="variant">variant</SelectItem>
                        </SelectContent>
                      </Select>
                      <Input type="number" placeholder="allocation %"
                        data-testid="variant-allocation"
                        value={newVar.allocation_pct}
                        onChange={(e) => setNewVar({ ...newVar, allocation_pct: e.target.value })} />
                    </div>
                    <Button type="button" size="sm" className="mt-2"
                      onClick={addVariant} disabled={busy}
                      data-testid="variant-add">
                      <Plus size={14} className="mr-1" /> Add variant
                    </Button>
                  </div>
                ) : null}

                {rec ? (
                  <div className="rounded-lg border border-[#eee3ca] bg-[#fbf7ee] px-3 py-2 text-xs"
                    data-testid="experiment-recommendation">
                    <div className="flex items-center gap-1 font-semibold text-[#3f3320]">
                      <Trophy size={14} className="text-[#8a6a3c]" />
                      Recommendation (advisory only — no auto-publish)
                    </div>
                    <div className="mt-1 text-[#5f5330]">
                      {rec.winner_variant_id
                        ? `Suggested winner: ${rec.winner_variant_key} (${rec.reason})`
                        : `No winner yet: ${rec.reason}`}
                    </div>
                  </div>
                ) : null}

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="text-[#8a6a3c]">
                      <tr>
                        <th className="py-1">Variant</th>
                        <th>Alloc</th>
                        <th>Assign</th>
                        <th>Exp</th>
                        <th>Conv</th>
                        <th>Rate</th>
                        <th>Rev</th>
                        <th>Lift</th>
                      </tr>
                    </thead>
                    <tbody data-testid="report-body">
                      {(report?.variants || []).map((r) => (
                        <tr key={r.variant_id} className="border-t border-[#eee3ca]"
                          data-testid="report-variant-row">
                          <td className="py-1 font-medium text-[#3f3320]">
                            {r.variant_key}
                            {r.is_control ? (
                              <Badge variant="outline" className="ml-1">control</Badge>
                            ) : null}
                          </td>
                          <td>{r.allocation_pct}%</td>
                          <td>{r.assignments}</td>
                          <td>{r.exposures}</td>
                          <td>{r.conversions}</td>
                          <td>{fmtRate(r.conversion_rate)}</td>
                          <td>{fmtNum(r.revenue)}</td>
                          <td>
                            {r.lift_vs_control === null || r.lift_vs_control === undefined
                              ? "—"
                              : `${(r.lift_vs_control * 100).toFixed(1)}%`}
                            {r.significance?.insufficient_sample
                              ? <span className="ml-1 text-[10px] text-amber-700">(low n)</span>
                              : null}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
