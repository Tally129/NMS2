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
  Plus, ClipboardList, AlertTriangle, Clock3, Pause, CheckCircle2, Circle,
  Filter, Search, RotateCcw,
} from "lucide-react";
import { useToast } from "../../hooks/use-toast";
import { useAuth } from "../../lib/auth";
import { getErrorMessage } from "../../lib/errors";
import TasksWidget from "../../components/TasksWidget";

const STATUSES = [
  { value: "new", label: "New" },
  { value: "in_progress", label: "In progress" },
  { value: "waiting", label: "Waiting" },
  { value: "completed", label: "Completed" },
];
const PRIORITIES = [
  { value: "low", label: "Low" },
  { value: "normal", label: "Normal" },
  { value: "high", label: "High" },
  { value: "urgent", label: "Urgent" },
];
const CATEGORIES = [
  { value: "review_labs", label: "Review labs" },
  { value: "call_patient", label: "Call patient" },
  { value: "follow_up_appointment", label: "Follow-up appointment" },
  { value: "collect_payment", label: "Collect payment" },
  { value: "review_intake", label: "Review intake" },
  { value: "upload_documents", label: "Upload documents" },
  { value: "insurance_followup", label: "Insurance follow-up" },
  { value: "telehealth_followup", label: "Telehealth follow-up" },
  { value: "other", label: "Other" },
];

const priorityColor = (p) => ({
  low: "bg-slate-100 text-slate-600 border-slate-200",
  normal: "bg-[#eaf2ec] text-[#3d6b52] border-[#cfe0d3]",
  high: "bg-[#fdf3d0] text-[#8a6a3c] border-[#e6d38a]",
  urgent: "bg-[#fdecec] text-[#7a2a2a] border-[#f0b4b4]",
}[p] || "bg-slate-100 text-slate-600");

const statusColor = (s) => ({
  new: "bg-[#eaf2ec] text-[#3d6b52]",
  in_progress: "bg-[#e0eaf3] text-[#3a5a7a]",
  waiting: "bg-[#fdf3d0] text-[#8a6a3c]",
  completed: "bg-slate-100 text-slate-500",
}[s] || "bg-slate-100 text-slate-500");

export default function TasksPage() {
  const { user } = useAuth();
  const { toast } = useToast();
  const [tasks, setTasks] = React.useState([]);
  const [users, setUsers] = React.useState([]);
  const [clients, setClients] = React.useState([]);
  const [filters, setFilters] = React.useState({
    mine: false, status: "", priority: "", search: "",
  });
  const [showNew, setShowNew] = React.useState(false);
  const [selected, setSelected] = React.useState(null);

  const load = React.useCallback(async () => {
    const params = {};
    if (filters.mine) params.mine = true;
    if (filters.status) params.status = filters.status;
    if (filters.priority) params.priority = filters.priority;
    if (filters.search) params.search = filters.search;
    try {
      const r = await api.get("/tasks", { params });
      setTasks(r.data || []);
    } catch (e) {
      toast({ title: "Could not load tasks", description: getErrorMessage(e) || "" });
    }
  }, [filters, toast]);

  React.useEffect(() => { load(); }, [load]);
  React.useEffect(() => {
    api.get("/admin/users").then((r) => setUsers(r.data || [])).catch(() => {});
    api.get("/clients").then((r) => setClients(r.data || [])).catch(() => {});
  }, []);

  const bump = async (id, patch) => {
    try {
      await api.patch(`/tasks/${id}`, patch);
      load();
      if (selected?.id === id) {
        const r = await api.get(`/tasks/${id}`);
        setSelected(r.data);
      }
    } catch (e) {
      toast({ title: "Update failed", description: getErrorMessage(e) || "" });
    }
  };

  const overdueTasks = tasks.filter(
    (t) => t.due_date && new Date(t.due_date) < new Date() && t.status !== "completed"
  );

  return (
    <PortalLayout>
      <PortalHeader
        title="Tasks"
        subtitle={`${tasks.length} shown · ${overdueTasks.length} overdue`}
        actions={
          <Button
            onClick={() => setShowNew(true)}
            className="btn-lift h-11 rounded-full bg-[#2f6a4a] hover:bg-[#265739] text-white"
            data-testid="tasks-new-btn"
          >
            <Plus size={16} className="mr-2" /> New task
          </Button>
        }
      />

      <div className="mb-6">
        <TasksWidget linkTo="#" />
      </div>

      {/* Filters */}
      <div className="rounded-2xl border border-[#e2ebe4] bg-white p-4 mb-5 flex flex-wrap gap-3 items-end" data-testid="tasks-filters">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <Input
            value={filters.search}
            onChange={(e) => setFilters({ ...filters, search: e.target.value })}
            placeholder="Search titles…"
            className="pl-9 border-[#d9e2db]"
            data-testid="tasks-filter-search"
          />
        </div>
        <div className="w-[140px]">
          <Label className="text-xs text-slate-500">Status</Label>
          <Select
            value={filters.status || "all"}
            onValueChange={(v) => setFilters({ ...filters, status: v === "all" ? "" : v })}
          >
            <SelectTrigger className="border-[#d9e2db]" data-testid="tasks-filter-status">
              <SelectValue placeholder="All" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              {STATUSES.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="w-[140px]">
          <Label className="text-xs text-slate-500">Priority</Label>
          <Select
            value={filters.priority || "all"}
            onValueChange={(v) => setFilters({ ...filters, priority: v === "all" ? "" : v })}
          >
            <SelectTrigger className="border-[#d9e2db]" data-testid="tasks-filter-priority">
              <SelectValue placeholder="All" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All priorities</SelectItem>
              {PRIORITIES.map((p) => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <Button
          variant={filters.mine ? "default" : "outline"}
          onClick={() => setFilters({ ...filters, mine: !filters.mine })}
          className={filters.mine ? "bg-[#2f6a4a] text-white h-10" : "h-10 border-[#d9e2db]"}
          data-testid="tasks-filter-mine"
        >
          <Filter size={14} className="mr-2" /> {filters.mine ? "Mine only" : "All"}
        </Button>
        <Button
          variant="outline" className="h-10 border-[#d9e2db]"
          onClick={() => setFilters({ mine: false, status: "", priority: "", search: "" })}
          data-testid="tasks-filter-reset"
        >
          <RotateCcw size={14} className="mr-2" /> Reset
        </Button>
      </div>

      {/* Task list */}
      <div className="rounded-2xl border border-[#e2ebe4] bg-white overflow-hidden" data-testid="tasks-list">
        {tasks.length === 0 ? (
          <div className="p-10 text-center text-slate-500">
            <ClipboardList size={28} className="mx-auto mb-3 text-slate-300" />
            No tasks match your filters yet.
          </div>
        ) : (
          <table className="w-full">
            <thead className="bg-[#f4f7f2] text-left text-xs uppercase tracking-wider text-slate-500">
              <tr>
                <th className="p-3">Title</th>
                <th className="p-3">Patient</th>
                <th className="p-3">Assigned</th>
                <th className="p-3">Due</th>
                <th className="p-3">Priority</th>
                <th className="p-3">Status</th>
                <th className="p-3"></th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((t) => {
                const overdue = t.due_date && new Date(t.due_date) < new Date() && t.status !== "completed";
                return (
                  <tr key={t.id} className="border-t border-[#e2ebe4] hover:bg-[#fbfdfb]" data-testid={`task-row-${t.id}`}>
                    <td className="p-3">
                      <button
                        onClick={() => setSelected(t)}
                        className="text-left font-medium text-[#1f2a22] hover:underline"
                        data-testid={`task-open-${t.id}`}
                      >
                        {t.title}
                      </button>
                      <div className="text-[11px] text-slate-500 mt-0.5">
                        {CATEGORIES.find((c) => c.value === t.category)?.label || t.category}
                      </div>
                    </td>
                    <td className="p-3 text-sm text-slate-700">{t.client_name || "—"}</td>
                    <td className="p-3 text-sm text-slate-700">
                      {t.assigned_staff_name || t.assigned_provider_name || "—"}
                    </td>
                    <td className={`p-3 text-sm ${overdue ? "text-[#7a2a2a] font-medium" : "text-slate-600"}`}>
                      {t.due_date ? new Date(t.due_date).toLocaleDateString() : "—"}
                      {overdue && <div className="text-[10px] uppercase">Overdue</div>}
                    </td>
                    <td className="p-3">
                      <span className={`px-2 py-1 rounded-full border text-[11px] ${priorityColor(t.priority)}`}>
                        {t.priority}
                      </span>
                    </td>
                    <td className="p-3">
                      <span className={`px-2 py-1 rounded-full text-[11px] ${statusColor(t.status)}`}>
                        {STATUSES.find((s) => s.value === t.status)?.label || t.status}
                      </span>
                    </td>
                    <td className="p-3 text-right">
                      {t.status !== "completed" ? (
                        <Button
                          size="sm" variant="outline"
                          onClick={() => bump(t.id, { status: "completed" })}
                          className="h-8 rounded-full border-[#cfe0d3] text-[#2f6a4a]"
                          data-testid={`task-complete-${t.id}`}
                        >
                          <CheckCircle2 size={13} className="mr-1" /> Complete
                        </Button>
                      ) : (
                        <span className="text-slate-400 text-xs inline-flex items-center gap-1">
                          <Circle size={12} /> done
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <NewTaskDialog
        open={showNew} onOpenChange={setShowNew} users={users} clients={clients}
        onCreated={() => { setShowNew(false); load(); }}
      />
      <TaskDetailDialog
        task={selected} onClose={() => setSelected(null)} users={users}
        onPatch={bump}
      />
    </PortalLayout>
  );
}

function NewTaskDialog({ open, onOpenChange, users, clients, onCreated }) {
  const { toast } = useToast();
  const [form, setForm] = React.useState({
    title: "", priority: "normal", category: "other",
    description: "", client_id: "", assigned_staff_id: "",
    assigned_provider_id: "", due_date: "",
  });
  const [busy, setBusy] = React.useState(false);
  const submit = async () => {
    if (!form.title || form.title.length < 2) {
      toast({ title: "Enter a title" });
      return;
    }
    setBusy(true);
    try {
      const payload = {
        title: form.title, priority: form.priority, category: form.category,
        description: form.description || undefined,
        client_id: form.client_id || undefined,
        assigned_staff_id: form.assigned_staff_id || undefined,
        assigned_provider_id: form.assigned_provider_id || undefined,
        due_date: form.due_date ? new Date(form.due_date).toISOString() : undefined,
      };
      await api.post("/tasks", payload);
      toast({ title: "Task created" });
      setForm({ title: "", priority: "normal", category: "other", description: "", client_id: "", assigned_staff_id: "", assigned_provider_id: "", due_date: "" });
      onCreated();
    } catch (e) {
      toast({ title: "Create failed", description: getErrorMessage(e) || "" });
    } finally { setBusy(false); }
  };

  const staffUsers = users.filter((u) => ["staff", "medical_assistant", "admin"].includes(u.role));
  const providerUsers = users.filter((u) => u.role === "practitioner");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-white max-w-lg" data-testid="new-task-dialog">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">New task</DialogTitle>
          <DialogDescription>Assign clinical or operational work to a teammate.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label>Title</Label>
            <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })}
                   className="mt-1" data-testid="new-task-title" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Priority</Label>
              <Select value={form.priority} onValueChange={(v) => setForm({ ...form, priority: v })}>
                <SelectTrigger data-testid="new-task-priority"><SelectValue /></SelectTrigger>
                <SelectContent>{PRIORITIES.map((p) => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div>
              <Label>Category</Label>
              <Select value={form.category} onValueChange={(v) => setForm({ ...form, category: v })}>
                <SelectTrigger data-testid="new-task-category"><SelectValue /></SelectTrigger>
                <SelectContent>{CATEGORIES.map((c) => <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Patient (optional)</Label>
              <Select value={form.client_id || "_none"} onValueChange={(v) => setForm({ ...form, client_id: v === "_none" ? "" : v })}>
                <SelectTrigger data-testid="new-task-client"><SelectValue placeholder="None" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="_none">— None —</SelectItem>
                  {clients.slice(0, 200).map((c) => <SelectItem key={c.id} value={c.id}>{c.full_name || c.email}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Due</Label>
              <Input type="date" value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} data-testid="new-task-due" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Assigned staff</Label>
              <Select value={form.assigned_staff_id || "_none"} onValueChange={(v) => setForm({ ...form, assigned_staff_id: v === "_none" ? "" : v })}>
                <SelectTrigger data-testid="new-task-staff"><SelectValue placeholder="None" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="_none">— None —</SelectItem>
                  {staffUsers.map((u) => <SelectItem key={u.id} value={u.id}>{u.full_name || u.email}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Assigned provider</Label>
              <Select value={form.assigned_provider_id || "_none"} onValueChange={(v) => setForm({ ...form, assigned_provider_id: v === "_none" ? "" : v })}>
                <SelectTrigger data-testid="new-task-provider"><SelectValue placeholder="None" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="_none">— None —</SelectItem>
                  {providerUsers.map((u) => <SelectItem key={u.id} value={u.id}>{u.full_name || u.email}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div>
            <Label>Internal notes</Label>
            <Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })}
                      rows={3} data-testid="new-task-description" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            onClick={submit} disabled={busy}
            className="bg-[#2f6a4a] hover:bg-[#265739] text-white rounded-full"
            data-testid="new-task-submit"
          >
            {busy ? "Creating…" : "Create task"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function TaskDetailDialog({ task, onClose, users, onPatch }) {
  const [note, setNote] = React.useState("");
  if (!task) return null;
  const submitNote = async () => {
    if (!note.trim()) return;
    await onPatch(task.id, { add_note: note.trim() });
    setNote("");
  };
  return (
    <Dialog open={!!task} onOpenChange={onClose}>
      <DialogContent className="bg-white max-w-lg" data-testid="task-detail-dialog">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">{task.title}</DialogTitle>
          <DialogDescription>
            {task.client_name ? `Patient: ${task.client_name}` : "No patient linked"} · Created by {task.created_by_name}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <div className="flex gap-2 flex-wrap">
            <span className={`px-2 py-1 rounded-full text-[11px] ${statusColor(task.status)}`}>{task.status}</span>
            <span className={`px-2 py-1 rounded-full border text-[11px] ${priorityColor(task.priority)}`}>{task.priority}</span>
            {task.due_date && (
              <span className="px-2 py-1 rounded-full border text-[11px] border-slate-200 text-slate-600">
                Due {new Date(task.due_date).toLocaleDateString()}
              </span>
            )}
          </div>
          {task.description && (
            <div className="rounded-lg bg-[#f4f7f2] p-3 text-slate-700 whitespace-pre-wrap">{task.description}</div>
          )}
          <div>
            <Label>Change status</Label>
            <div className="flex gap-2 mt-1 flex-wrap">
              {STATUSES.map((s) => (
                <Button
                  key={s.value} size="sm"
                  variant={task.status === s.value ? "default" : "outline"}
                  onClick={() => onPatch(task.id, { status: s.value })}
                  className={task.status === s.value ? "bg-[#2f6a4a] text-white" : "border-[#d9e2db]"}
                  data-testid={`task-status-${s.value}`}
                >
                  {s.label}
                </Button>
              ))}
            </div>
          </div>
          <div>
            <Label>Add note</Label>
            <div className="flex gap-2 mt-1">
              <Input value={note} onChange={(e) => setNote(e.target.value)} data-testid="task-note-input" />
              <Button
                onClick={submitNote} disabled={!note.trim()}
                className="bg-[#2f6a4a] hover:bg-[#265739] text-white rounded-full"
                data-testid="task-note-submit"
              >Add</Button>
            </div>
          </div>
          {task.internal_notes?.length > 0 && (
            <div className="max-h-40 overflow-y-auto space-y-2 border-t border-[#e2ebe4] pt-3">
              {task.internal_notes.map((n, i) => (
                <div key={i} className="text-xs text-slate-600">
                  <span className="font-medium text-[#2f6a4a]">{n.actor_name}</span>{" "}
                  <span className="text-slate-400">{new Date(n.ts).toLocaleString()}</span>
                  <div>{n.body}</div>
                </div>
              ))}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
