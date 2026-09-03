import React from "react";
import { useSearchParams } from "react-router-dom";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Textarea } from "../../components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { useToast } from "../../hooks/use-toast";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../../components/ui/dialog";
import { MessageSquare, Plus, Send, FileText, Paperclip, ClipboardPlus, CheckCircle2 } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { normalizeArray } from "../../lib/collections";

export default function Messages() {
  const { user } = useAuth();
  const { toast } = useToast();
  const [searchParams] = useSearchParams();
  const requestedClientId = searchParams.get("client_id");
  const [threads, setThreads] = React.useState([]);
  const [active, setActive] = React.useState(null);
  const [messages, setMessages] = React.useState([]);
  const [body, setBody] = React.useState("");
  const [templates, setTemplates] = React.useState([]);
  const [newOpen, setNewOpen] = React.useState(false);
  const [participants, setParticipants] = React.useState([]);


  const [newForm, setNewForm] = React.useState({ participant_id: "", subject: "", first_message: "" });
  const fileRef = React.useRef(null);
  const [uploading, setUploading] = React.useState(false);
  const [attachments, setAttachments] = React.useState([]);

  // Patient-only consolidated care-team chat.
  // Backend threads/messages remain separate for audit/history purposes.
  const [patientMessages, setPatientMessages] = React.useState([]);
  const [patientFilter, setPatientFilter] = React.useState("all");
  const [patientLoading, setPatientLoading] = React.useState(false);
  const [patientReplyThreadId, setPatientReplyThreadId] = React.useState(null);
  const patientChatEndRef = React.useRef(null);

  const loadThreads = React.useCallback(() => api.get("/messages/threads").then((r) => setThreads(normalizeArray(r.data, ["threads"]))), []);

  const loadPatientConversation = React.useCallback(async () => {
    if (user?.role !== "client") return;

    setPatientLoading(true);

    try {
      const threadResponse = await api.get("/messages/threads");
      const patientThreads = normalizeArray(
        threadResponse.data,
        ["threads"]
      );

      setThreads(patientThreads);

      // Capture unread counts BEFORE fetching thread messages because the
      // message endpoint marks the opened thread read.
      const unreadByThread = Object.fromEntries(
        patientThreads.map((thread) => [
          thread.id,
          Number(thread.unread_for_me || 0),
        ])
      );

      const results = await Promise.all(
        patientThreads.map(async (thread) => {
          try {
            const response = await api.get(
              `/messages/threads/${thread.id}`
            );

            const threadMessages = normalizeArray(
              response.data,
              ["messages"]
            );

            const unreadCount = unreadByThread[thread.id] || 0;
            let remainingUnread = unreadCount;

            // Walk newest -> oldest. Only incoming messages count toward
            // the patient's unread snapshot.
            const unreadIds = new Set();

            for (
              let i = threadMessages.length - 1;
              i >= 0 && remainingUnread > 0;
              i -= 1
            ) {
              const message = threadMessages[i];

              if (message.sender_id !== user?.id) {
                unreadIds.add(message.id);
                remainingUnread -= 1;
              }
            }

            return threadMessages.map((message) => ({
              ...message,
              _thread: thread,
              _wasUnread: unreadIds.has(message.id),
            }));
          } catch {
            return [];
          }
        })
      );

      const combined = results
        .flat()
        .sort(
          (a, b) =>
            new Date(a.created_at).getTime() -
            new Date(b.created_at).getTime()
        );

      setPatientMessages(combined);

      // Replies continue in the most recently active ordinary thread.
      const replyThread =
        patientThreads.find(
          (thread) =>
            thread.thread_type !== "telehealth_invitation"
        ) ||
        patientThreads[0] ||
        null;

      setPatientReplyThreadId(replyThread?.id || null);
    } catch {
      setPatientMessages([]);
      setThreads([]);
    } finally {
      setPatientLoading(false);
    }
  }, [user?.id, user?.role]);

  React.useEffect(() => {
    if (user?.role === "client") {
      loadPatientConversation();
      api.get("/practitioners").then((r) =>
        setParticipants(
          normalizeArray(r.data, ["participants"])
        )
      );
    } else {
      loadThreads();
      api.get("/clients").then((r) =>
        setParticipants(
          normalizeArray(r.data, ["participants"])
        )
      );
    }

    api.get("/messages/templates").then((r) =>
      setTemplates(r.data.templates || [])
    );
  }, [
    loadPatientConversation,
    loadThreads,
    user?.role,
  ]);

  React.useEffect(() => {
    setActive(null);
    setMessages([]);
    setBody("");
    setAttachments([]);
    setNewOpen(false);

    if (requestedClientId) {
      setNewForm({
        participant_id: requestedClientId,
        subject: "Patient Care",
        first_message: "",
      });
    }
  }, [requestedClientId]);

  React.useEffect(() => {
    if (!requestedClientId) {
      return undefined;
    }

    if (user?.role === "client") {
      return undefined;
    }

    let cancelled = false;

    const resolvePatientThread = async () => {
      setActive(null);
      setMessages([]);
      setNewOpen(false);

      try {
        const response = await api.get(
          `/messages/threads/by-client/${encodeURIComponent(
            requestedClientId
          )}`
        );

        if (cancelled) {
          return;
        }

        const resolvedThread = response.data?.thread;

        if (resolvedThread) {
          setActive(resolvedThread);
          setNewOpen(false);
          return;
        }

        setNewForm({
          participant_id: requestedClientId,
          subject: "Patient Care",
          first_message: "",
        });

        setNewOpen(true);
      } catch (error) {
        if (cancelled) {
          return;
        }

        setActive(null);
        setNewForm({
          participant_id: requestedClientId,
          subject: "Patient Care",
          first_message: "",
        });

        setNewOpen(true);

        toast({
          title: "Conversation not found",
          description:
            "A new secure conversation has been prepared for this patient.",
        });
      }
    };

    resolvePatientThread();

    return () => {
      cancelled = true;
    };
  }, [
    requestedClientId,
    user?.role,
    toast,
  ]);

  React.useEffect(() => {
    if (!active?.id) {
      setMessages([]);
      return undefined;
    }

    let cancelled = false;
    const activeThreadId = active.id;

    api.get(`/messages/threads/${activeThreadId}`)
      .then((response) => {
        if (!cancelled) {
          setMessages(
            normalizeArray(
              response.data,
              ["messages"]
            )
          );
        }
      })
      .catch(() => {
        if (!cancelled) {
          setMessages([]);
        }
      });

    loadThreads();

    return () => {
      cancelled = true;
    };
  }, [active?.id, loadThreads]);

  const sendPatientMessage = async () => {
    if (!body.trim() && attachments.length === 0) return;

    let threadId = patientReplyThreadId;

    try {
      // If this patient has never had a conversation, create one with the
      // selected/default care-team participant.
      if (!threadId) {
        const participant =
          newForm.participant_id ||
          participants[0]?.id;

        if (!participant) {
          toast({
            title: "No care-team recipient is available.",
          });
          return;
        }

        const created = await api.post(
          "/messages/threads",
          {
            participant_id: participant,
            subject: "Patient Care",
            first_message: "",
          }
        );

        threadId = created.data?.id;

        if (!threadId) {
          throw new Error("Thread creation failed");
        }

        setPatientReplyThreadId(threadId);
      }

      await api.post(
        `/messages/threads/${threadId}/messages`,
        {
          body: body.trim(),
          attachment_file_ids: normalizeArray(
            attachments
          ).map((a) => a.id),
        }
      );

      setBody("");
      setAttachments([]);

      await loadPatientConversation();

      window.setTimeout(() => {
        patientChatEndRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "end",
        });
      }, 50);
    } catch {
      toast({
        title: "Message could not be sent",
      });
    }
  };

  const send = async () => {
    if (!body.trim() && attachments.length === 0) return;
    try {
      await api.post(`/messages/threads/${active.id}/messages`, {
        body: body.trim(),
        attachment_file_ids: normalizeArray(attachments).map((a) => a.id),
      });
      setBody("");
      setAttachments([]);
      const r = await api.get(`/messages/threads/${active.id}`);
      setMessages(normalizeArray(r.data, ["messages"]));
      loadThreads();
    } catch (e) { toast({ title: "Failed" }); }
  };

  const createThread = async () => {
    if (!newForm.participant_id || !newForm.subject) return toast({ title: "Fill all fields" });
    try {
      const { data } = await api.post("/messages/threads", newForm);
      setNewOpen(false);
      setNewForm({
        participant_id: "",
        subject: requestedClientId ? "Patient Care" : "",
        first_message: "",
      });
      await loadThreads();
      setActive(data);
    } catch (e) { toast({ title: "Failed" }); }
  };

  const uploadAttachment = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("category", "doc");
      if (active?.client_id) fd.append("client_id", active.client_id);
      const { data } = await api.post("/files/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setAttachments((a) => [...a, { id: data.id, filename: data.filename }]);
      e.target.value = "";
    } catch { toast({ title: "Upload failed" }); }
    finally { setUploading(false); }
  };

  // Handoff #6: promote a thread into the tasks system. Assignment,
  // priority, due date, status and escalation live on the linked task; the
  // thread only stores `linked_task_id`.
  const promoteToTask = async (thread) => {
    try {
      const r = await api.post(
        `/messages/threads/${thread.id}/promote-to-task`,
        { priority: "normal", category: "message_followup" },
      );
      toast({
        title: "Task created",
        description: "Manage assignment, priority and due date in the Tasks page.",
      });
      // Reflect the linkage in the UI without a full reload round-trip.
      setActive((cur) => (cur && cur.id === thread.id
        ? { ...cur, linked_task_id: r.data?.id }
        : cur));
      loadThreads();
    } catch (e) {
      const code = e?.response?.data?.detail?.code;
      if (code === "task_already_linked") {
        toast({ title: "This thread already has a linked task." });
      } else {
        toast({ title: "Could not create task" });
      }
    }
  };

  const patientMessageCategory = (message) => {
    const role = String(message?.sender_role || "").toLowerCase();

    if (role === "practitioner") return "provider";

    if (
      ["staff", "admin", "medical_assistant"].includes(role)
    ) {
      return "staff";
    }

    if (["system", "automation"].includes(role)) {
      return "system";
    }

    return "other";
  };

  // These counts intentionally use the unread snapshot captured before
  // thread fetches mark messages read. This tells the patient which
  // category contained new activity when they entered Messages.
  const patientUnreadCounts = normalizeArray(patientMessages).reduce(
    (counts, message) => {
      if (!message._wasUnread) return counts;

      counts.all += 1;
      counts.unread += 1;

      const category = patientMessageCategory(message);

      if (Object.prototype.hasOwnProperty.call(counts, category)) {
        counts[category] += 1;
      }

      return counts;
    },
    {
      all: 0,
      unread: 0,
      provider: 0,
      staff: 0,
      system: 0,
    }
  );

  const patientFilterOptions = [
    {
      id: "all",
      label: "All",
      count: patientUnreadCounts.all,
    },
    {
      id: "unread",
      label: "Unread",
      count: patientUnreadCounts.unread,
    },
    {
      id: "provider",
      label: "Provider",
      count: patientUnreadCounts.provider,
    },
    {
      id: "staff",
      label: "Staff",
      count: patientUnreadCounts.staff,
    },
    {
      id: "system",
      label: "System",
      count: patientUnreadCounts.system,
    },
  ];

  const filteredPatientMessages = normalizeArray(patientMessages).filter(
    (message) => {
      if (patientFilter === "all") return true;

      if (patientFilter === "unread") {
        return message._wasUnread;
      }

      const role = String(
        message.sender_role || ""
      ).toLowerCase();

      if (patientFilter === "provider") {
        return role === "practitioner";
      }

      if (patientFilter === "staff") {
        return [
          "staff",
          "admin",
          "medical_assistant",
        ].includes(role);
      }

      if (patientFilter === "system") {
        return [
          "system",
          "automation",
        ].includes(role);
      }

      return true;
    }
  );

  const formatPatientDay = (value) => {
    const date = new Date(value);
    const today = new Date();
    const yesterday = new Date();

    yesterday.setDate(today.getDate() - 1);

    if (date.toDateString() === today.toDateString()) {
      return "Today";
    }

    if (
      date.toDateString() === yesterday.toDateString()
    ) {
      return "Yesterday";
    }

    return date.toLocaleDateString([], {
      month: "short",
      day: "numeric",
      year:
        date.getFullYear() !== today.getFullYear()
          ? "numeric"
          : undefined,
    });
  };

  const isPatientSystemMessage = (message) =>
    ["system", "automation"].includes(
      String(message.sender_role || "").toLowerCase()
    );

  if (user?.role === "client") {
    let previousDay = null;

    return (
      <PortalLayout>
        <PortalHeader
          title="Messages"
          subtitle="Secure conversation with your Natural Medical Solutions care team."
        />

        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden flex flex-col min-h-[560px] h-[calc(100vh-280px)]">
          <div className="px-4 sm:px-5 py-3 border-b border-[#e7dfc9]">
            <div className="flex items-center gap-2 mb-3">
              <div className="w-9 h-9 rounded-full bg-[#2f4a3a] text-[#f6f1e6] flex items-center justify-center flex-shrink-0">
                <MessageSquare size={17} />
              </div>

              <div className="min-w-0">
                <div className="font-medium text-[#1f2a22]">
                  Natural Medical Solutions
                </div>
                <div className="text-xs text-[#6a6a6a]">
                  Care Team
                </div>
              </div>
            </div>

            <div
              className="flex gap-2 overflow-x-auto pb-1"
              aria-label="Message filters"
            >
              {patientFilterOptions.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  onClick={() =>
                    setPatientFilter(option.id)
                  }
                  className={`whitespace-nowrap rounded-full px-3 py-1.5 text-xs font-medium border transition-colors ${
                    patientFilter === option.id
                      ? "bg-[#2f4a3a] border-[#2f4a3a] text-[#f6f1e6]"
                      : "bg-[#f6f1e6] border-[#e0d6bc] text-[#5f5a50] hover:border-[#c19a4b]"
                  }`}
                >
                  <span>{option.label}</span>

                  {option.count > 0 && (
                    <span
                      className={`ml-1.5 inline-flex min-w-[18px] h-[18px] items-center justify-center rounded-full px-1 text-[10px] font-semibold ${
                        patientFilter === option.id
                          ? "bg-[#f6f1e6] text-[#2f4a3a]"
                          : "bg-[#c19a4b] text-white"
                      }`}
                      aria-label={`${option.count} unread ${option.label.toLowerCase()} messages`}
                    >
                      {option.count > 99 ? "99+" : option.count}
                    </span>
                  )}
                </button>
              ))}
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-4 sm:p-5">
            {patientLoading ? (
              <div className="h-full flex items-center justify-center text-sm text-[#6a6a6a]">
                Loading messages…
              </div>
            ) : filteredPatientMessages.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-center px-6">
                <MessageSquare
                  size={28}
                  className="text-[#c19a4b] mb-3"
                />
                <div className="font-medium text-[#1f2a22]">
                  {patientFilter === "all"
                    ? "No messages yet"
                    : "No messages match this filter"}
                </div>
                <div className="text-xs text-[#6a6a6a] mt-1 max-w-sm">
                  {patientFilter === "all"
                    ? "Your secure care-team conversation will appear here."
                    : "Choose another filter to view more of your conversation."}
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                {filteredPatientMessages.map(
                  (message) => {
                    const mine =
                      message.sender_id === user?.id;

                    const day = formatPatientDay(
                      message.created_at
                    );

                    const showDay =
                      day !== previousDay;

                    previousDay = day;

                    const systemMessage =
                      isPatientSystemMessage(message);

                    if (systemMessage) {
                      return (
                        <React.Fragment
                          key={message.id}
                        >
                          {showDay && (
                            <div className="flex items-center gap-3 py-2">
                              <div className="h-px flex-1 bg-[#e7dfc9]" />
                              <span className="text-[11px] font-medium text-[#8a8173]">
                                {day}
                              </span>
                              <div className="h-px flex-1 bg-[#e7dfc9]" />
                            </div>
                          )}

                          <div className="flex justify-center py-1">
                            <div className="max-w-[90%] rounded-full bg-[#f1ead8] border border-[#e7dfc9] px-4 py-2 text-xs text-[#6a6258] text-center">
                              {message.body}
                            </div>
                          </div>
                        </React.Fragment>
                      );
                    }

                    const senderLabel = mine
                      ? "You"
                      : message.sender_name ||
                        (message.sender_role ===
                        "practitioner"
                          ? "Provider"
                          : "Care Team");

                    return (
                      <React.Fragment
                        key={message.id}
                      >
                        {showDay && (
                          <div className="flex items-center gap-3 py-2">
                            <div className="h-px flex-1 bg-[#e7dfc9]" />
                            <span className="text-[11px] font-medium text-[#8a8173]">
                              {day}
                            </span>
                            <div className="h-px flex-1 bg-[#e7dfc9]" />
                          </div>
                        )}

                        <div
                          className={`flex ${
                            mine
                              ? "justify-end"
                              : "justify-start"
                          }`}
                        >
                          <div className="max-w-[82%] sm:max-w-[72%]">
                            <div
                              className={`text-[11px] mb-1 ${
                                mine
                                  ? "text-right text-[#6a6a6a]"
                                  : "text-[#6a6a6a]"
                              }`}
                            >
                              {senderLabel}
                              {!mine &&
                                message.sender_role ===
                                  "practitioner" &&
                                " · Provider"}
                            </div>

                            <div
                              className={`rounded-2xl px-4 py-2.5 text-sm ${
                                mine
                                  ? "bg-[#2f4a3a] text-[#f6f1e6] rounded-br-md"
                                  : "bg-[#f1ead8] text-[#2a2a2a] rounded-bl-md"
                              }`}
                            >
                              <div className="whitespace-pre-wrap break-words">
                                {message.body}
                              </div>

                              {message
                                .attachment_file_ids
                                ?.length > 0 && (
                                <div className="mt-2 space-y-1">
                                  {message.attachment_file_ids.map(
                                    (fid) => (
                                      <div
                                        key={fid}
                                        className={`text-xs inline-flex items-center gap-1 ${
                                          mine
                                            ? "text-[#d7b878]"
                                            : "text-[#8a6a3c]"
                                        }`}
                                      >
                                        <FileText
                                          size={12}
                                        />
                                        Attached file
                                      </div>
                                    )
                                  )}
                                </div>
                              )}

                              <div
                                className={`text-[10px] mt-1 ${
                                  mine
                                    ? "text-[#d7b878] text-right"
                                    : "text-[#8a6a3c]"
                                }`}
                              >
                                {new Date(
                                  message.created_at
                                ).toLocaleTimeString(
                                  [],
                                  {
                                    hour: "numeric",
                                    minute: "2-digit",
                                  }
                                )}
                              </div>
                            </div>
                          </div>
                        </div>
                      </React.Fragment>
                    );
                  }
                )}

                <div ref={patientChatEndRef} />
              </div>
            )}
          </div>

          <div className="border-t border-[#e7dfc9] p-3 sm:p-4 bg-[#fbf7ee]">
            {attachments.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-2">
                {normalizeArray(attachments).map(
                  (attachment) => (
                    <div
                      key={attachment.id}
                      className="text-xs inline-flex items-center gap-2 bg-[#f1ead8] rounded-full px-3 py-1"
                    >
                      <Paperclip size={12} />
                      {attachment.filename}
                      <button
                        type="button"
                        onClick={() =>
                          setAttachments((items) =>
                            items.filter(
                              (item) =>
                                item.id !==
                                attachment.id
                            )
                          )
                        }
                        className="text-[#7a2a2a]"
                        aria-label={`Remove ${attachment.filename}`}
                      >
                        ×
                      </button>
                    </div>
                  )
                )}
              </div>
            )}

            <div className="flex gap-2 items-end">
              <Textarea
                value={body}
                onChange={(event) =>
                  setBody(event.target.value)
                }
                placeholder="Message your care team…"
                className="bg-[#f6f1e6] border-[#e0d6bc] min-h-[54px] flex-1 resize-none"
              />

              <input
                type="file"
                ref={fileRef}
                className="hidden"
                onChange={uploadAttachment}
              />

              <Button
                variant="outline"
                onClick={() =>
                  fileRef.current?.click()
                }
                disabled={uploading}
                aria-label="Attach file"
                className="rounded-full border-[#2f4a3a] text-[#2f4a3a] bg-transparent hover:bg-[#2f4a3a] hover:text-[#f6f1e6] h-11 w-11 p-0"
              >
                <Paperclip size={16} />
              </Button>

              <Button
                onClick={sendPatientMessage}
                aria-label="Send message"
                className="rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6] h-11 w-11 p-0"
              >
                <Send size={16} />
              </Button>
            </div>

            <div className="text-[10px] text-[#8a8173] mt-2 text-center">
              Secure messaging · Message details remain inside your patient portal
            </div>
          </div>
        </div>
      </PortalLayout>
    );
  }

  return (
    <PortalLayout>
      <PortalHeader
        title="Messages"
        subtitle="Secure messages between patients and the care team. Email alerts never include message details."
        actions={<Button onClick={() => setNewOpen(true)} className="rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"><Plus size={14} className="mr-2" /> New message</Button>}
      />

      <div className="grid md:grid-cols-[320px_1fr] gap-4 h-[calc(100vh-280px)] min-h-[480px]">
        {/* Thread list */}
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-y-auto">
          {threads.length === 0 ? (
            <div className="p-6 text-sm text-[#6a6a6a] text-center">
              <MessageSquare size={24} className="mx-auto text-[#c19a4b] mb-2" />
              No conversations yet.
            </div>
          ) : (
            normalizeArray(threads).map((t) => (
              <button
                key={t.id}
                onClick={() => setActive(t)}
                className={`w-full text-left px-4 py-3 border-b border-[#e7dfc9] hover:bg-[#f1ead8]/50 ${active?.id === t.id ? "bg-[#f1ead8]" : ""}`}
              >
                <div className="flex items-center justify-between">
                  <div className="font-medium text-[#1f2a22] text-sm truncate">
                    {user?.role === "client" ? t.practitioner_name : t.client_name}
                  </div>
                  {t.unread_for_me > 0 && (
                    <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-[#c19a4b] text-[#1f2a22] text-[10px] font-semibold">{t.unread_for_me}</span>
                  )}
                </div>
                <div className="text-xs text-[#8a6a3c] mt-0.5 truncate">{t.subject}</div>
                <div className="text-xs text-[#6a6a6a] mt-1 truncate">{t.last_message_preview || "—"}</div>
              </button>
            ))
          )}
        </div>

        {/* Thread view */}
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] flex flex-col">
          {!active ? (
            <div className="flex-1 flex items-center justify-center text-[#6a6a6a] text-sm">Select a conversation or start a new one.</div>
          ) : (
            <>
              <div className="px-5 py-3 border-b border-[#e7dfc9] flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="font-display text-lg text-[#1f2a22]">{active.subject}</div>
                  <div className="text-xs text-[#6a6a6a]">with {user?.role === "client" ? active.practitioner_name : active.client_name}</div>
                </div>
                {user?.role !== "client" && (
                  active.linked_task_id ? (
                    <span
                      className="inline-flex items-center gap-1 text-[11px] text-[#3d6b52] px-2 py-1 rounded-full bg-[#eaf2ec] border border-[#cfe0d3] flex-shrink-0"
                      data-testid={`message-task-linked-${active.id}`}
                    >
                      <CheckCircle2 size={12} /> Task linked
                    </span>
                  ) : (
                    <Button
                      size="sm" variant="outline"
                      className="h-8 rounded-full border-[#e6d38a] text-[#8a6a3c] flex-shrink-0"
                      onClick={() => promoteToTask(active)}
                      data-testid={`message-to-task-${active.id}`}
                    >
                      <ClipboardPlus size={13} className="mr-1" /> Create task
                    </Button>
                  )
                )}
              </div>
              <div className="flex-1 overflow-y-auto p-5 space-y-3">
                {normalizeArray(messages).map((m) => {
                  const mine = m.sender_id === user?.id;
                  return (
                    <div key={m.id} className={`flex ${mine ? "justify-end" : "justify-start"}`}>
                      <div className={`max-w-[75%] rounded-2xl px-4 py-2 text-sm ${mine ? "bg-[#2f4a3a] text-[#f6f1e6]" : "bg-[#f1ead8] text-[#2a2a2a]"}`}>
                        <div className="whitespace-pre-wrap">{m.body}</div>
                        {m.attachment_file_ids?.length > 0 && (
                          <div className="mt-2 space-y-1">
                            {m.attachment_file_ids.map((fid) => (
                              <div key={fid} className={`text-xs inline-flex items-center gap-1 ${mine ? "text-[#d7b878]" : "text-[#8a6a3c]"}`}>
                                <FileText size={12} /> Attached file
                              </div>
                            ))}
                          </div>
                        )}
                        <div className={`text-[10px] mt-1 ${mine ? "text-[#d7b878]" : "text-[#8a6a3c]"}`}>
                          {new Date(m.created_at).toLocaleString([], { hour: "numeric", minute: "2-digit", month: "short", day: "numeric" })}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="border-t border-[#e7dfc9] p-4 space-y-2">
                {templates.length > 0 && user?.role !== "client" && (
                  <div className="flex flex-wrap gap-1">
                    {normalizeArray(templates).map((t) => (
                      <button key={t.id} onClick={() => setBody((b) => (b ? b + "\n\n" : "") + t.body)} className="text-[11px] rounded-full border border-[#e0d6bc] bg-[#f6f1e6] px-3 py-1 hover:border-[#c19a4b]">
                        {t.label}
                      </button>
                    ))}
                  </div>
                )}
                {attachments.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {normalizeArray(attachments).map((a) => (
                      <div key={a.id} className="text-xs inline-flex items-center gap-2 bg-[#f1ead8] rounded-full px-3 py-1">
                        <Paperclip size={12} /> {a.filename}
                        <button onClick={() => setAttachments((x) => x.filter((i) => i.id !== a.id))} className="text-[#7a2a2a]">×</button>
                      </div>
                    ))}
                  </div>
                )}
                <div className="flex gap-2 items-end">
                  <Textarea value={body} onChange={(e) => setBody(e.target.value)} placeholder="Type a message…" className="bg-[#f6f1e6] border-[#e0d6bc] min-h-[64px] flex-1" />
                  <input type="file" ref={fileRef} className="hidden" onChange={uploadAttachment} />
                  <Button variant="outline" onClick={() => fileRef.current?.click()} disabled={uploading} className="rounded-full border-[#2f4a3a] text-[#2f4a3a] bg-transparent hover:bg-[#2f4a3a] hover:text-[#f6f1e6] h-11">
                    <Paperclip size={16} />
                  </Button>
                  <Button onClick={send} className="rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6] h-11"><Send size={16} /></Button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      <Dialog open={newOpen} onOpenChange={setNewOpen}>
        <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9]">
          <DialogHeader>
            <DialogTitle className="font-display text-2xl">New conversation</DialogTitle>
            <DialogDescription>Start a secure thread with a recipient.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div><Label>{user?.role === "client" ? "Practitioner" : "Patient"}</Label>
              <Select
                value={newForm.participant_id}
                onValueChange={(value) =>
                  setNewForm({
                    ...newForm,
                    participant_id: value,
                  })
                }
              >
                <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"><SelectValue placeholder="Choose" /></SelectTrigger>
                <SelectContent>{normalizeArray(participants).map((p) => <SelectItem key={p.id} value={p.id}>{p.full_name || p.email}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div><Label>Subject</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={newForm.subject} onChange={(e) => setNewForm({ ...newForm, subject: e.target.value })} placeholder="e.g. Follow-up question" /></div>
            <div><Label>Message</Label><Textarea className="mt-2 bg-[#f6f1e6] border-[#e0d6bc] min-h-[80px]" value={newForm.first_message} onChange={(e) => setNewForm({ ...newForm, first_message: e.target.value })} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setNewOpen(false)}>Cancel</Button>
            <Button onClick={createThread} className="bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]">Send</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PortalLayout>
  );
}
