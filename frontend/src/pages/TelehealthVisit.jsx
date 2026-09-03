import React from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import api, { API_BASE, LS } from "../lib/api";
import { useAuth } from "../lib/auth";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Checkbox } from "../components/ui/checkbox";
import { useToast } from "../hooks/use-toast";
import { getErrorMessage } from "../lib/errors";
import {
  Video, Mic, MicOff, VideoOff, PhoneOff, ArrowLeft,
  ShieldCheck, AlertCircle, Loader2, CheckCircle2, MonitorUp,
  MessageSquare, Send, Circle, Square, Sparkles, FileText, Save,
  UserCheck, UserX, DoorOpen,
} from "lucide-react";
import { normalizeArray } from "../lib/collections";
import TelehealthClinicalPanel from "../components/telehealth/TelehealthClinicalPanel";

const formatRecordingElapsed = (seconds) => {
  const value = Math.max(0, Number(seconds) || 0);
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const secs = value % 60;

  return [hours, minutes, secs]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
};

const FALLBACK_ICE = [
  { urls: "stun:stun.l.google.com:19302" },
  { urls: "stun:stun1.l.google.com:19302" },
];

export default function TelehealthVisit() {
  const { id } = useParams();
  const { user } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [appt, setAppt] = React.useState(null);
  const [stage, setStage] = React.useState("loading");
  const [errMsg, setErrMsg] = React.useState("");
  const [consent, setConsent] = React.useState({
    acknowledged: false,
    recordingConsent: false,
    signature: "",
  });

  const [localStream, setLocalStream] = React.useState(null);
  const [micOn, setMicOn] = React.useState(true);
  const [camOn, setCamOn] = React.useState(true);
  const [sharing, setSharing] = React.useState(false);
  const [peerOnline, setPeerOnline] = React.useState(false);
  const [chatMsgs, setChatMsgs] = React.useState([]);
  const [chatDraft, setChatDraft] = React.useState("");
  const [chatOpen, setChatOpen] = React.useState(false);
  const [clinicalOpen, setClinicalOpen] = React.useState(false);
  const [recording, setRecording] = React.useState(false);
  const [recordingSaved, setRecordingSaved] =
    React.useState(false);
  const [recordingStartedAt, setRecordingStartedAt] =
    React.useState(null);
  const [recordingElapsed, setRecordingElapsed] =
    React.useState(0);
  const [recordingReminderDue, setRecordingReminderDue] =
    React.useState(false);
  const [
    showRecordingExceptionDialog,
    setShowRecordingExceptionDialog,
  ] = React.useState(false);
  const [
    recordingExceptionCode,
    setRecordingExceptionCode,
  ] = React.useState("");
  const [
    recordingExceptionReason,
    setRecordingExceptionReason,
  ] = React.useState("");
  const [transcriptionJobName, setTranscriptionJobName] =
    React.useState("");
  const [transcriptionStatus, setTranscriptionStatus] =
    React.useState("");
  const [soap, setSoap] = React.useState({ subjective: "", objective: "", assessment: "", plan: "" });
  const [soapSavedAt, setSoapSavedAt] = React.useState(null);
  const [soapOpen, setSoapOpen] = React.useState(false);
  const [aiBusy, setAiBusy] = React.useState(false);
  const [waitingRoom, setWaitingRoom] = React.useState({ state: "idle" });
  const [declineReason, setDeclineReason] = React.useState("");
  const [showDeclineDialog, setShowDeclineDialog] = React.useState(false);
  const [busyAction, setBusyAction] = React.useState("");

  const localVideoRef = React.useRef(null);
  const remoteVideoRef = React.useRef(null);
  const wsRef = React.useRef(null);
  const pcRef = React.useRef(null);
  const pendingIceRef = React.useRef([]);
  const localStreamRef = React.useRef(null); // mirror for cleanup
  const recorderRef = React.useRef(null);
  const recChunksRef = React.useRef([]);
  const recordingUploadResolveRef = React.useRef(null);
  const recordingUploadRejectRef = React.useRef(null);

  // Current provider encounter lifecycle.
  // Refs are used so navigation/unload handlers always see
  // the latest value without stale React closures.
  const providerEncounterActiveRef =
    React.useRef(false);

  const providerEndCompletedRef =
    React.useRef(false);

  const attachLocalVideo = React.useCallback((video) => {
    localVideoRef.current = video;

    if (!video) return;

    const stream =
      localStreamRef.current || localStream;

    if (!stream) return;

    if (video.srcObject !== stream) {
      video.srcObject = stream;
    }

    video.muted = true;
    video.playsInline = true;
    video.autoplay = true;

    video.play().catch(() => {
      // Browser may require another user interaction.
    });
  }, [localStream]);

  const isProvider = user?.role && user.role !== "client";
  const role = isProvider ? "provider" : "client";

  React.useEffect(() => {
    if (stage !== "in-call" || !isProvider) {
      return;
    }

    setClinicalOpen(true);
    setChatOpen(false);
    setSoapOpen(false);
  }, [stage, isProvider]);


  React.useEffect(() => {
    providerEncounterActiveRef.current = Boolean(
      isProvider &&
      (
        stage === "in-call" ||
        waitingRoom?.state === "admitted"
      )
    );

    if (waitingRoom?.state === "ended") {
      providerEndCompletedRef.current = true;
      providerEncounterActiveRef.current = false;
    }
  }, [
    isProvider,
    stage,
    waitingRoom?.state,
  ]);


  // Protect an active provider encounter from refresh,
  // tab close, or direct browser navigation.
  React.useEffect(() => {
    const handleBeforeUnload = (event) => {
      if (
        !providerEncounterActiveRef.current ||
        providerEndCompletedRef.current
      ) {
        return;
      }

      event.preventDefault();
      event.returnValue = "";
    };

    window.addEventListener(
      "beforeunload",
      handleBeforeUnload
    );

    return () => {
      window.removeEventListener(
        "beforeunload",
        handleBeforeUnload
      );
    };
  }, []);

  React.useEffect(() => {
    if (!recording || !recordingStartedAt) {
      setRecordingElapsed(0);
      return;
    }

    const update = () => {
      setRecordingElapsed(
        Math.floor(
          (Date.now() - recordingStartedAt) / 1000
        )
      );
    };

    update();
    const interval = window.setInterval(update, 1000);

    return () => window.clearInterval(interval);
  }, [recording, recordingStartedAt]);

  React.useEffect(() => {
    if (
      !isProvider ||
      stage !== "in-call" ||
      recording ||
      recordingSaved
    ) {
      setRecordingReminderDue(false);
      return;
    }

    const timer = window.setTimeout(() => {
      setRecordingReminderDue(true);

      toast({
        title: "Recording & transcription not started",
        description:
          "Start the clinical recording or document an exception before ending this visit.",
      });
    }, 60000);

    return () => window.clearTimeout(timer);
  }, [
    isProvider,
    stage,
    recording,
    recordingSaved,
    toast,
  ]);

  // 1) Load appointment
  React.useEffect(() => {
    const run = async () => {
      try {
        const r = await api.get("/appointments");
        const mine = normalizeArray(
          r.data,
          ["appointments", "items", "appts"]
        ).find(
          (appointment) =>
            String(appointment.id) === String(id)
        );
        if (!mine) { setErrMsg("Visit not found."); setStage("error"); return; }
        setAppt(mine);
        const wrState = (mine.waiting_room || {}).state;
        if (isProvider) {
          // Provider: skip consent; go to wait screen. If already admitted, will
          // auto-start call via the waiting-room effect.
          if (wrState === "admitted") setStage("tech");
          else setStage("provider-wait");
        } else {
          if (!mine.consent_telehealth) setStage("consent");
          else if (wrState === "declined") setStage("declined");
          else if (wrState === "ended") setStage("ended");
          else if (wrState === "requested") setStage("waiting");
          else if (wrState === "admitted") setStage("tech");
          else setStage("tech");
        }
      } catch (e) {
        setErrMsg(getErrorMessage(e) || "Could not load visit."); setStage("error");
      }
    };
    run();
  }, [id, isProvider]);

  // 2) Camera/mic preview during tech / provider-wait stage
  React.useEffect(() => {
    if (!["tech", "provider-wait", "waiting"].includes(stage) || localStream) return;
    (async () => {
      try {
        const s = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
        setLocalStream(s);
        localStreamRef.current = s;
        if (localVideoRef.current) localVideoRef.current.srcObject = s;
      } catch (e) {
        toast({ title: "Camera/mic blocked", description: "Allow access in your browser to continue." });
      }
    })();
    // eslint-disable-next-line
  }, [stage]);

  // Reattach the existing camera stream whenever React replaces the
  // local <video> element during tech → waiting → in-call transitions.
  React.useEffect(() => {
    const video = localVideoRef.current;

    if (!video || !localStream) return;

    if (video.srcObject !== localStream) {
      video.srcObject = localStream;
    }

    video.muted = true;
    video.playsInline = true;
    video.autoplay = true;

    const playPreview = async () => {
      try {
        await video.play();
      } catch {
        // Browser may require another user interaction before autoplay.
      }
    };

    playPreview();
  }, [localStream, stage]);

  // Cleanup on unmount
  React.useEffect(() => {
    return () => endCall(false);
    // eslint-disable-next-line
  }, []);

  // ---------- Waiting room ----------
  const fetchWaitingRoom = React.useCallback(async () => {
    try {
      const r = await api.get(`/appointments/${id}/telehealth/waiting-room`);
      setWaitingRoom(r.data || { state: "idle" });
      return r.data;
    } catch {
      return null;
    }
  }, [id]);

  // Provider: poll waiting-room until admitted or ended; also fetch once on load.
  React.useEffect(() => {
    if (!id) return;
    fetchWaitingRoom();
  }, [id, fetchWaitingRoom]);

  // Client polling while in the waiting stage; provider polling in wait-for-patient.
  React.useEffect(() => {
    if (!["waiting", "provider-wait"].includes(stage)) return;
    const t = setInterval(fetchWaitingRoom, 3000);
    return () => clearInterval(t);
  }, [stage, fetchWaitingRoom]);

  // React to waiting-room state transitions.
  // For an admitted visit, wait until camera/mic access has completed
  // before starting WebRTC. This also supports browser refresh/rejoin:
  // both patient and provider load an admitted visit into the tech stage.
  React.useEffect(() => {
    const s = waitingRoom?.state;

    if (!s) return;

    if (isProvider) {
      if (
        s === "admitted" &&
        ["provider-wait", "tech"].includes(stage) &&
        localStream
      ) {
        startCall();
      }

      return;
    }

    if (
      s === "admitted" &&
      ["waiting", "tech"].includes(stage) &&
      localStream
    ) {
      startCall();
      return;
    }

    if (
      s === "declined" &&
      ["waiting", "tech"].includes(stage)
    ) {
      setStage("declined");
      return;
    }

    if (
      s === "ended" &&
      ["waiting", "tech", "in-call"].includes(stage)
    ) {
      setStage("ended");
    }

    // eslint-disable-next-line
  }, [
    waitingRoom,
    stage,
    localStream,
    isProvider,
  ]);

  const requestJoin = async () => {
    setBusyAction("request");
    try {
      const r = await api.post(`/appointments/${id}/telehealth/request-join`);
      setWaitingRoom(r.data || { state: "requested" });

      // Move to the waiting-room UI. The local-stream effect will attach
      // the existing mobile camera stream to the newly mounted video.
      setStage("waiting");
    } catch (e) {
      toast({ title: "Could not request to join", description: getErrorMessage(e) || "" });
    } finally { setBusyAction(""); }
  };

  const providerAdmit = async () => {
    setBusyAction("admit");
    try {
      const r = await api.post(`/appointments/${id}/telehealth/admit`);
      setWaitingRoom(r.data);
      toast({ title: "Patient admitted" });
    } catch (e) {
      toast({ title: "Admit failed", description: getErrorMessage(e) || "" });
    } finally { setBusyAction(""); }
  };

  const providerDecline = async () => {
    if (declineReason.trim().length < 3) {
      toast({ title: "Enter a decline reason (min 3 characters)" });
      return;
    }
    setBusyAction("decline");
    try {
      const r = await api.post(`/appointments/${id}/telehealth/decline`, { reason: declineReason.trim() });
      setWaitingRoom(r.data);
      setShowDeclineDialog(false);
      setDeclineReason("");
      toast({ title: "Session declined" });
      setStage("declined");
    } catch (e) {
      toast({ title: "Decline failed", description: getErrorMessage(e) || "" });
    } finally { setBusyAction(""); }
  };

  const providerEnd = async () => {
    if (busyAction === "end") return;

    setBusyAction("end");

    try {
      if (
        recorderRef.current &&
        recorderRef.current.state === "recording"
      ) {
        toast({
          title: "Finishing clinical recording",
          description:
            "Uploading the recording before ending the visit.",
        });

        await stopRecordingAndWaitForUpload();
      }

      const r = await api.post(
        `/appointments/${id}/telehealth/end`,
        {}
      );

      providerEndCompletedRef.current = true;
      providerEncounterActiveRef.current = false;

      setWaitingRoom(r.data);
      endCall(true);
    } catch (e) {
      const detail = e?.response?.data?.detail;

      if (
        detail?.code
        === "recording_or_exception_required"
      ) {
        setShowRecordingExceptionDialog(true);

        toast({
          title: "Documentation required",
          description:
            detail?.message ||
            "Record the visit or document why recording could not be completed.",
        });
      } else {
        toast({
          title: "End paused",
          description:
            getErrorMessage(e) ||
            "The visit was not ended.",
        });
      }
    } finally {
      setBusyAction("");
    }
  };

  const submitRecordingException = async () => {
    if (!recordingExceptionCode) {
      toast({
        title: "Select an exception reason",
      });
      return;
    }

    if (recordingExceptionReason.trim().length < 3) {
      toast({
        title: "Add a brief explanation",
      });
      return;
    }

    setBusyAction("end-exception");

    try {
      const r = await api.post(
        `/appointments/${id}/telehealth/end`,
        {
          recording_exception_code:
            recordingExceptionCode,
          recording_exception_reason:
            recordingExceptionReason.trim(),
        }
      );

      providerEndCompletedRef.current = true;
      providerEncounterActiveRef.current = false;

      setWaitingRoom(r.data);
      setShowRecordingExceptionDialog(false);
      endCall(true);
    } catch (e) {
      toast({
        title: "Could not end visit",
        description: getErrorMessage(e) || "",
      });
    } finally {
      setBusyAction("");
    }
  };

  // ---------- consent ----------
  const submitConsent = async () => {
    if (!consent.acknowledged || !consent.signature.trim()) {
      toast({ title: "Acknowledge and type your name to consent." }); return;
    }
    try {
      await api.post(
        `/appointments/${id}/telehealth/consent`,
        {
          signature: consent.signature.trim(),
          recording_consent: consent.recordingConsent,
        }
      );
      toast({ title: "Consent recorded" });
      const r = await api.get("/appointments");
      const mine = normalizeArray(
        r.data,
        ["appointments", "items", "appts"]
      ).find(
        (appointment) =>
          String(appointment.id) === String(id)
      );

      if (mine) {
        setAppt(mine);
      }
      setStage("tech");
    } catch (e) { toast({ title: "Failed", description: getErrorMessage(e) || "" }); }
  };

  // ---------- WebRTC + signaling ----------
  const sendWS = (obj) => { if (wsRef.current?.readyState === 1) wsRef.current.send(JSON.stringify(obj)); };

  const newPC = (signalingStream, iceServers = FALLBACK_ICE) => {
    const pc = new RTCPeerConnection({ iceServers });
    pc.onicecandidate = (e) => { if (e.candidate) sendWS({ type: "ice-candidate", candidate: e.candidate }); };
    pc.ontrack = (event) => {
      console.info(
        "Remote track received:",
        event.track?.kind,
        event.track?.readyState,
      );

      let remoteStream = event.streams?.[0];

      // Some mobile browsers deliver a track without a populated streams
      // array. Build a MediaStream so the remote video still receives it.
      if (!remoteStream && event.track) {
        remoteStream = new MediaStream([event.track]);
      }

      if (remoteVideoRef.current && remoteStream) {
        remoteVideoRef.current.srcObject = remoteStream;
        remoteVideoRef.current
          .play()
          .catch((error) =>
            console.warn("Remote video play failed:", error)
          );
      }

      if (event.track) {
        event.track.onunmute = () => {
          setPeerOnline(true);

          if (remoteVideoRef.current) {
            remoteVideoRef.current
              .play()
              .catch(() => {});
          }
        };

        event.track.onended = () => {
          console.warn("Remote track ended:", event.track.kind);
        };
      }
    };
    pc.onconnectionstatechange = () => {
      if (["failed", "disconnected", "closed"].includes(pc.connectionState)) {
        setPeerOnline(false);
      }
    };
    if (signalingStream) {
      signalingStream.getTracks().forEach((track) => {
        track.enabled = true;

        console.info(
          "Adding local track:",
          track.kind,
          track.readyState,
          track.enabled,
        );

        pc.addTrack(track, signalingStream);
      });
    }
    return pc;
  };

  const startCall = async () => {
    if (!localStream) { toast({ title: "Allow camera & mic first" }); return; }
    setStage("in-call");
    // Fetch ICE config + one-shot ticket (no JWT in URL)
    let iceServers = FALLBACK_ICE;
    let ticket = "";
    try {
      const cfg = await api.get("/webrtc/config");
      if (cfg.data?.iceServers?.length) iceServers = cfg.data.iceServers;
    } catch {}
    try {
      const t = await api.post(`/visits/${id}/ws-ticket`);
      ticket = t.data?.ticket || "";
    } catch (e) {
      setErrMsg(getErrorMessage(e) || "Could not authorize visit.");
      setStage("error");
      return;
    }
    const wsUrl = API_BASE.replace(/^http/, "ws") + `/ws/visit/${id}?ticket=${encodeURIComponent(ticket)}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      api.get(`/visits/${id}/chat`).then((r) => {
        setChatMsgs(normalizeArray(r.data, ["chatMsgs"]).map((m) => ({ from: m.from_role, body: m.body, ts: m.ts })));
      }).catch(() => {});
      // Provider: load any in-progress live SOAP
      if (isProvider) {
        api.get(`/visits/${id}/live-soap`).then((r) => setSoap({
          subjective: r.data?.subjective || "",
          objective: r.data?.objective || "",
          assessment: r.data?.assessment || "",
          plan: r.data?.plan || "",
        })).catch(() => {});
      }
    };

    pcRef.current = newPC(localStream, iceServers);

    ws.onmessage = async (ev) => {
      let data; try { data = JSON.parse(ev.data); } catch { return; }
      const pc = pcRef.current;

      if (data.type === "joined") {
        setPeerOnline(!!data.peer_present);
        if (isProvider && data.peer_present) {
          // Provider initiates the offer
          await createOffer();
        }
      } else if (data.type === "peer-joined") {
        setPeerOnline(true);
        toast({ title: "Other party joined" });
        if (isProvider) await createOffer();
      } else if (data.type === "peer-left") {
        setPeerOnline(false);
        toast({ title: "Other party disconnected" });
      } else if (data.type === "webrtc-offer") {
        await pc.setRemoteDescription(
          new RTCSessionDescription(data.sdp)
        );

        // Mobile candidates can arrive before the offer. Apply them only
        // after the remote description exists.
        for (const candidate of pendingIceRef.current) {
          try {
            await pc.addIceCandidate(candidate);
          } catch (error) {
            console.warn("Queued ICE candidate failed:", error);
          }
        }
        pendingIceRef.current = [];

        const answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);

        sendWS({
          type: "webrtc-answer",
          sdp: pc.localDescription,
        });
      } else if (data.type === "webrtc-answer") {
        await pc.setRemoteDescription(
          new RTCSessionDescription(data.sdp)
        );

        for (const candidate of pendingIceRef.current) {
          try {
            await pc.addIceCandidate(candidate);
          } catch (error) {
            console.warn("Queued ICE candidate failed:", error);
          }
        }
        pendingIceRef.current = [];
      } else if (data.type === "ice-candidate") {
        if (!data.candidate) return;

        const candidate = new RTCIceCandidate(data.candidate);

        if (pc.remoteDescription?.type) {
          try {
            await pc.addIceCandidate(candidate);
          } catch (error) {
            console.warn("ICE candidate failed:", error);
          }
        } else {
          pendingIceRef.current.push(candidate);
        }
      } else if (data.type === "chat") {
        setChatMsgs((m) => [...m, { from: data.from, body: data.body, ts: new Date().toISOString() }]);
      } else if (data.type === "waiting-room") {
        setWaitingRoom({
          state: data.state, request_at: data.request_at,
          admitted_at: data.admitted_at, declined_at: data.declined_at,
          decline_reason: data.decline_reason, ended_at: data.ended_at,
        });
      }
    };

    ws.onerror = (e) => console.warn("WS error", e);
    ws.onclose = () => { /* peer-left will fire from server when it disconnects */ };
  };

  const createOffer = async () => {
    const pc = pcRef.current; if (!pc) return;
    const offer = await pc.createOffer({ offerToReceiveVideo: true, offerToReceiveAudio: true });
    await pc.setLocalDescription(offer);
    sendWS({ type: "webrtc-offer", sdp: offer });
  };

  const toggleMic = () => {
    if (!localStream) return;
    localStream.getAudioTracks().forEach((t) => (t.enabled = !micOn));
    setMicOn((v) => !v);
    sendWS({ type: "media-state", mic: !micOn, cam: camOn });
  };
  const toggleCam = () => {
    if (!localStream) return;
    localStream.getVideoTracks().forEach((t) => (t.enabled = !camOn));
    setCamOn((v) => !v);
    sendWS({ type: "media-state", mic: micOn, cam: !camOn });
  };

  const toggleScreenShare = async () => {
    const pc = pcRef.current; if (!pc) return;
    if (!sharing) {
      try {
        const screen = await navigator.mediaDevices.getDisplayMedia({ video: true });
        const screenTrack = screen.getVideoTracks()[0];
        const sender = pc.getSenders().find((s) => s.track && s.track.kind === "video");
        if (sender) await sender.replaceTrack(screenTrack);
        screenTrack.onended = () => toggleScreenShare();
        setSharing(true);
        sendWS({ type: "screen-share", on: true });
      } catch (e) { toast({ title: "Screen share denied" }); }
    } else {
      const camTrack = localStream.getVideoTracks()[0];
      const sender = pc.getSenders().find((s) => s.track && s.track.kind === "video");
      if (sender && camTrack) await sender.replaceTrack(camTrack);
      setSharing(false);
      sendWS({ type: "screen-share", on: false });
    }
  };

  const sendChat = () => {
    const body = chatDraft.trim(); if (!body) return;
    setChatMsgs((m) => [...m, { from: role, body, ts: new Date().toISOString() }]);
    sendWS({ type: "chat", body });
    setChatDraft("");
  };

  // ---------- recording ----------
  const startRecording = async () => {
    if (!localStream || recording) return;

    // Refresh the appointment before recording so the provider
    // sees consent submitted after the provider opened the visit.
    let currentAppt = appt;

    try {
      const response = await api.get("/appointments");
      const refreshed = normalizeArray(
        response.data,
        ["appointments", "items", "appts"]
      ).find(
        (appointment) =>
          String(appointment.id) === String(id)
      );

      if (refreshed) {
        currentAppt = refreshed;
        setAppt(refreshed);
      }
    } catch (e) {
      toast({
        title: "Could not verify recording consent",
        description:
          getErrorMessage(e) ||
          "Please try again before recording.",
      });
      return;
    }

    if (!currentAppt?.telehealth?.recording_consent) {
      toast({
        title: "Recording consent required",
        description:
          "The patient has not consented to recording and AI-assisted documentation.",
      });
      return;
    }

    try {
      // Clinical documentation recording is audio-only.
      // The live telehealth video call remains unchanged.
      const composite = new MediaStream();

      localStream
        .getAudioTracks()
        .forEach((track) =>
          composite.addTrack(track)
        );

      const remote =
        remoteVideoRef.current?.srcObject;

      if (remote) {
        remote
          .getAudioTracks()
          .forEach((track) =>
            composite.addTrack(track)
          );
      }

      if (composite.getAudioTracks().length === 0) {
        throw new Error(
          "No audio tracks are available to record."
        );
      }

      const supportedMimeTypes = [
        "audio/webm;codecs=opus",
        "audio/webm",
      ];

      const mimeType =
        supportedMimeTypes.find((type) =>
          MediaRecorder.isTypeSupported(type)
        ) || "";

      const mr = mimeType
        ? new MediaRecorder(
            composite,
            { mimeType }
          )
        : new MediaRecorder(composite);

      recorderRef.current = mr;
      recChunksRef.current = [];

      mr.ondataavailable = (e) => {
        if (e.data.size > 0) {
          recChunksRef.current.push(e.data);
        }
      };

      mr.onstop = async () => {
        const blobType =
          mr.mimeType ||
          mimeType ||
          "audio/webm";

        const blob = new Blob(
          recChunksRef.current,
          { type: blobType }
        );

        const fd = new FormData();
        fd.append(
          "file",
          blob,
          `visit-${id}.webm`
        );
        try {
          setTranscriptionStatus("UPLOADING");

          const uploadResponse = await api.post(
            `/visits/${id}/recording`,
            fd,
            {
              headers: {
                "Content-Type": "multipart/form-data",
              },
            }
          );

          setRecordingSaved(true);

          const transcription =
            uploadResponse?.data?.transcription || null;

          const jobName =
            transcription?.job_name || "";

          const jobStatus =
            transcription?.status || "";

          if (jobName) {
            setTranscriptionJobName(jobName);
            setTranscriptionStatus(
              jobStatus || "IN_PROGRESS"
            );

            toast({
              title: "Recording uploaded",
              description:
                "Transcribing visit and preparing the SOAP draft.",
            });
          } else {
            setTranscriptionStatus(
              jobStatus || "FAILED_TO_START"
            );

            toast({
              title: "Recording saved",
              description:
                transcription?.error ||
                "The recording was saved, but clinical transcription did not start.",
            });
          }

          if (recordingUploadResolveRef.current) {
            recordingUploadResolveRef.current(
              uploadResponse?.data || null
            );
          }
        } catch (e) {
          setRecordingSaved(false);

          toast({
            title: "Recording upload failed",
            description: getErrorMessage(e) || "",
          });

          if (recordingUploadRejectRef.current) {
            recordingUploadRejectRef.current(e);
          }
        } finally {
          recordingUploadResolveRef.current = null;
          recordingUploadRejectRef.current = null;
        }
      };
      mr.start(1000);
      setRecording(true);
      setRecordingSaved(false);
      setRecordingStartedAt(Date.now());
      setRecordingReminderDue(false);

      toast({
        title: "Recording & transcription started",
      });
    } catch (e) { toast({ title: "Cannot record", description: e.message }); }
  };
  const stopRecording = () => {
    if (recorderRef.current) recorderRef.current.stop();
    setRecording(false);
  };

  // ---------- HealthScribe status polling ----------
  React.useEffect(() => {
    if (
      !transcriptionJobName ||
      transcriptionStatus !== "IN_PROGRESS"
    ) {
      return;
    }

    let cancelled = false;

    const poll = async () => {
      try {
        const response = await api.get(
          `/visits/${id}/transcription`,
          {
            params: {
              job_name: transcriptionJobName,
            },
          }
        );

        if (cancelled) return;

        const result = response?.data || {};
        const status = result.status || "UNKNOWN";

        setTranscriptionStatus(status);

        if (status === "COMPLETED") {
          const draft = result.soap_draft || {};

          setSoap({
            subjective: draft.subjective || "",
            objective: draft.objective || "",
            assessment: draft.assessment || "",
            plan: draft.plan || "",
          });

          setSoapOpen(true);

          toast({
            title: "SOAP draft ready",
            description:
              "HealthScribe populated a draft for provider review.",
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

        window.setTimeout(poll, 5000);
      } catch (error) {
        if (cancelled) return;

        setTranscriptionStatus("POLL_ERROR");

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
    };
  }, [
    transcriptionJobName,
    transcriptionStatus,
    id,
    toast,
  ]);

  // ---------- SOAP autosave (provider only, debounced 5s) ----------
  React.useEffect(() => {
    if (!isProvider || stage !== "in-call") return;
    const t = setTimeout(async () => {
      try {
        const r = await api.put(`/visits/${id}/live-soap`, soap);
        setSoapSavedAt(r.data?.saved_at || new Date().toISOString());
      } catch {}
    }, 5000);
    return () => clearTimeout(t);
  }, [soap, isProvider, stage, id]);

  const autoDraftFromChat = async () => {
    setAiBusy(true);
    try {
      const r = await api.post(`/visits/${id}/auto-draft`);
      setSoap({
        subjective: r.data.subjective || "",
        objective: r.data.objective || "",
        assessment: r.data.assessment || "",
        plan: r.data.plan || "",
      });
      toast({ title: "Auto-draft applied (from chat)" });
    } catch (e) { toast({ title: "Auto-draft failed", description: getErrorMessage(e) || "" }); }
    finally { setAiBusy(false); }
  };

  const llmDraft = async () => {
    setAiBusy(true);
    try {
      const r = await api.post(`/visits/${id}/llm-soap`);
      setSoap({
        subjective: r.data.subjective || "",
        objective: r.data.objective || "",
        assessment: r.data.assessment || "",
        plan: r.data.plan || "",
      });
      toast({ title: "AI SOAP draft generated" });
    } catch (e) { toast({ title: "AI draft failed", description: getErrorMessage(e) || "" }); }
    finally { setAiBusy(false); }
  };

  const finalizeSoap = async () => {
    try {
      const r = await api.get("/appointments");
      const a = normalizeArray(
        r.data,
        ["appointments", "items", "appts"]
      ).find(
        (appointment) =>
          String(appointment.id) === String(id)
      );

      if (!a) return;
      await api.post("/notes", { ...soap, client_id: a.client_id });
      toast({ title: "SOAP note saved to chart" });
    } catch (e) { toast({ title: "Save failed", description: getErrorMessage(e) || "" }); }
  };

  const endCall = (navigateToEnd = true) => {
    try { if (recorderRef.current && recorderRef.current.state === "recording") recorderRef.current.stop(); } catch {}
    if (pcRef.current) { try { pcRef.current.close(); } catch {} pcRef.current = null; }
    if (wsRef.current) { try { wsRef.current.close(); } catch {} wsRef.current = null; }
    if (localStreamRef.current) {
      localStreamRef.current.getTracks().forEach((t) => t.stop());
      localStreamRef.current = null;
    }
    setLocalStream(null);
    if (navigateToEnd) setStage("ended");
  };

  return (
    <div className="min-h-screen bg-[#0e1a14] text-[#f6f1e6] flex flex-col" data-testid="telehealth-page">
      <div className="border-b border-[#2f4a3a] px-6 py-4 flex items-center justify-between bg-[#1a2a22]">
        {isProvider ? (
          <button
            type="button"
            onClick={() => {
              if (
                providerEncounterActiveRef.current &&
                !providerEndCompletedRef.current
              ) {
                toast({
                  title: "End the visit before leaving",
                  description:
                    "Use End Visit so the clinical recording and documentation workflow can finish safely.",
                });

                return;
              }

              navigate("/portal");
            }}
            className="flex items-center gap-2 text-sm text-[#c19a4b] hover:text-[#f6f1e6]"
            data-testid="telehealth-back-portal"
          >
            <ArrowLeft size={16} />
            Back to portal
          </button>
        ) : (
          <Link
            to="/portal"
            className="flex items-center gap-2 text-sm text-[#c19a4b] hover:text-[#f6f1e6]"
          >
            <ArrowLeft size={16} />
            Back to portal
          </Link>
        )}
        <div className="text-sm">
          <span className="text-[#8a9a8e]">Telehealth visit</span>
          {appt && <span className="ml-3 text-[#f6f1e6]">{new Date(appt.start).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}</span>}
        </div>
        <div className="text-xs text-[#8a9a8e]">{user?.email}</div>
      </div>

      <div className="flex-1 p-6 md:p-10 max-w-6xl mx-auto w-full">
        {stage === "loading" && (
          <div className="text-center text-[#8a9a8e] py-16"><Loader2 className="inline animate-spin mr-2" size={18} /> Loading visit…</div>
        )}

        {stage === "error" && (
          <Panel>
            <div className="flex items-center gap-3 text-[#e9b5b5]">
              <AlertCircle size={22} />
              <div className="font-display text-2xl">Something went wrong</div>
            </div>
            <p className="text-[#c8d4cc] mt-3">{errMsg}</p>
            <Button onClick={() => navigate("/portal")} className="mt-5 rounded-full bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]">
              Back to portal
            </Button>
          </Panel>
        )}

        {stage === "consent" && (
          <Panel data-testid="telehealth-consent-panel">
            <div className="flex items-center gap-2 text-[#c19a4b] mb-4">
              <ShieldCheck size={20} /> <span className="eyebrow">Telehealth consent</span>
            </div>
            <h1 className="font-display text-3xl md:text-4xl mb-3">Before we connect</h1>
            <p className="text-[#c8d4cc] mb-6 leading-relaxed">
              Telehealth visits use secure video to connect you with your practitioner. We follow the same
              clinical standards as an in-person visit. For emergencies, call 911 immediately.
            </p>
            <ul className="space-y-2 text-sm text-[#c8d4cc] mb-6">
              <li>• I understand the risks and benefits of telehealth.</li>
              <li>• I am physically located in a state where my provider is licensed.</li>
              <li>• I will be in a private space during the visit.</li>
              <li>• I consent to receive care via video.</li>
            </ul>
            <label className="flex items-center gap-2 mb-4">
              <Checkbox checked={consent.acknowledged} onCheckedChange={(v) => setConsent({ ...consent, acknowledged: !!v })} data-testid="telehealth-consent-cb" />
              <span className="text-sm">I acknowledge and consent to the telehealth visit</span>
            </label>
            <div className="mb-5 rounded-xl border border-[#2f4a3a] bg-[#0e1a14] p-4">
              <div className="text-sm font-medium text-[#f6f1e6]">
                AI-assisted visit documentation
              </div>

              <p className="mt-2 text-xs leading-relaxed text-[#c8d4cc]">
                You may allow this telehealth visit to be audio recorded
                for transcription and preparation of a draft clinical note.
                Your provider will review and edit the draft before it is
                saved to your medical chart. Recording is optional, and
                declining it will not prevent your telehealth visit.
              </p>

              <label className="mt-4 flex items-start gap-2">
                <Checkbox
                  checked={consent.recordingConsent}
                  onCheckedChange={(value) =>
                    setConsent({
                      ...consent,
                      recordingConsent: !!value,
                    })
                  }
                  data-testid="telehealth-recording-consent"
                />

                <span className="text-sm text-[#f6f1e6]">
                  I consent to audio recording, transcription, and
                  AI-assisted draft documentation for this visit.
                </span>
              </label>
            </div>

            <div className="mb-6 max-w-md">
              <Label className="text-[#c8d4cc]">Type your full name as e-signature</Label>
              <Input className="mt-2 bg-[#0e1a14] border-[#2f4a3a] text-[#f6f1e6]" value={consent.signature} onChange={(e) => setConsent({ ...consent, signature: e.target.value })} data-testid="telehealth-consent-sig" />
            </div>
            <Button onClick={submitConsent} disabled={!consent.acknowledged || !consent.signature.trim()}
              className="rounded-full h-11 bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]" data-testid="telehealth-consent-submit">
              <CheckCircle2 size={16} className="mr-2" /> Continue
            </Button>
          </Panel>
        )}

        {stage === "tech" && (
          <Panel data-testid="telehealth-tech-panel">
            <h1 className="font-display text-3xl mb-2">Test your camera & microphone</h1>
            <p className="text-[#c8d4cc] mb-6">Make sure you can be seen and heard before joining.</p>
            <div className="rounded-2xl bg-[#0e1a14] border border-[#2f4a3a] overflow-hidden aspect-video relative max-w-2xl mx-auto mb-6">
              <video
                ref={attachLocalVideo}
                autoPlay
                muted
                playsInline
                disablePictureInPicture
                className="w-full h-full object-cover"
 data-testid="techcheck-video" />
              {!localStream && (
                <div className="absolute inset-0 flex items-center justify-center text-[#8a9a8e]">
                  <Loader2 className="animate-spin mr-2" size={18} /> Requesting camera & mic…
                </div>
              )}
              <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex gap-2">
                <button onClick={toggleMic} className={`p-3 rounded-full ${micOn ? "bg-[#2f4a3a]" : "bg-[#7a2a2a]"} text-[#f6f1e6]`} data-testid="techcheck-mic-toggle">
                  {micOn ? <Mic size={16} /> : <MicOff size={16} />}
                </button>
                <button onClick={toggleCam} className={`p-3 rounded-full ${camOn ? "bg-[#2f4a3a]" : "bg-[#7a2a2a]"} text-[#f6f1e6]`} data-testid="techcheck-cam-toggle">
                  {camOn ? <Video size={16} /> : <VideoOff size={16} />}
                </button>
              </div>
            </div>
            <div className="flex justify-end">
              <Button
                onClick={isProvider ? startCall : requestJoin}
                disabled={!localStream || busyAction === "request"}
                className="rounded-full h-11 bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]"
                data-testid="telehealth-join-btn"
              >
                {isProvider
                  ? (<><Video size={16} className="mr-2" /> Join visit</>)
                  : (busyAction === "request"
                      ? (<><Loader2 size={16} className="mr-2 animate-spin" /> Requesting…</>)
                      : (<><DoorOpen size={16} className="mr-2" /> Request to join</>))}
              </Button>
            </div>
          </Panel>
        )}

        {stage === "waiting" && (
          <Panel data-testid="telehealth-waiting-panel">
            <div className="flex items-center gap-2 text-[#c19a4b] mb-4">
              <DoorOpen size={20} /> <span className="eyebrow">Waiting room</span>
            </div>
            <h1 className="font-display text-3xl md:text-4xl mb-3">You're in the waiting room</h1>
            <p className="text-[#c8d4cc] mb-6 leading-relaxed">
              Your provider has been notified. They'll admit you as soon as they're ready.
              Feel free to keep testing your camera and microphone below.
            </p>
            <div className="rounded-2xl bg-[#0e1a14] border border-[#2f4a3a] overflow-hidden aspect-video relative max-w-2xl mx-auto mb-4">
              <video
                ref={attachLocalVideo}
                autoPlay
                muted
                playsInline
                disablePictureInPicture
                className="w-full h-full object-cover"
 data-testid="waiting-video" />
              <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex gap-2">
                <button onClick={toggleMic} className={`p-3 rounded-full ${micOn ? "bg-[#2f4a3a]" : "bg-[#7a2a2a]"} text-[#f6f1e6]`} data-testid="waiting-mic-toggle">
                  {micOn ? <Mic size={16} /> : <MicOff size={16} />}
                </button>
                <button onClick={toggleCam} className={`p-3 rounded-full ${camOn ? "bg-[#2f4a3a]" : "bg-[#7a2a2a]"} text-[#f6f1e6]`} data-testid="waiting-cam-toggle">
                  {camOn ? <Video size={16} /> : <VideoOff size={16} />}
                </button>
              </div>
            </div>
            <div className="flex items-center justify-center gap-2 text-[#8a9a8e] text-sm" data-testid="waiting-status">
              <Loader2 className="animate-spin" size={14} /> Waiting for provider to admit you…
            </div>
            <div className="mt-6 text-center">
              <Button variant="outline" onClick={() => endCall(true)} className="rounded-full border-[#7a2a2a] text-[#7a2a2a] hover:bg-[#7a2a2a] hover:text-[#f6f1e6]" data-testid="waiting-cancel">
                Leave waiting room
              </Button>
            </div>
          </Panel>
        )}

        {stage === "declined" && (
          <Panel data-testid="telehealth-declined-panel">
            <div className="flex items-center gap-3 text-[#e9b5b5] mb-3">
              <UserX size={22} />
              <div className="font-display text-3xl">Session declined</div>
            </div>
            <p className="text-[#c8d4cc] mb-3">Your provider was unable to admit you at this time.</p>
            {waitingRoom?.decline_reason && (
              <div className="rounded-lg border border-[#7a2a2a] bg-[#1a0e0e] p-4 text-sm text-[#f6f1e6] mb-4" data-testid="decline-reason">
                <div className="eyebrow text-[#e9b5b5] mb-1">Reason from provider</div>
                {waitingRoom.decline_reason}
              </div>
            )}
            <Button onClick={() => navigate("/portal")} className="rounded-full bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]">
              Back to portal
            </Button>
          </Panel>
        )}

        {stage === "provider-wait" && isProvider && (
          <Panel data-testid="telehealth-provider-wait">
            <div className="flex items-center gap-2 text-[#c19a4b] mb-4">
              <DoorOpen size={20} /> <span className="eyebrow">Provider waiting room</span>
            </div>
            <h1 className="font-display text-3xl mb-3">
              {waitingRoom?.state === "requested"
                ? `${appt?.client_name || "Patient"} is in the waiting room`
                : "Waiting for patient to request to join"}
            </h1>
            <p className="text-[#c8d4cc] mb-5">
              {waitingRoom?.state === "requested"
                ? "Admit them to start the visit, or decline with a reason if the session cannot proceed."
                : "The patient will appear here once they complete their device check and request to join."}
            </p>
            <div className="rounded-2xl bg-[#0e1a14] border border-[#2f4a3a] overflow-hidden aspect-video relative max-w-2xl mx-auto mb-6">
              <video
                ref={attachLocalVideo}
                autoPlay
                muted
                playsInline
                disablePictureInPicture
                className="w-full h-full object-cover"
 data-testid="provider-preview-video" />
              {!localStream && (
                <div className="absolute inset-0 flex items-center justify-center text-[#8a9a8e]">
                  <Loader2 className="animate-spin mr-2" size={18} /> Requesting camera & mic…
                </div>
              )}
            </div>
            <div className="flex flex-wrap gap-3">
              <Button
                onClick={providerAdmit}
                disabled={waitingRoom?.state !== "requested" || busyAction === "admit"}
                className="rounded-full h-11 bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6] disabled:opacity-40"
                data-testid="provider-admit-btn"
              >
                <UserCheck size={16} className="mr-2" />
                {busyAction === "admit" ? "Admitting…" : "Admit patient"}
              </Button>
              <Button
                onClick={() => setShowDeclineDialog(true)}
                disabled={waitingRoom?.state !== "requested" || busyAction === "decline"}
                variant="outline"
                className="rounded-full h-11 border-[#7a2a2a] text-[#e9b5b5] hover:bg-[#7a2a2a] hover:text-[#f6f1e6] disabled:opacity-40"
                data-testid="provider-decline-btn"
              >
                <UserX size={16} className="mr-2" /> Decline
              </Button>
              <Button
                onClick={providerEnd}
                variant="outline"
                className="rounded-full h-11 border-[#8a9a8e] text-[#c8d4cc] hover:bg-[#2f4a3a]"
                data-testid="provider-end-btn"
              >
                <PhoneOff size={16} className="mr-2" /> End session
              </Button>
            </div>
            {showDeclineDialog && (
              <div className="mt-5 rounded-2xl border border-[#7a2a2a] bg-[#1a0e0e] p-5" data-testid="decline-dialog">
                <Label className="text-[#f6f1e6]">Decline reason (shown to patient)</Label>
                <Input
                  className="mt-2 bg-[#0e1a14] border-[#7a2a2a] text-[#f6f1e6]"
                  value={declineReason}
                  onChange={(e) => setDeclineReason(e.target.value)}
                  placeholder="Brief reason (min 3 chars)"
                  data-testid="decline-reason-input"
                  maxLength={240}
                />
                <div className="flex gap-2 mt-3">
                  <Button
                    onClick={providerDecline}
                    disabled={declineReason.trim().length < 3 || busyAction === "decline"}
                    className="rounded-full bg-[#7a2a2a] hover:bg-[#5f1f1f] text-[#f6f1e6] disabled:opacity-40"
                    data-testid="decline-confirm-btn"
                  >
                    Confirm decline
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => { setShowDeclineDialog(false); setDeclineReason(""); }}
                    className="rounded-full"
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            )}
          </Panel>
        )}

        {stage === "in-call" && (
          <div className="grid lg:grid-cols-[minmax(0,1fr)_420px] gap-4 h-[75vh]" data-testid="telehealth-in-call">
            {/* Video stage */}
            <div className="rounded-2xl border border-[#2f4a3a] bg-black relative overflow-hidden">
              <video ref={remoteVideoRef} autoPlay playsInline className="w-full h-full object-cover" data-testid="remote-video" />
              {!peerOnline && (
                <div className="absolute inset-0 flex flex-col items-center justify-center text-[#8a9a8e] bg-[#0e1a14]/90">
                  <Loader2 className="animate-spin mb-3" size={28} />
                  <p className="text-sm">Waiting for the {isProvider ? "patient" : "provider"} to join…</p>
                </div>
              )}
              {/* Local PIP */}
              <div className="absolute bottom-4 right-4 w-40 aspect-video rounded-lg overflow-hidden border-2 border-[#c19a4b] shadow-lg">
                <video
                ref={attachLocalVideo}
                autoPlay
                muted
                playsInline
                disablePictureInPicture
                className="w-full h-full object-cover"
 />
              </div>
              {/* Controls */}
              <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex gap-2 bg-[#0e1a14]/80 rounded-full px-3 py-2 backdrop-blur">
                <button onClick={toggleMic} className={`p-3 rounded-full ${micOn ? "bg-[#2f4a3a]" : "bg-[#7a2a2a]"}`} title="Mic" data-testid="call-mic-toggle">
                  {micOn ? <Mic size={16} /> : <MicOff size={16} />}
                </button>
                <button onClick={toggleCam} className={`p-3 rounded-full ${camOn ? "bg-[#2f4a3a]" : "bg-[#7a2a2a]"}`} title="Camera" data-testid="call-cam-toggle">
                  {camOn ? <Video size={16} /> : <VideoOff size={16} />}
                </button>
                <button onClick={toggleScreenShare} className={`p-3 rounded-full ${sharing ? "bg-[#c19a4b] text-[#1f2a22]" : "bg-[#2f4a3a]"}`} title="Share screen" data-testid="call-share-toggle">
                  <MonitorUp size={16} />
                </button>
                {isProvider && (
                  <button
                    type="button"
                    onClick={() => {
                      setClinicalOpen((current) => !current);
                      setChatOpen(false);
                      setSoapOpen(false);
                    }}
                    className={`p-3 rounded-full ${
                      clinicalOpen
                        ? "bg-[#c19a4b] text-[#1f2a22]"
                        : "bg-[#2f4a3a]"
                    }`}
                    title="Patient chart"
                    data-testid="call-chart-toggle"
                  >
                    <FileText size={16} />
                  </button>
                )}

                <button onClick={() => {
                  setChatOpen((v) => !v);
                  setClinicalOpen(false);
                  setSoapOpen(false);
                }} className={`p-3 rounded-full ${chatOpen ? "bg-[#c19a4b] text-[#1f2a22]" : "bg-[#2f4a3a]"}`} title="Chat" data-testid="call-chat-toggle">
                  <MessageSquare size={16} />
                </button>
                {isProvider && (
                  <button onClick={() => {
                    setSoapOpen((v) => !v);
                    setClinicalOpen(false);
                    setChatOpen(false);
                  }} className={`p-3 rounded-full ${soapOpen ? "bg-[#c19a4b] text-[#1f2a22]" : "bg-[#2f4a3a]"}`} title="SOAP note" data-testid="call-soap-toggle">
                    <FileText size={16} />
                  </button>
                )}
                {isProvider && (
                  <button onClick={recording ? stopRecording : startRecording} className={`p-3 rounded-full ${recording ? "bg-[#7a2a2a]" : "bg-[#2f4a3a]"}`} title="Record" data-testid="call-record-toggle">
                    {recording ? <Square size={16} fill="currentColor" /> : <Circle size={16} />}
                  </button>
                )}
                <button onClick={() => (isProvider ? providerEnd() : endCall(true))} className="p-3 rounded-full bg-[#7a2a2a]" title="Leave" data-testid="call-leave">
                  <PhoneOff size={16} />
                </button>
              </div>
              {isProvider && recording && (
                <div
                  className="absolute top-4 left-4 rounded-xl bg-[#7a2a2a] px-4 py-3 text-xs shadow-lg"
                  data-testid="telehealth-recording-active"
                >
                  <div className="flex items-center gap-2 font-semibold">
                    <Circle
                      size={10}
                      fill="currentColor"
                    />
                    RECORDING & TRANSCRIPTION ACTIVE
                  </div>
                  <div className="mt-1 font-mono text-sm">
                    {formatRecordingElapsed(
                      recordingElapsed
                    )}
                  </div>
                </div>
              )}

              {isProvider &&
                !recording &&
                !recordingSaved && (
                  <div
                    className={`absolute top-4 left-4 max-w-sm rounded-xl border px-4 py-3 text-xs shadow-lg ${
                      recordingReminderDue
                        ? "border-[#d9a3a3] bg-[#5b2020]"
                        : "border-[#c19a4b] bg-[#3a2f18]"
                    }`}
                    data-testid="telehealth-recording-required"
                  >
                    <div className="flex items-center gap-2 font-semibold">
                      <AlertCircle size={16} />
                      RECORDING & TRANSCRIPTION NOT STARTED
                    </div>

                    <p className="mt-1 leading-5">
                      Confirm patient consent, then start
                      the clinical recording for visit
                      documentation.
                    </p>

                    <Button
                      type="button"
                      size="sm"
                      onClick={startRecording}
                      className="mt-2 rounded-full bg-[#f6f1e6] text-[#1f2a22] hover:bg-white"
                      data-testid="telehealth-start-recording-banner"
                    >
                      Start Recording & Transcription
                    </Button>
                  </div>
                )}

              {isProvider && recordingSaved && !recording && (
                <div
                  className="absolute top-4 left-4 rounded-xl border border-[#6f9d7b] bg-[#183324] px-4 py-3 text-xs shadow-lg"
                  data-testid="telehealth-recording-saved"
                >
                  <div className="flex items-center gap-2 font-semibold">
                    <CheckCircle2 size={16} />
                    Recording saved
                  </div>
                  <div className="mt-1">
                    {transcriptionStatus === "FAILED_TO_START"
                      ? "Transcription needs attention."
                      : "Clinical transcription is processing."}
                  </div>
                </div>
              )}

              {showRecordingExceptionDialog && (
                <div
                  className="absolute inset-0 z-40 flex items-center justify-center bg-black/80 p-4"
                  data-testid="recording-exception-dialog"
                >
                  <div className="w-full max-w-lg rounded-2xl border border-[#c19a4b] bg-[#1a2a22] p-6 text-[#f6f1e6] shadow-2xl">
                    <div className="flex items-center gap-2 text-lg font-semibold">
                      <AlertCircle size={20} />
                      Recording exception required
                    </div>

                    <p className="mt-2 text-sm leading-6 text-[#c8d4cc]">
                      This admitted visit has no saved
                      clinical recording. Document why
                      recording could not be completed
                      before ending the encounter.
                    </p>

                    <Label className="mt-4 block">
                      Reason
                    </Label>

                    <select
                      value={recordingExceptionCode}
                      onChange={(e) =>
                        setRecordingExceptionCode(
                          e.target.value
                        )
                      }
                      className="mt-2 h-11 w-full rounded-md border border-[#8a9a8e] bg-[#0e1a14] px-3 text-[#f6f1e6]"
                      data-testid="recording-exception-code"
                    >
                      <option value="">
                        Select reason
                      </option>
                      <option value="patient_declined">
                        Patient declined recording
                      </option>
                      <option value="consent_withdrawn">
                        Consent withdrawn
                      </option>
                      <option value="technical_failure">
                        Technical failure
                      </option>
                      <option value="visit_did_not_occur">
                        Visit did not occur
                      </option>
                      <option value="other">
                        Other
                      </option>
                    </select>

                    <Label className="mt-4 block">
                      Brief explanation
                    </Label>

                    <textarea
                      value={recordingExceptionReason}
                      onChange={(e) =>
                        setRecordingExceptionReason(
                          e.target.value
                        )
                      }
                      maxLength={1000}
                      rows={4}
                      className="mt-2 w-full rounded-md border border-[#8a9a8e] bg-[#0e1a14] p-3 text-sm text-[#f6f1e6]"
                      placeholder="Document what prevented recording/transcription."
                      data-testid="recording-exception-reason"
                    />

                    <div className="mt-4 flex gap-2">
                      <Button
                        type="button"
                        onClick={submitRecordingException}
                        disabled={
                          !recordingExceptionCode ||
                          recordingExceptionReason.trim()
                            .length < 3 ||
                          busyAction === "end-exception"
                        }
                        className="rounded-full bg-[#7a2a2a] text-white hover:bg-[#5f1f1f]"
                        data-testid="recording-exception-confirm"
                      >
                        End Visit With Exception
                      </Button>

                      <Button
                        type="button"
                        variant="outline"
                        onClick={() =>
                          setShowRecordingExceptionDialog(
                            false
                          )
                        }
                        className="rounded-full"
                      >
                        Return to visit
                      </Button>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Provider clinical workspace */}
            {isProvider && (
              <aside
                className={`rounded-2xl border border-[#2f4a3a] bg-[#1a2a22] overflow-hidden ${
                  clinicalOpen ? "flex flex-col" : "hidden"
                }`}
                data-testid="call-clinical-workspace"
              >
                <TelehealthClinicalPanel
                  clientId={appt?.client_id}
                  appointmentId={appt?.id}
                  patientName={appt?.client_name}
                />
              </aside>
            )}

            {/* Chat sidebar */}
            <aside className={`rounded-2xl border border-[#2f4a3a] bg-[#1a2a22] flex flex-col overflow-hidden ${(chatOpen && !soapOpen && !clinicalOpen) ? "" : "hidden"} ${(!chatOpen && !soapOpen && !clinicalOpen && !isProvider) ? "lg:flex" : ""}`} data-testid="call-chat-panel">
              <div className="p-3 border-b border-[#2f4a3a] eyebrow text-[#c19a4b]">Visit chat</div>
              <div className="flex-1 overflow-y-auto p-3 space-y-2 text-sm" data-testid="chat-messages">
                {chatMsgs.length === 0 && <div className="text-[#8a9a8e] text-xs">No messages yet.</div>}
                {normalizeArray(chatMsgs).map((m, i) => (
                  <div key={i} className={`flex ${m.from === role ? "justify-end" : "justify-start"}`}>
                    <div className={`px-3 py-1.5 rounded-2xl max-w-[80%] ${m.from === role ? "bg-[#2f4a3a] text-[#f6f1e6]" : "bg-[#0e1a14] text-[#c8d4cc] border border-[#2f4a3a]"}`}>
                      <div className="text-[10px] uppercase tracking-wider opacity-70 mb-0.5">{m.from}</div>
                      {m.body}
                    </div>
                  </div>
                ))}
              </div>
              <form onSubmit={(e) => { e.preventDefault(); sendChat(); }} className="p-2 border-t border-[#2f4a3a] flex gap-2">
                <Input className="bg-[#0e1a14] border-[#2f4a3a] text-[#f6f1e6]" value={chatDraft}
                  onChange={(e) => setChatDraft(e.target.value)} placeholder="Type a message…" data-testid="chat-input" />
                <Button type="submit" className="bg-[#c19a4b] text-[#1f2a22] hover:bg-[#a8853f]" data-testid="chat-send">
                  <Send size={14} />
                </Button>
              </form>
            </aside>

            {/* SOAP sidebar (provider only) */}
            {isProvider && soapOpen && (
              <aside className="rounded-2xl border border-[#2f4a3a] bg-[#1a2a22] flex flex-col overflow-hidden" data-testid="call-soap-panel">
                <div className="p-3 border-b border-[#2f4a3a] flex items-center justify-between">
                  <span className="eyebrow text-[#c19a4b]">Live SOAP note</span>
                  <span className="text-[10px] text-[#8a9a8e]">
                    {soapSavedAt ? `saved ${new Date(soapSavedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : "auto-saves every 5s"}
                  </span>
                </div>
                <div className="flex-1 overflow-y-auto p-3 space-y-3 text-sm">
                  {[
                    { k: "subjective", label: "S — Subjective" },
                    { k: "objective", label: "O — Objective" },
                    { k: "assessment", label: "A — Assessment" },
                    { k: "plan", label: "P — Plan" },
                  ].map((f) => (
                    <div key={f.k}>
                      <Label className="text-[#c19a4b] text-[10px] uppercase tracking-widest">{f.label}</Label>
                      <textarea
                        rows={3}
                        className="mt-1 w-full bg-[#0e1a14] border border-[#2f4a3a] rounded-md p-2 text-sm text-[#f6f1e6]"
                        value={soap[f.k]}
                        onChange={(e) => setSoap({ ...soap, [f.k]: e.target.value })}
                        data-testid={`soap-${f.k}`}
                      />
                    </div>
                  ))}
                </div>
                <div className="p-3 border-t border-[#2f4a3a] grid grid-cols-2 gap-2">
                  <Button onClick={autoDraftFromChat} disabled={aiBusy} variant="outline" size="sm" className="rounded-full text-xs border-[#c19a4b] text-[#c19a4b] hover:bg-[#c19a4b] hover:text-[#1f2a22]" data-testid="soap-auto-draft">
                    From chat
                  </Button>
                  <Button onClick={llmDraft} disabled={aiBusy} size="sm" className="rounded-full text-xs bg-[#c19a4b] text-[#1f2a22] hover:bg-[#a8853f]" data-testid="soap-llm-draft">
                    <Sparkles size={12} className="mr-1" /> {aiBusy ? "…" : "AI draft"}
                  </Button>
                  <div
                    className="col-span-2 rounded-xl border border-[#8a6a3c] bg-[#0e1a14] px-3 py-2 text-xs leading-relaxed text-[#c8d4cc]"
                    data-testid="soap-documentation-notice"
                  >
                    The permanent SOAP note is created from the
                    recorded visit after transcription. End the
                    visit normally, then review and finalize the
                    linked VisitNote from Telehealth Hub.
                  </div>
                </div>
              </aside>
            )}
          </div>
        )}

        {stage === "ended" && (
          <Panel>
            <div className="text-center py-8">
              <CheckCircle2 size={40} className="text-[#c19a4b] mx-auto mb-3" />
              <h1 className="font-display text-3xl mb-2">Visit ended</h1>
              <p className="text-[#c8d4cc] mb-6">Thank you. A visit summary will be available in your chart.</p>
              <Button onClick={() => navigate("/portal")} className="rounded-full bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]">
                Back to portal
              </Button>
            </div>
          </Panel>
        )}
      </div>
    </div>
  );
}

function Panel({ children, ...rest }) {
  return <div className="rounded-2xl border border-[#2f4a3a] bg-[#1a2a22] p-6 md:p-10" {...rest}>{children}</div>;
}