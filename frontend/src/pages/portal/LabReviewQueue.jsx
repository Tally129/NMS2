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
import { FlaskConical, ClipboardPlus, ShieldOff, AlertTriangle, CheckCircle2 } from "lucide-react";
import { useToast } from "../../hooks/use-toast";
import { getErrorMessage } from "../../lib/errors";

const REVIEW_STATUSES = [
  { value: "new", label: "New", color: "bg-[#eaf2ec] text-[#3d6b52]" },
  { value: "waiting_for_review", label: "Waiting for provider review", color: "bg-[#fdf3d0] text-[#8a6a3c]" },
  { value: "reviewed", label: "Reviewed", color: "bg-[#e0eaf3] text-[#3a5a7a]" },
  { value: "patient_notified", label: "Patient notified", color: "bg-slate-100 text-slate-600" },
  { value: "follow_up_needed", label: "Follow-up needed", color: "bg-[#fdecec] text-[#7a2a2a]" },
];

const outOfRange = (lab) => {
  if (lab.value == null || lab.reference_low == null || lab.reference_high == null) return false;
  return lab.value < lab.reference_low || lab.value > lab.reference_high;
};

export default function LabReviewQueue() {
  const { toast } = useToast();
  const [rows, setRows] = React.useState([]);
  const [filter, setFilter] = React.useState("");
  const [selected, setSelected] = React.useState(null);
  const [creatingTask, setCreatingTask] = React.useState(null);

  const load = React.useCallback(async () => {
    try {
      const r = await api.get("/labs/review-queue", { params: filter ? { status: filter } : {} });
      setRows(r.data || []);
    } catch (e) {
      toast({ title: "Could not load queue", description: getErrorMessage(e) || "" });
    }
  }, [filter, toast]);

  React.useEffect(() => { load(); }, [load]);

  const transition = async (lab, next, notes) => {
    try {
      await api.patch(`/labs/${lab.id}/review-status`, {
        review_status: next,
        review_notes: notes || undefined,
      });
      toast({ title: `Marked ${REVIEW_STATUSES.find((s) => s.value === next)?.label || next}` });
      setSelected(null);
      load();
    } catch (e) {
      const err = getErrorMessage(e);
      if (err && err.includes("delegation")) {
        toast({ title: "Provider authorization required",
                description: "Ask the assigned provider to authorize you first." });
      } else {
        toast({ title: "Update failed", description: err || "" });
      }
    }
  };

  return (
    <PortalLayout>
      <PortalHeader
        title="Lab review queue"
        subtitle={`${rows.length} items`}
        actions={
          <Select value={filter || "open"} onValueChange={(v) => setFilter(v === "open" ? "" : v)}>
            <SelectTrigger className="w-[220px] h-10 border-[#d9e2db]" data-testid="lab-queue-filter">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="open">Open (default view)</SelectItem>
              {REVIEW_STATUSES.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}
            </SelectContent>
          </Select>
        }
      />

      <div className="rounded-2xl border border-[#e2ebe4] bg-white overflow-hidden" data-testid="lab-queue-table">
        {rows.length === 0 ? (
          <div className="p-10 text-center text-slate-500">
            <FlaskConical size={26} className="mx-auto mb-3 text-slate-300" />
            No labs pending review.
          </div>
        ) : (
          <table className="w-full">
            <thead className="bg-[#f4f7f2] text-left text-xs uppercase tracking-wider text-slate-500">
              <tr>
                <th className="p-3">Patient</th>
                <th className="p-3">Test</th>
                <th className="p-3">Result</th>
                <th className="p-3">Uploaded</th>
                <th className="p-3">Ordering provider</th>
                <th className="p-3">Status</th>
                <th className="p-3"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((lab) => {
                const abnormal = outOfRange(lab);
                const status = lab.review_status || "new";
                const badge = REVIEW_STATUSES.find((s) => s.value === status);
                return (
                  <tr key={lab.id} className="border-t border-[#e2ebe4] hover:bg-[#fbfdfb]" data-testid={`lab-row-${lab.id}`}>
                    <td className="p-3 text-sm text-[#1f2a22] font-medium">{lab.client_name || "—"}</td>
                    <td className="p-3 text-sm">{lab.test_name}</td>
                    <td className={`p-3 text-sm ${abnormal ? "text-[#7a2a2a] font-medium" : "text-slate-700"}`}>
                      {lab.value} {lab.unit || ""}
                      {abnormal && <AlertTriangle size={12} className="inline ml-1 -mt-1" />}
                    </td>
                    <td className="p-3 text-xs text-slate-500">
                      {lab.created_at ? new Date(lab.created_at).toLocaleDateString() : "—"}
                    </td>
                    <td className="p-3 text-sm text-slate-700">{lab.ordering_provider_name || lab.recorded_by_name || "—"}</td>
                    <td className="p-3">
                      <span className={`px-2 py-1 rounded-full text-[11px] ${badge?.color || "bg-slate-100"}`}>
                        {badge?.label || status}
                      </span>
                    </td>
                    <td className="p-3 text-right space-x-2">
                      <Button
                        size="sm" variant="outline"
                        className="h-8 rounded-full border-[#cfe0d3] text-[#2f6a4a]"
                        onClick={() => setSelected(lab)}
                        data-testid={`lab-review-${lab.id}`}
                      >
                        Review
                      </Button>
                      <Button
                        size="sm" variant="outline"
                        className="h-8 rounded-full border-[#e6d38a] text-[#8a6a3c]"
                        onClick={() => setCreatingTask(lab)}
                        data-testid={`lab-to-task-${lab.id}`}
                      >
                        <ClipboardPlus size={13} className="mr-1" /> To task
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <ReviewDialog
        lab={selected} onClose={() => setSelected(null)} onTransition={transition}
      />
      <LabToTaskDialog
        lab={creatingTask} onClose={() => setCreatingTask(null)}
        onCreated={() => { setCreatingTask(null); toast({ title: "Task created from lab" }); }}
      />
    </PortalLayout>
  );
}

function ReviewDialog({ lab, onClose, onTransition }) {
  const [notes, setNotes] = React.useState("");
  const [next, setNext] = React.useState("reviewed");
  React.useEffect(() => {
    if (lab) {
      setNotes(lab.review_notes || "");
      setNext(lab.review_status === "new" ? "reviewed" : "patient_notified");
    }
  }, [lab]);
  if (!lab) return null;
  return (
    <Dialog open={!!lab} onOpenChange={onClose}>
      <DialogContent className="bg-white max-w-lg" data-testid="lab-review-dialog">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">
            {lab.test_name} · {lab.client_name}
          </DialogTitle>
          <DialogDescription>
            {lab.value} {lab.unit} · reference {lab.reference_low ?? "?"}–{lab.reference_high ?? "?"}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label>Move to</Label>
            <Select value={next} onValueChange={setNext}>
              <SelectTrigger className="mt-1" data-testid="lab-review-next-status"><SelectValue /></SelectTrigger>
              <SelectContent>
                {REVIEW_STATUSES.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>Notes</Label>
            <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} data-testid="lab-review-notes" />
          </div>
          {lab.review_history?.length > 0 && (
            <div className="max-h-32 overflow-y-auto text-xs space-y-1 border-t border-[#e2ebe4] pt-2">
              {lab.review_history.map((h, i) => (
                <div key={i} className="text-slate-600">
                  <span className="font-medium text-[#2f6a4a]">{h.actor_name}</span>{" "}
                  {h.from} → {h.to}{" "}
                  <span className="text-slate-400">{new Date(h.ts).toLocaleString()}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button
            onClick={() => onTransition(lab, next, notes)}
            className="bg-[#2f6a4a] hover:bg-[#265739] text-white rounded-full"
            data-testid="lab-review-save"
          >
            <CheckCircle2 size={14} className="mr-1" /> Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function LabToTaskDialog({ lab, onClose, onCreated }) {
  const { toast } = useToast();
  const [priority, setPriority] = React.useState("high");
  const [note, setNote] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  if (!lab) return null;
  const submit = async () => {
    setBusy(true);
    try {
      await api.post(`/labs/${lab.id}/create-task`, { priority, note });
      onCreated();
    } catch (e) {
      toast({ title: "Task create failed", description: getErrorMessage(e) || "" });
    } finally { setBusy(false); }
  };
  return (
    <Dialog open={!!lab} onOpenChange={onClose}>
      <DialogContent className="bg-white max-w-md" data-testid="lab-to-task-dialog">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">Create task from lab</DialogTitle>
          <DialogDescription>Links back to this lab result automatically.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="rounded-lg bg-[#f4f7f2] p-3 text-sm text-slate-700">
            {lab.test_name} · {lab.value} {lab.unit || ""} · {lab.client_name}
          </div>
          <div>
            <Label>Priority</Label>
            <Select value={priority} onValueChange={setPriority}>
              <SelectTrigger className="mt-1" data-testid="lab-to-task-priority"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="low">Low</SelectItem>
                <SelectItem value="normal">Normal</SelectItem>
                <SelectItem value="high">High</SelectItem>
                <SelectItem value="urgent">Urgent</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>Task note</Label>
            <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} data-testid="lab-to-task-note" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button
            onClick={submit} disabled={busy}
            className="bg-[#2f6a4a] hover:bg-[#265739] text-white rounded-full"
            data-testid="lab-to-task-submit"
          >
            {busy ? "Creating…" : "Create task"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
