import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
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
  Home, DollarSign, ShoppingBag, Receipt as RcpIcon, BarChart3, Settings2,
  BookText, Wallet, Landmark, FileText, Download, ClipboardList,
} from "lucide-react";
import { useToast } from "../../hooks/use-toast";
import { getErrorMessage } from "../../lib/errors";
import HealthTab from "./AccountingHealthTab";
import BankingTab from "./BankingTab";
import OverviewSection from "./accounting/OverviewSection";
import { QuickActions } from "./accounting/QuickActions";
import { useAsyncGet, AsyncPanel } from "./accounting/useAsync";

const fmt = (cents) => `$${(Number(cents || 0) / 100).toFixed(2)}`;

const SECTIONS = [
  { key: "overview", label: "Overview", Icon: Home,       hint: "Everything at a glance" },
  { key: "money",    label: "Money",    Icon: DollarSign, hint: "Banking, transfers, reconciliation" },
  { key: "sales",    label: "Sales",    Icon: ShoppingBag, hint: "Invoices, payments, memberships" },
  { key: "expenses", label: "Expenses", Icon: RcpIcon,    hint: "Vendors, bills, expenses" },
  { key: "reports",  label: "Reports",  Icon: BarChart3,  hint: "Profit & Loss, Balance Sheet, Cash Flow" },
  { key: "advanced", label: "Advanced", Icon: Settings2,  hint: "Ledger internals for accountants" },
];

/** Consolidated admin Accounting workspace — 6 sections, lazy-mount. */
export default function Accounting() {
  const [section, setSection] = React.useState(() => {
    try { return localStorage.getItem("acct.section") || "overview"; }
    catch { return "overview"; }
  });
  const [newExpenseOpen, setNewExpenseOpen] = React.useState(false);
  const [newJournalOpen, setNewJournalOpen] = React.useState(false);
  const [newTransferOpen, setNewTransferOpen] = React.useState(false);

  const goto = (k) => {
    setSection(k);
    try { localStorage.setItem("acct.section", k); } catch {}
  };

  return (
    <PortalLayout>
      <PortalHeader
        title="Accounting"
        subtitle="Overview · Money · Sales · Expenses · Reports · Advanced"
      />

      <QuickActions
        onOpenNewExpense={() => { goto("expenses"); setNewExpenseOpen(true); }}
        onOpenNewTransfer={() => { goto("money"); setNewTransferOpen(true); }}
        onOpenNewJournal={() => { goto("advanced"); setNewJournalOpen(true); }}
      />

      {/* Top-level section nav — only ONE section renders at a time */}
      <div className="rounded-2xl border border-[#e2ebe4] bg-[#f4f7f2] p-1 mb-5 flex flex-wrap gap-1" data-testid="accounting-sections">
        {SECTIONS.map(({ key, label, Icon }) => (
          <button
            key={key}
            onClick={() => goto(key)}
            className={`px-4 py-2 text-sm rounded-full inline-flex items-center gap-1.5 transition ${
              section === key
                ? "bg-[#2f6a4a] text-white shadow-sm"
                : "text-[#2f6a4a] hover:bg-white"
            }`}
            data-testid={`section-${key}`}
          >
            <Icon size={13} /> {label}
          </button>
        ))}
      </div>

      {section === "overview" && <OverviewSection onGoTo={goto} />}
      {section === "money"    && <MoneySection openTransfer={newTransferOpen} setOpenTransfer={setNewTransferOpen} />}
      {section === "sales"    && <SalesSection />}
      {section === "expenses" && <ExpensesSection openNew={newExpenseOpen} setOpenNew={setNewExpenseOpen} />}
      {section === "reports"  && <ReportsSection />}
      {section === "advanced" && <AdvancedSection openJournal={newJournalOpen} setOpenJournal={setNewJournalOpen} />}
    </PortalLayout>
  );
}

/* ================================================================= MONEY */
function MoneySection() {
  // Banking already covers accounts, transactions, reconciliation, exceptions,
  // transfers, and cash reports. Reuse it wholesale.
  return (
    <div data-testid="money-section">
      <BankingTab />
    </div>
  );
}

/* ================================================================= SALES */
function SalesSection() {
  // Sales pages already live under other routes. Show a directory to open them.
  const cards = [
    { title: "Point of Sale",   subtitle: "Ring up invoices, take payments, apply memberships & gift cards.", to: "/portal/pos", icon: ShoppingBag },
    { title: "Front Desk",      subtitle: "Check-ins, memberships, and daily patient flow.", to: "/portal/front-desk", icon: RcpIcon },
    { title: "Sales report (MTD)", subtitle: "Detailed revenue-by-category report.", to: null, icon: BarChart3, section: "reports" },
  ];
  return (
    <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="sales-section">
      {cards.map((c) => (
        <a
          key={c.title}
          href={c.to || "#"}
          className="rounded-2xl border border-[#e2ebe4] bg-white p-5 hover:shadow-sm transition block"
          data-testid={`sales-card-${c.title.toLowerCase().replace(/\W+/g, "-")}`}
        >
          <div className="flex items-center gap-2 text-[#3d6b52] mb-2">
            <c.icon size={14} />
            <div className="eyebrow">{c.title}</div>
          </div>
          <p className="text-sm text-slate-500">{c.subtitle}</p>
        </a>
      ))}
      <div className="rounded-2xl border border-dashed border-[#e2ebe4] bg-white p-5 text-sm text-slate-500 md:col-span-2 lg:col-span-3" data-testid="sales-note">
        Gift cards, packages, and store-credit ledgers post to the same accounting engine.
        Manage them from Point of Sale — every sale automatically emits accounting events.
      </div>
    </div>
  );
}

/* ============================================================== EXPENSES */
function ExpensesSection({ openNew, setOpenNew }) {
  const [tab, setTab] = React.useState("expenses");
  const tabs = [
    { k: "expenses", label: "Expenses" },
    { k: "vendors",  label: "Vendors" },
    { k: "bills",    label: "Bills" },
  ];
  return (
    <div className="space-y-4" data-testid="expenses-section">
      <div className="flex flex-wrap gap-2">
        {tabs.map((t) => (
          <button key={t.k}
            onClick={() => setTab(t.k)}
            className={`px-3 py-1.5 rounded-full text-sm border transition ${
              tab === t.k
                ? "bg-[#2f6a4a] text-white border-[#2f6a4a]"
                : "bg-white text-[#2f6a4a] border-[#cfe0d3] hover:bg-[#eaf2ec]"
            }`}
            data-testid={`expenses-sub-${t.k}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "expenses" && <ExpensesTab openNew={openNew} setOpenNew={setOpenNew} />}
      {tab === "vendors"  && <VendorsPane />}
      {tab === "bills"    && <BillsPane />}
    </div>
  );
}

/* ================================================================ REPORTS */
function ReportsSection() {
  // Stable month-to-date window — memoized so useEffect never re-fires.
  const { start, end } = React.useMemo(() => {
    const now = new Date();
    return {
      start: new Date(now.getFullYear(), now.getMonth(), 1).toISOString(),
      end: now.toISOString(),
    };
  }, []);
  const key = `${start}|${end}`;

  const pl = useAsyncGet("/accounting/reports/profit-and-loss", { start, end }, key);
  const bs = useAsyncGet("/accounting/reports/balance-sheet", { as_of: end }, key);
  const tb = useAsyncGet("/accounting/reports/trial-balance", null, "tb");
  const ar = useAsyncGet("/accounting/reports/ar-aging", null, "ar");
  const cf = useAsyncGet("/accounting/cash/flow", { start, end }, key);

  return (
    <div className="grid md:grid-cols-2 gap-5" data-testid="reports-section">
      <ReportCard title="Profit & Loss (Month to date)" icon={FileText} state={pl}>
        {pl.data && (
          <>
            <Row label="Revenue" value={fmt(pl.data.total_revenue_cents)} strong />
            <Row label="COGS" value={fmt(pl.data.total_cogs_cents)} />
            <Row label="Gross profit" value={fmt(pl.data.gross_profit_cents)} />
            <Row label="Expenses" value={fmt(pl.data.total_expenses_cents)} />
            <Row label="Net income" value={fmt(pl.data.net_income_cents)} strong accent />
          </>
        )}
      </ReportCard>

      <ReportCard title="Balance Sheet" icon={Landmark}
        badge={bs.data?.balanced ? "Balanced" : "Out of balance"}
        badgeTone={bs.data?.balanced ? "ok" : "err"} state={bs}>
        {bs.data && (
          <>
            <Row label="Total assets" value={fmt(bs.data.total_assets_cents)} strong />
            <Row label="Total liabilities" value={fmt(bs.data.total_liabilities_cents)} />
            <Row label="Equity + retained" value={fmt((bs.data.total_equity_cents || 0) + (bs.data.current_period_net_income_cents || 0))} />
            <Row label="Liab + Equity" value={fmt(bs.data.total_liab_and_equity_cents)} strong />
          </>
        )}
      </ReportCard>

      <ReportCard title="Cash flow (MTD)" icon={Wallet} state={cf}>
        {cf.data && (
          <>
            <Row label="Inflow" value={fmt(cf.data.totals?.inflow_cents)} />
            <Row label="Outflow" value={fmt(cf.data.totals?.outflow_cents)} />
            <Row label="Net" value={fmt(cf.data.totals?.net_cents)} strong accent />
          </>
        )}
      </ReportCard>

      <ReportCard title="A/R Aging" icon={ClipboardList} state={ar}>
        {ar.data && (
          <>
            <Row label="Current" value={fmt(ar.data.buckets?.current)} />
            <Row label="1-30 days" value={fmt(ar.data.buckets?.["1_30"])} />
            <Row label="31-60 days" value={fmt(ar.data.buckets?.["31_60"])} />
            <Row label="61-90 days" value={fmt(ar.data.buckets?.["61_90"])} />
            <Row label="Over 90 days" value={fmt(ar.data.buckets?.over_90)} accent />
            <Row label="Total outstanding" value={fmt(ar.data.total_cents)} strong />
          </>
        )}
      </ReportCard>

      <ReportCard title="Balance check (Trial Balance)" icon={BookText} state={tb}
        badge={tb.data?.balanced ? "Balanced" : "Off"}
        badgeTone={tb.data?.balanced ? "ok" : "err"}>
        {tb.data && (
          <div className="max-h-64 overflow-y-auto text-xs">
            <table className="w-full">
              <thead className="text-slate-500"><tr><th className="text-left">Account</th><th className="text-right">Debit</th><th className="text-right">Credit</th></tr></thead>
              <tbody>
                {(tb.data.rows || []).map((r) => (
                  <tr key={r.code} className="border-t border-[#eef1eb]">
                    <td className="py-1">{r.code} · {r.name}</td>
                    <td className="text-right">{fmt(r.debit_cents)}</td>
                    <td className="text-right">{fmt(r.credit_cents)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot className="font-semibold border-t"><tr><td>Totals</td><td className="text-right">{fmt(tb.data.total_debit_cents)}</td><td className="text-right">{fmt(tb.data.total_credit_cents)}</td></tr></tfoot>
            </table>
          </div>
        )}
      </ReportCard>

      <div className="rounded-2xl border border-[#e2ebe4] bg-white p-5" data-testid="report-more">
        <div className="flex items-center gap-2 text-[#3d6b52] mb-2"><BarChart3 size={14} /><div className="eyebrow">More reports</div></div>
        <p className="text-sm text-slate-500 mb-3">
          Payroll totals, tax quarters, and 1099 recipients live in <strong>Advanced</strong>.
        </p>
      </div>
    </div>
  );
}

/* =============================================================== ADVANCED */
function AdvancedSection({ openJournal, setOpenJournal }) {
  const [tab, setTab] = React.useState("journal");
  const tabs = [
    { k: "journal",  label: "Transaction history",   subtitle: "Journal Entries" },
    { k: "gl",       label: "Account activity",      subtitle: "General Ledger" },
    { k: "coa",      label: "Account categories",    subtitle: "Chart of Accounts" },
    { k: "payroll",  label: "Payroll",               subtitle: "" },
    { k: "tax",      label: "Tax",                   subtitle: "" },
    { k: "1099",     label: "1099",                  subtitle: "" },
    { k: "health",   label: "Ledger health",         subtitle: "Backfill · Balance check · Processing issues" },
  ];
  return (
    <div className="space-y-4" data-testid="advanced-section">
      <div className="flex flex-wrap gap-2">
        {tabs.map((t) => (
          <button key={t.k}
            onClick={() => setTab(t.k)}
            className={`px-3 py-1.5 rounded-full text-sm border transition ${
              tab === t.k
                ? "bg-[#2f6a4a] text-white border-[#2f6a4a]"
                : "bg-white text-[#2f6a4a] border-[#cfe0d3] hover:bg-[#eaf2ec]"
            }`}
            data-testid={`adv-sub-${t.k}`}
            title={t.subtitle}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "journal" && <JournalTab openNew={openJournal} setOpenNew={setOpenJournal} />}
      {tab === "gl"      && <GeneralLedgerTab />}
      {tab === "coa"     && <CoATab />}
      {tab === "payroll" && <PayrollTab />}
      {tab === "tax"     && <TaxTab />}
      {tab === "1099"    && <OneOhNineNineTab />}
      {tab === "health"  && <HealthTab />}
    </div>
  );
}

/* ============================================================== SUB-COMPS */

/* ------ Journal (Transaction history) ------ */
function JournalTab({ openNew, setOpenNew }) {
  const journal = useAsyncGet("/accounting/journal", null, "journal");
  const entries = journal.data || [];
  return (
    <div className="mt-5" data-testid="journal-tab">
      <div className="flex justify-between mb-3 items-center">
        <div className="text-xs text-slate-500">Transaction History <span className="text-slate-400">(Journal Entries)</span></div>
        <Button className="bg-[#2f6a4a] hover:bg-[#265739] text-white rounded-full" onClick={() => setOpenNew(true)} data-testid="new-journal-btn">
          New manual entry
        </Button>
      </div>
      <AsyncPanel {...journal} onRetry={journal.refetch} errorMessage="Couldn't load transactions" emptyMessage="No entries yet.">
        <div className="rounded-2xl border border-[#e2ebe4] bg-white overflow-x-auto">
          <table className="w-full text-sm min-w-[600px]">
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
            </tbody>
          </table>
        </div>
      </AsyncPanel>
      <ManualJournalDialog open={openNew} onOpenChange={setOpenNew} onCreated={journal.refetch} />
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
  const accounts = useAsyncGet("/accounting/accounts", null, "accounts-list");
  const submit = async () => {
    try {
      await api.post("/accounting/journal/manual", { memo, lines });
      toast({ title: "Journal entry posted" });
      setMemo("");
      setLines([{ account_code: "", debit_cents: 0, credit_cents: 0 }, { account_code: "", debit_cents: 0, credit_cents: 0 }]);
      onCreated && onCreated();
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
                  <SelectContent>{(accounts.data || []).map((a) => <SelectItem key={a.code} value={a.code}>{a.code} · {a.name}</SelectItem>)}</SelectContent>
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

/* ------ General Ledger (Account activity) ------ */
function GeneralLedgerTab() {
  const accounts = useAsyncGet("/accounting/accounts", null, "accounts-list");
  const [code, setCode] = React.useState("");
  React.useEffect(() => {
    if (!code && Array.isArray(accounts.data) && accounts.data[0]) setCode(accounts.data[0].code);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accounts.data]);
  const gl = useAsyncGet(code ? `/accounting/gl/${code}` : null, null, code || "");
  return (
    <div className="mt-5" data-testid="gl-tab">
      <div className="flex gap-3 mb-4 items-end">
        <div className="w-[320px]">
          <Label>Account category</Label>
          <Select value={code} onValueChange={setCode}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>{(accounts.data || []).map((a) => <SelectItem key={a.code} value={a.code}>{a.code} · {a.name}</SelectItem>)}</SelectContent>
          </Select>
        </div>
      </div>
      {code && (
        <AsyncPanel {...gl} onRetry={gl.refetch} errorMessage="Couldn't load account activity">
          {gl.data && (
            <div className="rounded-2xl border border-[#e2ebe4] bg-white overflow-x-auto">
              <table className="w-full text-sm min-w-[720px]">
                <thead className="bg-[#f4f7f2] text-xs uppercase text-slate-500"><tr><th className="p-3 text-left">Date</th><th className="p-3 text-left">Memo</th><th className="p-3 text-right">Debit</th><th className="p-3 text-right">Credit</th><th className="p-3 text-right">Running</th></tr></thead>
                <tbody>
                  {(gl.data.rows || []).map((r, i) => (
                    <tr key={i} className="border-t border-[#e2ebe4]">
                      <td className="p-3 text-xs">{new Date(r.posted_at).toLocaleDateString()}</td>
                      <td className="p-3 text-xs">{r.memo}</td>
                      <td className="p-3 text-right">{r.debit_cents ? fmt(r.debit_cents) : ""}</td>
                      <td className="p-3 text-right">{r.credit_cents ? fmt(r.credit_cents) : ""}</td>
                      <td className="p-3 text-right font-medium">{fmt(r.running_cents)}</td>
                    </tr>
                  ))}
                  {(gl.data.rows || []).length === 0 && <tr><td colSpan={5} className="p-8 text-center text-slate-400">No activity yet.</td></tr>}
                </tbody>
              </table>
              <div className="p-3 bg-[#f4f7f2] text-sm">
                Closing balance: <span className="font-semibold">{fmt(gl.data.closing_balance_cents)}</span>
              </div>
            </div>
          )}
        </AsyncPanel>
      )}
    </div>
  );
}

/* ------ Chart of Accounts (Account categories) ------ */
function CoATab() {
  const accounts = useAsyncGet("/accounting/accounts", null, "accounts-list");
  const toggle = async (a) => {
    await api.patch(`/accounting/accounts/${a.code}`, { active: !a.active });
    accounts.refetch();
  };
  return (
    <div className="mt-5" data-testid="coa-tab">
      <div className="text-xs text-slate-500 mb-3">Account categories <span className="text-slate-400">(Chart of Accounts)</span></div>
      <AsyncPanel {...accounts} onRetry={accounts.refetch} errorMessage="Couldn't load account categories">
        <div className="rounded-2xl border border-[#e2ebe4] bg-white overflow-x-auto">
          <table className="w-full text-sm min-w-[600px]">
            <thead className="bg-[#f4f7f2] text-xs uppercase text-slate-500"><tr><th className="p-3 text-left">Code</th><th className="p-3 text-left">Name</th><th className="p-3">Type</th><th className="p-3">Balance</th><th className="p-3">Locked</th><th className="p-3">Active</th></tr></thead>
            <tbody>
              {(accounts.data || []).map((a) => (
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
      </AsyncPanel>
    </div>
  );
}

/* ------ Expenses ------ */
function ExpensesTab({ openNew, setOpenNew }) {
  const { toast } = useToast();
  const rows = useAsyncGet("/accounting/expenses", null, "expenses");
  const accountsAll = useAsyncGet("/accounting/accounts", null, "accounts-list");
  const expenseAccounts = React.useMemo(
    () => (accountsAll.data || []).filter((a) => a.type === "expense"),
    [accountsAll.data]
  );
  const [form, setForm] = React.useState({ amount: "", expense_account: "6900", payment_method: "check", memo: "" });
  const submit = async () => {
    try {
      await api.post("/accounting/expenses", {
        amount_cents: Math.round(Number(form.amount) * 100),
        expense_account: form.expense_account,
        payment_method: form.payment_method, memo: form.memo,
      });
      toast({ title: "Expense recorded" });
      setForm({ amount: "", expense_account: "6900", payment_method: "check", memo: "" });
      rows.refetch();
      if (openNew) setOpenNew(false);
    } catch (e) { toast({ title: "Failed", description: getErrorMessage(e) || "" }); }
  };
  const formCard = (
    <div className="rounded-2xl border border-[#e2ebe4] bg-white p-5">
      <h3 className="font-display text-xl mb-3">Record expense</h3>
      <div className="space-y-3">
        <div><Label>Amount</Label><Input type="number" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} data-testid="new-expense-amount" /></div>
        <div><Label>Expense account</Label>
          <Select value={form.expense_account} onValueChange={(v) => setForm({ ...form, expense_account: v })}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>{expenseAccounts.map((a) => <SelectItem key={a.code} value={a.code}>{a.code} · {a.name}</SelectItem>)}</SelectContent>
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
        <Button onClick={submit} className="bg-[#2f6a4a] hover:bg-[#265739] text-white rounded-full" data-testid="new-expense-submit">Record</Button>
      </div>
    </div>
  );
  return (
    <div className="mt-4 grid md:grid-cols-2 gap-5" data-testid="expenses-tab">
      {formCard}
      <AsyncPanel {...rows} onRetry={rows.refetch} errorMessage="Couldn't load expenses" emptyMessage="No expenses yet.">
        <div className="rounded-2xl border border-[#e2ebe4] bg-white overflow-x-auto">
          <table className="w-full text-sm min-w-[420px]">
            <thead className="bg-[#f4f7f2] text-xs uppercase text-slate-500"><tr><th className="p-3 text-left">Date</th><th className="p-3">Account</th><th className="p-3">Memo</th><th className="p-3 text-right">Amount</th></tr></thead>
            <tbody>
              {(rows.data || []).map((e) => (
                <tr key={e.id} className="border-t border-[#e2ebe4]">
                  <td className="p-3 text-xs">{new Date(e.created_at).toLocaleDateString()}</td>
                  <td className="p-3 font-mono text-xs">{e.expense_account}</td>
                  <td className="p-3 text-xs">{e.memo || "—"}</td>
                  <td className="p-3 text-right">{fmt(e.amount_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </AsyncPanel>
    </div>
  );
}

/* ------ Vendors ------ */
function VendorsPane() {
  const vendors = useAsyncGet("/accounting/vendors", null, "vendors");
  const [vf, setVf] = React.useState({ name: "", is_1099: false, tax_id: "" });
  const addVendor = async () => {
    if (!vf.name) return;
    await api.post("/accounting/vendors", vf);
    setVf({ name: "", is_1099: false, tax_id: "" });
    vendors.refetch();
  };
  return (
    <div className="mt-4" data-testid="vendors-pane">
      <div className="rounded-2xl border border-[#e2ebe4] bg-white p-5 mb-4">
        <h3 className="font-display text-xl mb-3">Add vendor</h3>
        <div className="grid md:grid-cols-4 gap-2 items-end">
          <div className="md:col-span-2"><Label className="text-xs">Name</Label><Input placeholder="Vendor name" value={vf.name} onChange={(e) => setVf({ ...vf, name: e.target.value })} /></div>
          <div><Label className="text-xs">Tax ID (for 1099)</Label><Input value={vf.tax_id} onChange={(e) => setVf({ ...vf, tax_id: e.target.value })} /></div>
          <div className="flex flex-col gap-1">
            <label className="flex items-center gap-2 text-xs h-10">
              <input type="checkbox" checked={vf.is_1099} onChange={(e) => setVf({ ...vf, is_1099: e.target.checked })} /> 1099
            </label>
            <Button onClick={addVendor} className="bg-[#2f6a4a] hover:bg-[#265739] text-white rounded-full">Add vendor</Button>
          </div>
        </div>
      </div>
      <AsyncPanel {...vendors} onRetry={vendors.refetch} errorMessage="Couldn't load vendors" emptyMessage="No vendors yet.">
        <div className="rounded-2xl border border-[#e2ebe4] bg-white overflow-x-auto">
          <table className="w-full text-sm min-w-[500px]">
            <thead className="bg-[#f4f7f2] text-xs uppercase text-slate-500"><tr><th className="p-3 text-left">Name</th><th className="p-3">Tax ID</th><th className="p-3">1099</th></tr></thead>
            <tbody>
              {(vendors.data || []).map((v) => (
                <tr key={v.id} className="border-t border-[#e2ebe4]">
                  <td className="p-3">{v.name}</td>
                  <td className="p-3 font-mono text-xs">{v.tax_id || "—"}</td>
                  <td className="p-3 text-xs">{v.is_1099 ? "Yes" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </AsyncPanel>
    </div>
  );
}

/* ------ Bills ------ */
function BillsPane() {
  const { toast } = useToast();
  const bills = useAsyncGet("/accounting/bills", null, "bills");
  const vendors = useAsyncGet("/accounting/vendors", null, "vendors");
  const payBill = async (b) => {
    await api.post(`/accounting/bills/${b.id}/pay`, null, { params: { payment_method: "check" } });
    toast({ title: "Bill paid" });
    bills.refetch();
  };
  return (
    <div className="mt-4" data-testid="bills-pane">
      <AsyncPanel {...bills} onRetry={bills.refetch} errorMessage="Couldn't load bills" emptyMessage="No open bills.">
        <div className="rounded-2xl border border-[#e2ebe4] bg-white overflow-x-auto">
          <table className="w-full text-sm min-w-[520px]">
            <thead className="bg-[#f4f7f2] text-xs uppercase text-slate-500"><tr><th className="p-3 text-left">Vendor</th><th className="p-3 text-right">Amount</th><th className="p-3">Status</th><th className="p-3"></th></tr></thead>
            <tbody>
              {(bills.data || []).map((b) => (
                <tr key={b.id} className="border-t border-[#e2ebe4]">
                  <td className="p-3">{(vendors.data || []).find((v) => v.id === b.vendor_id)?.name || "—"}</td>
                  <td className="p-3 text-right">{fmt(b.amount_cents)}</td>
                  <td className="p-3 text-xs">{b.status}</td>
                  <td className="p-3 text-right">{b.status !== "paid" && <Button size="sm" onClick={() => payBill(b)} className="h-7 bg-[#2f6a4a] text-white rounded-full">Pay</Button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </AsyncPanel>
    </div>
  );
}

/* ------ Payroll ------ */
function PayrollTab() {
  const employees = useAsyncGet("/accounting/employees", null, "employees");
  const runs = useAsyncGet("/accounting/payroll/runs", null, "payroll-runs");
  return (
    <div className="mt-5 space-y-5" data-testid="payroll-tab">
      <AsyncPanel {...employees} onRetry={employees.refetch} errorMessage="Couldn't load employees" emptyMessage="No employees yet.">
        <div className="rounded-2xl border border-[#e2ebe4] bg-white p-5 overflow-x-auto">
          <h3 className="font-display text-xl mb-3">Employees &amp; contractors</h3>
          <table className="w-full text-sm min-w-[500px]">
            <thead className="text-xs uppercase text-slate-500"><tr><th className="text-left">Name</th><th>Kind</th><th className="text-right">Gross YTD</th><th className="text-right">PTO hrs</th><th>1099</th></tr></thead>
            <tbody>
              {(employees.data || []).map((e) => (
                <tr key={e.id} className="border-t border-[#eef1eb]">
                  <td className="py-2">{e.full_name}</td>
                  <td className="text-xs">{e.kind}</td>
                  <td className="text-right">{fmt(e.gross_ytd_cents)}</td>
                  <td className="text-right">{e.pto_balance_hours}</td>
                  <td className="text-center">{e.is_1099 ? "Yes" : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </AsyncPanel>
      <AsyncPanel {...runs} onRetry={runs.refetch} errorMessage="Couldn't load payroll runs" emptyMessage="No payroll runs yet.">
        <div className="rounded-2xl border border-[#e2ebe4] bg-white p-5 overflow-x-auto">
          <h3 className="font-display text-xl mb-3">Payroll runs</h3>
          <table className="w-full text-sm min-w-[520px]">
            <thead className="text-xs uppercase text-slate-500"><tr><th className="text-left">Period</th><th className="text-right">Gross</th><th className="text-right">Taxes</th><th>Status</th></tr></thead>
            <tbody>
              {(runs.data || []).map((r) => (
                <tr key={r.id} className="border-t border-[#eef1eb]">
                  <td className="py-2 text-xs">{new Date(r.period_start).toLocaleDateString()} – {new Date(r.period_end).toLocaleDateString()}</td>
                  <td className="text-right">{fmt(r.total_gross_cents)}</td>
                  <td className="text-right">{fmt(r.total_taxes_cents)}</td>
                  <td className="text-xs">{r.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </AsyncPanel>
    </div>
  );
}

/* ------ Tax ------ */
function TaxTab() {
  const [year, setYear] = React.useState(new Date().getFullYear());
  const summary = useAsyncGet("/accounting/tax/summary", { year }, `tax-${year}`);
  return (
    <div className="mt-5" data-testid="tax-tab">
      <div className="mb-3">
        <Label>Year</Label>
        <Input className="w-32" type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} />
      </div>
      <AsyncPanel {...summary} onRetry={summary.refetch} errorMessage="Couldn't load tax summary" emptyMessage="No data for this year.">
        <div className="rounded-2xl border border-[#e2ebe4] bg-white overflow-x-auto">
          <table className="w-full text-sm min-w-[520px]">
            <thead className="bg-[#f4f7f2] text-xs uppercase text-slate-500"><tr><th className="p-3 text-left">Quarter</th><th className="p-3 text-right">Sales tax collected</th><th className="p-3 text-right">Payroll taxes accrued</th></tr></thead>
            <tbody>
              {(summary.data?.quarters || []).map((q) => (
                <tr key={q.quarter} className="border-t border-[#e2ebe4]">
                  <td className="p-3">{q.quarter}</td>
                  <td className="p-3 text-right">{fmt(q.sales_tax_collected_cents)}</td>
                  <td className="p-3 text-right">{fmt(q.payroll_tax_accrued_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </AsyncPanel>
    </div>
  );
}

/* ------ 1099 ------ */
function OneOhNineNineTab() {
  const [year, setYear] = React.useState(new Date().getFullYear());
  const data = useAsyncGet("/accounting/1099/vendors", { year }, `1099-${year}`);
  const downloadCsv = () => { window.open(`/api/accounting/1099/csv?year=${year}`, "_blank"); };
  return (
    <div className="mt-5" data-testid="tab1099">
      <div className="flex gap-3 items-end mb-3 flex-wrap">
        <div><Label>Year</Label><Input className="w-32" type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} /></div>
        <Button onClick={downloadCsv} variant="outline" className="border-[#cfe0d3] text-[#2f6a4a]">
          <Download size={13} className="mr-1" /> Download CSV
        </Button>
      </div>
      <AsyncPanel {...data} onRetry={data.refetch} errorMessage="Couldn't load 1099 recipients" emptyMessage={`No 1099 recipients ≥ $600 for ${year}.`}>
        <div className="rounded-2xl border border-[#e2ebe4] bg-white overflow-x-auto">
          <table className="w-full text-sm min-w-[520px]">
            <thead className="bg-[#f4f7f2] text-xs uppercase text-slate-500"><tr><th className="p-3 text-left">Recipient</th><th className="p-3">Kind</th><th className="p-3">Tax ID</th><th className="p-3 text-right">Paid this year</th></tr></thead>
            <tbody>
              {(data.data?.recipients || []).map((r) => (
                <tr key={r.vendor_id} className="border-t border-[#e2ebe4]">
                  <td className="p-3">{r.name}</td>
                  <td className="p-3 text-xs">{r.kind}</td>
                  <td className="p-3 text-xs font-mono">{r.tax_id || "—"}</td>
                  <td className="p-3 text-right">{fmt(r.total_paid_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </AsyncPanel>
    </div>
  );
}

/* ---------------- helpers ---------------- */
function ReportCard({ title, icon: Icon, badge, badgeTone, state, children }) {
  const tone = badgeTone === "err" ? "bg-[#fdecec] text-[#7a2a2a]" : "bg-[#eaf2ec] text-[#3d6b52]";
  return (
    <div className="rounded-2xl border border-[#e2ebe4] bg-white p-5" data-testid={`report-${title.toLowerCase().replace(/\W+/g, "-")}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 text-[#3d6b52]">
          <Icon size={16} />
          <div className="eyebrow">{title}</div>
        </div>
        {badge && <span className={`text-[10px] px-2 py-0.5 rounded-full ${tone}`}>{badge}</span>}
      </div>
      <AsyncPanel {...state} onRetry={state.refetch} errorMessage={`Couldn't load ${title.toLowerCase()}`} className="!p-4">
        <div className="space-y-1 text-sm">{children}</div>
      </AsyncPanel>
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
