import React from "react";
import { Link, useNavigate } from "react-router-dom";
import PortalLayout, { PortalHeader, StatCard } from "../PortalLayout";
import api, { API_BASE, LS } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../../components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../../components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { useToast } from "../../hooks/use-toast";
import { getErrorMessage } from "../../lib/errors";
import {
  Video, Calendar, Clock, History, Settings2, Loader2, Play, Mic, MicOff, VideoOff,
  Lock, FileVideo, ExternalLink, Plus, Sparkles, Phone, Wifi, DoorOpen, UserCheck, UserX,
} from "lucide-react";
import { normalizeArray } from "../../lib/collections";

/**
 * Telehealth Hub — single-purpose page for all telehealth activity.
 * Tabs:  Upcoming · Active now · History · Equipment test · Recordings (provider+ only)
 */
export default function TelehealthHub() {
  const { user } = useAuth();
  const { toast } = useToast();
  const isProvider = user?.role && user.role !== "client";
  const [appts, setAppts] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [filter, setFilter] = React.useState("all");
  const [showInstant, setShowInstant] = React.useState(false);
  const [historyPage, setHistoryPage] = React.useState(1);
  const [historySearch, setHistorySearch] = React.useState("");
  const historyPageSize = 25;

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get("/appointments");
      setAppts(normalizeArray(r.data, ["appts"]).filter((a) => a.visit_mode === "telehealth"));
    } finally { setLoading(false); }
  };
  React.useEffect(() => { load(); const t = setInterval(load, 30_000); return () => clearInterval(t); }, []);

  const now = new Date();
  const inOneHour = new Date(now.getTime() + 60 * 60_000);
  const inAnHourFromStart = (a) => {
    const s = new Date(a.start);
    return s >= now && s <= inOneHour;
  };
  const isEnded = (a) =>
    a.waiting_room?.state === "ended";

  const isUpcoming = (a) =>
    !isEnded(a) &&
    new Date(a.start) >= now &&
    !["completed", "canceled", "no_show"].includes(a.status);

  const isActive = (a) => {
    const waitingState = a.waiting_room?.state;

    return (
      !["ended", "expired", "declined"].includes(
        waitingState
      ) &&
      (
        a.status === "in_session" ||
        a.status === "arrived"
      )
    );
  };

  const isHistory = (a) =>
    isEnded(a) ||
    ["completed", "no_show", "canceled"].includes(a.status) ||
    new Date(a.end || a.start) < now;

  const filtered = (list) => filter === "all" ? list :
    list.filter((a) => filter === "today" ? new Date(a.start).toDateString() === now.toDateString() :
                       filter === "week" ? (new Date(a.start) - now) / 86_400_000 <= 7 : true);

  const upcoming = filtered(
    normalizeArray(appts)
      .filter(isUpcoming)
      .sort((a, b) => new Date(a.start) - new Date(b.start))
  );

  const active = normalizeArray(appts).filter(isActive);

  const historyAll = filtered(
    normalizeArray(appts)
      .filter(isHistory)
      .sort((a, b) => new Date(b.start) - new Date(a.start))
  ).filter((appointment) => {
    const search = historySearch.trim().toLowerCase();

    if (!search) return true;

    return [
      appointment.client_name,
      appointment.practitioner_name,
      appointment.visit_type,
      appointment.reason,
      appointment.status,
    ].some((value) =>
      String(value || "").toLowerCase().includes(search)
    );
  });

  const historyPageCount = Math.max(
    1,
    Math.ceil(historyAll.length / historyPageSize)
  );

  const safeHistoryPage = Math.min(
    historyPage,
    historyPageCount
  );

  const historyStart =
    (safeHistoryPage - 1) * historyPageSize;

  const history = historyAll.slice(
    historyStart,
    historyStart + historyPageSize
  );

  React.useEffect(() => {
    setHistoryPage(1);
  }, [filter, historySearch]);

  return (
    <PortalLayout>
      <PortalHeader
        title="Telehealth"
        subtitle="Your secure self-hosted video care hub"
        actions={
          <div className="flex gap-2">
            <Select value={filter} onValueChange={setFilter}>
              <SelectTrigger className="h-9 w-32 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="th-filter-select"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All</SelectItem>
                <SelectItem value="today">Today</SelectItem>
                <SelectItem value="week">This week</SelectItem>
              </SelectContent>
            </Select>
            {isProvider && (
              <Button onClick={() => setShowInstant(true)} className="h-9 rounded-full bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]" data-testid="th-instant-btn">
                <Plus size={14} className="mr-1" /> Instant visit
              </Button>
            )}
          </div>
        }
      />

      <div className="grid sm:grid-cols-3 gap-4 mb-8">
        <StatCard label="Active now" value={active.length} icon={Video} accent={active.length ? "text-[#2f4a3a]" : undefined} />
        <StatCard label="Starting within 1h" value={normalizeArray(appts).filter(inAnHourFromStart).length} icon={Clock} />
        <StatCard label="Upcoming total" value={upcoming.length} icon={Calendar} />
      </div>

      {isProvider && <WaitingRoomQueue />}
      {!isProvider && <PatientVisitInvitations rows={appts} />}

      <Tabs defaultValue="upcoming">
        <TabsList className="bg-[#f1ead8]">
          <TabsTrigger value="upcoming" data-testid="th-tab-upcoming">Upcoming</TabsTrigger>
          {active.length > 0 && <TabsTrigger value="active" data-testid="th-tab-active"><span className="text-[#2f4a3a]">● Active</span></TabsTrigger>}
          <TabsTrigger value="history" data-testid="th-tab-history"><History size={12} className="mr-1" /> History</TabsTrigger>
          <TabsTrigger value="equipment" data-testid="th-tab-equipment"><Settings2 size={12} className="mr-1" /> Equipment</TabsTrigger>
        </TabsList>

        <TabsContent value="upcoming" className="mt-4">
          <VisitList rows={upcoming} loading={loading} emptyMsg="No upcoming telehealth visits scheduled." showJoinHints />
        </TabsContent>

        <TabsContent value="active" className="mt-4">
          <VisitList
            rows={active}
            loading={false}
            emptyMsg="No active visits."
            active
            onChanged={load}
          />
        </TabsContent>

        <TabsContent value="history" className="mt-4">
          <div className="mb-4 flex flex-col gap-3 rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-4 sm:flex-row sm:items-center sm:justify-between">
            <Input
              value={historySearch}
              onChange={(event) =>
                setHistorySearch(event.target.value)
              }
              placeholder="Search patient, provider, visit type, reason, or status…"
              className="max-w-xl bg-[#f6f1e6] border-[#e0d6bc]"
              data-testid="th-history-search"
            />

            <div className="text-xs text-[#6a6a6a]">
              {historyAll.length} historical{" "}
              {historyAll.length === 1 ? "visit" : "visits"}
            </div>
          </div>

          <VisitList
            rows={history}
            loading={false}
            emptyMsg="No past telehealth visits match these filters."
            showRecordings={isProvider}
            canArchive={isProvider}
            onChanged={load}
          />

          {historyAll.length > historyPageSize && (
            <div className="mt-5 flex flex-col items-center justify-between gap-3 rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-4 sm:flex-row">
              <Button
                type="button"
                variant="outline"
                disabled={safeHistoryPage <= 1}
                onClick={() =>
                  setHistoryPage((page) =>
                    Math.max(1, page - 1)
                  )
                }
                className="rounded-full border-[#8a6a3c] text-[#8a6a3c]"
                data-testid="th-history-prev"
              >
                Previous
              </Button>

              <div className="text-sm text-[#6a6a6a]">
                Page {safeHistoryPage} of {historyPageCount}
              </div>

              <Button
                type="button"
                variant="outline"
                disabled={
                  safeHistoryPage >= historyPageCount
                }
                onClick={() =>
                  setHistoryPage((page) =>
                    Math.min(
                      historyPageCount,
                      page + 1
                    )
                  )
                }
                className="rounded-full border-[#8a6a3c] text-[#8a6a3c]"
                data-testid="th-history-next"
              >
                Next
              </Button>
            </div>
          )}
        </TabsContent>

        <TabsContent value="equipment" className="mt-4">
          <EquipmentTest />
        </TabsContent>
      </Tabs>

      {isProvider && <InstantVisitDialog open={showInstant} onOpenChange={setShowInstant} onCreated={load} />}
    </PortalLayout>
  );
}

function VisitList({
  rows,
  loading,
  emptyMsg,
  showJoinHints,
  showRecordings,
  active,
  canArchive = false,
  onChanged,
}) {
  if (loading) return <div className="text-center text-[#6a6a6a] py-12"><Loader2 className="inline animate-spin mr-2" size={16} /> Loading…</div>;
  if (rows.length === 0) return <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-12 text-center text-[#6a6a6a]">{emptyMsg}</div>;
  return (
    <div className="space-y-3">
      {rows.map((a) => (
        <VisitCard
          key={a.id}
          a={a}
          canJoin={showJoinHints || active}
          active={active}
          showRecordings={showRecordings}
          canArchive={canArchive}
          onChanged={onChanged}
        />
      ))}
    </div>
  );
}

function DocumentationBadge({ appointment }) {
  const status =
    appointment?.telehealth?.documentation_status || "";

  const config = {
    transcribing: {
      label: "Transcribing",
      className:
        "border-[#8a6a3c] bg-[#f8f1df] text-[#6f542d]",
    },
    recording_saved: {
      label: "Recording saved",
      className:
        "border-[#8a6a3c] bg-[#f8f1df] text-[#6f542d]",
    },
    soap_review_required: {
      label: "SOAP Review Required",
      className:
        "border-[#c19a4b] bg-[#fff4d8] text-[#7c5a16]",
    },
    transcription_failed: {
      label: "Transcription Failed",
      className:
        "border-[#b16a6a] bg-[#fff0f0] text-[#7a2a2a]",
    },
    recording_exception: {
      label: "Recording Exception",
      className:
        "border-[#b16a6a] bg-[#fff0f0] text-[#7a2a2a]",
    },
    complete: {
      label: "Documentation Complete",
      className:
        "border-[#719078] bg-[#edf6ef] text-[#2f4a3a]",
    },
  };

  if (!status || !config[status]) {
    return null;
  }

  const item = config[status];

  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-medium ${item.className}`}
      data-testid={`telehealth-documentation-${status}`}
    >
      {item.label}
    </span>
  );
}


function VisitCard({
  a,
  canJoin,
  active,
  showRecordings,
  canArchive = false,
  onChanged,
}) {
  const { toast } = useToast();
  const navigate = useNavigate();
  const [archiving, setArchiving] = React.useState(false);
  const [ending, setEnding] = React.useState(false);
  const [reviewingSoap, setReviewingSoap] =
    React.useState(false);
  const start = new Date(a.start);
  const now = new Date();
  const minsUntil = Math.round((start - now) / 60_000);
  const joinable = active || (minsUntil >= -10 && minsUntil <= 60);  // 10-min grace, 1h pre
  const dateLabel = start.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
  const timeLabel = start.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

  const endSession = async () => {
    const confirmed = window.confirm(
      "End this telehealth session? The visit will move to History and the patient will no longer be able to remain in the active room."
    );

    if (!confirmed) return;

    setEnding(true);

    try {
      await api.post(
        `/appointments/${a.id}/telehealth/end`
      );

      toast({
        title: "Telehealth session ended",
        description:
          "The visit was moved to History.",
      });

      await onChanged?.();
    } catch (error) {
      toast({
        title: "Could not end session",
        description:
          getErrorMessage(error) || "Try again.",
      });
    } finally {
      setEnding(false);
    }
  };

  const reviewSoap = async () => {
    setReviewingSoap(true);

    try {
      const response = await api.post(
        `/visits/${a.id}/promote-soap`
      );

      const noteId = response?.data?.note_id;

      toast({
        title: "SOAP ready for review",
        description:
          response?.data?.created === false
            ? "Opening the existing visit note."
            : "The HealthScribe draft was moved into the permanent clinical-note workflow.",
      });

      // Open the patient's chart at the Notes section.
      // The note remains a draft until the assigned provider
      // explicitly finalizes it.
      navigate(
        `/portal/provider/patients/${a.client_id}` +
          `?note_id=${encodeURIComponent(
            noteId || ""
          )}#notes`
      );
    } catch (error) {
      toast({
        title: "Could not open SOAP review",
        description:
          getErrorMessage(error) ||
          "The SOAP draft could not be promoted.",
      });
    } finally {
      setReviewingSoap(false);
    }
  };

  const archiveVisit = async () => {
    const confirmed = window.confirm(
      "Archive this telehealth visit? It will be removed from the normal list, but its clinical history will be preserved."
    );

    if (!confirmed) return;

    setArchiving(true);

    try {
      await api.post(`/appointments/${a.id}/archive`);
      toast({ title: "Visit archived" });
      await onChanged?.();
    } catch (error) {
      toast({
        title: "Archive failed",
        description: getErrorMessage(error) || "Try again.",
      });
    } finally {
      setArchiving(false);
    }
  };

  return (
    <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5 flex flex-col md:flex-row md:items-center gap-4" data-testid={`th-visit-${a.id}`}>
      <div className="md:w-32 text-center">
        <div className="text-[10px] uppercase tracking-widest text-[#8a6a3c]">{dateLabel}</div>
        <div className="font-display text-2xl text-[#1f2a22] mt-0.5">{timeLabel}</div>
        {minsUntil > 0 && minsUntil <= 60 && <div className="text-xs text-[#c19a4b] mt-1">in {minsUntil}m</div>}
        {active && <div className="text-xs text-[#2f4a3a] mt-1 flex items-center justify-center gap-1"><span className="w-2 h-2 rounded-full bg-[#2f4a3a] animate-pulse" /> Live now</div>}
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-medium text-[#1f2a22]">{a.client_name || a.practitioner_name || "—"}</div>
        <div className="text-sm text-[#6a6a6a] mt-0.5">{a.visit_type || "Telehealth visit"}</div>
        {a.reason && <div className="text-xs text-[#8a6a3c] mt-1 italic truncate">{a.reason}</div>}
        <div className="flex flex-wrap items-center gap-3 mt-2 text-xs">
          <span className="inline-flex items-center gap-1 text-[#2f4a3a]">
            <Lock size={11} />
            End-to-end · self-hosted
          </span>

          {a.consent_telehealth && (
            <span className="text-[#5b6f5b]">
              ✓ consent on file
            </span>
          )}

          <DocumentationBadge appointment={a} />
        </div>
      </div>
      <div className="flex flex-col items-end gap-2 md:w-44">
        <Link to={`/portal/visit/${a.id}`} className={joinable ? "" : "pointer-events-none"}>
          <Button
            disabled={!joinable}
            className={`rounded-full h-10 w-full ${active ? "bg-[#2f4a3a] hover:bg-[#263d30]" : "bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]"} ${joinable ? "" : "opacity-40"}`}
            data-testid={`th-join-${a.id}`}
          >
            <Video size={14} className="mr-2" /> {active ? "Rejoin" : "Join visit"}
          </Button>
        </Link>
        {active && (
          <Button
            type="button"
            variant="outline"
            onClick={endSession}
            disabled={ending}
            className="rounded-full h-9 w-full border-[#7a2a2a] text-[#7a2a2a] hover:bg-[#fff5f5]"
            data-testid={`th-end-${a.id}`}
          >
            {ending ? (
              <>
                <Loader2
                  size={13}
                  className="mr-2 animate-spin"
                />
                Ending…
              </>
            ) : (
              <>
                <DoorOpen size={13} className="mr-2" />
                End session
              </>
            )}
          </Button>
        )}

        {a?.telehealth?.documentation_status ===
          "soap_review_required" && (
          <Button
            type="button"
            onClick={reviewSoap}
            disabled={reviewingSoap}
            className="rounded-full h-9 w-full bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]"
            data-testid={`telehealth-review-soap-${a.id}`}
          >
            {reviewingSoap ? (
              <>
                <Loader2
                  size={13}
                  className="mr-2 animate-spin"
                />
                Opening SOAP…
              </>
            ) : (
              <>
                <FileText
                  size={13}
                  className="mr-2"
                />
                Review SOAP
              </>
            )}
          </Button>
        )}

        {showRecordings && (a.recordings || []).length > 0 && (
          <span className="text-xs text-[#6a6a6a] flex items-center gap-1"><FileVideo size={11} /> {a.recordings.length} recording(s)</span>
        )}

        {canArchive && (
          <Button
            type="button"
            variant="outline"
            onClick={archiveVisit}
            disabled={archiving}
            className="rounded-full h-9 w-full border-[#8a6a3c] text-[#8a6a3c] hover:bg-[#f1ead8]"
            data-testid={`th-archive-${a.id}`}
          >
            {archiving ? (
              <>
                <Loader2 size={13} className="mr-2 animate-spin" />
                Archiving…
              </>
            ) : (
              <>
                <History size={13} className="mr-2" />
                Archive
              </>
            )}
          </Button>
        )}
      </div>
    </div>
  );
}

function EquipmentTest() {
  const { toast } = useToast();
  const videoRef = React.useRef(null);
  const [stream, setStream] = React.useState(null);
  const [micOn, setMicOn] = React.useState(true);
  const [camOn, setCamOn] = React.useState(true);
  const [iceServers, setIceServers] = React.useState([]);
  const [vapidStatus, setVapidStatus] = React.useState("checking");

  const start = async () => {
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      setStream(s);
      if (videoRef.current) videoRef.current.srcObject = s;
    } catch (e) { toast({ title: "Camera/mic blocked", description: "Allow access in your browser settings." }); }
  };
  const stop = () => {
    if (stream) { stream.getTracks().forEach((t) => t.stop()); setStream(null); }
    if (videoRef.current) videoRef.current.srcObject = null;
  };

  React.useEffect(() => () => stop(), []); // eslint-disable-line

  React.useEffect(() => {
    api.get("/webrtc/config").then((r) => setIceServers(r.data?.iceServers || [])).catch(() => {});
    if ("Notification" in window) setVapidStatus(Notification.permission);
  }, []);

  const toggleMic = () => { if (stream) { stream.getAudioTracks().forEach((t) => (t.enabled = !micOn)); setMicOn((v) => !v); } };
  const toggleCam = () => { if (stream) { stream.getVideoTracks().forEach((t) => (t.enabled = !camOn)); setCamOn((v) => !v); } };

  const hasTurn = normalizeArray(iceServers).some((s) => (s.urls || "").startsWith("turn:") || (s.urls || "").startsWith("turns:"));

  return (
    <div className="grid lg:grid-cols-[2fr_1fr] gap-6" data-testid="equipment-panel">
      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5">
        <div className="eyebrow text-[#8a6a3c] mb-3">Camera & microphone</div>
        <div className="rounded-2xl bg-black overflow-hidden aspect-video relative mb-4">
          <video ref={videoRef} autoPlay muted playsInline className="w-full h-full object-cover" data-testid="eq-video" />
          {!stream && (
            <button onClick={start} className="absolute inset-0 flex flex-col items-center justify-center text-[#c19a4b] hover:text-[#f6f1e6] transition" data-testid="eq-start-btn">
              <Play size={36} className="mb-2" />
              <span className="text-sm">Tap to test camera & mic</span>
            </button>
          )}
        </div>
        <div className="flex gap-2">
          <Button onClick={toggleMic} disabled={!stream} variant="outline" className="rounded-full">
            {micOn ? <Mic size={14} /> : <MicOff size={14} />}
          </Button>
          <Button onClick={toggleCam} disabled={!stream} variant="outline" className="rounded-full">
            {camOn ? <Video size={14} /> : <VideoOff size={14} />}
          </Button>
          {stream && <Button onClick={stop} variant="outline" className="rounded-full text-[#7a2a2a] border-[#7a2a2a]">Stop</Button>}
        </div>
      </div>
      <div className="space-y-4">
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5">
          <div className="eyebrow text-[#8a6a3c] mb-3">Network</div>
          <Diag label="STUN servers" value={`${normalizeArray(iceServers).filter((s) => (s.urls || "").startsWith("stun")).length} configured`} ok />
          <Diag label="TURN relay" value={hasTurn ? "configured" : "not configured (STUN only)"} ok={hasTurn} warn={!hasTurn} />
          <Diag label="Browser" value={navigator.userAgent.split(" ").slice(-2)[0]} ok />
          <div className="text-xs text-[#6a6a6a] mt-3 flex items-center gap-1">
            <Wifi size={11} /> If you're behind a strict firewall, ask your admin to enable a TURN server.
          </div>
        </div>
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5">
          <div className="eyebrow text-[#8a6a3c] mb-3">Notifications</div>
          <Diag label="Push permission" value={vapidStatus} ok={vapidStatus === "granted"} warn={vapidStatus === "default"} fail={vapidStatus === "denied"} />
          <div className="text-xs text-[#6a6a6a] mt-3">Grant to receive visit-start pings.</div>
        </div>
      </div>
    </div>
  );
}

function Diag({ label, value, ok, warn, fail }) {
  const color = fail ? "text-[#7a2a2a]" : warn ? "text-[#8a6a3c]" : ok ? "text-[#2f4a3a]" : "text-[#6a6a6a]";
  return (
    <div className="flex justify-between text-sm py-1">
      <span className="text-[#3a3a3a]">{label}</span>
      <span className={`font-medium ${color}`}>{value}</span>
    </div>
  );
}

function PatientVisitInvitations({ rows }) {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [joiningId, setJoiningId] = React.useState("");

  const invitations = (rows || []).filter((appointment) => {
    const waitingRoom = appointment.waiting_room || {};
    const state = waitingRoom.state;

    if (state !== "invited") return false;

    const expiresAt = waitingRoom.expires_at
      ? new Date(waitingRoom.expires_at)
      : null;

    return !expiresAt || expiresAt.getTime() > Date.now();
  });

  const join = async (appointment) => {
    setJoiningId(appointment.id);

    try {
      await api.post(
        `/appointments/${appointment.id}/telehealth/request-join`
      );

      navigate(`/portal/visit/${appointment.id}`);
    } catch (error) {
      toast({
        title: "Unable to join",
        description:
          getErrorMessage(error) ||
          "The telehealth invitation may have expired.",
      });
    } finally {
      setJoiningId("");
    }
  };

  if (!invitations.length) return null;

  return (
    <div
      className="mb-8 rounded-2xl border border-[#c19a4b] bg-[#fbf3df] p-5"
      data-testid="patient-telehealth-invitations"
    >
      <div className="eyebrow text-[#8a6a3c]">
        Telehealth request
      </div>

      <div className="mt-3 space-y-3">
        {invitations.map((appointment) => {
          const waitingRoom = appointment.waiting_room || {};

          return (
            <div
              key={appointment.id}
              className="flex flex-col justify-between gap-4 rounded-xl border border-[#e0d6bc] bg-[#fbf7ee] p-4 md:flex-row md:items-center"
            >
              <div>
                <div className="font-display text-xl text-[#1f2a22]">
                  {waitingRoom.provider_name ||
                    appointment.practitioner_name ||
                    "Your provider"}{" "}
                  is inviting you to a video visit
                </div>

                <div className="mt-1 text-sm text-[#6a6a6a]">
                  Select Join waiting room. Your provider will admit
                  you when ready.
                </div>

                {waitingRoom.expires_at && (
                  <div className="mt-2 text-xs text-[#8a6a3c]">
                    Invitation expires at{" "}
                    {new Date(
                      waitingRoom.expires_at
                    ).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </div>
                )}
              </div>

              <Button
                onClick={() => join(appointment)}
                disabled={joiningId === appointment.id}
                className="rounded-full bg-[#2f4a3a] text-[#f6f1e6] hover:bg-[#263d30]"
                data-testid={`patient-join-instant-${appointment.id}`}
              >
                {joiningId === appointment.id
                  ? "Joining…"
                  : "Join waiting room"}
              </Button>
            </div>
          );
        })}
      </div>
    </div>
  );
}


function InstantVisitDialog({ open, onOpenChange, onCreated }) {
  const { toast } = useToast();
  const navigate = useNavigate();
  const [clients, setClients] = React.useState([]);
  const [form, setForm] = React.useState({ client_id: "", reason: "", duration: 30 });
  const [submitting, setSubmitting] = React.useState(false);

  React.useEffect(() => { if (open) api.get("/clients").then((r) => setClients(normalizeArray(r.data, ["clients"]))); }, [open]);

  const submit = async () => {
    if (!form.client_id) { toast({ title: "Select a patient" }); return; }
    setSubmitting(true);
    try {
      const start = new Date();
      const end = new Date(start.getTime() + form.duration * 60_000);
      const r = await api.post("/appointments", {
        client_id: form.client_id,
        start: start.toISOString(),
        end: end.toISOString(),
        visit_mode: "telehealth",
        visit_type: "Instant telehealth",
        reason: form.reason,
        status: "scheduled",
      });

      await api.post(
        `/appointments/${r.data.id}/telehealth/invite`
      );

      toast({
        title: "Invitation sent",
        description:
          "The patient can now join your waiting room from their portal.",
      });

      onOpenChange(false);
      onCreated && onCreated();

      // Provider enters their waiting-room view immediately.
      navigate(`/portal/visit/${r.data.id}`);
    } catch (e) {
      toast({ title: "Failed to start", description: getErrorMessage(e) || "" });
    } finally { setSubmitting(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9]">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">Start an instant visit</DialogTitle>
          <DialogDescription>Creates a telehealth appointment now and opens the visit room.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label>Patient</Label>
            <Select value={form.client_id} onValueChange={(v) => setForm({ ...form, client_id: v })}>
              <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="th-instant-client"><SelectValue placeholder="Select patient…" /></SelectTrigger>
              <SelectContent>{normalizeArray(clients).map((c) => <SelectItem key={c.id} value={c.id}>{c.full_name || c.email}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div><Label>Reason</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} placeholder="Optional" /></div>
          <div><Label>Duration (min)</Label><Input type="number" className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.duration} onChange={(e) => setForm({ ...form, duration: parseInt(e.target.value || "30") })} /></div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={submit} disabled={submitting} className="bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6] rounded-full" data-testid="th-instant-submit">
            <Sparkles size={14} className="mr-1" /> {submitting ? "Starting…" : "Start now"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------- Provider waiting-room queue ----------
function WaitingRoomQueue() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [queue, setQueue] = React.useState([]);
  const [busyId, setBusyId] = React.useState("");
  const [declineFor, setDeclineFor] = React.useState(null);
  const [reason, setReason] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      const r = await api.get("/telehealth/waiting-room/queue");
      setQueue(normalizeArray(r.data, ["queue"]));
    } catch {
      // 403 for staff/etc — silently ignore
    }
  }, []);

  React.useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load]);

  const admit = async (appt) => {
    setBusyId(appt.appointment_id);
    try {
      await api.post(`/appointments/${appt.appointment_id}/telehealth/admit`);
      toast({ title: `Admitted ${appt.client_name || "patient"}` });
      navigate(`/portal/visit/${appt.appointment_id}`);
    } catch (e) {
      toast({ title: "Admit failed", description: getErrorMessage(e) || "" });
    } finally {
      setBusyId("");
      load();
    }
  };

  const submitDecline = async () => {
    if (!declineFor || reason.trim().length < 3) return;
    setBusyId(declineFor.appointment_id);
    try {
      await api.post(`/appointments/${declineFor.appointment_id}/telehealth/decline`,
        { reason: reason.trim() });
      toast({ title: "Session declined" });
      setDeclineFor(null); setReason("");
    } catch (e) {
      toast({ title: "Decline failed", description: getErrorMessage(e) || "" });
    } finally {
      setBusyId("");
      load();
    }
  };

  if (queue.length === 0) return null;
  return (
    <div className="rounded-2xl border border-[#c19a4b] bg-[#fbf7ee] p-5 mb-8" data-testid="waiting-room-queue">
      <div className="flex items-center gap-2 mb-3">
        <DoorOpen size={16} className="text-[#c19a4b]" />
        <div className="eyebrow text-[#8a6a3c]">Waiting room ({queue.length})</div>
      </div>
      <div className="space-y-3">
        {normalizeArray(queue).map((q) => (
          <div key={q.appointment_id} className="flex flex-col md:flex-row md:items-center gap-3 border-t border-[#e7dfc9] pt-3 first:border-t-0 first:pt-0" data-testid={`waiting-row-${q.appointment_id}`}>
            <div className="flex-1 min-w-0">
              <div className="font-medium text-[#1f2a22]">{q.client_name || "Patient"}</div>
              <div className="text-xs text-[#6a6a6a]">
                Requested {q.waiting_room?.request_at ? new Date(q.waiting_room.request_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "just now"}
                {q.visit_type && ` · ${q.visit_type}`}
              </div>
              {q.reason && <div className="text-xs text-[#8a6a3c] italic truncate">{q.reason}</div>}
            </div>
            <div className="flex gap-2">
              <Button
                onClick={() => admit(q)}
                disabled={busyId === q.appointment_id}
                className="rounded-full h-9 bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
                data-testid={`waiting-admit-${q.appointment_id}`}
              >
                <UserCheck size={13} className="mr-1" /> Admit
              </Button>
              <Button
                onClick={() => { setDeclineFor(q); setReason(""); }}
                variant="outline"
                className="rounded-full h-9 border-[#7a2a2a] text-[#7a2a2a] hover:bg-[#7a2a2a] hover:text-[#f6f1e6]"
                data-testid={`waiting-decline-${q.appointment_id}`}
              >
                <UserX size={13} className="mr-1" /> Decline
              </Button>
            </div>
          </div>
        ))}
      </div>

      <Dialog open={!!declineFor} onOpenChange={(v) => !v && setDeclineFor(null)}>
        <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9]" data-testid="waiting-decline-dialog">
          <DialogHeader>
            <DialogTitle className="font-display text-2xl">Decline this visit</DialogTitle>
            <DialogDescription>
              The reason you enter will be shown to {declineFor?.client_name || "the patient"} and recorded in the audit log.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <Label>Decline reason</Label>
            <Input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="bg-[#f6f1e6] border-[#e0d6bc]"
              maxLength={240}
              placeholder="Brief reason (min 3 chars)"
              data-testid="waiting-decline-reason-input"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeclineFor(null)}>Cancel</Button>
            <Button
              onClick={submitDecline}
              disabled={reason.trim().length < 3}
              className="bg-[#7a2a2a] hover:bg-[#5f1f1f] text-[#f6f1e6] rounded-full"
              data-testid="waiting-decline-confirm"
            >
              Confirm decline
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
