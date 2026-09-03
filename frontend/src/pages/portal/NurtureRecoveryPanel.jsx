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
import { Textarea } from "../../components/ui/textarea";

import {
  AlarmClock,
  CheckCircle2,
  Loader2,
  Mail,
  Plus,
  RefreshCw,
  ShieldCheck,
  SkipForward,
  Sprout,
} from "lucide-react";


function SectionCard({ title, subtitle, icon: Icon, actions, children, testId }) {
  return (
    <section
      className="rounded-2xl border border-[#d8cba9] bg-[#fbf7ee] p-5"
      data-testid={testId}
    >
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          {Icon ? (
            <div className="rounded-xl border border-[#d8cba9] bg-white p-2 text-[#8a6a3c]">
              <Icon size={18} />
            </div>
          ) : null}
          <div>
            <h3 className="text-lg font-semibold text-[#3f3320]">{title}</h3>
            {subtitle ? (
              <p className="mt-1 max-w-3xl text-sm text-[#806837]">{subtitle}</p>
            ) : null}
          </div>
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}


function EmptyState({ children }) {
  return (
    <div className="rounded-xl border border-dashed border-[#c9b98e] bg-white px-4 py-6 text-center text-sm text-[#806837]">
      {children}
    </div>
  );
}


function StatusBadge({ status }) {
  const tone = {
    active: "bg-emerald-100 text-emerald-800",
    completed: "bg-sky-100 text-sky-800",
    stopped: "bg-amber-100 text-amber-800",
    failed: "bg-rose-100 text-rose-800",
    pending_approval: "bg-amber-100 text-amber-800",
    approved: "bg-emerald-100 text-emerald-800",
    held: "bg-slate-200 text-slate-700",
    skipped: "bg-slate-200 text-slate-700",
    cancelled: "bg-slate-200 text-slate-700",
    draft: "bg-slate-200 text-slate-700",
  }[status] || "bg-slate-200 text-slate-700";
  return (
    <span className={"rounded-full px-2 py-0.5 text-[11px] font-medium " + tone}>
      {status}
    </span>
  );
}


const INITIAL_SEQUENCE = {
  name: "",
  slug: "",
  trigger_type: "manual",
};

const INITIAL_STEP = {
  step_key: "",
  action_type: "create_task",
  delay_minutes: "0",
  subject: "",
  body_html: "",
  task_type: "recover_no_show",
};

const TASK_TYPES = [
  "recover_no_show",
  "follow_up_later",
  "call_lead",
  "email_lead",
  "confirm_appointment",
  "schedule_appointment",
  "review_qualification",
];


export default function NurtureRecoveryPanel() {
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [success, setSuccess] = React.useState("");

  const [overview, setOverview] = React.useState(null);
  const [sequences, setSequences] = React.useState([]);
  const [actions, setActions] = React.useState([]);
  const [enrollments, setEnrollments] = React.useState([]);

  const [newSequence, setNewSequence] = React.useState(INITIAL_SEQUENCE);
  const [selectedSequenceId, setSelectedSequenceId] = React.useState("");
  const [newStep, setNewStep] = React.useState(INITIAL_STEP);
  const [enrollForm, setEnrollForm] = React.useState({
    sequence_id: "",
    lead_id: "",
  });
  const [leads, setLeads] = React.useState([]);
  const [expandedSeqId, setExpandedSeqId] = React.useState("");
  const [seqSteps, setSeqSteps] = React.useState({});

  const flash = (setter, value) => {
    setter(value);
    window.setTimeout(() => setter(""), 12000);
  };

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const [ov, seq, act, enr, lds] = await Promise.all([
        api.get("/marketing-os/nurture/overview"),
        api.get("/marketing-os/nurture/sequences"),
        api.get("/marketing-os/nurture/actions", {
          params: { status: "pending_approval", limit: 100 },
        }),
        api.get("/marketing-os/nurture/enrollments", {
          params: { limit: 100 },
        }),
        api.get("/marketing-os/leads", { params: { limit: 50 } }),
      ]);
      setOverview(ov.data);
      setSequences(seq.data?.sequences || []);
      setActions(act.data?.actions || []);
      setEnrollments(enr.data?.enrollments || []);
      setLeads(lds.data?.leads || []);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to load nurture data");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  const sequenceName = (id) =>
    sequences.find((s) => s.id === id)?.name || id;

  const toggleSteps = async (id) => {
    if (expandedSeqId === id) {
      setExpandedSeqId("");
      return;
    }
    setExpandedSeqId(id);
    if (!seqSteps[id]) {
      try {
        const r = await api.get(`/marketing-os/nurture/sequences/${id}`);
        setSeqSteps((prev) => ({ ...prev, [id]: r.data?.steps || [] }));
      } catch (err) {
        setError(err?.response?.data?.detail || "Could not load steps");
      }
    }
  };

  const createSequence = async () => {
    setBusy(true);
    setError("");
    try {
      await api.post("/marketing-os/nurture/sequences", {
        name: newSequence.name,
        slug: newSequence.slug,
        status: "draft",
        trigger_type: newSequence.trigger_type,
      });
      setNewSequence(INITIAL_SEQUENCE);
      flash(setSuccess, "Sequence created (draft)");
      await load();
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not create sequence");
    } finally {
      setBusy(false);
    }
  };

  const activateSequence = async (id) => {
    setBusy(true);
    setError("");
    try {
      await api.patch(`/marketing-os/nurture/sequences/${id}`, {
        status: "active",
      });
      flash(setSuccess, "Sequence activated");
      await load();
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not activate sequence");
    } finally {
      setBusy(false);
    }
  };

  const addStep = async () => {
    if (!selectedSequenceId) {
      setError("Pick a sequence to add a step to");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const payload = {
        step_key: newStep.step_key,
        action_type: newStep.action_type,
        delay_minutes: Number(newStep.delay_minutes) || 0,
      };
      if (newStep.action_type === "send_email") {
        payload.subject = newStep.subject;
        payload.body_html = newStep.body_html;
      } else if (newStep.action_type === "create_task") {
        payload.config = { task_type: newStep.task_type };
      }
      await api.post(
        `/marketing-os/nurture/sequences/${selectedSequenceId}/steps`,
        payload
      );
      setNewStep(INITIAL_STEP);
      flash(setSuccess, "Step added");
      await load();
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not add step");
    } finally {
      setBusy(false);
    }
  };

  const enroll = async () => {
    setBusy(true);
    setError("");
    try {
      await api.post("/marketing-os/nurture/enroll", {
        sequence_id: enrollForm.sequence_id,
        lead_id: enrollForm.lead_id,
      });
      setEnrollForm({ sequence_id: "", lead_id: "" });
      flash(setSuccess, "Lead enrolled");
      await load();
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not enroll lead");
    } finally {
      setBusy(false);
    }
  };

  const runScheduler = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await api.post("/marketing-os/nurture/scheduler/tick", {
        limit: 100,
      });
      flash(
        setSuccess,
        `Scheduler tick: ${r.data.actions_created} queued, ` +
          `${r.data.enrollments_stopped} stopped`
      );
      await load();
    } catch (err) {
      setError(err?.response?.data?.detail || "Scheduler tick failed");
    } finally {
      setBusy(false);
    }
  };

  const approve = async (id) => {
    setBusy(true);
    setError("");
    try {
      const r = await api.post(
        `/marketing-os/nurture/actions/${id}/approve`
      );
      flash(
        setSuccess,
        r.data.status === "held"
          ? "Email approved but HELD (outreach disabled)"
          : "Action approved and task created"
      );
      await load();
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not approve");
    } finally {
      setBusy(false);
    }
  };

  const skip = async (id) => {
    setBusy(true);
    setError("");
    try {
      await api.post(`/marketing-os/nurture/actions/${id}/skip`, {});
      flash(setSuccess, "Action skipped");
      await load();
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not skip");
    } finally {
      setBusy(false);
    }
  };

  const safety = overview?.safety || {};

  return (
    <SectionCard
      title="Nurture & Appointment Recovery"
      subtitle="Deterministic marketing-lead follow-up. Email is queued for human review and held — no automatic outreach, no PHI, no SMS."
      icon={Sprout}
      testId="nurture-recovery-panel"
      actions={
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={runScheduler}
            disabled={busy}
            data-testid="nurture-run-scheduler"
          >
            <AlarmClock size={16} className="mr-1" /> Run scheduler
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={load}
            disabled={busy}
          >
            <RefreshCw size={16} className="mr-1" /> Refresh
          </Button>
        </div>
      }
    >
      <div className="mb-4 flex flex-wrap items-center gap-2 rounded-xl border border-[#d8cba9] bg-white px-4 py-3 text-xs text-[#5f5330]">
        <ShieldCheck size={16} className="text-emerald-700" />
        <span className="font-medium">Safety:</span>
        <span>automatic outreach {safety.automatic_outreach ? "ON" : "OFF"}</span>
        <span>· human approval {safety.human_approval_required ? "required" : "off"}</span>
        <span>· SMS {safety.sms_enabled ? "on" : "off"}</span>
        <span>· PHI {safety.phi_used ? "used" : "none"}</span>
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
        <div className="grid gap-5">
          {/* Overview stats */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              ["Overdue actions", overview?.pending_overdue_count ?? 0],
              ["Upcoming actions", overview?.pending_upcoming_count ?? 0],
              [
                "Active enrollments",
                overview?.enrollments_by_status?.active ?? 0,
              ],
              ["Sequences", sequences.length],
            ].map(([label, value]) => (
              <div
                key={label}
                className="rounded-xl border border-[#d8cba9] bg-white p-3"
              >
                <div className="text-[10px] uppercase tracking-widest text-[#8a6a3c]">
                  {label}
                </div>
                <div className="mt-1 text-xl font-semibold text-[#3f3320]">
                  {value}
                </div>
              </div>
            ))}
          </div>

          {/* Action queue */}
          <div>
            <h4 className="mb-2 text-sm font-semibold text-[#3f3320]">
              Pending approval queue
            </h4>
            {actions.length === 0 ? (
              <EmptyState>No actions awaiting approval.</EmptyState>
            ) : (
              <div className="grid gap-2">
                {actions.map((a) => (
                  <div
                    key={a.id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#e2dac5] bg-white px-4 py-3"
                    data-testid="nurture-action-row"
                  >
                    <div className="flex items-center gap-3">
                      {a.action_type === "send_email" ? (
                        <Mail size={16} className="text-[#8a6a3c]" />
                      ) : (
                        <CheckCircle2 size={16} className="text-[#8a6a3c]" />
                      )}
                      <div>
                        <div className="text-sm font-medium text-[#3f3320]">
                          {a.action_type === "send_email"
                            ? a.subject || "Email"
                            : a.preview?.task_type || "Task"}
                        </div>
                        <div className="text-[11px] text-[#806837]">
                          {sequenceName(a.sequence_id)} ·{" "}
                          {new Date(a.scheduled_at).toLocaleString()}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {a.action_type === "send_email" ? (
                        <Badge variant="outline">held on approve</Badge>
                      ) : null}
                      <Button
                        type="button"
                        size="sm"
                        onClick={() => approve(a.id)}
                        disabled={busy}
                        data-testid="nurture-approve"
                      >
                        Approve
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => skip(a.id)}
                        disabled={busy}
                        data-testid="nurture-skip"
                      >
                        <SkipForward size={14} className="mr-1" /> Skip
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Builder + enroll */}
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-[#e2dac5] bg-white p-4">
              <h4 className="mb-3 text-sm font-semibold text-[#3f3320]">
                Create sequence
              </h4>
              <div className="grid gap-2">
                <Label>Name</Label>
                <Input
                  value={newSequence.name}
                  onChange={(e) =>
                    setNewSequence({ ...newSequence, name: e.target.value })
                  }
                  data-testid="nurture-seq-name"
                />
                <Label>Slug</Label>
                <Input
                  value={newSequence.slug}
                  onChange={(e) =>
                    setNewSequence({ ...newSequence, slug: e.target.value })
                  }
                  placeholder="no-show-recovery"
                  data-testid="nurture-seq-slug"
                />
                <Button
                  type="button"
                  onClick={createSequence}
                  disabled={busy}
                  className="mt-2"
                  data-testid="nurture-seq-create"
                >
                  <Plus size={16} className="mr-1" /> Create draft
                </Button>
              </div>

              <div className="mt-4 border-t border-[#eee3ca] pt-4">
                <h4 className="mb-2 text-sm font-semibold text-[#3f3320]">
                  Add step
                </h4>
                <Label>Sequence</Label>
                <Select
                  value={selectedSequenceId}
                  onValueChange={setSelectedSequenceId}
                >
                  <SelectTrigger data-testid="nurture-step-seq">
                    <SelectValue placeholder="Select a sequence" />
                  </SelectTrigger>
                  <SelectContent>
                    {sequences.map((s) => (
                      <SelectItem key={s.id} value={s.id}>
                        {s.name} ({s.status})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                <div className="mt-2 grid grid-cols-2 gap-2">
                  <div>
                    <Label>Step key</Label>
                    <Input
                      value={newStep.step_key}
                      onChange={(e) =>
                        setNewStep({ ...newStep, step_key: e.target.value })
                      }
                      placeholder="day1_email"
                      data-testid="nurture-step-key"
                    />
                  </div>
                  <div>
                    <Label>Delay (min)</Label>
                    <Input
                      type="number"
                      value={newStep.delay_minutes}
                      onChange={(e) =>
                        setNewStep({
                          ...newStep,
                          delay_minutes: e.target.value,
                        })
                      }
                      data-testid="nurture-step-delay"
                    />
                  </div>
                </div>

                <Label className="mt-2">Action type</Label>
                <Select
                  value={newStep.action_type}
                  onValueChange={(v) =>
                    setNewStep({ ...newStep, action_type: v })
                  }
                >
                  <SelectTrigger data-testid="nurture-step-action-type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="create_task">create_task</SelectItem>
                    <SelectItem value="send_email">send_email</SelectItem>
                    <SelectItem value="wait">wait</SelectItem>
                  </SelectContent>
                </Select>

                {newStep.action_type === "create_task" ? (
                  <>
                    <Label className="mt-2">Task type</Label>
                    <Select
                      value={newStep.task_type}
                      onValueChange={(v) =>
                        setNewStep({ ...newStep, task_type: v })
                      }
                    >
                      <SelectTrigger data-testid="nurture-step-task-type">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {TASK_TYPES.map((t) => (
                          <SelectItem key={t} value={t}>
                            {t}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </>
                ) : null}

                {newStep.action_type === "send_email" ? (
                  <>
                    <Label className="mt-2">Subject</Label>
                    <Input
                      value={newStep.subject}
                      onChange={(e) =>
                        setNewStep({ ...newStep, subject: e.target.value })
                      }
                      data-testid="nurture-step-subject"
                    />
                    <Label className="mt-2">Body (HTML, no PHI)</Label>
                    <Textarea
                      value={newStep.body_html}
                      onChange={(e) =>
                        setNewStep({ ...newStep, body_html: e.target.value })
                      }
                      rows={3}
                      data-testid="nurture-step-body"
                    />
                  </>
                ) : null}

                <Button
                  type="button"
                  onClick={addStep}
                  disabled={busy}
                  className="mt-3"
                  data-testid="nurture-step-add"
                >
                  <Plus size={16} className="mr-1" /> Add step
                </Button>
              </div>
            </div>

            <div className="rounded-xl border border-[#e2dac5] bg-white p-4">
              <h4 className="mb-3 text-sm font-semibold text-[#3f3320]">
                Sequences
              </h4>
              {sequences.length === 0 ? (
                <EmptyState>No sequences yet.</EmptyState>
              ) : (
                <div className="grid gap-2">
                  {sequences.map((s) => (
                    <div
                      key={s.id}
                      className="rounded-lg border border-[#eee3ca] px-3 py-2"
                      data-testid="nurture-sequence-row"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div>
                          <div className="text-sm font-medium text-[#3f3320]">
                            {s.name}
                          </div>
                          <div className="text-[11px] text-[#806837]">
                            {s.slug} · {s.trigger_type}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <StatusBadge status={s.status} />
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => toggleSteps(s.id)}
                            data-testid="nurture-view-steps"
                          >
                            {expandedSeqId === s.id ? "Hide" : "Steps"}
                          </Button>
                          {s.status === "draft" ? (
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              onClick={() => activateSequence(s.id)}
                              disabled={busy}
                            >
                              Activate
                            </Button>
                          ) : null}
                        </div>
                      </div>
                      {expandedSeqId === s.id ? (
                        <div
                          className="mt-2 border-t border-[#eee3ca] pt-2"
                          data-testid="nurture-steps-list"
                        >
                          {(seqSteps[s.id] || []).length === 0 ? (
                            <div className="text-[11px] text-[#806837]">
                              No steps yet.
                            </div>
                          ) : (
                            <ol className="grid gap-1">
                              {(seqSteps[s.id] || []).map((st) => (
                                <li
                                  key={st.id}
                                  className="flex items-center justify-between gap-2 text-[12px] text-[#3f3320]"
                                  data-testid="nurture-step-item"
                                >
                                  <span>
                                    <span className="font-medium">
                                      #{st.position} {st.step_key}
                                    </span>{" "}
                                    <span className="text-[#806837]">
                                      · {st.action_type}
                                      {st.action_type === "send_email" &&
                                      st.subject
                                        ? ` · "${st.subject}"`
                                        : ""}
                                    </span>
                                  </span>
                                  <span className="text-[10px] text-[#806837]">
                                    +{st.delay_minutes}m
                                  </span>
                                </li>
                              ))}
                            </ol>
                          )}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              )}

              <div className="mt-4 border-t border-[#eee3ca] pt-4">
                <h4 className="mb-2 text-sm font-semibold text-[#3f3320]">
                  Enroll a lead
                </h4>
                <Label>Sequence</Label>
                <Select
                  value={enrollForm.sequence_id}
                  onValueChange={(v) =>
                    setEnrollForm({ ...enrollForm, sequence_id: v })
                  }
                >
                  <SelectTrigger data-testid="nurture-enroll-seq">
                    <SelectValue placeholder="Active sequence" />
                  </SelectTrigger>
                  <SelectContent>
                    {sequences
                      .filter((s) => s.status === "active")
                      .map((s) => (
                        <SelectItem key={s.id} value={s.id}>
                          {s.name}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
                <Label className="mt-2">Lead</Label>
                <Select
                  value={enrollForm.lead_id}
                  onValueChange={(v) =>
                    setEnrollForm({ ...enrollForm, lead_id: v })
                  }
                >
                  <SelectTrigger data-testid="nurture-enroll-lead">
                    <SelectValue placeholder="Select a marketing lead" />
                  </SelectTrigger>
                  <SelectContent>
                    {leads.map((l) => (
                      <SelectItem key={l.id} value={l.id}>
                        {l.marketing_subject_id} ({l.lead_status})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  type="button"
                  onClick={enroll}
                  disabled={busy}
                  className="mt-3"
                  data-testid="nurture-enroll-submit"
                >
                  Enroll
                </Button>
              </div>
            </div>
          </div>

          {/* Enrollments */}
          <div>
            <h4 className="mb-2 text-sm font-semibold text-[#3f3320]">
              Enrollments
            </h4>
            {enrollments.length === 0 ? (
              <EmptyState>No enrollments yet.</EmptyState>
            ) : (
              <div className="grid gap-2">
                {enrollments.slice(0, 25).map((e) => (
                  <div
                    key={e.id}
                    className="flex items-center justify-between gap-2 rounded-lg border border-[#eee3ca] bg-white px-3 py-2 text-sm"
                  >
                    <div className="text-[#3f3320]">
                      {sequenceName(e.sequence_id)}
                      <span className="ml-2 text-[11px] text-[#806837]">
                        step {e.current_step_position}
                        {e.stop_reason ? ` · ${e.stop_reason}` : ""}
                      </span>
                    </div>
                    <StatusBadge status={e.status} />
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </SectionCard>
  );
}
