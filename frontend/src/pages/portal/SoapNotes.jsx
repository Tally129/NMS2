import React from "react";
import { Link } from "react-router-dom";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Textarea } from "../../components/ui/textarea";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../../components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../../components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { useToast } from "../../hooks/use-toast";
import { useAuth } from "../../lib/auth";
import { getErrorMessage } from "../../lib/errors";
import {
  FileText, Search, Loader2, ClipboardList, Plus, Edit3, Trash2,
  User, ChevronRight, Sparkles, Save, History as HistoryIcon, X,
} from "lucide-react";
import { normalizeArray } from "../../lib/collections";

/**
 * Phase 11 — clinic-wide SOAP Notes hub.
 *  • Notes tab: filter by patient + provider; click row to open the patient chart.
 *  • Templates tab: provider/admin can manage SOAP starter templates.
 *  • New SOAP: pre-fills from a chosen template + chosen patient → saves to that patient.
 */
export default function SoapNotes() {
  const { user } = useAuth();
  const { toast } = useToast();
  const isProvider = user?.role === "practitioner" || user?.role === "admin";

  const [tab, setTab] = React.useState("notes");
  const [notes, setNotes] = React.useState([]);
  const [templates, setTemplates] = React.useState([]);
  const [providers, setProviders] = React.useState([]);
  const [clients, setClients] = React.useState([]);
  const [providerFilter, setProviderFilter] = React.useState("all");
  const [clientFilter, setClientFilter] = React.useState("all");
  const [search, setSearch] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [editorState, setEditorState] = React.useState(null); // { client_id, template_id?, draft }
  const [tplEditor, setTplEditor] = React.useState(null); // SOAP template editor

  const loadNotes = React.useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (providerFilter !== "all") params.practitioner_id = providerFilter;
      if (search) params.search = search;
      const r = await api.get("/notes/all", { params });
      let rows = r.data || [];
      if (clientFilter !== "all") rows = rows.filter((n) => n.client_id === clientFilter);
      setNotes(rows);
    } finally { setLoading(false); }
  }, [providerFilter, clientFilter, search]);

  const loadTemplates = async () => {
    try { const r = await api.get("/soap-templates"); setTemplates(normalizeArray(r.data, ["templates"])); } catch {}
  };

  React.useEffect(() => {
    api.get("/practitioners").then((r) => setProviders(normalizeArray(r.data, ["providers"]))).catch(() => {});
    api.get("/clients").then((r) => setClients(normalizeArray(r.data, ["clients"]))).catch(() => {});
    loadTemplates();
  }, []);
  React.useEffect(() => { const t = setTimeout(loadNotes, 250); return () => clearTimeout(t); }, [loadNotes]);

  return (
    <PortalLayout>
      <PortalHeader
        title="SOAP Notes"
        subtitle="All visit notes across the clinic — filter, edit, and start new ones from templates."
        actions={
          isProvider && (
            <div className="flex gap-2 flex-wrap">
              <Button
                onClick={() => setEditorState({ client_id: "", template_id: "", draft: { subjective: "", objective: "", assessment: "", plan: "" } })}
                className="rounded-full h-10 bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
                data-testid="soap-new-btn"
              >
                <Plus size={14} className="mr-2" /> New SOAP note
              </Button>
            </div>
          )
        }
      />

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="bg-[#f1ead8]">
          <TabsTrigger value="notes" data-testid="soap-tab-notes">
            <FileText size={12} className="mr-1" /> Notes ({notes.length})
          </TabsTrigger>
          <TabsTrigger value="templates" data-testid="soap-tab-templates">
            <ClipboardList size={12} className="mr-1" /> Templates ({templates.length})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="notes" className="mt-5">
          <div className="flex flex-col md:flex-row gap-3 mb-5 flex-wrap">
            <div className="relative flex-1 min-w-[240px] max-w-md">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8a6a3c]" />
              <Input
                placeholder="Search by patient name…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9 bg-[#f6f1e6] border-[#e0d6bc]"
                data-testid="soap-search"
              />
            </div>
            <Select value={clientFilter} onValueChange={setClientFilter}>
              <SelectTrigger className="w-56 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="soap-client-filter">
                <SelectValue placeholder="All patients" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All patients</SelectItem>
                {normalizeArray(clients).map((c) => <SelectItem key={c.id} value={c.id}>{c.full_name || c.email}</SelectItem>)}
              </SelectContent>
            </Select>
            <Select value={providerFilter} onValueChange={setProviderFilter}>
              <SelectTrigger className="w-56 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="soap-provider-filter">
                <SelectValue placeholder="All providers" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All providers</SelectItem>
                {normalizeArray(providers).map((p) => <SelectItem key={p.id} value={p.id}>{p.full_name || p.email}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden" data-testid="soap-notes-table">
            <table className="w-full text-sm">
              <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
                <tr>
                  <th className="text-left py-3 px-4">Date</th>
                  <th className="text-left py-3 px-4">Patient</th>
                  <th className="text-left py-3 px-4">Provider</th>
                  <th className="text-left py-3 px-4">Subjective preview</th>
                  <th className="text-right py-3 px-4">Open</th>
                </tr>
              </thead>
              <tbody>
                {loading && <tr><td colSpan={5} className="py-10 text-center text-[#6a6a6a]"><Loader2 className="inline animate-spin mr-2" size={14} /> Loading…</td></tr>}
                {!loading && notes.length === 0 && <tr><td colSpan={5} className="py-12 text-center text-[#6a6a6a]">No notes match. Try clearing filters or create a new note.</td></tr>}
                {!loading && normalizeArray(notes).map((n) => (
                  <tr key={n.id} className="border-t border-[#e7dfc9] hover:bg-[#f1ead8]" data-testid={`soap-note-row-${n.id}`}>
                    <td className="py-3 px-4 text-xs text-[#6a6a6a] whitespace-nowrap">
                      {new Date(n.created_at).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })}
                    </td>
                    <td className="py-3 px-4 font-medium text-[#1f2a22]">
                      <Link to={`/portal/provider/patients/${n.client_id}`} className="hover:underline inline-flex items-center gap-1.5">
                        <User size={12} className="text-[#8a6a3c]" /> {n.client_name || n.client_id}
                      </Link>
                    </td>
                    <td className="py-3 px-4 text-[#3a3a3a]">{n.practitioner_name || "—"}</td>
                    <td className="py-3 px-4 text-[#6a6a6a] truncate max-w-md">{(n.subjective || "").slice(0, 140) || "—"}</td>
                    <td className="py-3 px-4 text-right">
                      <Link to={`/portal/provider/patients/${n.client_id}#notes`} className="text-[#2f4a3a] hover:underline inline-flex items-center gap-1 text-xs">
                        Open chart <ChevronRight size={11} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </TabsContent>

        <TabsContent value="templates" className="mt-5">
          <div className="flex justify-end mb-4">
            {isProvider && (
              <Button
                onClick={() => setTplEditor({ title: "New template", description: "", subjective: "", objective: "", assessment: "", plan: "", visit_type: null, active: true })}
                className="rounded-full h-9 bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
                data-testid="soap-tpl-new-btn"
              >
                <Plus size={13} className="mr-1" /> New template
              </Button>
            )}
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="soap-templates-grid">
            {normalizeArray(templates).map((t) => (
              <div key={t.id} className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5 flex flex-col" data-testid={`soap-tpl-${t.id}`}>
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div className="flex items-start gap-2 min-w-0">
                    <ClipboardList size={16} className="text-[#8a6a3c] mt-0.5" />
                    <h3 className="font-display text-lg text-[#1f2a22] leading-tight">{t.title}</h3>
                  </div>
                  {t.visit_type && (
                    <span className="text-[10px] uppercase tracking-widest px-2 py-1 rounded-full bg-[#f1ead8] border border-[#e0d6bc] text-[#8a6a3c] whitespace-nowrap">
                      {t.visit_type}
                    </span>
                  )}
                </div>
                <p className="text-sm text-[#5a5a5a] line-clamp-3 min-h-[3em] mb-3">{t.description || "—"}</p>
                <div className="text-xs text-[#6a6a6a] flex items-center gap-1 mb-4">
                  <Sparkles size={11} /> Pre-fills S / O / A / P sections
                </div>
                <div className="mt-auto flex items-center gap-3 text-sm pt-3 border-t border-[#e7dfc9]">
                  {isProvider && (
                    <button onClick={() => setEditorState({ client_id: "", template_id: t.id, draft: { subjective: t.subjective, objective: t.objective, assessment: t.assessment, plan: t.plan } })} className="text-[#c19a4b] hover:text-[#8a6a3c] inline-flex items-center gap-1" data-testid={`soap-use-tpl-${t.id}`}>
                      <Sparkles size={12} /> Use
                    </button>
                  )}
                  {isProvider && (
                    <button onClick={() => setTplEditor(t)} className="text-[#3a3a3a] hover:text-[#2f4a3a] inline-flex items-center gap-1" data-testid={`soap-tpl-edit-${t.id}`}>
                      <Edit3 size={12} /> Edit
                    </button>
                  )}
                </div>
              </div>
            ))}
            {templates.length === 0 && <div className="col-span-full text-sm text-[#6a6a6a] text-center py-10">No templates yet.</div>}
          </div>
        </TabsContent>
      </Tabs>

      <NoteEditorDialog
        state={editorState}
        templates={templates}
        clients={clients}
        onOpenChange={(v) => !v && setEditorState(null)}
        onSaved={() => { setEditorState(null); loadNotes(); }}
      />
      <TemplateEditorDialog
        template={tplEditor}
        onOpenChange={(v) => !v && setTplEditor(null)}
        onSaved={() => { setTplEditor(null); loadTemplates(); }}
      />
    </PortalLayout>
  );
}

// ---------- New / edit SOAP note dialog ----------
function NoteEditorDialog({ state, templates, clients, onOpenChange, onSaved }) {
  const { toast } = useToast();
  const [draft, setDraft] = React.useState(null);
  const [clientId, setClientId] = React.useState("");
  const [appointmentId, setAppointmentId] = React.useState("");
  const [templateId, setTemplateId] = React.useState("");
  const [encounterText, setEncounterText] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [generating, setGenerating] = React.useState(false);

  // In-person Clinical Scribe
  const [recordingConsent, setRecordingConsent] =
    React.useState(false);
  const [recording, setRecording] =
    React.useState(false);
  const [transcriptionJobName, setTranscriptionJobName] =
    React.useState("");
  const [transcriptionStatus, setTranscriptionStatus] =
    React.useState("");

  const recorderRef = React.useRef(null);
  const recordingChunksRef = React.useRef([]);
  const recordingStreamRef = React.useRef(null);

  React.useEffect(() => {
    if (state) {
      setDraft(state.draft);
      setClientId(state.client_id || "");
      setAppointmentId(state.appointment_id || "");
      setTemplateId(state.template_id || "");
      setEncounterText(state.encounter_text || "");
    }
  }, [state]);
  const applyTemplate = (tplId) => {
    setTemplateId(tplId);
    if (!tplId || tplId === "blank") return;
    const t = normalizeArray(templates).find((x) => x.id === tplId);
    if (!t) return;
    setDraft({ subjective: t.subjective || "", objective: t.objective || "", assessment: t.assessment || "", plan: t.plan || "" });
  };

  // ---------- In-person Clinical Scribe ----------

  const startClinicalRecording = async () => {
    if (!clientId) {
      toast({
        title: "Select a patient first",
      });
      return;
    }

    if (!recordingConsent) {
      toast({
        title: "Recording consent required",
        description:
          "Confirm the patient's consent before recording.",
      });
      return;
    }

    if (recording) return;

    try {
      const stream =
        await navigator.mediaDevices.getUserMedia({
          audio: true,
          video: false,
        });

      recordingStreamRef.current = stream;

      let mimeType = "";

      if (
        typeof MediaRecorder !== "undefined" &&
        MediaRecorder.isTypeSupported(
          "audio/webm;codecs=opus"
        )
      ) {
        mimeType = "audio/webm;codecs=opus";
      } else if (
        typeof MediaRecorder !== "undefined" &&
        MediaRecorder.isTypeSupported(
          "audio/webm"
        )
      ) {
        mimeType = "audio/webm";
      }

      const recorder = mimeType
        ? new MediaRecorder(
            stream,
            { mimeType }
          )
        : new MediaRecorder(stream);

      recorderRef.current = recorder;
      recordingChunksRef.current = [];

      recorder.ondataavailable = (event) => {
        if (event.data?.size > 0) {
          recordingChunksRef.current.push(
            event.data
          );
        }
      };

      recorder.onstop = async () => {
        try {
          const blobType =
            recorder.mimeType ||
            mimeType ||
            "audio/webm";

          const blob = new Blob(
            recordingChunksRef.current,
            { type: blobType }
          );

          if (!blob.size) {
            throw new Error(
              "The recording did not contain any audio."
            );
          }

          setTranscriptionStatus("UPLOADING");

          const formData = new FormData();

          formData.append(
            "file",
            blob,
            "in-person-visit.webm"
          );

          formData.append(
            "client_id",
            clientId
          );

          formData.append(
            "recording_consent",
            "true"
          );

          const response = await api.post(
            "/notes/clinical-scribe/recording",
            formData
          );

          const jobName =
            response?.data?.job_name || "";

          const status =
            response?.data?.status ||
            "IN_PROGRESS";

          if (!jobName) {
            throw new Error(
              "HealthScribe did not return a job name."
            );
          }

          setTranscriptionJobName(jobName);
          setTranscriptionStatus(status);

          toast({
            title: "Recording uploaded",
            description:
              "Transcribing the visit and preparing a SOAP draft.",
          });
        } catch (error) {
          setTranscriptionStatus(
            "FAILED_TO_START"
          );

          toast({
            title: "Clinical transcription could not start",
            description:
              getErrorMessage(error) ||
              "The recording could not be processed.",
          });
        } finally {
          recordingChunksRef.current = [];

          const stream =
            recordingStreamRef.current;

          if (stream) {
            stream
              .getTracks()
              .forEach((track) => track.stop());
          }

          recordingStreamRef.current = null;
          recorderRef.current = null;
        }
      };

      recorder.start(1000);

      setRecording(true);
      setTranscriptionStatus("");

      toast({
        title: "Clinical recording started",
      });
    } catch (error) {
      const stream =
        recordingStreamRef.current;

      if (stream) {
        stream
          .getTracks()
          .forEach((track) => track.stop());
      }

      recordingStreamRef.current = null;

      toast({
        title: "Microphone unavailable",
        description:
          getErrorMessage(error) ||
          "Allow microphone access to record the visit.",
      });
    }
  };

  const stopClinicalRecording = () => {
    const recorder = recorderRef.current;

    if (
      recorder &&
      recorder.state !== "inactive"
    ) {
      recorder.stop();
    }

    setRecording(false);
  };

  React.useEffect(() => {
    if (
      !transcriptionJobName ||
      transcriptionStatus !== "IN_PROGRESS" ||
      !clientId
    ) {
      return;
    }

    let cancelled = false;
    let timer = null;

    const poll = async () => {
      try {
        const response = await api.get(
          "/notes/clinical-scribe/transcription",
          {
            params: {
              client_id: clientId,
              job_name: transcriptionJobName,
            },
          }
        );

        if (cancelled) return;

        const result =
          response?.data || {};

        const status =
          result.status || "UNKNOWN";

        setTranscriptionStatus(status);

        if (status === "COMPLETED") {
          const soapDraft =
            result.soap_draft || {};

          setDraft({
            subjective:
              soapDraft.subjective || "",
            objective:
              soapDraft.objective || "",
            assessment:
              soapDraft.assessment || "",
            plan:
              soapDraft.plan || "",
          });

          toast({
            title: "SOAP draft ready",
            description:
              "HealthScribe populated the draft. Review and edit it before saving.",
          });

          return;
        }

        if (status === "FAILED") {
          toast({
            title: "Clinical transcription failed",
            description:
              result.failure_reason ||
              "HealthScribe could not process the recording.",
          });

          return;
        }

        timer = window.setTimeout(
          poll,
          5000
        );
      } catch (error) {
        if (cancelled) return;

        setTranscriptionStatus(
          "POLL_ERROR"
        );

        toast({
          title: "Transcription status unavailable",
          description:
            getErrorMessage(error) ||
            "Unable to check the HealthScribe job.",
        });
      }
    };

    poll();

    return () => {
      cancelled = true;

      if (timer) {
        window.clearTimeout(timer);
      }
    };
  }, [
    transcriptionJobName,
    transcriptionStatus,
    clientId,
        toast,
    ]);

  React.useEffect(() => {
    return () => {
      try {
        const recorder =
          recorderRef.current;

        if (
          recorder &&
          recorder.state !== "inactive"
        ) {
          recorder.stop();
        }
      } catch {}

      const stream =
        recordingStreamRef.current;

      if (stream) {
        stream
          .getTracks()
          .forEach((track) => track.stop());
      }
    };
  }, []);

  if (!state || !draft) return null;

  const generateWithAi = async () => {
    if (!clientId) {
      toast({ title: "Select a patient first" });
      return;
    }

    if (encounterText.trim().length < 10) {
      toast({
        title: "Add encounter notes",
        description: "Enter a visit summary, transcript, or clinician notes.",
      });
      return;
    }

    setGenerating(true);

    try {
      const response = await api.post("/notes/ai-draft", {
        client_id: clientId,
        template_id:
          templateId && templateId !== "blank"
            ? templateId
            : null,
        encounter_text: encounterText.trim(),
      });

      setDraft({
        subjective: response.data?.subjective || "",
        objective: response.data?.objective || "",
        assessment: response.data?.assessment || "",
        plan: response.data?.plan || "",
      });

      toast({
        title: "SOAP draft generated",
        description: "Review and edit every section before saving.",
      });
    } catch (error) {
      toast({
        title: "AI draft failed",
        description:
          getErrorMessage(error) ||
          "The SOAP draft could not be generated.",
      });
    } finally {
      setGenerating(false);
    }
  };

  const save = async () => {
    if (!clientId) { toast({ title: "Select a patient" }); return; }
    setSaving(true);
    try {
      const payload = {
        client_id: clientId,
        ...draft,
      };

      if (appointmentId) {
        payload.appointment_id = appointmentId;
      }

      await api.post("/notes", payload);

      toast({
        title: "SOAP note saved",
        description: appointmentId
          ? "Saved to the patient chart and linked to this visit."
          : "Visible in the patient chart.",
      });
      onSaved && onSaved();
    } catch (e) { toast({ title: "Failed", description: getErrorMessage(e) || "" }); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open={!!state} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9] max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">New SOAP note</DialogTitle>
          <DialogDescription>Choose a patient and (optionally) a template, then edit the SOAP sections.</DialogDescription>
        </DialogHeader>
        <div className="space-y-5">
          <div className="grid md:grid-cols-2 gap-3">
            <div>
              <Label>Patient</Label>
              <Select value={clientId} onValueChange={setClientId}>
                <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="soap-editor-client"><SelectValue placeholder="Select patient…" /></SelectTrigger>
                <SelectContent>{normalizeArray(clients).map((c) => <SelectItem key={c.id} value={c.id}>{c.full_name || c.email}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div>
              <Label>Template</Label>
              <Select value={templateId || "blank"} onValueChange={applyTemplate}>
                <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="soap-editor-template"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="blank">Blank</SelectItem>
                  {normalizeArray(templates).map((t) => <SelectItem key={t.id} value={t.id}>{t.title}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div
            className="rounded-xl border border-[#d8c89f] bg-[#fbf7ee] p-4"
            data-testid="clinical-scribe-panel"
          >
            <div className="flex flex-col gap-4">
              <div>
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <Label>In-person Clinical Scribe</Label>
                    <p className="mt-1 text-xs text-[#6a6a6a]">
                      Record the room conversation and generate an
                      editable SOAP draft with HealthScribe.
                    </p>
                  </div>

                  <span
                    className={
                      "rounded-full border px-2 py-1 text-[10px] uppercase tracking-wider " +
                      (recording
                        ? "border-red-200 bg-red-50 text-red-700"
                        : transcriptionStatus === "COMPLETED"
                        ? "border-green-200 bg-green-50 text-green-700"
                        : "border-[#e0d6bc] bg-[#f6f1e6] text-[#8a6a3c]")
                    }
                  >
                    {recording
                      ? "Recording"
                      : transcriptionStatus === "UPLOADING"
                      ? "Uploading"
                      : transcriptionStatus === "IN_PROGRESS"
                      ? "Transcribing"
                      : transcriptionStatus === "COMPLETED"
                      ? "Draft ready"
                      : "Ready"}
                  </span>
                </div>
              </div>

              <label className="flex items-start gap-3 rounded-lg border border-[#e0d6bc] bg-white p-3">
                <input
                  type="checkbox"
                  checked={recordingConsent}
                  disabled={recording}
                  onChange={(event) =>
                    setRecordingConsent(
                      event.target.checked
                    )
                  }
                  className="mt-1 h-4 w-4"
                  data-testid="clinical-scribe-consent"
                />

                <span className="text-sm text-[#3a3a3a]">
                  I confirm the patient has consented to audio
                  recording, transcription, and AI-assisted draft
                  documentation for this visit.
                </span>
              </label>

              <div className="flex flex-wrap items-center gap-3">
                {!recording ? (
                  <Button
                    type="button"
                    onClick={startClinicalRecording}
                    disabled={
                      !clientId ||
                      !recordingConsent ||
                      transcriptionStatus === "UPLOADING" ||
                      transcriptionStatus === "IN_PROGRESS"
                    }
                    className="rounded-full bg-[#2f4a3a] text-[#f6f1e6] hover:bg-[#263d30]"
                    data-testid="clinical-scribe-start"
                  >
                    Start Recording
                  </Button>
                ) : (
                  <Button
                    type="button"
                    onClick={stopClinicalRecording}
                    className="rounded-full bg-red-700 text-white hover:bg-red-800"
                    data-testid="clinical-scribe-stop"
                  >
                    Stop & Generate SOAP
                  </Button>
                )}

                {transcriptionStatus === "UPLOADING" && (
                  <span className="flex items-center text-xs text-[#6a6a6a]">
                    <Loader2
                      size={13}
                      className="mr-2 animate-spin"
                    />
                    Uploading clinical recording…
                  </span>
                )}

                {transcriptionStatus === "IN_PROGRESS" && (
                  <span className="flex items-center text-xs text-[#6a6a6a]">
                    <Loader2
                      size={13}
                      className="mr-2 animate-spin"
                    />
                    Transcribing and drafting SOAP note…
                  </span>
                )}

                {transcriptionStatus === "COMPLETED" && (
                  <span className="text-xs text-green-700">
                    SOAP draft generated — review the sections below.
                  </span>
                )}

                {[
                  "FAILED",
                  "FAILED_TO_START",
                  "POLL_ERROR",
                ].includes(transcriptionStatus) && (
                  <span className="text-xs text-red-700">
                    Clinical transcription was not completed.
                  </span>
                )}
              </div>

              <p className="text-[11px] leading-5 text-[#6a6a6a]">
                Patient identity remains associated with the chart
                inside NMS. Review all generated documentation before
                saving it to the medical record.
              </p>
            </div>
          </div>

          <div className="rounded-xl border border-[#d8c89f] bg-[#f6f1e6] p-4">
            <div className="mb-2 flex items-start justify-between gap-3">
              <div>
                <Label>Encounter notes or transcript</Label>
                <p className="mt-1 text-xs text-[#6a6a6a]">
                  Paste the visit summary, dictation, transcript, or rough
                  clinician notes. AI creates an editable draft only.
                </p>
              </div>

              <span className="rounded-full border border-[#e0d6bc] bg-[#fbf7ee] px-2 py-1 text-[10px] uppercase tracking-wider text-[#8a6a3c]">
                Clinician review required
              </span>
            </div>

            <Textarea
              value={encounterText}
              onChange={(event) => setEncounterText(event.target.value)}
              rows={6}
              maxLength={12000}
              placeholder="Example: Patient reports improved energy since the last visit but continues to experience..."
              className="mt-2 bg-white border-[#e0d6bc]"
              data-testid="soap-ai-encounter"
            />

            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <span className="text-xs text-[#6a6a6a]">
                {encounterText.length.toLocaleString()} / 12,000 characters
              </span>

              <Button
                type="button"
                onClick={generateWithAi}
                disabled={generating}
                className="rounded-full bg-[#8a6a3c] text-white hover:bg-[#725630]"
                data-testid="soap-ai-generate"
              >
                {generating ? (
                  <Loader2 size={14} className="mr-2 animate-spin" />
                ) : (
                  <Sparkles size={14} className="mr-2" />
                )}
                {generating ? "Generating…" : "Generate SOAP with AI"}
              </Button>
            </div>
          </div>

          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">
            AI-generated content may contain errors or omissions. Verify all
            patient statements, findings, assessments, and plans before saving
            or finalizing the note.
          </div>

          <SoapSection label="Subjective" value={draft.subjective} onChange={(v) => setDraft({ ...draft, subjective: v })} testid="soap-s" />
          <SoapSection label="Objective" value={draft.objective} onChange={(v) => setDraft({ ...draft, objective: v })} testid="soap-o" />
          <SoapSection label="Assessment" value={draft.assessment} onChange={(v) => setDraft({ ...draft, assessment: v })} testid="soap-a" />
          <SoapSection label="Plan" value={draft.plan} onChange={(v) => setDraft({ ...draft, plan: v })} testid="soap-p" />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={save} disabled={saving} className="bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6] rounded-full" data-testid="soap-editor-save">
            {saving ? <Loader2 size={14} className="animate-spin mr-1" /> : <Save size={14} className="mr-1" />} Save note
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
function SoapSection({ label, value, onChange, testid }) {
  return (
    <div>
      <Label>{label}</Label>
      <Textarea className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" rows={4} value={value || ""} onChange={(e) => onChange(e.target.value)} data-testid={testid} />
    </div>
  );
}

// ---------- SOAP template editor ----------
function TemplateEditorDialog({ template, onOpenChange, onSaved }) {
  const { toast } = useToast();
  const [t, setT] = React.useState(template);
  const [saving, setSaving] = React.useState(false);
  React.useEffect(() => { setT(template); }, [template]);
  if (!t) return null;

  const upd = (patch) => setT((prev) => ({ ...prev, ...patch }));
  const save = async () => {
    if (!t.title?.trim()) { toast({ title: "Title required" }); return; }
    setSaving(true);
    try {
      const body = {
        title: t.title.trim(),
        description: t.description || "",
        subjective: t.subjective || "",
        objective: t.objective || "",
        assessment: t.assessment || "",
        plan: t.plan || "",
        visit_type: t.visit_type || null,
        active: t.active !== false,
      };
      if (t.id) await api.put(`/soap-templates/${t.id}`, body);
      else await api.post("/soap-templates", body);
      toast({ title: "Template saved" });
      onSaved && onSaved();
    } catch (e) { toast({ title: "Failed", description: getErrorMessage(e) || "" }); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open={!!template} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9] max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">{t.id ? "Edit SOAP template" : "New SOAP template"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid md:grid-cols-2 gap-3">
            <div>
              <Label>Title</Label>
              <Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={t.title || ""} onChange={(e) => upd({ title: e.target.value })} data-testid="soap-tpl-editor-title" />
            </div>
            <div>
              <Label>Visit type</Label>
              <Select value={t.visit_type || "any"} onValueChange={(v) => upd({ visit_type: v === "any" ? null : v })}>
                <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="any">Any visit</SelectItem>
                  <SelectItem value="telehealth">Telehealth</SelectItem>
                  <SelectItem value="in_person">In-person</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div>
            <Label>Description</Label>
            <Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={t.description || ""} onChange={(e) => upd({ description: e.target.value })} />
          </div>
          <SoapSection label="Subjective" value={t.subjective} onChange={(v) => upd({ subjective: v })} testid="tpl-s" />
          <SoapSection label="Objective" value={t.objective} onChange={(v) => upd({ objective: v })} testid="tpl-o" />
          <SoapSection label="Assessment" value={t.assessment} onChange={(v) => upd({ assessment: v })} testid="tpl-a" />
          <SoapSection label="Plan" value={t.plan} onChange={(v) => upd({ plan: v })} testid="tpl-p" />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={save} disabled={saving} className="bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6] rounded-full" data-testid="soap-tpl-editor-save">
            {saving ? <Loader2 size={14} className="animate-spin mr-1" /> : <Save size={14} className="mr-1" />} Save template
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}