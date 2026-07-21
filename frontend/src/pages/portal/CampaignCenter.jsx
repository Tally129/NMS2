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
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "../../components/ui/dialog";
import {
  Send, Megaphone, Mail, MessageSquare, Users, Calendar, Loader2,
  AlertTriangle, CheckCircle2, Clock,
} from "lucide-react";
import { useToast } from "../../hooks/use-toast";
import { getErrorMessage } from "../../lib/errors";

const FILTER_TYPES = [
  { value: "all_marketing", label: "All marketing-opted-in patients" },
  { value: "inactive", label: "Inactive patients", param: "inactive_days", paramLabel: "Days inactive", defaultValue: "90" },
  { value: "upcoming_appointments", label: "Patients with upcoming appointments", param: "days_ahead", paramLabel: "Days ahead", defaultValue: "14" },
  { value: "due_for_followup", label: "Due for follow-up", param: "since_days", paramLabel: "Since (days)", defaultValue: "60" },
  { value: "membership", label: "Active members" },
  { value: "treatment_group", label: "Treatment / protocol group", param: "group_title", paramLabel: "Group title / plan name", defaultValue: "" },
];

const channelIcon = (c) => (c === "sms" ? MessageSquare : Mail);
const statusChip = (s) => ({
  scheduled: "bg-[#fdf3d0] text-[#8a6a3c]",
  sending: "bg-[#e0eaf3] text-[#3a5a7a]",
  sent: "bg-[#eaf2ec] text-[#3d6b52]",
  sent_with_failures: "bg-[#fdf3d0] text-[#8a6a3c]",
  failed: "bg-[#fdecec] text-[#7a2a2a]",
  draft: "bg-slate-100 text-slate-500",
}[s] || "bg-slate-100 text-slate-500");

export default function CampaignCenter() {
  const { toast } = useToast();
  const [campaigns, setCampaigns] = React.useState([]);
  const [showNew, setShowNew] = React.useState(false);
  const [selected, setSelected] = React.useState(null);

  const load = React.useCallback(async () => {
    try {
      const r = await api.get("/campaigns");
      setCampaigns(r.data || []);
    } catch (e) {
      toast({ title: "Could not load campaigns", description: getErrorMessage(e) || "" });
    }
  }, [toast]);

  React.useEffect(() => { load(); }, [load]);

  return (
    <PortalLayout>
      <PortalHeader
        title="Campaign center"
        subtitle="Outreach to opted-in patients only"
        actions={
          <Button
            onClick={() => setShowNew(true)}
            className="btn-lift h-11 rounded-full bg-[#2f6a4a] hover:bg-[#265739] text-white"
            data-testid="campaign-new-btn"
          >
            <Megaphone size={16} className="mr-2" /> New campaign
          </Button>
        }
      />

      <div className="rounded-2xl border border-[#e2ebe4] bg-white overflow-hidden" data-testid="campaign-list">
        {campaigns.length === 0 ? (
          <div className="p-10 text-center text-slate-500">
            <Megaphone size={26} className="mx-auto mb-3 text-slate-300" />
            No campaigns yet. Create one to reach opted-in patients.
          </div>
        ) : (
          <table className="w-full">
            <thead className="bg-[#f4f7f2] text-left text-xs uppercase tracking-wider text-slate-500">
              <tr>
                <th className="p-3">Title</th>
                <th className="p-3">Channel</th>
                <th className="p-3">Audience</th>
                <th className="p-3">Status</th>
                <th className="p-3">Stats</th>
                <th className="p-3">Created</th>
                <th className="p-3"></th>
              </tr>
            </thead>
            <tbody>
              {campaigns.map((c) => {
                const Icon = channelIcon(c.channel);
                return (
                  <tr key={c.id} className="border-t border-[#e2ebe4] hover:bg-[#fbfdfb]" data-testid={`campaign-row-${c.id}`}>
                    <td className="p-3 font-medium text-[#1f2a22]">{c.title}</td>
                    <td className="p-3 text-sm text-slate-700 inline-flex items-center gap-1">
                      <Icon size={13} /> {c.channel.toUpperCase()}
                    </td>
                    <td className="p-3 text-xs text-slate-500">
                      {FILTER_TYPES.find((f) => f.value === c.filter_type)?.label || c.filter_type}
                    </td>
                    <td className="p-3">
                      <span className={`px-2 py-1 rounded-full text-[11px] ${statusChip(c.status)}`}>
                        {c.status.replace(/_/g, " ")}
                      </span>
                    </td>
                    <td className="p-3 text-xs text-slate-600">
                      {c.stats
                        ? `${c.stats.success}✓ / ${c.stats.failure}✗ / ${c.stats.skipped} skipped`
                        : (c.schedule_at ? `Scheduled ${new Date(c.schedule_at).toLocaleString()}` : "—")}
                    </td>
                    <td className="p-3 text-xs text-slate-500">
                      {new Date(c.created_at).toLocaleDateString()}
                    </td>
                    <td className="p-3 text-right">
                      <Button
                        size="sm" variant="outline"
                        className="h-8 rounded-full border-[#cfe0d3] text-[#2f6a4a]"
                        onClick={() => setSelected(c)}
                        data-testid={`campaign-open-${c.id}`}
                      >
                        Details
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <NewCampaignDialog open={showNew} onOpenChange={setShowNew} onSent={() => { setShowNew(false); load(); }} />
      <CampaignDetail id={selected?.id} onClose={() => setSelected(null)} />
    </PortalLayout>
  );
}

function NewCampaignDialog({ open, onOpenChange, onSent }) {
  const { toast } = useToast();
  const [form, setForm] = React.useState({
    title: "", subject: "", message: "", channel: "email",
    filter_type: "all_marketing", filter_params: {}, mode: "now", schedule_at: "",
  });
  const [estimate, setEstimate] = React.useState(null);
  const [estimating, setEstimating] = React.useState(false);
  const [busy, setBusy] = React.useState(false);

  const filterConfig = FILTER_TYPES.find((f) => f.value === form.filter_type);

  React.useEffect(() => {
    // reset filter_params when type changes
    setForm((p) => ({
      ...p,
      filter_params: filterConfig?.param
        ? { [filterConfig.param]: filterConfig.defaultValue }
        : {},
    }));
    // eslint-disable-next-line
  }, [form.filter_type]);

  const runEstimate = async () => {
    setEstimating(true);
    setEstimate(null);
    try {
      const r = await api.post("/campaigns/estimate", {
        channel: form.channel,
        filter_type: form.filter_type,
        filter_params: form.filter_params,
      });
      setEstimate(r.data);
    } catch (e) {
      toast({ title: "Estimate failed", description: getErrorMessage(e) || "" });
    } finally { setEstimating(false); }
  };

  const submit = async () => {
    if (!form.title || !form.message) { toast({ title: "Title and message required" }); return; }
    if (form.channel === "email" && !form.subject) { toast({ title: "Subject required for email" }); return; }
    setBusy(true);
    try {
      const payload = {
        title: form.title,
        subject: form.subject || undefined,
        message: form.message,
        channel: form.channel,
        filter_type: form.filter_type,
        filter_params: form.filter_params,
        schedule_at: form.mode === "schedule" && form.schedule_at
          ? new Date(form.schedule_at).toISOString()
          : undefined,
      };
      const r = await api.post("/campaigns", payload);
      const s = r.data;
      if (s.status === "scheduled") {
        toast({ title: "Campaign scheduled",
                description: `${s.title} · runs ${new Date(s.schedule_at).toLocaleString()}` });
      } else {
        toast({ title: "Campaign dispatched",
                description: `${s.stats?.success ?? 0} sent · ${s.stats?.skipped ?? 0} skipped` });
      }
      onSent();
    } catch (e) {
      toast({ title: "Campaign failed", description: getErrorMessage(e) || "" });
    } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-white max-w-xl" data-testid="new-campaign-dialog">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">New campaign</DialogTitle>
          <DialogDescription>
            Marketing opt-outs are automatically excluded. Invalid contact methods are skipped.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <Label>Title (internal)</Label>
            <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })}
                   className="mt-1" data-testid="campaign-title" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Channel</Label>
              <Select value={form.channel} onValueChange={(v) => setForm({ ...form, channel: v })}>
                <SelectTrigger data-testid="campaign-channel"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="email">Email</SelectItem>
                  <SelectItem value="sms">SMS</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Audience</Label>
              <Select value={form.filter_type} onValueChange={(v) => setForm({ ...form, filter_type: v })}>
                <SelectTrigger data-testid="campaign-filter"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {FILTER_TYPES.map((f) => <SelectItem key={f.value} value={f.value}>{f.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
          {filterConfig?.param && (
            <div>
              <Label>{filterConfig.paramLabel}</Label>
              <Input
                value={form.filter_params[filterConfig.param] || ""}
                onChange={(e) => setForm({ ...form, filter_params: { [filterConfig.param]: e.target.value } })}
                className="mt-1"
                data-testid="campaign-filter-param"
              />
            </div>
          )}
          {form.channel === "email" && (
            <div>
              <Label>Email subject</Label>
              <Input value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })}
                     className="mt-1" data-testid="campaign-subject" />
            </div>
          )}
          <div>
            <Label>Message</Label>
            <Textarea rows={4} value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })} data-testid="campaign-message" />
          </div>
          <div className="flex gap-3 items-end">
            <div className="flex-1">
              <Label>Delivery</Label>
              <Select value={form.mode} onValueChange={(v) => setForm({ ...form, mode: v })}>
                <SelectTrigger data-testid="campaign-mode"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="now">Send now</SelectItem>
                  <SelectItem value="schedule">Schedule for later</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {form.mode === "schedule" && (
              <div className="flex-1">
                <Label>Send at</Label>
                <Input type="datetime-local"
                       value={form.schedule_at}
                       onChange={(e) => setForm({ ...form, schedule_at: e.target.value })}
                       data-testid="campaign-schedule-at" />
              </div>
            )}
          </div>

          {/* Recipient estimator */}
          <div className="rounded-lg border border-[#cfe0d3] bg-[#f6faf7] p-3">
            <div className="flex items-center justify-between mb-2">
              <div className="eyebrow text-[#3d6b52]">Estimated recipients</div>
              <Button
                size="sm" variant="outline"
                onClick={runEstimate} disabled={estimating}
                className="h-8 rounded-full border-[#cfe0d3] text-[#2f6a4a]"
                data-testid="campaign-estimate-btn"
              >
                {estimating ? <Loader2 className="animate-spin" size={13} /> : "Estimate"}
              </Button>
            </div>
            {estimate ? (
              <div className="text-sm text-slate-700 space-y-1" data-testid="campaign-estimate-result">
                <div><Users size={12} className="inline -mt-0.5" /> Eligible: <b>{estimate.eligible}</b></div>
                <div className="text-xs text-slate-500">
                  Candidates: {estimate.candidates} · Excluded: {estimate.skipped_total}
                </div>
                {Object.entries(estimate.skipped_by_reason || {}).length > 0 && (
                  <div className="text-xs text-slate-500">
                    Exclusions: {Object.entries(estimate.skipped_by_reason).map(([k, v]) => `${k.replace(/_/g," ")} ${v}`).join(" · ")}
                  </div>
                )}
              </div>
            ) : (
              <div className="text-xs text-slate-500">Click "Estimate" to see how many patients will receive this.</div>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            onClick={submit} disabled={busy}
            className="bg-[#2f6a4a] hover:bg-[#265739] text-white rounded-full"
            data-testid="campaign-submit"
          >
            {busy ? "Sending…" : (form.mode === "schedule"
              ? (<><Clock size={13} className="mr-1" /> Schedule</>)
              : (<><Send size={13} className="mr-1" /> Send now</>))}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function CampaignDetail({ id, onClose }) {
  const [c, setC] = React.useState(null);
  React.useEffect(() => {
    if (!id) return;
    api.get(`/campaigns/${id}`).then((r) => setC(r.data)).catch(() => setC(null));
  }, [id]);
  if (!id) return null;
  return (
    <Dialog open={!!id} onOpenChange={onClose}>
      <DialogContent className="bg-white max-w-2xl" data-testid="campaign-detail-dialog">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">{c?.title || "Campaign"}</DialogTitle>
          <DialogDescription>
            {c ? `${c.channel.toUpperCase()} · ${c.status.replace(/_/g, " ")}` : "Loading…"}
          </DialogDescription>
        </DialogHeader>
        {c && (
          <div className="space-y-3 text-sm">
            {c.subject && <div><b>Subject:</b> {c.subject}</div>}
            <div className="rounded-lg bg-[#f4f7f2] p-3 whitespace-pre-wrap">{c.message}</div>
            {c.stats && (
              <div className="grid grid-cols-4 gap-2 text-xs">
                <Stat label="Success" value={c.stats.success} tone="text-[#2f6a4a]" />
                <Stat label="Failure" value={c.stats.failure} tone="text-[#7a2a2a]" />
                <Stat label="Skipped" value={c.stats.skipped} tone="text-[#8a6a3c]" />
                <Stat label="Candidates" value={c.stats.candidates} tone="text-slate-500" />
              </div>
            )}
            {c.delivery_log?.length > 0 && (
              <div className="max-h-56 overflow-y-auto border-t border-[#e2ebe4] pt-3">
                <div className="text-xs eyebrow text-slate-500 mb-2">Delivery log</div>
                <table className="w-full text-xs">
                  <thead className="text-slate-400 text-left">
                    <tr><th>Recipient</th><th>Status</th><th>Reason</th><th>Time</th></tr>
                  </thead>
                  <tbody>
                    {c.delivery_log.slice(0, 200).map((row, i) => (
                      <tr key={i} className="border-t border-slate-100">
                        <td className="py-1">{(row.client_id || "").slice(0, 8)}…</td>
                        <td className="py-1">{row.status}</td>
                        <td className="py-1 text-slate-500">{row.reason || row.error || ""}</td>
                        <td className="py-1 text-slate-400">{row.ts ? new Date(row.ts).toLocaleTimeString() : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Stat({ label, value, tone }) {
  return (
    <div className="rounded-lg border border-[#e2ebe4] bg-white p-2 text-center">
      <div className={`text-xl font-display ${tone}`}>{value}</div>
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
    </div>
  );
}
