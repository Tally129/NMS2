import React from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../../../components/ui/button";
import { Badge } from "../../../components/ui/badge";
import {
  Wallet, TrendingUp, Receipt, Users, Package, AlertCircle,
  Landmark, RefreshCw, ChevronRight, Activity,
} from "lucide-react";
import { useAsyncGet, AsyncPanel } from "./useAsync";

const fmt = (cents) => {
  const n = Number(cents || 0) / 100;
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  })}`;
};

/**
 * A single quiet home page for Accounting. Every card fetches once (via
 * useAsyncGet with a stable key) and shows loading / error / empty / data
 * states. Nothing loops.
 */
export default function OverviewSection({ onGoTo }) {
  const navigate = useNavigate();
  const cash = useAsyncGet("/accounting/cash/dashboard", null, "cash");
  const health = useAsyncGet("/accounting/dashboard", null, "acct-health");
  const arAging = useAsyncGet("/accounting/reports/ar-aging", null, "ar-aging");
  const exceptions = useAsyncGet(
    "/accounting/reconciliation/exceptions", null, "recon-exceptions"
  );

  const refreshAll = () => {
    cash.refetch(); health.refetch(); arAging.refetch(); exceptions.refetch();
  };

  return (
    <div className="space-y-5" data-testid="overview-section">
      <div className="flex items-center justify-between">
        <div className="text-xs text-slate-500">
          Live snapshot from your ledger. Click any card to jump to the details.
        </div>
        <Button size="sm" variant="outline" onClick={refreshAll} className="rounded-full border-[#cfe0d3] text-[#2f6a4a]" data-testid="overview-refresh">
          <RefreshCw size={12} className="mr-1" /> Refresh all
        </Button>
      </div>

      <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Cash today */}
        <SnapshotCard
          testid="ov-cash"
          icon={Wallet}
          label="Cash today"
          onClick={() => onGoTo("money")}
          state={cash}
          render={(d) => fmt(d.totals?.current_cash_cents)}
        />
        {/* Revenue today */}
        <SnapshotCard
          testid="ov-revenue-today"
          icon={TrendingUp}
          label="Revenue today"
          tone="ok"
          onClick={() => onGoTo("reports")}
          state={health}
          render={(d) => fmt(d.revenue_today_cents)}
        />
        {/* Outstanding invoices */}
        <SnapshotCard
          testid="ov-ar"
          icon={Receipt}
          label="Outstanding invoices"
          onClick={() => onGoTo("sales")}
          state={arAging}
          render={(d) => fmt(d.total_cents)}
          sub={(d) => `${((d.buckets?.over_90 || 0) / 100).toFixed(0)} over 90d`}
        />
        {/* Expenses MTD (from dashboard cash-out proxy = payroll+SG&A) */}
        <SnapshotCard
          testid="ov-expenses"
          icon={Landmark}
          label="A/P outstanding"
          onClick={() => onGoTo("expenses")}
          state={health}
          render={(d) => fmt(d.accounts_payable_cents)}
        />
      </div>

      <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* Recon alerts */}
        <div className="rounded-2xl border border-[#e2ebe4] bg-white p-4 cursor-pointer hover:bg-[#f4f7f2] transition" onClick={() => onGoTo("money")} data-testid="ov-recon-alerts">
          <div className="flex items-center gap-2 text-[#3d6b52] mb-2">
            <AlertCircle size={14} />
            <div className="eyebrow">Reconciliation alerts</div>
          </div>
          <AsyncPanel {...exceptions} onRetry={exceptions.refetch}
            errorMessage="Couldn't load exceptions"
            emptyMessage="Nothing to reconcile 🎉">
            <ReconLine
              counts={exceptions.data?.counts || {}}
              onReview={() => onGoTo("money")}
            />
          </AsyncPanel>
        </div>

        {/* Ledger health snapshot */}
        <div className="rounded-2xl border border-[#e2ebe4] bg-white p-4 cursor-pointer hover:bg-[#f4f7f2] transition" onClick={() => onGoTo("advanced")} data-testid="ov-health">
          <div className="flex items-center gap-2 text-[#3d6b52] mb-2">
            <Activity size={14} />
            <div className="eyebrow">Ledger health</div>
          </div>
          <AsyncPanel {...health} onRetry={health.refetch} errorMessage="Couldn't load health">
            <div className="space-y-1 text-sm">
              <RowKV label="Balance check" value={
                <Badge className={health.data?.trial_balance?.balanced
                  ? "bg-[#eaf2ec] text-[#3d6b52]" : "bg-[#fdecec] text-[#7a2a2a]"}>
                  {health.data?.trial_balance?.balanced ? "Balanced" : "Off"}
                </Badge>
              } />
              <RowKV label="Unposted events" value={String(health.data?.unposted_event_count ?? "—")} />
              <RowKV label="Processing issues" value={String(health.data?.dead_letter_count ?? "—")} />
            </div>
          </AsyncPanel>
        </div>

        {/* Quick nav to reports */}
        <div className="rounded-2xl border border-[#e2ebe4] bg-white p-4 cursor-pointer hover:bg-[#f4f7f2] transition" onClick={() => onGoTo("reports")} data-testid="ov-reports">
          <div className="flex items-center gap-2 text-[#3d6b52] mb-2">
            <Package size={14} />
            <div className="eyebrow">Full reports</div>
          </div>
          <p className="text-xs text-slate-500 mb-3">
            Profit &amp; Loss, Balance Sheet, Cash Flow, Sales, Payroll, Tax — every report is one tap away.
          </p>
          <div className="text-sm text-[#2f6a4a] inline-flex items-center gap-1">
            Open reports <ChevronRight size={12} />
          </div>
        </div>
      </div>
    </div>
  );
}

function SnapshotCard({ testid, icon: Icon, label, onClick, state, render, sub, tone }) {
  const t = tone === "ok" ? "border-[#cfe0d3] bg-[#f6faf7]" : "border-[#e2ebe4] bg-white";
  return (
    <div className={`rounded-2xl border p-4 cursor-pointer hover:shadow-sm transition ${t}`} onClick={onClick} data-testid={testid}>
      <div className="flex items-center gap-2 text-[#3d6b52] mb-2">
        <Icon size={13} />
        <div className="eyebrow">{label}</div>
      </div>
      <AsyncPanel {...state} onRetry={state.refetch}
        errorMessage={`Couldn't load ${label.toLowerCase()}`}
        className="!p-0 !border-0 !bg-transparent !text-left"
        emptyMessage="—">
        <div className="font-display text-2xl">{render(state.data || {})}</div>
        {sub && <div className="text-xs text-slate-500 mt-1">{sub(state.data || {})}</div>}
      </AsyncPanel>
    </div>
  );
}

function ReconLine({ counts, onReview }) {
  const total = (counts.unmatched_bank_transactions || 0)
    + (counts.duplicate_bank_imports || 0)
    + (counts.amount_mismatches || 0)
    + (counts.duplicate_ledger_entries || 0);
  if (total === 0) {
    return <p className="text-xs text-slate-500">Everything matches. Great work.</p>;
  }
  return (
    <div className="space-y-1 text-sm">
      <RowKV label="Unmatched bank txns" value={String(counts.unmatched_bank_transactions || 0)} />
      <RowKV label="Duplicate imports" value={String(counts.duplicate_bank_imports || 0)} />
      <RowKV label="Amount mismatches" value={String(counts.amount_mismatches || 0)} />
      <RowKV label="Duplicate journals" value={String(counts.duplicate_ledger_entries || 0)} />
      <div className="pt-2 text-xs text-[#2f6a4a] inline-flex items-center gap-1 cursor-pointer" onClick={onReview}>
        Review in Money <ChevronRight size={11} />
      </div>
    </div>
  );
}

function RowKV({ label, value }) {
  return (
    <div className="flex justify-between text-sm">
      <span className="text-slate-500">{label}</span>
      <span>{value}</span>
    </div>
  );
}
