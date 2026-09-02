import React from "react";

import api from "../../lib/api";
import { toast } from "sonner";

import { Button } from "../../components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "../../components/ui/sheet";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../components/ui/select";
import { Textarea } from "../../components/ui/textarea";
import { Input } from "../../components/ui/input";

import {
  Users,
  Loader2,
  RefreshCw,
  ShieldCheck,
  AlertTriangle,
  Clock,
} from "lucide-react";


const VIEWS = [
  { key: "", label: "All" },
  { key: "new_leads", label: "New" },
  { key: "needs_attention", label: "Needs Attention" },
  { key: "follow_up_today", label: "Follow Up Today" },
  { key: "appointment_requested", label: "Appt. Requested" },
  { key: "booked", label: "Booked" },
  { key: "no_show", label: "No Show" },
  { key: "nurture", label: "Nurture" },
  { key: "won", label: "Won" },
  { key: "lost", label: "Lost" },
];

const LEAD_STAGES = [
  "new", "contact_attempted", "contacted", "qualified", "nurture",
  "appointment_requested", "booked", "confirmed", "showed", "no_show",
  "won", "lost",
];

const TASK_TYPES = [
  "call_lead", "email_lead", "review_qualification", "schedule_appointment",
  "confirm_appointment", "recover_no_show", "follow_up_later",
];

const METRIC_TILES = [
  { key: "total_leads", label: "Total Leads", kind: "int" },
  { key: "total_new_leads", label: "New", kind: "int" },
  { key: "uncontacted_leads", label: "Uncontacted", kind: "int" },
  { key: "overdue_leads", label: "Overdue", kind: "int" },
  { key: "contact_rate", label: "Contact Rate", kind: "pct" },
  { key: "booking_rate", label: "Booking Rate", kind: "pct" },
  { key: "show_rate", label: "Show Rate", kind: "pct" },
];


function fmt(kind, value) {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  if (kind === "pct") return `${(n * 100).toFixed(1)}%`;
  if (kind === "int") return Math.round(n).toLocaleString();
  return String(value);
}


function leadAge(created) {
  if (!created) return "—";
  const then = new Date(created).getTime();
  if (Number.isNaN(then)) return "—";
  const mins = Math.max(0, Math.floor((Date.now() - then) / 60000));
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  return `${Math.floor(hrs / 24)}d`;
}


function subjectLabel(lead) {
  const s = lead?.marketing_subject_id || "";
  return s.length > 10 ? `Lead ${s.slice(0, 8)}…` : `Lead ${s}`;
}


function PriorityDot({ priority }) {
  const color =
    priority === "high" ? "bg-[#c0603a]"
      : priority === "low" ? "bg-[#9aa39a]"
        : "bg-[#c9a24b]";
  return (
    <span className={`inline-block h-2.5 w-2.5 rounded-full ${color}`}
      title={priority} />
  );
}


function speedLabel(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const s = Number(seconds);
  if (!Number.isFinite(s)) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}


function LeadDetailDrawer({ leadId, open, onClose, onChanged }) {
  const [loading, setLoading] = React.useState(false);
  const [detail, setDetail] = React.useState(null);
  const [timeline, setTimeline] = React.useState([]);
  const [nextStatus, setNextStatus] = React.useState("");
  const [ownerInput, setOwnerInput] = React.useState("");
  const [taskType, setTaskType] = React.useState(TASK_TYPES[0]);

  const load = React.useCallback(async () => {
    if (!leadId) return;
    setLoading(true);
    try {
      const [d, t] = await Promise.all([
        api.get(`/marketing-os/leads/${leadId}`),
        api.get(`/marketing-os/leads/${leadId}/timeline`),
      ]);
      setDetail(d.data || null);
      setTimeline(t.data?.timeline || []);
      setOwnerInput(d.data?.lead?.assigned_owner_id || "");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not load lead");
    } finally {
      setLoading(false);
    }
  }, [leadId]);

  React.useEffect(() => {
    if (open) load();
  }, [open, load]);

  const lead = detail?.lead || null;
  const tasks = detail?.tasks || [];

  const changeStatus = async () => {
    if (!nextStatus) return;
    try {
      await api.patch(`/marketing-os/leads/${leadId}/status`, {
        lead_status: nextStatus,
      });
      toast.success(`Stage changed to ${nextStatus}`);
      setNextStatus("");
      await load();
      onChanged?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Transition not allowed");
    }
  };

  const reassign = async () => {
    try {
      await api.patch(`/marketing-os/leads/${leadId}/owner`, {
        assigned_owner_id: ownerInput.trim() || null,
      });
      toast.success("Owner updated");
      await load();
      onChanged?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not reassign");
    }
  };

  const addTask = async () => {
    try {
      await api.post(`/marketing-os/leads/tasks`, {
        lead_id: leadId, task_type: taskType,
      });
      toast.success("Task created");
      await load();
      onChanged?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not create task");
    }
  };

  const completeTask = async (taskId) => {
    try {
      await api.patch(`/marketing-os/leads/tasks/${taskId}`, {
        status: "completed",
      });
      await load();
      onChanged?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not update task");
    }
  };

  return (
    <Sheet open={open} onOpenChange={(v) => !v && onClose()}>
      <SheetContent
        className="w-full overflow-y-auto sm:max-w-xl"
        data-testid="lead-detail-drawer"
      >
        <SheetHeader>
          <SheetTitle>{lead ? subjectLabel(lead) : "Lead"}</SheetTitle>
        </SheetHeader>

        {loading || !lead ? (
          <div className="flex items-center gap-2 py-8 text-sm text-[#6a6a6a]">
            <Loader2 size={16} className="animate-spin" /> Loading…
          </div>
        ) : (
          <div className="mt-4 space-y-5 text-sm">
            {/* Attribution */}
            <div className="rounded-xl border border-[#e7dfc9] bg-white p-4">
              <div className="mb-2 text-[10px] uppercase tracking-widest text-[#8a6a3c]">
                Attribution
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>Source: <b>{lead.source || "—"}</b></div>
                <div>Medium: <b>{lead.medium || "—"}</b></div>
                <div>Campaign: <b>{lead.campaign_name || "—"}</b></div>
                <div>Method: <b>{lead.attribution_model || "—"}</b></div>
                <div>Opportunity: <b>{lead.opportunity_score ?? "—"}</b></div>
                <div>Priority: <b>{lead.priority}</b></div>
                <div>Appt: <b>{lead.appointment_status || "—"}</b></div>
                <div>Qualification: <b>{lead.qualification_status}</b></div>
                <div>Service Interest: <b>{lead.service_interest || "—"}</b></div>
                <div>Response: <b>{speedLabel(lead.first_response_seconds)}</b></div>
              </div>
            </div>

            {/* Status */}
            <div className="rounded-xl border border-[#e7dfc9] bg-white p-4">
              <div className="mb-2 text-[10px] uppercase tracking-widest text-[#8a6a3c]">
                Stage: <b>{lead.lead_status}</b>
              </div>
              <div className="flex items-center gap-2">
                <Select value={nextStatus} onValueChange={setNextStatus}>
                  <SelectTrigger className="w-full"
                    data-testid="lead-status-select">
                    <SelectValue placeholder="Move to stage…" />
                  </SelectTrigger>
                  <SelectContent>
                    {LEAD_STAGES.map((s) => (
                      <SelectItem key={s} value={s}
                        data-testid={`lead-status-option-${s}`}>{s}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button size="sm" onClick={changeStatus}
                  disabled={!nextStatus} data-testid="lead-status-apply">
                  Apply
                </Button>
              </div>
            </div>

            {/* Owner */}
            <div className="rounded-xl border border-[#e7dfc9] bg-white p-4">
              <div className="mb-2 text-[10px] uppercase tracking-widest text-[#8a6a3c]">
                Owner
              </div>
              <div className="flex items-center gap-2">
                <Input value={ownerInput}
                  onChange={(e) => setOwnerInput(e.target.value)}
                  placeholder="Staff user id (blank = unassign)"
                  data-testid="lead-owner-input" />
                <Button size="sm" variant="outline" onClick={reassign}
                  data-testid="lead-owner-apply">Assign</Button>
              </div>
            </div>

            {/* Tasks */}
            <div className="rounded-xl border border-[#e7dfc9] bg-white p-4">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-widest text-[#8a6a3c]">
                  Tasks
                </span>
              </div>
              <div className="mb-3 flex items-center gap-2">
                <Select value={taskType} onValueChange={setTaskType}>
                  <SelectTrigger className="w-full"
                    data-testid="lead-task-type-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TASK_TYPES.map((t) => (
                      <SelectItem key={t} value={t}>{t}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button size="sm" onClick={addTask}
                  data-testid="lead-task-add">Add</Button>
              </div>
              <div className="space-y-1">
                {tasks.length === 0 ? (
                  <div className="text-xs text-[#6a6a6a]">No tasks yet.</div>
                ) : tasks.map((t) => (
                  <div key={t.id}
                    className="flex items-center justify-between text-xs"
                    data-testid={`lead-task-${t.id}`}>
                    <span>
                      {t.task_type} · <span className="text-[#6a6a6a]">
                        {t.status}</span>
                    </span>
                    {t.status === "open" && (
                      <Button size="sm" variant="ghost"
                        onClick={() => completeTask(t.id)}
                        data-testid={`lead-task-complete-${t.id}`}>
                        Complete
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Timeline */}
            <div className="rounded-xl border border-[#e7dfc9] bg-white p-4">
              <div className="mb-2 text-[10px] uppercase tracking-widest text-[#8a6a3c]">
                Activity Timeline
              </div>
              <div className="space-y-2" data-testid="lead-timeline">
                {timeline.length === 0 ? (
                  <div className="text-xs text-[#6a6a6a]">No activity yet.</div>
                ) : timeline.map((a) => (
                  <div key={a.id} className="text-xs">
                    <span className="font-medium">{a.activity_type}</span>
                    {a.summary ? ` — ${a.summary}` : ""}
                    <div className="text-[10px] text-[#9aa39a]">
                      {a.occurred_at
                        ? new Date(a.occurred_at).toLocaleString() : ""}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}


export default function LeadOperationsPanel() {
  const [loading, setLoading] = React.useState(true);
  const [refreshing, setRefreshing] = React.useState(false);
  const [error, setError] = React.useState("");
  const [view, setView] = React.useState("");
  const [leads, setLeads] = React.useState([]);
  const [metrics, setMetrics] = React.useState(null);
  const [activeLead, setActiveLead] = React.useState(null);

  const load = React.useCallback(async (v, { manual = false } = {}) => {
    if (manual) setRefreshing(true); else setLoading(true);
    setError("");
    try {
      const q = v ? `?view=${v}` : "";
      const [l, m] = await Promise.all([
        api.get(`/marketing-os/leads${q}`),
        api.get(`/marketing-os/leads/metrics`),
      ]);
      setLeads(l.data?.leads || []);
      setMetrics(m.data || null);
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message ||
        "Could not load lead operations.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  React.useEffect(() => { load(view); }, [load, view]);

  const speed = metrics?.speed_to_lead || {};

  return (
    <section
      className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5"
      data-testid="lead-operations-panel"
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-widest text-[#8a6a3c]">
            Appointment Setter • Lead Queue
          </div>
          <div className="flex items-center gap-2 font-display text-xl text-[#1f2a22]">
            <Users size={18} className="text-[#2f4a3a]" />
            Lead Operations
          </div>
        </div>
        <Button type="button" variant="outline" size="sm"
          onClick={() => load(view, { manual: true })}
          disabled={refreshing || loading} data-testid="lead-ops-refresh">
          {refreshing
            ? <Loader2 size={14} className="mr-2 animate-spin" />
            : <RefreshCw size={14} className="mr-2" />}
          Refresh
        </Button>
      </div>

      <div className="mb-4 flex items-center gap-2 rounded-lg border border-[#b9d2bf] bg-[#edf5ef] px-3 py-2 text-xs text-[#2f6a4a]"
        data-testid="lead-ops-safety-note">
        <ShieldCheck size={14} />
        Internal staff workflow. No automatic outreach, no external provider
        writes, no PHI. Stage changes require staff action.
      </div>

      {/* Metrics */}
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
        {METRIC_TILES.map((t) => (
          <div key={t.key}
            className="rounded-xl border border-[#e7dfc9] bg-white p-3"
            data-testid={`lead-metric-${t.key}`}>
            <div className="text-[10px] uppercase tracking-widest text-[#8a6a3c]">
              {t.label}
            </div>
            <div className="mt-1 text-lg font-semibold text-[#1f2a22]">
              {fmt(t.kind, metrics?.[t.key])}
            </div>
          </div>
        ))}
        <div className="rounded-xl border border-[#e7dfc9] bg-white p-3"
          data-testid="lead-metric-speed">
          <div className="text-[10px] uppercase tracking-widest text-[#8a6a3c]">
            Avg Speed
          </div>
          <div className="mt-1 text-lg font-semibold text-[#1f2a22]">
            {speedLabel(speed.average_speed_to_lead_seconds)}
          </div>
        </div>
      </div>

      {/* View tabs */}
      <div className="mb-3 flex flex-wrap gap-1" data-testid="lead-view-tabs">
        {VIEWS.map((v) => (
          <button key={v.key || "all"} type="button"
            onClick={() => setView(v.key)}
            data-testid={`lead-view-${v.key || "all"}`}
            className={
              "rounded-full px-3 py-1 text-xs font-semibold transition-colors " +
              (view === v.key
                ? "bg-[#2f4a3a] text-white"
                : "border border-[#e7dfc9] bg-white text-[#6a6a6a] hover:text-[#1f2a22]")
            }>
            {v.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center gap-2 px-1 py-6 text-sm text-[#6a6a6a]"
          data-testid="lead-ops-loading">
          <Loader2 size={16} className="animate-spin" /> Loading leads…
        </div>
      ) : error ? (
        <div className="rounded-xl border border-[#d9b7b7] bg-[#f9eeee] px-4 py-6 text-sm text-[#7a2a2a]"
          data-testid="lead-ops-error">{error}</div>
      ) : leads.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[#d8cba9] bg-white px-4 py-8 text-center text-sm text-[#6a6a6a]"
          data-testid="lead-ops-empty">
          No leads in this view yet. Use "Sync from events" to build the queue
          from marketing activity.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-[#e7dfc9] bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#e7dfc9] text-left text-[10px] uppercase tracking-widest text-[#8a6a3c]">
                <th className="p-3">Lead</th>
                <th className="p-3">Source</th>
                <th className="p-3">Campaign</th>
                <th className="p-3">Age</th>
                <th className="p-3">Score</th>
                <th className="p-3">Priority</th>
                <th className="p-3">Status</th>
                <th className="p-3">Appt</th>
                <th className="p-3">Owner</th>
                <th className="p-3"></th>
              </tr>
            </thead>
            <tbody>
              {leads.map((lead) => (
                <tr key={lead.id}
                  className="cursor-pointer border-b border-[#f0eadb] last:border-0 hover:bg-[#fbf7ee]"
                  onClick={() => setActiveLead(lead.id)}
                  data-testid={`lead-row-${lead.id}`}>
                  <td className="p-3 font-medium text-[#1f2a22]">
                    {subjectLabel(lead)}
                  </td>
                  <td className="p-3">{lead.source || "—"}</td>
                  <td className="p-3">{lead.campaign_name || "—"}</td>
                  <td className="p-3">{leadAge(lead.lead_created_at || lead.created_at)}</td>
                  <td className="p-3">{lead.opportunity_score ?? "—"}</td>
                  <td className="p-3"><PriorityDot priority={lead.priority} /></td>
                  <td className="p-3">{lead.lead_status}</td>
                  <td className="p-3">{lead.appointment_status || "—"}</td>
                  <td className="p-3 text-xs">{lead.assigned_owner_id || "—"}</td>
                  <td className="p-3">
                    {lead.overdue_task_count > 0 && (
                      <span className="inline-flex items-center gap-1 text-[11px] text-[#c0603a]"
                        title="Overdue task"
                        data-testid={`lead-overdue-${lead.id}`}>
                        <AlertTriangle size={12} /> overdue
                      </span>
                    )}
                    {lead.next_action_at && (
                      <span className="ml-1 inline-flex items-center gap-1 text-[11px] text-[#8a6a3c]">
                        <Clock size={12} />
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <LeadDetailDrawer
        leadId={activeLead}
        open={Boolean(activeLead)}
        onClose={() => setActiveLead(null)}
        onChanged={() => load(view, { manual: true })}
      />
    </section>
  );
}
