import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Textarea } from "../../components/ui/textarea";
import {
  Tabs, TabsList, TabsTrigger, TabsContent,
} from "../../components/ui/tabs";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "../../components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "../../components/ui/dialog";
import {
  BookText, Receipt, Users, Wallet, Landmark, FileText, Download,
  Percent, ClipboardList, ChevronRight,
} from "lucide-react";
import { useToast } from "../../hooks/use-toast";
import { getErrorMessage } from "../../lib/errors";

const fmt = (cents) => `$${(Number(cents || 0) / 100).toFixed(2)}`;

/** Consolidated admin Accounting workspace. */
export default function Accounting() {
  return (
    <PortalLayout>
      <PortalHeader
        title="Accounting"
        subtitle="Chart of Accounts · Journal · General Ledger · Reports · Vendors · Payroll · Tax · 1099"
      />
      <Tabs defaultValue="reports" className="w-full">
        <TabsList className="bg-[#f4f7f2] border border-[#e2ebe4] flex flex-wrap gap-1 h-auto p-1" data-testid="accounting-tabs">
          <TabsTrigger value="reports" data-testid="tab-reports">Reports</TabsTrigger>
          <TabsTrigger value="journal" data-testid="tab-journal">Journal</TabsTrigger>
          <TabsTrigger value="gl" data-testid="tab-gl">General Ledger</TabsTrigger>
          <TabsTrigger value="coa" data-testid="tab-coa">Chart of Accounts</TabsTrigger>
          <TabsTrigger value="expenses" data-testid="tab-expenses">Expenses</TabsTrigger>
          <TabsTrigger value="vendors" data-testid="tab-vendors">Vendors &amp; Bills</TabsTrigger>
          <TabsTrigger value="payroll" data-testid="tab-payroll">Payroll</TabsTrigger>
          <TabsTrigger value="tax" data-testid="tab-tax">Tax</TabsTrigger>
          <TabsTrigger value="1099" data-testid="tab-1099">1099</TabsTrigger>
        </TabsList>
        <TabsContent value="reports"><ReportsTab /></TabsContent>
        <TabsContent value="journal"><JournalTab /></TabsContent>
        <TabsContent value="gl"><GeneralLedgerTab /></TabsContent>
        <TabsContent value="coa"><CoATab /></TabsContent>
        <TabsContent value="expenses"><ExpensesTab /></TabsContent>
        <TabsContent value="vendors"><VendorsBillsTab /></TabsContent>
        <TabsContent value="payroll"><PayrollTab /></TabsContent>
        <TabsContent value="tax"><TaxTab /></TabsContent>
        <TabsContent value="1099"><OneOhNineNineTab /></TabsContent>
      </Tabs>
    </PortalLayout>
  );
}

/* ---------------- Reports ---------------- */
function ReportsTab() {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), 1).toISOString();
  const end = now.toISOString();
  const [pl, setPl] = React.useState(null);
  const [bs, setBs] = React.useState(null);
  const [tb, setTb] = React.useState(null);
  const [ar, setAr] = React.useState(null);

  React.useEffect(() => {
    api.get("/accounting/reports/profit-and-loss", { params: { start, end } }).then((r) => setPl(r.data));
    api.get("/accounting/reports/balance-sheet", { params: { as_of: end } }).then((r) => setBs(r.data));
    api.get("/accounting/reports/trial-balance").then((r) => setTb(r.data));
    api.get("/accounting/reports/ar-aging").then((r) => setAr(r.data));
  }, [start, end]);

  return (
    <div className="grid md:grid-cols-2 gap-5 mt-5" data-testid="reports-grid">
      <Card title="Profit & Loss (Month to date)" icon={FileText}>
        {pl && (
          <>
            <Row label="Revenue" value={fmt(pl.total_revenue_cents)} strong />
            <Row label="COGS" value={fmt(pl.total_cogs_cents)} />
            <Row label="Gross profit" value={fmt(pl.gross_profit_cents)} />
            <Row label="Expenses" value={fmt(pl.total_expenses_cents)} />
            <Row label="Net income" value={fmt(pl.net_income_cents)} strong accent />
          </>
        )}
      </Card>
      <Card title="Balance Sheet" icon={Landmark} badge={bs?.balanced ? "Balanced" : "OUT OF BALANCE"} badgeTone={bs?.balanced ? "ok" : "err"}>
        {bs && (
          <>
            <Row label="Total assets" value={fmt(bs.total_assets_cents)} strong />
            <Row label="Total liabilities" value={fmt(bs.total_liabilities_cents)} />
            <Row label="Equity + retained" value={fmt(bs.total_equity_cents + bs.current_period_net_income_cents)} />
            <Row label="Liab + Equity" value={fmt(bs.total_liab_and_equity_cents)} strong />
          </>
        )}
      </Card>
      <Card title="Trial Balance" icon={BookText} badge={tb?.balanced ? "Balanced" : "OUT OF BALANCE"} badgeTone={tb?.balanced ? "ok" : "err"}>
        {tb && (
          <div className="max-h-64 overflow-y-auto text-xs">
            <table className="w-full">
              <thead className="text-slate-500"><tr><th className="text-left">Account</th><th className="text-right">Debit</th><th className="text-right">Credit</th></tr></thead>
              <tbody>
                {tb.rows.map((r) => (
                  <tr key={r.code} className="border-t border-[#eef1eb]">
                    <td className="py-1">{r.code} · {r.name}</td>
                    <td className="text-right">{fmt(r.debit_cents)}</td>
                    <td className="text-right">{fmt(r.credit_cents)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot className="font-semibold border-t"><tr><td>Totals</td><td className="text-right">{fmt(tb.total_debit_cents)}</td><td className="text-right">{fmt(tb.total_credit_cents)}</td></tr></tfoot>
            </table>
          </div>
        )}
      </Card>
      <Card title="A/R Aging" icon={ClipboardList}>
        {ar && (
          <>
            <Row label="Current" value={fmt(ar.buckets.current)} />
            <Row label="1-30 days" value={fmt(ar.buckets["1_30"])} />
            <Row label="31-60 days" value={fmt(ar.buckets["31_60"])} />
            <Row label="61-90 days" value={fmt(ar.buckets["61_90"])} />
            <Row label="Over 90 days" value={fmt(ar.buckets.over_90)} accent />
            <Row label="Total outstanding" value={fmt(ar.total_cents)} strong />
          </>
        )}
      </Card>
    </div>
  );
}

/* ---------------- Journal ---------------- */
function JournalTab() {
  const { toast } = useToast();
  const [entries, setEntries] = React.useState([]);
  const [showManual, setShowManual] = React.useState(false);
  const load = React.useCallback(() => api.get("/accounting/journal").then((r) => setEntries(r.data)), []);
  React.useEffect(() => { load(); }, [load]);
  return (
    <div className="mt-5" data-testid="journal-tab">
      <div className="flex justify-end mb-3">
        <Button className="bg-[#2f6a4a] hover:bg-[#265739] text-white rounded-full" onClick={() => setShowManual(true)} data-testid="new-journal-btn">
          New manual entry
        </Button>
      </div>
      <div className="rounded-2xl border border-[#e2ebe4] bg-white overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-[#f4f7f2] text-left text-xs uppercase text-slate-500">
            <tr><th className="p-3">Posted</th><th className="p-3">Memo</th><th className="p-3">Source</th><th className="p-3 text-right">Debits</th><th className="p-3 text-right">Credits</th></tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id} className="border-t border-[#e2ebe4]" data-testid={`journal-row-${e.id}`}>
                <td className="p-3 text-xs text-slate-500">{new Date(e.posted_at).toLocaleString()}</td>
                <td className="p-3">{e.memo}</td>
                <td className="p-3 text-xs text-slate-500">{e.source_type}</td>
                <td className="p-3 text-right">{fmt(e.total_debits)}</td>
                <td className="p-3 text-right">{fmt(e.total_credits)}</td>
              </tr>
            ))}
            {entries.length === 0 && <tr><td colSpan={5} className="p-8 text-center text-slate-400">No entries yet.</td></tr>}
          </tbody>
        </table>
      </div>
      <ManualJournalDialog open={showManual} onOpenChange={setShowManual} onCreated={load} />
    </div>
  );
}

function ManualJournalDialog({ open, onOpenChange, onCreated }) {
  const { toast } = useToast();
  const [memo, setMemo] = React.useState("");
  const [lines, setLines] = React.useState([
    { account_code: "", debit_cents: 0, credit_cents: 0 },
    { account_code: "", debit_cents: 0, credit_cents: 0 },
  ]);
  const [accounts, setAccounts] = React.useState([]);
  React.useEffect(() => { api.get("/accounting/accounts").then((r) => setAccounts(r.data)); }, []);
  const submit = async () => {
    try {
      await api.post("/accounting/journal/manual", { memo, lines });
      toast({ title: "Journal entry posted" });
      setMemo(""); setLines([{ account_code: "", debit_cents: 0, credit_cents: 0 }, { account_code: "", debit_cents: 0, credit_cents: 0 }]);
      onCreated();
      onOpenChange(false);
    } catch (e) { toast({ title: "Failed", description: getErrorMessage(e) || "Entry must be balanced" }); }
  };
  const updateLine = (i, k, v) => { const c = [...lines]; c[i] = { ...c[i], [k]: v }; setLines(c); };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-white max-w-2xl" data-testid="manual-journal-dialog">
        <DialogHeader><DialogTitle className="font-display text-2xl">New manual journal entry</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div><Label>Memo</Label><Input value={memo} onChange={(e) => setMemo(e.target.value)} data-testid="manual-memo" /></div>
          {lines.map((ln, i) => (
            <div key={i} className="grid grid-cols-4 gap-2 items-end">
              <div className="col-span-2">
                <Label className="text-xs">Account</Label>
                <Select value={ln.account_code} onValueChange={(v) => updateLine(i, "account_code", v)}>
                  <SelectTrigger><SelectValue placeholder="Choose…" /></SelectTrigger>
                  <SelectContent>{accounts.map((a) => <SelectItem key={a.code} value={a.code}>{a.code} · {a.name}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div><Label className="text-xs">Debit</Label><Input type="number" value={ln.debit_cents / 100} onChange={(e) => updateLine(i, "debit_cents", Math.round(Number(e.target.value) * 100))} /></div>
              <div><Label className="text-xs">Credit</Label><Input type="number" value={ln.credit_cents / 100} onChange={(e) => updateLine(i, "credit_cents", Math.round(Number(e.target.value) * 100))} /></div>
            </div>
          ))}
          <Button size="sm" variant="outline" onClick={() => setLines([...lines, { account_code: "", debit_cents: 0, credit_cents: 0 }])}>Add line</Button>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={submit} className="bg-[#2f6a4a] hover:bg-[#265739] text-white rounded-full" data-testid="manual-submit">Post entry</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ---------------- General Ledger ---------------- */
function GeneralLedgerTab() {
  const [accounts, setAccounts] = React.useState([]);
  const [code, setCode] = React.useState("");
  const [gl, setGl] = React.useState(null);
  React.useEffect(() => { api.get("/accounting/accounts").then((r) => { setAccounts(r.data); if (r.data[0]) setCode(r.data[0].code); }); }, []);
  React.useEffect(() => { if (code) api.get(`/accounting/gl/${code}`).then((r) => setGl(r.data)); }, [code]);
  return (
    <div className="mt-5" data-testid="gl-tab">
      <div className="flex gap-3 mb-4 items-end">
        <div className="w-[320px]"><Label>Account</Label>
          <Select value={code} onValueChange={setCode}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>{accounts.map((a) => <SelectItem key={a.code} value={a.code}>{a.code} · {a.name}</SelectItem>)}</SelectContent>
          </Select>
        </div>
      </div>
      {gl && (
        <div className="rounded-2xl border border-[#e2ebe4] bg-white overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-[#f4f7f2] text-xs uppercase text-slate-500"><tr><th className="p-3 text-left">Date</th><th className="p-3 text-left">Memo</th><th className="p-3 text-right">Debit</th><th className="p-3 text-right">Credit</th><th className="p-3 text-right">Running</th></tr></thead>
            <tbody>
              {gl.rows.map((r, i) => (
                <tr key={i} className="border-t border-[#e2ebe4]">
                  <td className="p-3 text-xs">{new Date(r.posted_at).toLocaleDateString()}</td>
                  <td className="p-3">{r.memo}</td>
                  <td className="p-3 text-right">{r.debit_cents ? fmt(r.debit_cents) : ""}</td>
                  <td className="p-3 text-right">{r.credit_cents ? fmt(r.credit_cents) : ""}</td>
                  <td className="p-3 text-right font-medium">{fmt(r.running_cents)}</td>
                </tr>
              ))}
              {gl.rows.length === 0 && <tr><td colSpan={5} className="p-8 text-center text-slate-400">No activity yet.</td></tr>}
            </tbody>
          </table>
          <div className="p-3 bg-[#f4f7f2] text-sm">
            Closing balance: <span className="font-semibold">{fmt(gl.closing_balance_cents)}</span>
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------------- Chart of Accounts ---------------- */
function CoATab() {
  const [accounts, setAccounts] = React.useState([]);
  React.useEffect(() => { api.get("/accounting/accounts").then((r) => setAccounts(r.data)); }, []);
  const toggle = async (a) => {
    await api.patch(`/accounting/accounts/${a.code}`, { active: !a.active });
    api.get("/accounting/accounts").then((r) => setAccounts(r.data));
  };
  return (
    <div className="mt-5 rounded-2xl border border-[#e2ebe4] bg-white overflow-hidden" data-testid="coa-tab">
      <table className="w-full text-sm">
        <thead className="bg-[#f4f7f2] text-xs uppercase text-slate-500"><tr><th className="p-3 text-left">Code</th><th className="p-3 text-left">Name</th><th className="p-3">Type</th><th className="p-3">Balance</th><th className="p-3">Locked</th><th className="p-3">Active</th></tr></thead>
        <tbody>
          {accounts.map((a) => (
            <tr key={a.code} className="border-t border-[#e2ebe4]">
              <td className="p-3 font-mono">{a.code}</td>
              <td className="p-3">{a.name}</td>
              <td className="p-3 text-xs uppercase text-slate-500">{a.type}</td>
              <td className="p-3 text-xs">{a.normal_balance}</td>
              <td className="p-3">{a.system_locked ? "Yes" : "—"}</td>
              <td className="p-3">
                <Button size="sm" variant="outline" onClick={() => toggle(a)} className="h-7">
                  {a.active ? "Active" : "Inactive"}
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ---------------- Expenses ---------------- */
function ExpensesTab() {
  const { toast } = useToast();
  const [rows, setRows] = React.useState([]);
  const [accounts, setAccounts] = React.useState([]);
  const [form, setForm] = React.useState({ amount: "", expense_account: "6900", payment_method: "check", memo: "" });
  const load = () => api.get("/accounting/expenses").then((r) => setRows(r.data));
  React.useEffect(() => { load(); api.get("/accounting/accounts").then((r) => setAccounts(r.data.filter((a) => a.type === "expense"))); }, []);
  const submit = async () => {
    try {
      await api.post("/accounting/expenses", {
        amount_cents: Math.round(Number(form.amount) * 100),
        expense_account: form.expense_account,
        payment_method: form.payment_method, memo: form.memo,
      });
      toast({ title: "Expense recorded" });
      setForm({ amount: "", expense_account: "6900", payment_method: "check", memo: "" });
      load();
    } catch (e) { toast({ title: "Failed", description: getErrorMessage(e) || "" }); }
  };
  return (
    <div className="mt-5 grid md:grid-cols-2 gap-5" data-testid="expenses-tab">
      <div className="rounded-2xl border border-[#e2ebe4] bg-white p-5">
        <h3 className="font-display text-xl mb-3">Record expense</h3>
        <div className="space-y-3">
          <div><Label>Amount</Label><Input type="number" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} /></div>
          <div><Label>Expense account</Label>
            <Select value={form.expense_account} onValueChange={(v) => setForm({ ...form, expense_account: v })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{accounts.map((a) => <SelectItem key={a.code} value={a.code}>{a.code} · {a.name}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div><Label>Payment method</Label>
            <Select value={form.payment_method} onValueChange={(v) => setForm({ ...form, payment_method: v })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="cash">Cash</SelectItem>
                <SelectItem value="check">Check</SelectItem>
                <SelectItem value="card_other">Credit card</SelectItem>
                <SelectItem value="ach">ACH</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div><Label>Memo</Label><Textarea rows={2} value={form.memo} onChange={(e) => setForm({ ...form, memo: e.target.value })} /></div>
          <Button onClick={submit} className="bg-[#2f6a4a] hover:bg-[#265739] text-white rounded-full">Record</Button>
        </div>
      </div>
      <div className="rounded-2xl border border-[#e2ebe4] bg-white overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-[#f4f7f2] text-xs uppercase text-slate-500"><tr><th className="p-3 text-left">Date</th><th className="p-3">Account</th><th className="p-3">Memo</th><th className="p-3 text-right">Amount</th></tr></thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.id} className="border-t border-[#e2ebe4]">
                <td className="p-3 text-xs">{new Date(e.created_at).toLocaleDateString()}</td>
                <td className="p-3 font-mono text-xs">{e.expense_account}</td>
                <td className="p-3 text-xs">{e.memo || "—"}</td>
                <td className="p-3 text-right">{fmt(e.amount_cents)}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={4} className="p-6 text-center text-slate-400">No expenses.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ---------------- Vendors & Bills ---------------- */
function VendorsBillsTab() {
  const { toast } = useToast();
  const [vendors, setVendors] = React.useState([]);
  const [bills, setBills] = React.useState([]);
  const [vf, setVf] = React.useState({ name: "", is_1099: false, tax_id: "" });
  const load = () => { api.get("/accounting/vendors").then((r) => setVendors(r.data)); api.get("/accounting/bills").then((r) => setBills(r.data)); };
  React.useEffect(load, []);
  const addVendor = async () => {
    if (!vf.name) return;
    await api.post("/accounting/vendors", vf);
    setVf({ name: "", is_1099: false, tax_id: "" });
    load();
  };
  const payBill = async (b) => { await api.post(`/accounting/bills/${b.id}/pay`, null, { params: { payment_method: "check" } }); toast({ title: "Bill paid" }); load(); };
  return (
    <div className="mt-5 grid md:grid-cols-2 gap-5" data-testid="vendors-tab">
      <div className="rounded-2xl border border-[#e2ebe4] bg-white p-5">
        <h3 className="font-display text-xl mb-3">Vendors</h3>
        <div className="grid grid-cols-2 gap-2 mb-3">
          <Input placeholder="Name" value={vf.name} onChange={(e) => setVf({ ...vf, name: e.target.value })} />
          <Input placeholder="Tax ID (for 1099)" value={vf.tax_id} onChange={(e) => setVf({ ...vf, tax_id: e.target.value })} />
          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={vf.is_1099} onChange={(e) => setVf({ ...vf, is_1099: e.target.checked })} /> Is 1099 vendor
          </label>
          <Button onClick={addVendor} className="bg-[#2f6a4a] hover:bg-[#265739] text-white rounded-full">Add</Button>
        </div>
        <ul className="text-sm space-y-1 max-h-64 overflow-y-auto">
          {vendors.map((v) => <li key={v.id} className="flex justify-between border-b border-[#eef1eb] py-1"><span>{v.name}</span><span className="text-xs text-slate-500">{v.is_1099 ? "1099" : ""}</span></li>)}
        </ul>
      </div>
      <div className="rounded-2xl border border-[#e2ebe4] bg-white p-5">
        <h3 className="font-display text-xl mb-3">Open bills</h3>
        <table className="w-full text-sm">
          <thead className="text-xs uppercase text-slate-500"><tr><th className="text-left">Vendor</th><th className="text-right">Amount</th><th className="text-right">Status</th><th></th></tr></thead>
          <tbody>
            {bills.map((b) => (
              <tr key={b.id} className="border-t border-[#eef1eb]">
                <td className="py-2">{vendors.find((v) => v.id === b.vendor_id)?.name || "—"}</td>
                <td className="text-right">{fmt(b.amount_cents)}</td>
                <td className="text-right text-xs">{b.status}</td>
                <td className="text-right">{b.status !== "paid" && <Button size="sm" onClick={() => payBill(b)} className="h-7 bg-[#2f6a4a] text-white rounded-full">Pay</Button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ---------------- Payroll ---------------- */
function PayrollTab() {
  const [employees, setEmployees] = React.useState([]);
  const [runs, setRuns] = React.useState([]);
  const load = () => { api.get("/accounting/employees").then((r) => setEmployees(r.data)); api.get("/accounting/payroll/runs").then((r) => setRuns(r.data)); };
  React.useEffect(load, []);
  return (
    <div className="mt-5 space-y-5" data-testid="payroll-tab">
      <div className="rounded-2xl border border-[#e2ebe4] bg-white p-5">
        <h3 className="font-display text-xl mb-3">Employees & contractors</h3>
        <table className="w-full text-sm">
          <thead className="text-xs uppercase text-slate-500"><tr><th className="text-left">Name</th><th>Kind</th><th className="text-right">Gross YTD</th><th className="text-right">PTO hrs</th><th>1099</th></tr></thead>
          <tbody>
            {employees.map((e) => (
              <tr key={e.id} className="border-t border-[#eef1eb]">
                <td className="py-2">{e.full_name}</td>
                <td className="text-xs">{e.kind}</td>
                <td className="text-right">{fmt(e.gross_ytd_cents)}</td>
                <td className="text-right">{e.pto_balance_hours}</td>
                <td className="text-center">{e.is_1099 ? "Yes" : ""}</td>
              </tr>
            ))}
            {employees.length === 0 && <tr><td colSpan={5} className="p-4 text-center text-slate-400">No employees yet.</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="rounded-2xl border border-[#e2ebe4] bg-white p-5">
        <h3 className="font-display text-xl mb-3">Payroll runs</h3>
        <table className="w-full text-sm">
          <thead className="text-xs uppercase text-slate-500"><tr><th className="text-left">Period</th><th className="text-right">Gross</th><th className="text-right">Taxes</th><th>Status</th></tr></thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id} className="border-t border-[#eef1eb]">
                <td className="py-2 text-xs">{new Date(r.period_start).toLocaleDateString()} – {new Date(r.period_end).toLocaleDateString()}</td>
                <td className="text-right">{fmt(r.total_gross_cents)}</td>
                <td className="text-right">{fmt(r.total_taxes_cents)}</td>
                <td className="text-xs">{r.status}</td>
              </tr>
            ))}
            {runs.length === 0 && <tr><td colSpan={4} className="p-4 text-center text-slate-400">No payroll runs yet. Use API to create.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ---------------- Tax ---------------- */
function TaxTab() {
  const [year, setYear] = React.useState(new Date().getFullYear());
  const [summary, setSummary] = React.useState(null);
  React.useEffect(() => { api.get("/accounting/tax/summary", { params: { year } }).then((r) => setSummary(r.data)); }, [year]);
  return (
    <div className="mt-5" data-testid="tax-tab">
      <div className="mb-3">
        <Label>Year</Label>
        <Input className="w-32" type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} />
      </div>
      {summary && (
        <div className="rounded-2xl border border-[#e2ebe4] bg-white overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-[#f4f7f2] text-xs uppercase text-slate-500"><tr><th className="p-3 text-left">Quarter</th><th className="p-3 text-right">Sales tax collected</th><th className="p-3 text-right">Payroll taxes accrued</th></tr></thead>
            <tbody>
              {summary.quarters.map((q) => (
                <tr key={q.quarter} className="border-t border-[#e2ebe4]">
                  <td className="p-3">{q.quarter}</td>
                  <td className="p-3 text-right">{fmt(q.sales_tax_collected_cents)}</td>
                  <td className="p-3 text-right">{fmt(q.payroll_tax_accrued_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ---------------- 1099 ---------------- */
function OneOhNineNineTab() {
  const [year, setYear] = React.useState(new Date().getFullYear());
  const [data, setData] = React.useState(null);
  React.useEffect(() => { api.get("/accounting/1099/vendors", { params: { year } }).then((r) => setData(r.data)); }, [year]);
  const downloadCsv = () => { window.open(`/api/accounting/1099/csv?year=${year}`, "_blank"); };
  return (
    <div className="mt-5" data-testid="tab1099">
      <div className="flex gap-3 items-end mb-3">
        <div><Label>Year</Label><Input className="w-32" type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} /></div>
        <Button onClick={downloadCsv} variant="outline" className="border-[#cfe0d3] text-[#2f6a4a]">
          <Download size={13} className="mr-1" /> Download CSV
        </Button>
      </div>
      {data && (
        <div className="rounded-2xl border border-[#e2ebe4] bg-white overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-[#f4f7f2] text-xs uppercase text-slate-500"><tr><th className="p-3 text-left">Recipient</th><th>Kind</th><th>Tax ID</th><th className="text-right">Paid this year</th></tr></thead>
            <tbody>
              {data.recipients.map((r) => (
                <tr key={r.vendor_id} className="border-t border-[#e2ebe4]">
                  <td className="p-3">{r.name}</td>
                  <td className="p-3 text-xs">{r.kind}</td>
                  <td className="p-3 text-xs font-mono">{r.tax_id || "—"}</td>
                  <td className="p-3 text-right">{fmt(r.total_paid_cents)}</td>
                </tr>
              ))}
              {data.recipients.length === 0 && <tr><td colSpan={4} className="p-6 text-center text-slate-400">No 1099 recipients ≥ $600 for {year}.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ---------------- helpers ---------------- */
function Card({ title, icon: Icon, badge, badgeTone, children }) {
  const tone = badgeTone === "err" ? "bg-[#fdecec] text-[#7a2a2a]" : "bg-[#eaf2ec] text-[#3d6b52]";
  return (
    <div className="rounded-2xl border border-[#e2ebe4] bg-white p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 text-[#3d6b52]">
          <Icon size={16} />
          <div className="eyebrow">{title}</div>
        </div>
        {badge && <span className={`text-[10px] px-2 py-0.5 rounded-full ${tone}`}>{badge}</span>}
      </div>
      <div className="space-y-1 text-sm">{children}</div>
    </div>
  );
}
function Row({ label, value, strong, accent }) {
  return (
    <div className={`flex justify-between ${strong ? "border-t border-[#e2ebe4] pt-2 font-semibold" : ""} ${accent ? "text-[#2f6a4a]" : ""}`}>
      <span>{label}</span><span>{value}</span>
    </div>
  );
}
