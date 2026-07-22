import React from "react";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Textarea } from "../../components/ui/textarea";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "../../components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "../../components/ui/dialog";
import {
  Landmark, Wallet, ArrowRightLeft, Upload, RefreshCw, CheckCircle2,
  AlertCircle, FileSpreadsheet, Link2, Unlink, Split,
} from "lucide-react";
import { useToast } from "../../hooks/use-toast";
import { getErrorMessage } from "../../lib/errors";

const fmt = (cents) => {
  const n = Number(cents || 0) / 100;
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

export default function BankingTab({ initialSubtab }) {
  const [subtab, setSubtab] = React.useState(initialSubtab || "dashboard");
  React.useEffect(() => {
    if (initialSubtab) setSubtab(initialSubtab);
  }, [initialSubtab]);
  return (
    <div className="mt-5" data-testid="banking-tab">
      <div className="flex flex-wrap gap-2 mb-4 border-b border-[#e2ebe4] pb-3">
        {[
          { k: "dashboard", label: "Cash Dashboard", icon: Wallet },
          { k: "accounts", label: "Bank Accounts", icon: Landmark },
          { k: "reconcile", label: "Reconciliation", icon: RefreshCw },
          { k: "exceptions", label: "Exceptions", icon: AlertCircle },
          { k: "transfers", label: "Transfers", icon: ArrowRightLeft },
          { k: "reports", label: "Reports", icon: FileSpreadsheet },
        ].map(({ k, label, icon: Icon }) => (
          <Button
            key={k} size="sm"
            variant={subtab === k ? "default" : "outline"}
            onClick={() => setSubtab(k)}
            data-testid={`banking-sub-${k}`}
            className={subtab === k ? "bg-[#2f6a4a] hover:bg-[#265739] text-white rounded-full" : "rounded-full border-[#cfe0d3] text-[#2f6a4a]"}
          >
            <Icon size={12} className="mr-1" /> {label}
          </Button>
        ))}
      </div>
      {subtab === "dashboard" && <CashDashboardPane />}
      {subtab === "accounts" && <BankAccountsPane />}
      {subtab === "reconcile" && <ReconciliationPane />}
      {subtab === "exceptions" && <ExceptionsPane />}
      {subtab === "transfers" && <TransfersPane />}
      {subtab === "reports" && <ReportsPane />}
    </div>
  );
}

/* ------------------------------------------------------------------ dashboard */
function CashDashboardPane() {
  const [data, setData] = React.useState(null);
  const load = () => api.get("/accounting/cash/dashboard").then((r) => setData(r.data || null)).catch(() => {});
  React.useEffect(() => { load(); }, []);
  if (!data || !data.totals) return <div className="text-slate-500 text-sm">Loading…</div>;
  const t = data.totals;
  const accounts = Array.isArray(data.accounts) ? data.accounts : [];
  return (
    <div className="space-y-5" data-testid="cash-dashboard">
      <div className="grid md:grid-cols-4 gap-4">
        <Widget label="Current cash" value={fmt(t.current_cash_cents)} tone="primary" />
        <Widget label="Cleared cash" value={fmt(t.cleared_cash_cents)} tone="ok" />
        <Widget label="Outstanding deposits" value={fmt(t.outstanding_deposits_cents)} />
        <Widget label="Outstanding checks" value={fmt(t.outstanding_checks_cents)} />
      </div>
      <div className="rounded-2xl border border-[#e2ebe4] bg-white overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-[#f4f7f2] text-xs uppercase text-slate-500">
            <tr>
              <th className="p-3 text-left">Account</th>
              <th className="p-3 text-left">Kind</th>
              <th className="p-3 text-right">Ledger</th>
              <th className="p-3 text-right">Cleared</th>
              <th className="p-3 text-right">Out. deposits</th>
              <th className="p-3 text-right">Out. checks</th>
              <th className="p-3 text-right">Bank stmt</th>
              <th className="p-3 text-right">Difference</th>
              <th className="p-3 text-xs">Last recon</th>
            </tr>
          </thead>
          <tbody>
            {accounts.map((a) => (
              <tr key={a.id} className="border-t border-[#e2ebe4]" data-testid={`cash-row-${a.id}`}>
                <td className="p-3">{a.name} <span className="text-xs text-slate-400 font-mono">· {a.gl_code}</span></td>
                <td className="p-3 text-xs uppercase text-slate-500">{a.kind}</td>
                <td className="p-3 text-right">{fmt(a.ledger_balance_cents)}</td>
                <td className="p-3 text-right">{fmt(a.cleared_balance_cents)}</td>
                <td className="p-3 text-right text-xs">{fmt(a.outstanding_deposits_cents)}</td>
                <td className="p-3 text-right text-xs">{fmt(a.outstanding_checks_cents)}</td>
                <td className="p-3 text-right">{fmt(a.bank_balance_cents)}</td>
                <td className={`p-3 text-right ${a.difference_cents === 0 ? "text-[#3d6b52]" : "text-[#7a2a2a]"}`}>{fmt(a.difference_cents)}</td>
                <td className="p-3 text-xs">{a.last_reconciled_at ? new Date(a.last_reconciled_at).toLocaleDateString() : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ accounts */
function BankAccountsPane() {
  const { toast } = useToast();
  const [rows, setRows] = React.useState([]);
  const [coa, setCoa] = React.useState([]);
  const [showNew, setShowNew] = React.useState(false);
  const [form, setForm] = React.useState({ name: "", kind: "checking", gl_account_code: "", institution: "", last_four: "" });
  const load = () => api.get("/accounting/bank-accounts", { params: { include_inactive: true } }).then((r) => setRows(Array.isArray(r.data) ? r.data : [])).catch(() => {});
  React.useEffect(() => { load(); api.get("/accounting/accounts").then((r) => setCoa(Array.isArray(r.data) ? r.data : [])).catch(() => {}); }, []);
  const save = async () => {
    try {
      await api.post("/accounting/bank-accounts", form);
      toast({ title: "Bank account created" });
      setShowNew(false); setForm({ name: "", kind: "checking", gl_account_code: "", institution: "", last_four: "" });
      load();
    } catch (e) { toast({ title: "Failed", description: getErrorMessage(e) || "" }); }
  };
  const patch = async (id, changes) => {
    await api.patch(`/accounting/bank-accounts/${id}`, changes);
    load();
  };
  return (
    <div data-testid="bank-accounts">
      <div className="flex justify-end mb-3">
        <Button onClick={() => setShowNew(true)} className="rounded-full bg-[#2f6a4a] hover:bg-[#265739] text-white" data-testid="new-bank-account">+ New bank account</Button>
      </div>
      <div className="rounded-2xl border border-[#e2ebe4] bg-white overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-[#f4f7f2] text-xs uppercase text-slate-500">
            <tr>
              <th className="p-3 text-left">Name</th>
              <th className="p-3">Kind</th>
              <th className="p-3">GL code</th>
              <th className="p-3">Institution</th>
              <th className="p-3">Last 4</th>
              <th className="p-3">Seeded</th>
              <th className="p-3">Active</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-[#e2ebe4]" data-testid={`ba-row-${r.id}`}>
                <td className="p-3 font-medium">{r.name}</td>
                <td className="p-3 text-xs uppercase text-slate-500">{r.kind}</td>
                <td className="p-3 font-mono text-xs">{r.gl_account_code}</td>
                <td className="p-3 text-xs">{r.institution || "—"}</td>
                <td className="p-3 text-xs font-mono">{r.last_four || "—"}</td>
                <td className="p-3 text-xs">{r.system_seeded ? "Yes" : "—"}</td>
                <td className="p-3">
                  <Button size="sm" variant="outline" className="h-7 rounded-full" onClick={() => patch(r.id, { active: !r.active })}>
                    {r.active ? "Active" : "Inactive"}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Dialog open={showNew} onOpenChange={setShowNew}>
        <DialogContent className="bg-white">
          <DialogHeader><DialogTitle className="font-display text-2xl">New bank account</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label>Name</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="ba-name" /></div>
            <div><Label>Kind</Label>
              <Select value={form.kind} onValueChange={(v) => setForm({ ...form, kind: v })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="checking">Checking</SelectItem>
                  <SelectItem value="savings">Savings</SelectItem>
                  <SelectItem value="payroll">Payroll</SelectItem>
                  <SelectItem value="petty_cash">Petty cash</SelectItem>
                  <SelectItem value="credit_card">Credit card</SelectItem>
                  <SelectItem value="merchant_clearing">Merchant clearing</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div><Label>GL account</Label>
              <Select value={form.gl_account_code} onValueChange={(v) => setForm({ ...form, gl_account_code: v })}>
                <SelectTrigger><SelectValue placeholder="Pick a chart-of-accounts code" /></SelectTrigger>
                <SelectContent>
                  {coa.filter((a) => ["asset", "liability"].includes(a.type)).map((a) => (
                    <SelectItem key={a.code} value={a.code}>{a.code} · {a.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div><Label>Institution</Label><Input value={form.institution} onChange={(e) => setForm({ ...form, institution: e.target.value })} /></div>
            <div><Label>Last 4</Label><Input value={form.last_four} maxLength={4} onChange={(e) => setForm({ ...form, last_four: e.target.value })} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowNew(false)}>Cancel</Button>
            <Button onClick={save} className="bg-[#2f6a4a] hover:bg-[#265739] text-white rounded-full" data-testid="ba-save">Create</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/* ------------------------------------------------------------------ reconciliation */
function ReconciliationPane() {
  const { toast } = useToast();
  const [accounts, setAccounts] = React.useState([]);
  const [selected, setSelected] = React.useState("");
  const [ws, setWs] = React.useState(null);
  const [proposals, setProposals] = React.useState([]);
  const [busy, setBusy] = React.useState(false);
  const [finalize, setFinalize] = React.useState({ statement_end_date: "", ending_balance: "", notes: "" });
  const fileRef = React.useRef(null);

  React.useEffect(() => {
    api.get("/accounting/bank-accounts").then((r) => {
      const list = Array.isArray(r.data) ? r.data : [];
      setAccounts(list);
      if (list[0]) setSelected(list[0].id);
    }).catch(() => {});
  }, []);

  const loadWs = React.useCallback(() => {
    if (!selected) return;
    api.get(`/accounting/reconciliation/${selected}/workspace`).then((r) => setWs(r.data)).catch(() => {});
  }, [selected]);
  React.useEffect(loadWs, [loadWs]);

  const upload = async (file) => {
    if (!file || !selected) return;
    const fd = new FormData(); fd.append("file", file);
    try {
      const r = await api.post(`/accounting/bank-accounts/${selected}/import`, fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast({ title: "Statement imported", description: `${r.data.row_count_new} new · ${r.data.row_count_duplicate} duplicates` });
      loadWs();
    } catch (e) { toast({ title: "Import failed", description: getErrorMessage(e) || "" }); }
  };

  const runAutoMatch = async () => {
    setBusy(true);
    try {
      const r = await api.post(`/accounting/reconciliation/${selected}/auto-match`);
      setProposals(r.data.proposals || []);
      toast({ title: `${r.data.proposals?.length || 0} proposals` });
    } catch (e) { toast({ title: "Auto-match failed", description: getErrorMessage(e) || "" }); }
    finally { setBusy(false); }
  };

  const confirmProposals = async () => {
    if (!proposals.length) return;
    try {
      const r = await api.post(`/accounting/reconciliation/confirm-matches`, { proposals });
      toast({ title: `Matched ${r.data.matched} (${r.data.skipped} skipped)` });
      setProposals([]); loadWs();
    } catch (e) { toast({ title: "Confirm failed", description: getErrorMessage(e) || "" }); }
  };

  const manualMatch = async (btId, jeId) => {
    try {
      await api.post(`/accounting/reconciliation/match`, { bank_transaction_id: btId, journal_entry_id: jeId });
      loadWs();
    } catch (e) { toast({ title: "Match failed", description: getErrorMessage(e) || "" }); }
  };

  const unmatch = async (btId) => {
    await api.post(`/accounting/reconciliation/unmatch/${btId}`);
    loadWs();
  };

  const doFinalize = async () => {
    if (!finalize.statement_end_date || finalize.ending_balance === "") {
      return toast({ title: "Enter statement date + balance" });
    }
    try {
      await api.post(`/accounting/reconciliation/finalize`, {
        bank_account_id: selected,
        statement_end_date: new Date(finalize.statement_end_date).toISOString(),
        ending_balance_cents: Math.round(Number(finalize.ending_balance) * 100),
        notes: finalize.notes,
      });
      toast({ title: "Reconciliation finalized" });
      setFinalize({ statement_end_date: "", ending_balance: "", notes: "" });
      loadWs();
    } catch (e) { toast({ title: "Finalize failed", description: getErrorMessage(e) || "" }); }
  };

  return (
    <div className="space-y-4" data-testid="recon-pane">
      <div className="flex flex-wrap gap-3 items-end">
        <div className="w-[280px]">
          <Label>Bank account</Label>
          <Select value={selected} onValueChange={setSelected}>
            <SelectTrigger data-testid="recon-account-select"><SelectValue /></SelectTrigger>
            <SelectContent>
              {accounts.map((a) => <SelectItem key={a.id} value={a.id}>{a.name} · {a.gl_account_code}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <input type="file" ref={fileRef} accept=".csv,.ofx,.qfx" className="hidden" onChange={(e) => upload(e.target.files?.[0])} data-testid="recon-file-input" />
        <Button variant="outline" onClick={() => fileRef.current?.click()} className="rounded-full border-[#cfe0d3] text-[#2f6a4a]" data-testid="recon-import-btn">
          <Upload size={13} className="mr-1" /> Import statement (CSV / OFX)
        </Button>
        <Button variant="outline" onClick={runAutoMatch} disabled={busy || !selected} className="rounded-full border-[#cfe0d3] text-[#2f6a4a]" data-testid="recon-automatch-btn">
          {busy ? "Matching…" : "Auto-match"}
        </Button>
      </div>

      {proposals.length > 0 && (
        <div className="rounded-2xl border border-[#eddfba] bg-[#fdf9ef] p-4" data-testid="recon-proposals">
          <div className="flex justify-between mb-2">
            <div className="eyebrow text-[#8a6d3b]">{proposals.length} proposed match{proposals.length > 1 ? "es" : ""}</div>
            <Button size="sm" onClick={confirmProposals} className="bg-[#2f6a4a] hover:bg-[#265739] text-white rounded-full">Confirm all</Button>
          </div>
          <table className="w-full text-xs">
            <thead className="text-slate-500 text-left">
              <tr><th>Bank txn</th><th>Journal memo</th><th className="text-right">Amount</th><th className="text-right">Confidence</th></tr>
            </thead>
            <tbody>
              {proposals.map((p) => (
                <tr key={p.bank_transaction_id} className="border-t border-[#eddfba]">
                  <td className="py-1">{new Date(p.bank_posted_at).toLocaleDateString()} · {p.description}</td>
                  <td>{p.memo}</td>
                  <td className="text-right">{fmt(p.bank_amount_cents)}</td>
                  <td className="text-right"><Badge className="bg-white border">{p.confidence}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {ws && ws.counts && (
        <div className="grid md:grid-cols-2 gap-4">
          <div className="rounded-2xl border border-[#e2ebe4] bg-white p-4" data-testid="recon-bank-side">
            <div className="flex justify-between mb-2">
              <div className="eyebrow text-[#3d6b52]">Bank transactions</div>
              <Badge className="bg-[#f4f7f2] text-[#3d6b52]">{ws.counts.bank_unmatched} unmatched</Badge>
            </div>
            <div className="max-h-[400px] overflow-y-auto">
              <table className="w-full text-xs">
                <tbody>
                  {(ws.bank_transactions || []).slice(0, 100).map((bt) => (
                    <tr key={bt.id} className="border-t border-[#eef1eb]" data-testid={`bt-${bt.id}`}>
                      <td className="py-1">{new Date(bt.posted_at).toLocaleDateString()}</td>
                      <td className="truncate max-w-[200px]" title={bt.description}>{bt.description}</td>
                      <td className={`text-right ${bt.amount_cents < 0 ? "text-[#7a2a2a]" : "text-[#3d6b52]"}`}>{fmt(bt.amount_cents)}</td>
                      <td className="text-center">
                        {bt.status === "unmatched" && <Link2 size={12} className="text-slate-400" />}
                        {bt.status === "matched" && <CheckCircle2 size={12} className="text-[#3d6b52]" />}
                        {bt.status === "reconciled" && <CheckCircle2 size={12} className="text-[#3d6b52]" />}
                        {bt.status === "split" && <Split size={12} className="text-[#3d6b52]" />}
                      </td>
                      <td>
                        {(bt.status === "matched" || bt.status === "split") && (
                          <Button size="sm" variant="ghost" className="h-6 p-1" onClick={() => unmatch(bt.id)} title="Unmatch">
                            <Unlink size={11} />
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div className="rounded-2xl border border-[#e2ebe4] bg-white p-4" data-testid="recon-ledger-side">
            <div className="flex justify-between mb-2">
              <div className="eyebrow text-[#3d6b52]">Journal entries</div>
              <Badge className="bg-[#f4f7f2] text-[#3d6b52]">{ws.counts.journal_unreconciled} to clear</Badge>
            </div>
            <div className="max-h-[400px] overflow-y-auto">
              <table className="w-full text-xs">
                <tbody>
                  {(ws.journal_entries || []).slice(0, 100).map((je) => (
                    <tr key={je.id} className="border-t border-[#eef1eb]" data-testid={`je-${je.id}`}>
                      <td className="py-1">{new Date(je.posted_at).toLocaleDateString()}</td>
                      <td className="truncate max-w-[220px]" title={je.memo}>{je.memo}</td>
                      <td className={`text-right ${(je.bank_amount_cents || 0) < 0 ? "text-[#7a2a2a]" : "text-[#3d6b52]"}`}>{fmt(je.bank_amount_cents)}</td>
                      <td className="text-center">
                        {je.reconciliation_id ? <CheckCircle2 size={12} className="text-[#3d6b52]" /> : <Link2 size={12} className="text-slate-400" />}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Finalize block */}
      <div className="rounded-2xl border border-[#e2ebe4] bg-white p-4">
        <div className="eyebrow text-[#3d6b52] mb-3">Finalize reconciliation</div>
        <div className="grid md:grid-cols-4 gap-3 items-end">
          <div><Label className="text-xs">Statement end date</Label><Input type="date" value={finalize.statement_end_date} onChange={(e) => setFinalize({ ...finalize, statement_end_date: e.target.value })} data-testid="finalize-date" /></div>
          <div><Label className="text-xs">Ending balance</Label><Input type="number" placeholder="0.00" value={finalize.ending_balance} onChange={(e) => setFinalize({ ...finalize, ending_balance: e.target.value })} data-testid="finalize-balance" /></div>
          <div className="md:col-span-2"><Label className="text-xs">Notes</Label><Input value={finalize.notes} onChange={(e) => setFinalize({ ...finalize, notes: e.target.value })} /></div>
          <Button onClick={doFinalize} className="bg-[#2f6a4a] hover:bg-[#265739] text-white rounded-full" data-testid="finalize-btn">
            <CheckCircle2 size={13} className="mr-1" /> Finalize
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ exceptions */
function ExceptionsPane() {
  const [data, setData] = React.useState(null);
  React.useEffect(() => { api.get("/accounting/reconciliation/exceptions").then((r) => setData(r.data || null)).catch(() => {}); }, []);
  if (!data || !data.counts) return <div className="text-slate-500 text-sm">Loading…</div>;
  const c = data.counts;
  return (
    <div className="space-y-4" data-testid="exceptions-pane">
      <div className="grid md:grid-cols-3 gap-3">
        <ExceptionCard label="Unmatched bank txns" value={c.unmatched_bank_transactions} tone={c.unmatched_bank_transactions ? "warn" : "ok"} />
        <ExceptionCard label="Unmatched ledger entries" value={c.unmatched_ledger_entries} tone={c.unmatched_ledger_entries ? "warn" : "ok"} />
        <ExceptionCard label="Duplicate bank imports" value={c.duplicate_bank_imports} tone={c.duplicate_bank_imports ? "err" : "ok"} />
        <ExceptionCard label="Amount mismatches" value={c.amount_mismatches} tone={c.amount_mismatches ? "warn" : "ok"} />
        <ExceptionCard label="Date mismatches" value={c.date_mismatches} tone={c.date_mismatches ? "warn" : "ok"} />
        <ExceptionCard label="Duplicate journal entries" value={c.duplicate_ledger_entries} tone={c.duplicate_ledger_entries ? "err" : "ok"} />
      </div>
      {data.amount_mismatches?.length > 0 && (
        <div className="rounded-2xl border border-[#eddfba] bg-[#fdf9ef] p-4">
          <div className="eyebrow text-[#8a6d3b] mb-2">Amount mismatches (bank vs ledger)</div>
          <table className="w-full text-xs">
            <thead className="text-slate-500 text-left"><tr><th>Bank txn</th><th className="text-right">Bank</th><th className="text-right">Ledger</th></tr></thead>
            <tbody>
              {data.amount_mismatches.slice(0, 20).map((m, i) => (
                <tr key={i} className="border-t border-[#eddfba]">
                  <td className="py-1">{new Date(m.posted_at).toLocaleDateString()}</td>
                  <td className="text-right">{fmt(m.bank_amount_cents)}</td>
                  <td className="text-right">{fmt(m.ledger_amount_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ExceptionCard({ label, value, tone }) {
  const c = tone === "err" ? "border-[#f4c9c9] bg-[#fdf5f5] text-[#7a2a2a]" :
            tone === "warn" ? "border-[#eddfba] bg-[#fdf9ef] text-[#8a6d3b]" :
            "border-[#cfe0d3] bg-[#f6faf7] text-[#3d6b52]";
  return (
    <div className={`rounded-2xl border p-4 ${c}`}>
      <div className="eyebrow">{label}</div>
      <div className="font-display text-3xl mt-1">{value}</div>
    </div>
  );
}

/* ------------------------------------------------------------------ transfers */
function TransfersPane() {
  const { toast } = useToast();
  const [accts, setAccts] = React.useState([]);
  const [rows, setRows] = React.useState([]);
  const [form, setForm] = React.useState({ from_bank_account_id: "", to_bank_account_id: "", amount: "", memo: "" });
  const load = () => {
    api.get("/accounting/bank-accounts").then((r) => setAccts(Array.isArray(r.data) ? r.data : [])).catch(() => {});
    api.get("/accounting/transfers").then((r) => setRows(Array.isArray(r.data) ? r.data : [])).catch(() => {});
  };
  React.useEffect(load, []);
  const submit = async () => {
    try {
      await api.post("/accounting/transfers", {
        from_bank_account_id: form.from_bank_account_id,
        to_bank_account_id: form.to_bank_account_id,
        amount_cents: Math.round(Number(form.amount) * 100),
        memo: form.memo,
      });
      toast({ title: "Transfer recorded" });
      setForm({ from_bank_account_id: "", to_bank_account_id: "", amount: "", memo: "" });
      load();
    } catch (e) { toast({ title: "Failed", description: getErrorMessage(e) || "" }); }
  };
  return (
    <div className="grid md:grid-cols-2 gap-5" data-testid="transfers-pane">
      <div className="rounded-2xl border border-[#e2ebe4] bg-white p-5">
        <h3 className="font-display text-xl mb-3">New transfer</h3>
        <div className="space-y-3">
          <div><Label>From</Label>
            <Select value={form.from_bank_account_id} onValueChange={(v) => setForm({ ...form, from_bank_account_id: v })}>
              <SelectTrigger data-testid="transfer-from"><SelectValue placeholder="Source account" /></SelectTrigger>
              <SelectContent>{accts.map((a) => <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div><Label>To</Label>
            <Select value={form.to_bank_account_id} onValueChange={(v) => setForm({ ...form, to_bank_account_id: v })}>
              <SelectTrigger data-testid="transfer-to"><SelectValue placeholder="Destination account" /></SelectTrigger>
              <SelectContent>{accts.map((a) => <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div><Label>Amount</Label><Input type="number" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} data-testid="transfer-amount" /></div>
          <div><Label>Memo</Label><Textarea rows={2} value={form.memo} onChange={(e) => setForm({ ...form, memo: e.target.value })} /></div>
          <Button onClick={submit} className="bg-[#2f6a4a] hover:bg-[#265739] text-white rounded-full" data-testid="transfer-submit">
            <ArrowRightLeft size={13} className="mr-1" /> Record transfer
          </Button>
        </div>
      </div>
      <div className="rounded-2xl border border-[#e2ebe4] bg-white overflow-hidden">
        <div className="p-4 bg-[#f4f7f2] eyebrow text-[#3d6b52]">Recent transfers</div>
        <table className="w-full text-sm">
          <tbody>
            {rows.map((r) => {
              const src = accts.find((a) => a.id === r.from_bank_account_id)?.name || "—";
              const dst = accts.find((a) => a.id === r.to_bank_account_id)?.name || "—";
              return (
                <tr key={r.id} className="border-t border-[#e2ebe4]">
                  <td className="p-3 text-xs">{new Date(r.created_at).toLocaleDateString()}</td>
                  <td className="p-3 text-xs">{src} → {dst}</td>
                  <td className="p-3 text-xs">{r.memo || "—"}</td>
                  <td className="p-3 text-right">{fmt(r.amount_cents)}</td>
                </tr>
              );
            })}
            {rows.length === 0 && <tr><td colSpan={4} className="p-6 text-center text-slate-400">No transfers.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ reports */
function ReportsPane() {
  const [outRec, setOutRec] = React.useState(null);
  const [flow, setFlow] = React.useState(null);
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), 1).toISOString();
  const end = now.toISOString();
  React.useEffect(() => {
    api.get("/accounting/cash/outstanding-reconciliation").then((r) => setOutRec(r.data || null)).catch(() => {});
    api.get("/accounting/cash/flow", { params: { start, end } }).then((r) => setFlow(r.data || null)).catch(() => {});
  }, [start, end]);
  return (
    <div className="grid md:grid-cols-2 gap-4" data-testid="banking-reports">
      <div className="rounded-2xl border border-[#e2ebe4] bg-white p-4">
        <div className="eyebrow text-[#3d6b52] mb-2">Cash flow (MTD)</div>
        {flow && flow.totals ? (
          <>
            <Row label="Inflow" value={fmt(flow.totals.inflow_cents)} />
            <Row label="Outflow" value={fmt(flow.totals.outflow_cents)} />
            <Row label="Net" value={fmt(flow.totals.net_cents)} strong />
          </>
        ) : <div className="text-slate-500 text-sm">Loading…</div>}
      </div>
      <div className="rounded-2xl border border-[#e2ebe4] bg-white p-4">
        <div className="eyebrow text-[#3d6b52] mb-2">Outstanding reconciliation</div>
        {outRec && outRec.totals ? (
          <>
            <Row label="Unmatched bank" value={fmt(outRec.totals.unmatched_bank_cents)} />
            <Row label="Unmatched ledger" value={fmt(outRec.totals.unmatched_ledger_cents)} />
            <div className="mt-3 text-xs text-slate-500">Per-account breakdown available via /api/accounting/cash/outstanding-reconciliation</div>
          </>
        ) : <div className="text-slate-500 text-sm">Loading…</div>}
      </div>
    </div>
  );
}

function Widget({ label, value, sub, tone }) {
  const c = tone === "ok" ? "border-[#cfe0d3] bg-[#f6faf7]" :
            tone === "primary" ? "border-[#cfe0d3] bg-white" :
            "border-[#e2ebe4] bg-white";
  return (
    <div className={`rounded-2xl border p-4 ${c}`}>
      <div className="eyebrow text-[#3d6b52]">{label}</div>
      <div className="font-display text-2xl mt-1">{value ?? "—"}</div>
      {sub && <div className="text-xs text-slate-500 mt-1">{sub}</div>}
    </div>
  );
}

function Row({ label, value, strong }) {
  return (
    <div className={`flex justify-between py-1 ${strong ? "border-t border-[#e2ebe4] pt-2 font-semibold" : ""}`}>
      <span>{label}</span><span>{value}</span>
    </div>
  );
}
