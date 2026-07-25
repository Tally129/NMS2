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
import RichTextEditor, { fillVariables } from "../../components/RichTextEditor";

// Preview merge-field context — realistic placeholder values so template
// authors can visualize the final email/SMS without touching real patient data.
const PREVIEW_CONTEXT = {
  patient: { first_name: "Alex", last_name: "Rivera", full_name: "Alex Rivera",
             email: "alex.rivera@example.com", phone: "(555) 123-4567" },
  appointment: { date: "Tue, Mar 4", time: "10:30 AM", provider: "Dr. Ravello" },
  provider: { name: "Dr. Ravello" },
  membership: { name: "Vitality Plan" },
  package: { name: "Detox Package" },
  clinic: { name: "Natural Medical Solutions", phone: "(770) 674-6311",
             email: "info@natmedsol.com" },
};

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
  processing: "bg-[#e0eaf3] text-[#3a5a7a]",
  sent: "bg-[#eaf2ec] text-[#3d6b52]",
  completed: "bg-[#eaf2ec] text-[#3d6b52]",
  sent_with_failures: "bg-[#fdf3d0] text-[#8a6a3c]",
  failed: "bg-[#fdecec] text-[#7a2a2a]",
  cancelled: "bg-slate-100 text-slate-500",
  draft: "bg-slate-100 text-slate-500",
}[s] || "bg-slate-100 text-slate-500");

export default function CampaignCenter() {
  const { toast } = useToast();
  const [campaigns, setCampaigns] = React.useState([]);
  const [config, setConfig] = React.useState(null);
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
  React.useEffect(() => {
    api.get("/campaigns/config/delivery")
      .then((r) => setConfig(r.data))
      .catch(() => setConfig(null));
  }, []);

  const cancel = async (c) => {
    try {
      await api.post(`/campaigns/${c.id}/cancel`);
      toast({ title: "Campaign cancelled" });
      load();
    } catch (e) {
      toast({ title: "Cancel failed", description: getErrorMessage(e) || "" });
    }
  };
  const retry = async (c) => {
    try {
      await api.post(`/campaigns/${c.id}/retry`);
      toast({ title: "Campaign retrying" });
      load();
    } catch (e) {
      toast({ title: "Retry failed", description: getErrorMessage(e) || "" });
    }
  };
  const duplicate = async (c) => {
    try {
      const r = await api.post(`/campaigns/${c.id}/duplicate`);
      toast({ title: "Draft created", description: r.data.title });
      load();
    } catch (e) {
      toast({ title: "Duplicate failed", description: getErrorMessage(e) || "" });
    }
  };
  const archive = async (c) => {
    try {
      await api.post(`/campaigns/${c.id}/archive`);
      toast({ title: "Campaign archived" });
      load();
    } catch (e) {
      toast({ title: "Archive failed", description: getErrorMessage(e) || "" });
    }
  };
  const pause = async (c) => {
    try {
      await api.post(`/campaigns/${c.id}/pause`);
      toast({ title: "Campaign paused" });
      load();
    } catch (e) {
      toast({ title: "Pause failed", description: getErrorMessage(e) || "" });
    }
  };
  const resume = async (c) => {
    try {
      const r = await api.post(`/campaigns/${c.id}/resume`);
      toast({ title: `Campaign resumed → ${r.data.status}` });
      load();
    } catch (e) {
      toast({ title: "Resume failed", description: getErrorMessage(e) || "" });
    }
  };
  const testSend = async (c) => {
    const to = window.prompt("Test send this campaign to which email?", "");
    if (!to) return;
    try {
      const r = await api.post(`/campaigns/${c.id}/test-send`, { recipients: [to] });
      const d = r.data.results?.[0]?.delivery;
      toast({
        title: `Test email ${d === "sent" ? "sent" : d === "sent_stub" ? "queued (stub)" : d}`,
        description: to,
      });
    } catch (e) {
      toast({ title: "Test send failed", description: getErrorMessage(e) || "" });
    }
  };

  const [showTemplates, setShowTemplates] = React.useState(false);
  const [prefill, setPrefill] = React.useState(null);
  return (
    <PortalLayout>
      <PortalHeader
        title="Campaign center"
        subtitle="Outreach to opted-in patients only"
        actions={
          <div className="flex gap-2">
            <Button
              onClick={() => setShowTemplates(true)}
              variant="outline"
              className="h-11 rounded-full border-[#c19a4b] text-[#8a6a3c]"
              data-testid="campaign-templates-btn"
            >
              <Mail size={16} className="mr-2" /> Templates
            </Button>
            <Button
              onClick={() => { setPrefill(null); setShowNew(true); }}
              className="btn-lift h-11 rounded-full bg-[#2f6a4a] hover:bg-[#265739] text-white"
              data-testid="campaign-new-btn"
            >
              <Megaphone size={16} className="mr-2" /> New campaign
            </Button>
          </div>
        }
      />

      {config && config.simulated && (
        <div
          data-testid="campaign-simulated-banner"
          className="mb-5 rounded-2xl border border-[#e6d38a] bg-[#fdf3d0] p-4 flex items-start gap-3"
        >
          <AlertTriangle size={16} className="mt-0.5 text-[#8a6a3c] flex-shrink-0" />
          <div className="text-sm text-[#8a6a3c]">
            <div className="font-medium">Simulated delivery — no live messages will be sent.</div>
            <div className="text-xs mt-1">
              Email: {config.email.mode === "live" ? "LIVE (SendGrid)" : "SIMULATED (sent_stub)"}
              {" · "}
              SMS: {config.sms.mode === "live" ? "LIVE (Twilio)" : "SIMULATED (sent_stub)"}
              {!config.email.sendgrid_api_key && " · Missing SENDGRID_API_KEY"}
              {!config.email.sendgrid_from_email && " · Missing SENDGRID_FROM_EMAIL"}
              {!config.sms.twilio_account_sid && " · Missing TWILIO_ACCOUNT_SID"}
              {!config.sms.twilio_auth_token && " · Missing TWILIO_AUTH_TOKEN"}
              {!config.sms.twilio_from_number && " · Missing TWILIO_FROM_NUMBER"}
            </div>
          </div>
        </div>
      )}

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
                    <td className="p-3 text-right space-x-1">
                      <Button
                        size="sm" variant="outline"
                        className="h-8 rounded-full border-[#cfe0d3] text-[#2f6a4a]"
                        onClick={() => setSelected(c)}
                        data-testid={`campaign-open-${c.id}`}
                      >
                        Details
                      </Button>
                      {c.status === "scheduled" && (
                        <Button
                          size="sm" variant="outline"
                          className="h-8 rounded-full border-[#f0b4b4] text-[#7a2a2a]"
                          onClick={() => cancel(c)}
                          data-testid={`campaign-cancel-${c.id}`}
                        >
                          Cancel
                        </Button>
                      )}
                      {(c.status === "scheduled" || c.status === "sending") && (
                        <Button
                          size="sm" variant="outline"
                          className="h-8 rounded-full border-[#c19a4b] text-[#8a6a3c]"
                          onClick={() => pause(c)}
                          data-testid={`campaign-pause-${c.id}`}
                        >
                          Pause
                        </Button>
                      )}
                      {c.status === "paused" && (
                        <Button
                          size="sm" variant="outline"
                          className="h-8 rounded-full border-[#2f6a4a] text-[#2f6a4a]"
                          onClick={() => resume(c)}
                          data-testid={`campaign-resume-${c.id}`}
                        >
                          Resume
                        </Button>
                      )}
                      {c.status === "failed" && (
                        <Button
                          size="sm" variant="outline"
                          className="h-8 rounded-full border-[#e6d38a] text-[#8a6a3c]"
                          onClick={() => retry(c)}
                          data-testid={`campaign-retry-${c.id}`}
                        >
                          Retry
                        </Button>
                      )}
                      {["draft", "scheduled", "paused"].includes(c.status) && c.channel === "email" && (
                        <Button
                          size="sm" variant="outline"
                          className="h-8 rounded-full border-[#8a6a3c] text-[#8a6a3c]"
                          onClick={() => testSend(c)}
                          data-testid={`campaign-test-${c.id}`}
                        >
                          Test send
                        </Button>
                      )}
                      <Button
                        size="sm" variant="outline"
                        className="h-8 rounded-full border-slate-300 text-slate-600"
                        onClick={() => duplicate(c)}
                        data-testid={`campaign-duplicate-${c.id}`}
                      >
                        Duplicate
                      </Button>
                      {!c.archived_at && ["sent", "completed", "failed", "cancelled"].includes(c.status) && (
                        <Button
                          size="sm" variant="ghost"
                          className="h-8 rounded-full text-slate-500"
                          onClick={() => archive(c)}
                          data-testid={`campaign-archive-${c.id}`}
                        >
                          Archive
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <NewCampaignDialog open={showNew} onOpenChange={setShowNew} initial={prefill} onSent={() => { setShowNew(false); setPrefill(null); load(); }} />
      <TemplatePickerDialog
        open={showTemplates}
        onClose={() => setShowTemplates(false)}
        onPick={(tpl) => {
          setShowTemplates(false);
          setPrefill({
            title: tpl.name,
            subject: tpl.subject,
            message: tpl.html,
            channel: "email",
            kind: tpl.kind || "marketing",
          });
          setShowNew(true);
        }}
      />
      <CampaignDetail id={selected?.id} onClose={() => setSelected(null)} />
    </PortalLayout>
  );
}

function NewCampaignDialog({ open, onOpenChange, onSent, initial }) {
  const { toast } = useToast();
  const [form, setForm] = React.useState({
    title: "", subject: "", message: "", message_text: "", channel: "email",
    filter_type: "all_marketing", filter_params: {}, mode: "now", schedule_at: "",
    kind: "marketing",
  });
  React.useEffect(() => {
    // Reset when the dialog opens; apply optional template prefill.
    if (open) {
      setForm((prev) => ({
        ...prev,
        title: initial?.title || "",
        subject: initial?.subject || "",
        message: initial?.message || "",
        message_text: "",
        channel: initial?.channel || "email",
        kind: initial?.kind || "marketing",
        filter_type: "all_marketing",
        filter_params: {},
        mode: "now",
        schedule_at: "",
      }));
      setEstimate(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initial]);
  const [estimate, setEstimate] = React.useState(null);
  const [estimating, setEstimating] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [showPreview, setShowPreview] = React.useState(false);

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
        kind: form.kind || "marketing",
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
      <DialogContent className="bg-white max-w-2xl" data-testid="new-campaign-dialog">
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
            <div className="flex items-center justify-between">
              <Label>{form.channel === "email" ? "Message (rich text)" : "Message (plain text)"}</Label>
              <button
                type="button"
                onClick={() => setShowPreview((v) => !v)}
                className="text-xs text-[#2f6a4a] hover:underline"
                data-testid="campaign-preview-toggle"
              >
                {showPreview ? "Hide preview" : "Show preview"}
              </button>
            </div>
            {form.channel === "email" ? (
              <div className="mt-1">
                <RichTextEditor
                  value={form.message}
                  onChange={(html) => setForm((p) => ({ ...p, message: html }))}
                  onPlainTextChange={(txt) => setForm((p) => ({ ...p, message_text: txt }))}
                  placeholder="Compose an email. Use the variables menu to insert merge fields."
                  testid="campaign-editor"
                />
              </div>
            ) : (
              <Textarea rows={4}
                value={form.message}
                onChange={(e) => setForm({ ...form, message: e.target.value })}
                placeholder="SMS message body. Merge fields like {{patient.first_name}} substitute at send time."
                data-testid="campaign-message" />
            )}
            {showPreview && (
              <div className="mt-2 rounded-lg border border-[#e2ebe4] bg-[#f7fbf8] p-3 max-h-56 overflow-y-auto"
                   data-testid="campaign-preview">
                {form.channel === "email" ? (
                  <div className="prose prose-sm max-w-none"
                       dangerouslySetInnerHTML={{ __html: fillVariables(form.message || "", PREVIEW_CONTEXT) }} />
                ) : (
                  <div className="whitespace-pre-wrap text-sm text-slate-700">
                    {fillVariables(form.message || "", PREVIEW_CONTEXT)}
                  </div>
                )}
              </div>
            )}
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
            {c.message && String(c.message).trim().startsWith("<") ? (
              <div
                className="rounded-lg bg-[#f4f7f2] p-3 prose prose-sm max-w-none"
                dangerouslySetInnerHTML={{ __html: c.message }}
              />
            ) : (
              <div className="rounded-lg bg-[#f4f7f2] p-3 whitespace-pre-wrap">{c.message}</div>
            )}
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

function TemplatePickerDialog({ open, onClose, onPick }) {
  const [templates, setTemplates] = React.useState({ defaults: [], custom: [] });
  const [category, setCategory] = React.useState("all");
  const [loading, setLoading] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    setLoading(true);
    api.get("/campaign-templates")
      .then((r) => setTemplates(r.data || { defaults: [], custom: [] }))
      .catch(() => setTemplates({ defaults: [], custom: [] }))
      .finally(() => setLoading(false));
  }, [open]);

  const all = [...templates.defaults, ...templates.custom];
  const filtered = category === "all" ? all : all.filter((t) => t.category === category);
  const categories = Array.from(new Set(all.map((t) => t.category))).sort();

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent className="bg-white max-w-3xl" data-testid="template-picker-dialog">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">Email template library</DialogTitle>
          <DialogDescription>
            Start from a template. You'll be able to edit every field before sending.
          </DialogDescription>
        </DialogHeader>
        <div className="flex gap-2 flex-wrap mb-3">
          <button
            onClick={() => setCategory("all")}
            className={`px-3 py-1 rounded-full text-xs border ${category === "all" ? "bg-[#2f6a4a] text-white border-[#2f6a4a]" : "border-[#e0d6bc] text-[#8a6a3c]"}`}
            data-testid="template-cat-all"
          >All ({all.length})</button>
          {categories.map((c) => (
            <button
              key={c}
              onClick={() => setCategory(c)}
              className={`px-3 py-1 rounded-full text-xs border ${category === c ? "bg-[#2f6a4a] text-white border-[#2f6a4a]" : "border-[#e0d6bc] text-[#8a6a3c]"}`}
              data-testid={`template-cat-${c}`}
            >{c.replace(/_/g, " ")}</button>
          ))}
        </div>
        {loading ? (
          <div className="p-6 text-center text-sm text-slate-500">Loading templates…</div>
        ) : (
          <div className="grid sm:grid-cols-2 gap-3 max-h-[520px] overflow-y-auto pr-1">
            {filtered.map((t) => (
              <button
                key={t.id}
                onClick={() => onPick(t)}
                className="text-left rounded-xl border border-[#e0d6bc] bg-[#fbf7ee] p-3 hover:bg-[#f1ead8] transition"
                data-testid={`template-${t.id}`}
              >
                <div className="flex items-center justify-between">
                  <div className="font-medium text-[#1f2a22] text-sm">{t.name}</div>
                  <span className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded ${t.kind === "transactional" ? "bg-[#e0eaf3] text-[#3a5a7a]" : "bg-[#eaf2ec] text-[#3d6b52]"}`}>
                    {t.kind || "marketing"}
                  </span>
                </div>
                <div className="text-xs text-[#6a6a6a] mt-1">{t.subject}</div>
                <div className="text-[10px] text-[#8a6a3c] mt-2 uppercase tracking-widest">{t.category?.replace(/_/g, " ")}</div>
              </button>
            ))}
            {filtered.length === 0 && <div className="col-span-2 text-sm text-slate-500 p-6 text-center">No templates in this category.</div>}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
