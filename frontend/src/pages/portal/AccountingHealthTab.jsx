import React from "react";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import {
  Wallet, TrendingUp, Landmark, Receipt, AlertCircle, CheckCircle2,
  Activity, RefreshCw, PlayCircle, ShieldCheck, Clock, HardDriveDownload,
} from "lucide-react";
import { useToast } from "../../hooks/use-toast";
import { getErrorMessage } from "../../lib/errors";

const fmt = (cents) => {
  const n = Number(cents || 0) / 100;
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

const SOURCES = [
  { key: "pos", label: "POS transactions" },
  { key: "invoices", label: "Invoices (issued)" },
  { key: "invoice_payments", label: "Invoice payments" },
  { key: "memberships", label: "Memberships" },
  { key: "inventory", label: "Inventory adjustments" },
  { key: "expenses", label: "Expenses" },
];

export default function HealthTab() {
  const { toast } = useToast();
  const [dashboard, setDashboard] = React.useState(null);
  const [validation, setValidation] = React.useState(null);
  const [runs, setRuns] = React.useState([]);
  const [selected, setSelected] = React.useState(
    SOURCES.reduce((acc, s) => ({ ...acc, [s.key]: true }), {})
  );
  const [dryRun, setDryRun] = React.useState(null);
  const [running, setRunning] = React.useState(false);
  const [loadingDry, setLoadingDry] = React.useState(false);
  const [loadingVal, setLoadingVal] = React.useState(false);

  const loadDashboard = React.useCallback(() => {
    api.get("/accounting/dashboard").then((r) => setDashboard(r.data));
  }, []);
  const loadRuns = React.useCallback(() => {
    api.get("/accounting/backfill/runs").then((r) => setRuns(r.data)).catch(() => {});
  }, []);

  React.useEffect(() => { loadDashboard(); loadRuns(); }, [loadDashboard, loadRuns]);

  const runValidation = async () => {
    setLoadingVal(true);
    try {
      const r = await api.get("/accounting/validate");
      setValidation(r.data);
    } catch (e) { toast({ title: "Validation failed", description: getErrorMessage(e) || "" }); }
    finally { setLoadingVal(false); }
  };

  const activeSources = () => Object.entries(selected).filter(([, v]) => v).map(([k]) => k);

  const runDry = async () => {
    setLoadingDry(true);
    try {
      const r = await api.post("/accounting/backfill/dry-run", { sources: activeSources() });
      setDryRun(r.data);
    } catch (e) { toast({ title: "Dry-run failed", description: getErrorMessage(e) || "" }); }
    finally { setLoadingDry(false); }
  };

  const runExecute = async () => {
    if (!window.confirm("Replay all selected sources through the event bus? Idempotent — safe to re-run.")) return;
    setRunning(true);
    try {
      const r = await api.post("/accounting/backfill/execute", { sources: activeSources() });
      toast({ title: "Backfill complete", description: `Posted ${r.data?.totals?.posted || 0} · Duplicates ${r.data?.totals?.duplicates || 0}` });
      setDryRun(null);
      loadDashboard();
      loadRuns();
    } catch (e) { toast({ title: "Backfill failed", description: getErrorMessage(e) || "" }); }
    finally { setRunning(false); }
  };

  const resumeRun = async (runId) => {
    setRunning(true);
    try {
      await api.post(`/accounting/backfill/runs/${runId}/resume`);
      toast({ title: "Run resumed" });
      loadRuns(); loadDashboard();
    } catch (e) { toast({ title: "Resume failed", description: getErrorMessage(e) || "" }); }
    finally { setRunning(false); }
  };

  return (
    <div className="mt-5 space-y-6" data-testid="accounting-health">
      {/* Health widgets */}
      <section className="grid md:grid-cols-3 lg:grid-cols-4 gap-4" data-testid="health-widgets">
        <Widget testid="widget-cash" icon={Wallet} label="Cash position" value={fmt(dashboard?.cash_position_cents)} tone="primary" />
        <Widget testid="widget-ar" icon={Receipt} label="Accounts receivable" value={fmt(dashboard?.accounts_receivable_cents)} />
        <Widget testid="widget-ap" icon={Landmark} label="Accounts payable" value={fmt(dashboard?.accounts_payable_cents)} />
        <Widget testid="widget-rev-mtd" icon={TrendingUp} label="Revenue MTD" value={fmt(dashboard?.revenue_mtd_cents)} tone="ok" />
        <Widget testid="widget-rev-today" icon={Activity} label="Revenue today" value={fmt(dashboard?.revenue_today_cents)} />
        <Widget testid="widget-sales-tax" icon={ShieldCheck} label="Sales tax liability" value={fmt(dashboard?.sales_tax_liability_cents)} />
        <Widget testid="widget-payroll-liab" icon={Clock} label="Payroll liability" value={fmt(dashboard?.payroll_liability_cents)} />
        <Widget
          testid="widget-tb"
          icon={dashboard?.trial_balance?.balanced ? CheckCircle2 : AlertCircle}
          label="Trial balance"
          value={dashboard?.trial_balance?.balanced ? "Balanced" : "OUT OF BALANCE"}
          tone={dashboard?.trial_balance?.balanced ? "ok" : "err"}
          sub={dashboard ? `DR ${fmt(dashboard.trial_balance.debit_cents)} · CR ${fmt(dashboard.trial_balance.credit_cents)}` : ""}
        />
        <Widget
          testid="widget-dead-letters"
          icon={AlertCircle}
          label="Dead-letter events"
          value={String(dashboard?.dead_letter_count ?? "—")}
          tone={dashboard?.dead_letter_count ? "warn" : "ok"}
        />
        <Widget
          testid="widget-unposted"
          icon={AlertCircle}
          label="Unposted events"
          value={String(dashboard?.unposted_event_count ?? "—")}
          sub={dashboard ? `of ${dashboard.total_event_count} total` : ""}
          tone={dashboard?.unposted_event_count ? "warn" : "ok"}
        />
      </section>

      {/* Refresh */}
      <div className="flex items-center gap-3">
        <Button variant="outline" onClick={loadDashboard} data-testid="refresh-dashboard" className="rounded-full border-[#cfe0d3] text-[#2f6a4a]">
          <RefreshCw size={13} className="mr-1" /> Refresh widgets
        </Button>
        <Button variant="outline" onClick={runValidation} disabled={loadingVal} data-testid="run-validation" className="rounded-full border-[#cfe0d3] text-[#2f6a4a]">
          <ShieldCheck size={13} className="mr-1" /> {loadingVal ? "Running…" : "Run ledger validation"}
        </Button>
      </div>

      {/* Validation report */}
      {validation && (
        <section className="rounded-2xl border border-[#e2ebe4] bg-white p-5" data-testid="validation-report">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2 text-[#3d6b52]">
              <ShieldCheck size={16} />
              <h3 className="font-display text-xl">Ledger validation</h3>
            </div>
            <Badge className={validation.healthy ? "bg-[#eaf2ec] text-[#3d6b52]" : "bg-[#fdecec] text-[#7a2a2a]"} data-testid="validation-status">
              {validation.healthy ? "Healthy" : "Attention needed"}
            </Badge>
          </div>
          <div className="grid md:grid-cols-2 gap-3">
            {Object.entries(validation.checks).map(([name, check]) => (
              <div key={name} className="rounded-xl border border-[#eef1eb] p-3" data-testid={`check-${name}`}>
                <div className="flex justify-between items-center">
                  <div className="text-sm capitalize">{name.replace(/_/g, " ")}</div>
                  <Badge className={check.ok ? "bg-[#eaf2ec] text-[#3d6b52]" : "bg-[#fdecec] text-[#7a2a2a]"}>
                    {check.ok ? "OK" : "Issue"}
                  </Badge>
                </div>
                {typeof check.count === "number" && (
                  <div className="text-xs text-slate-500 mt-1">Count: {check.count}</div>
                )}
                {name === "trial_balance" && (
                  <div className="text-xs text-slate-500 mt-1">
                    ΔDR-CR = {fmt(check.delta_cents)}
                  </div>
                )}
                {check.top_reasons?.length ? (
                  <div className="text-xs text-slate-500 mt-1">
                    Top: {check.top_reasons.slice(0, 2).map((r) => `${r.reason} (${r.count})`).join(", ")}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Backfill */}
      <section className="rounded-2xl border border-[#e2ebe4] bg-white p-5" data-testid="backfill-panel">
        <div className="flex items-center gap-2 text-[#3d6b52] mb-3">
          <HardDriveDownload size={16} />
          <h3 className="font-display text-xl">Historic backfill</h3>
        </div>
        <p className="text-sm text-slate-500 mb-4">
          Replays existing POS transactions, invoices, memberships, inventory adjustments and expenses through the accounting event bus. Idempotent — running twice never double-posts.
        </p>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mb-4">
          {SOURCES.map((s) => (
            <label key={s.key} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={!!selected[s.key]}
                onChange={(e) => setSelected({ ...selected, [s.key]: e.target.checked })}
                data-testid={`src-${s.key}`}
              />
              {s.label}
            </label>
          ))}
        </div>
        <div className="flex gap-2 flex-wrap">
          <Button onClick={runDry} disabled={loadingDry} variant="outline" className="rounded-full border-[#cfe0d3] text-[#2f6a4a]" data-testid="btn-dry-run">
            {loadingDry ? "Analysing…" : "Dry run"}
          </Button>
          <Button onClick={runExecute} disabled={running} className="rounded-full bg-[#2f6a4a] hover:bg-[#265739] text-white" data-testid="btn-execute">
            <PlayCircle size={13} className="mr-1" /> {running ? "Replaying…" : "Execute backfill"}
          </Button>
        </div>

        {dryRun && (
          <div className="mt-5 rounded-xl bg-[#f4f7f2] p-4" data-testid="dry-run-result">
            <div className="flex items-center gap-2 mb-3">
              <div className="eyebrow text-[#3d6b52]">Dry-run result</div>
              <Badge className="bg-white border border-[#cfe0d3]">
                {dryRun.totals?.candidates} candidates
              </Badge>
            </div>
            <div className="grid md:grid-cols-3 gap-2 text-sm">
              <SummaryPill label="Would post" value={dryRun.totals?.posted || 0} tone="ok" />
              <SummaryPill label="Already posted" value={dryRun.totals?.duplicates || 0} />
              <SummaryPill label="Dead-letter risk" value={dryRun.totals?.dead_letters || 0} tone={dryRun.totals?.dead_letters ? "warn" : "ok"} />
            </div>
            <table className="w-full text-xs mt-3">
              <thead className="text-slate-500 text-left">
                <tr><th>Source</th><th className="text-right">Candidates</th><th className="text-right">Would post</th><th className="text-right">Duplicates</th></tr>
              </thead>
              <tbody>
                {Object.entries(dryRun.per_source || {}).map(([s, c]) => (
                  <tr key={s} className="border-t border-[#e2ebe4]">
                    <td className="py-1 capitalize">{s.replace(/_/g, " ")}</td>
                    <td className="text-right">{c.candidates}</td>
                    <td className="text-right">{c.posted}</td>
                    <td className="text-right">{c.duplicates}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Run history */}
      <section className="rounded-2xl border border-[#e2ebe4] bg-white overflow-hidden" data-testid="backfill-history">
        <div className="p-4 bg-[#f4f7f2] flex items-center justify-between">
          <div className="eyebrow text-[#3d6b52]">Backfill history</div>
          <Button size="sm" variant="ghost" onClick={loadRuns} className="text-[#2f6a4a]">
            <RefreshCw size={12} className="mr-1" /> Refresh
          </Button>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-white text-xs uppercase text-slate-500">
            <tr>
              <th className="p-3 text-left">Started</th>
              <th className="p-3 text-left">Sources</th>
              <th className="p-3">Status</th>
              <th className="p-3 text-right">Posted</th>
              <th className="p-3 text-right">Dup</th>
              <th className="p-3"></th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id} className="border-t border-[#e2ebe4]" data-testid={`run-${r.id}`}>
                <td className="p-3 text-xs">{new Date(r.started_at).toLocaleString()}</td>
                <td className="p-3 text-xs">{(r.sources || []).join(", ")}</td>
                <td className="p-3 text-center text-xs">
                  <Badge className={
                    r.status === "completed" ? "bg-[#eaf2ec] text-[#3d6b52]" :
                    r.status === "failed" ? "bg-[#fdecec] text-[#7a2a2a]" :
                    "bg-[#fff7e6] text-[#8a6d3b]"
                  }>{r.status}</Badge>
                </td>
                <td className="p-3 text-right">{r.totals?.posted || 0}</td>
                <td className="p-3 text-right">{r.totals?.duplicates || 0}</td>
                <td className="p-3 text-right">
                  {r.status !== "completed" && (
                    <Button size="sm" variant="outline" onClick={() => resumeRun(r.id)} className="h-7 rounded-full">
                      Resume
                    </Button>
                  )}
                </td>
              </tr>
            ))}
            {runs.length === 0 && (
              <tr><td colSpan={6} className="p-6 text-center text-slate-400 text-sm">No backfill runs yet.</td></tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function Widget({ icon: Icon, label, value, sub, tone, testid }) {
  const toneClass =
    tone === "err" ? "border-[#f4c9c9] bg-[#fdf5f5]" :
    tone === "warn" ? "border-[#eddfba] bg-[#fdf9ef]" :
    tone === "ok" ? "border-[#cfe0d3] bg-[#f6faf7]" :
    tone === "primary" ? "border-[#cfe0d3] bg-white" :
    "border-[#e2ebe4] bg-white";
  return (
    <div className={`rounded-2xl border p-4 ${toneClass}`} data-testid={testid}>
      <div className="flex items-center gap-2 text-[#3d6b52] mb-2">
        <Icon size={14} />
        <div className="eyebrow">{label}</div>
      </div>
      <div className="font-display text-2xl">{value ?? "—"}</div>
      {sub && <div className="text-xs text-slate-500 mt-1">{sub}</div>}
    </div>
  );
}

function SummaryPill({ label, value, tone }) {
  const cls =
    tone === "ok" ? "bg-[#eaf2ec] text-[#3d6b52]" :
    tone === "warn" ? "bg-[#fdf9ef] text-[#8a6d3b]" :
    "bg-white border border-[#e2ebe4]";
  return (
    <div className={`rounded-xl px-3 py-2 ${cls}`}>
      <div className="text-xs uppercase tracking-wide opacity-70">{label}</div>
      <div className="font-display text-xl">{value}</div>
    </div>
  );
}
