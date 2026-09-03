import React from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import PortalLayout, { PortalHeader, StatCard } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../../components/ui/dialog";
import { useToast } from "../../hooks/use-toast";
import {
  UserPlus, LogIn, LogOut, Building2, Users, Clock, X,
  ClipboardCheck, FileText, FolderOpen, CheckCircle2, XCircle, CreditCard,
  Archive, RotateCcw,
} from "lucide-react";
import { getErrorMessage } from "../../lib/errors";
import { normalizeArray } from "../../lib/collections";

const STATUSES = [
  { v: "checked_in", label: "Checked in" },
  { v: "in_room", label: "In room" },
  { v: "checked_out", label: "Checked out" },
  { v: "no_show", label: "No-show" },
];

export default function FrontDesk() {
  const { toast } = useToast();
  const navigate = useNavigate();
  const [visits, setVisits] = React.useState([]);
  const [clients, setClients] = React.useState([]);
  const [requests, setRequests] = React.useState([]);   // pending appointment requests
  const [archivedRequests, setArchivedRequests] = React.useState([]);
  const [requestView, setRequestView] = React.useState("active");
  const [archiveBusyId, setArchiveBusyId] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [showCheckin, setShowCheckin] = React.useState(false);
  const [form, setForm] = React.useState({ client_id: "", room: "", walk_in: false });
  const [search, setSearch] = React.useState("");
  const [requestAction, setRequestAction] = React.useState(null);
  const [requestActionValue, setRequestActionValue] = React.useState("");
  const [requestActionBusy, setRequestActionBusy] = React.useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const filterKey = searchParams.get("filter") || "all"; // all | in_clinic | walk_in | checked_out

  const load = async () => {
    setLoading(true);
    try {
      const [v, c, r, ar] = await Promise.all([
        api.get("/front-desk/today"),
        api.getList("/clients", {}, ["clients"]),
        // Public submissions live in the dedicated
        // appointment-request queue.
        api.get("/appointment-requests").catch(
          () => ({ data: [] })
        ),
        api.get("/appointment-requests?archived=true").catch(
          () => ({ data: [] })
        ),
      ]);
      setVisits(normalizeArray(v.data, ["visits"]));
      setClients(normalizeArray(c.data, ["clients"]));
        const requestRows = normalizeArray(
          r.data,
          [
            "appointment_requests",
            "requests",
            "items",
          ]
        );

        setRequests(
          requestRows.filter(
            (request) => request.status === "new"
          )
        );

        const archivedRequestRows = normalizeArray(
          ar.data,
          [
            "appointment_requests",
            "requests",
            "items",
          ]
        );

        setArchivedRequests(archivedRequestRows);
    } catch (e) {
      toast({ title: "Failed to load", description: getErrorMessage(e) || "" });
    } finally {
      setLoading(false);
    }
  };

  React.useEffect(() => {
    load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const checkIn = async () => {
    if (!form.client_id) {
      toast({ title: "Select a patient" });
      return;
    }
    try {
      await api.post("/front-desk/check-in", form);
      toast({ title: "Checked in" });
      setShowCheckin(false);
      setForm({ client_id: "", room: "", walk_in: false });
      load();
    } catch (e) {
      toast({ title: "Failed", description: getErrorMessage(e) || "" });
    }
  };

  const approveRequest = async (request) => {
    if (!request?.id || requestActionBusy) return;

    setRequestActionBusy(true);

    try {
      const response = await api.post(
        `/appointment-requests/${request.id}/approve`
      );

      if (response.data?.already_approved) {
        toast({
          title: "Request already approved",
        });
      } else {
        toast({
          title: "Appointment request approved",
          description:
            "The patient has been notified.",
        });
      }

      await load();
    } catch (e) {
      toast({
        title: "Unable to approve request",
        description: getErrorMessage(e) || "",
      });
    } finally {
      setRequestActionBusy(false);
    }
  };

  const refreshAppointmentRequests = async () => {
    const [activeRes, archivedRes] = await Promise.all([
      api.get("/appointment-requests"),
      api.get("/appointment-requests?archived=true"),
    ]);

    const activeRows = normalizeArray(
      activeRes.data,
      [
        "appointment_requests",
        "requests",
        "items",
      ]
    );

    const archivedRows = normalizeArray(
      archivedRes.data,
      [
        "appointment_requests",
        "requests",
        "items",
      ]
    );

    setRequests(
      activeRows.filter(
        (request) => request.status === "new"
      )
    );

    setArchivedRequests(archivedRows);
  };

  const archiveRequest = async (request) => {
    if (!request?.id || archiveBusyId) return;

    const confirmed = window.confirm(
      "Archive this appointment request? It will be removed from the active queue, but you can restore it later."
    );

    if (!confirmed) return;

    setArchiveBusyId(request.id);

    try {
      await api.post(
        `/appointment-requests/${request.id}/archive`
      );

      await refreshAppointmentRequests();

      toast({
        title: "Appointment request archived",
        description:
          "The request was moved to Archived and can be restored later.",
      });
    } catch (e) {
      toast({
        title: "Unable to archive request",
        description: getErrorMessage(e) || "",
      });
    } finally {
      setArchiveBusyId(null);
    }
  };

  const restoreRequest = async (request) => {
    if (!request?.id || archiveBusyId) return;

    setArchiveBusyId(request.id);

    try {
      await api.post(
        `/appointment-requests/${request.id}/restore`
      );

      await refreshAppointmentRequests();

      toast({
        title: "Appointment request restored",
        description:
          "The request was returned to the active appointment request queue.",
      });

      setRequestView("active");
    } catch (e) {
      toast({
        title: "Unable to restore request",
        description: getErrorMessage(e) || "",
      });
    } finally {
      setArchiveBusyId(null);
    }
  };

  const openRequestAction = (request, action) => {
    setRequestAction({
      request,
      action,
    });

    setRequestActionValue("");
  };

  const closeRequestAction = () => {
    if (requestActionBusy) return;

    setRequestAction(null);
    setRequestActionValue("");
  };

  const submitRequestAction = async () => {
    const request = requestAction?.request;
    const action = requestAction?.action;

    if (!request?.id || !action) return;

    const value = requestActionValue.trim();

    if (action === "reschedule" && !value) {
      toast({
        title: "Select another date and time",
      });
      return;
    }

    setRequestActionBusy(true);

    try {
      if (action === "reschedule") {
        await api.post(
          `/appointment-requests/${request.id}/reschedule`,
          {
            suggested_time: value,
          }
        );

        toast({
          title: "Alternative time sent",
          description:
            "The patient has been notified.",
        });
      } else if (action === "decline") {
        await api.post(
          `/appointment-requests/${request.id}/decline`,
          {
            reason: value,
          }
        );

        toast({
          title: "Appointment request declined",
          description:
            "The patient has been notified.",
        });
      }

      setRequestAction(null);
      setRequestActionValue("");

      await load();
    } catch (e) {
      toast({
        title:
          action === "reschedule"
            ? "Unable to suggest another time"
            : "Unable to decline request",
        description: getErrorMessage(e) || "",
      });
    } finally {
      setRequestActionBusy(false);
    }
  };

  const updateVisit = async (id, payload) => {
    try {
      await api.put(`/front-desk/${id}`, payload);
      load();
    } catch (e) {
      toast({ title: "Failed", description: getErrorMessage(e) || "" });
    }
  };


  // Handoff #4: send the front-desk row into POS with context prefilled so
  // completion writes the transaction id back onto the appointment.
  const goToCheckout = (v) => {
    const params = new URLSearchParams();
    if (v.client_id) params.set("client_id", v.client_id);
    if (v.appointment_id) params.set("appointment_id", v.appointment_id);
    navigate(`/portal/staff/pos?${params.toString()}`);
  };

  const filtered = normalizeArray(visits).filter((v) => {
    if (search && !(v.client_name || "").toLowerCase().includes(search.toLowerCase())) return false;
    if (filterKey === "in_clinic") return v.status === "checked_in" || v.status === "in_room";
    if (filterKey === "walk_in") return v.walk_in;
    if (filterKey === "checked_out") return v.status === "checked_out";
    return true;
  });

  const setFilter = (key) => {
    const next = new URLSearchParams(searchParams);
    if (!key || key === filterKey || key === "all") next.delete("filter");
    else next.set("filter", key);
    setSearchParams(next);
  };

  const counts = {
    in: normalizeArray(visits).filter((v) => v.status === "checked_in" || v.status === "in_room").length,
    walk: normalizeArray(visits).filter((v) => v.walk_in).length,
    out: normalizeArray(visits).filter((v) => v.status === "checked_out").length,
  };

  return (
    <PortalLayout>
      <PortalHeader
        title="Front Desk"
        subtitle="Today's queue · check-ins · room assignments"
        actions={
          <Button
            onClick={() => setShowCheckin(true)}
            className="btn-lift rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
            data-testid="frontdesk-checkin-btn"
          >
            <UserPlus size={16} className="mr-2" /> Check in / Walk-in
          </Button>
        }
      />

      <div className="grid sm:grid-cols-3 gap-4 mb-6">
        <button
          type="button"
          onClick={() => setFilter("in_clinic")}
          className={`text-left rounded-2xl transition ${filterKey === "in_clinic" ? "ring-2 ring-[#2f4a3a]" : "hover:-translate-y-0.5"}`}
          data-testid="fd-kpi-in-clinic"
        >
          <StatCard label="In clinic" value={counts.in} icon={Users} accent={filterKey === "in_clinic" ? "text-[#2f4a3a]" : undefined} />
        </button>
        <button
          type="button"
          onClick={() => setFilter("walk_in")}
          className={`text-left rounded-2xl transition ${filterKey === "walk_in" ? "ring-2 ring-[#c19a4b]" : "hover:-translate-y-0.5"}`}
          data-testid="fd-kpi-walk-ins"
        >
          <StatCard label="Walk-ins" value={counts.walk} icon={Building2} accent={filterKey === "walk_in" ? "text-[#8a6a3c]" : undefined} />
        </button>
        <button
          type="button"
          onClick={() => setFilter("checked_out")}
          className={`text-left rounded-2xl transition ${filterKey === "checked_out" ? "ring-2 ring-[#5b6f5b]" : "hover:-translate-y-0.5"}`}
          data-testid="fd-kpi-completed"
        >
          <StatCard label="Completed" value={counts.out} icon={Clock} accent={filterKey === "checked_out" ? "text-[#5b6f5b]" : undefined} />
        </button>
      </div>
      {filterKey !== "all" && (
        <div className="mb-4 flex items-center gap-2 text-xs text-[#8a6a3c]">
          <span>Filtered by</span>
          <span className="px-2 py-0.5 rounded-full bg-[#f1ead8] border border-[#e0d6bc] uppercase tracking-wider text-[10px]">
            {filterKey.replace("_", " ")}
          </span>
          <button onClick={() => setFilter("all")} className="inline-flex items-center gap-1 hover:underline" data-testid="fd-filter-clear">
            <X size={11} /> Clear
          </button>
        </div>
      )}

      {/* Handoff #1: patient-initiated requests awaiting staff confirmation. */}
          {/* Patient-initiated appointment request queue */}
        <div
          id="appointment-requests"
          className="mb-6 rounded-2xl border border-[#c19a4b] bg-[#fdf6db] p-4"
          data-testid="frontdesk-requests-card"
        >
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between mb-4">
            <div>
              <div className="flex items-center gap-2">
                <div className="font-medium text-[#8a6a3c] text-sm">
                  Appointment Requests
                </div>

                {requestView === "active" && requests.length > 0 && (
                  <span
                    className="inline-flex min-w-[22px] h-[22px] px-1.5 items-center justify-center rounded-full bg-[#7a2a2a] text-white text-xs font-semibold"
                    data-testid="frontdesk-request-count"
                  >
                    {requests.length}
                  </span>
                )}
              </div>

              <div className="text-xs text-[#6a6a6a] mt-1">
                Requests submitted through the Request an Appointment form
              </div>
            </div>

            <div
              className="inline-flex self-start rounded-full border border-[#d8c67f] bg-white/70 p-1"
              data-testid="appointment-request-view-tabs"
            >
              <button
                type="button"
                onClick={() => setRequestView("active")}
                className={`rounded-full px-3 py-1.5 text-[10px] uppercase tracking-wider transition ${
                  requestView === "active"
                    ? "bg-[#8a6a3c] text-white"
                    : "text-[#8a6a3c] hover:bg-[#f8f2df]"
                }`}
                data-testid="appointment-requests-active-tab"
              >
                Awaiting Review
                {requests.length
                  ? ` (${requests.length})`
                  : ""}
              </button>

              <button
                type="button"
                onClick={() => setRequestView("archived")}
                className={`rounded-full px-3 py-1.5 text-[10px] uppercase tracking-wider transition ${
                  requestView === "archived"
                    ? "bg-[#8a6a3c] text-white"
                    : "text-[#8a6a3c] hover:bg-[#f8f2df]"
                }`}
                data-testid="appointment-requests-archived-tab"
              >
                Archived
                {archivedRequests.length
                  ? ` (${archivedRequests.length})`
                  : ""}
              </button>
            </div>
          </div>

          {requestView === "active" ? (
            requests.length === 0 ? (
              <div
                className="rounded-lg bg-white/60 border border-[#e6d38a] px-4 py-5 text-sm text-[#6a6a6a]"
                data-testid="frontdesk-no-requests"
              >
                No new appointment requests.
              </div>
            ) : (
              <ul className="space-y-3">
                {normalizeArray(requests).map((request) => (
                  <li
                    key={request.id}
                    className="rounded-xl bg-white/75 border border-[#e6d38a] px-4 py-3"
                    data-testid={`frontdesk-request-${request.id}`}
                  >
                    <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                      <div className="min-w-0">
                        <div className="font-medium text-[#1f2a22]">
                          {request.fullName ||
                            request.full_name ||
                            "Appointment request"}
                        </div>

                        <div className="text-xs text-[#6a6a6a] mt-1">
                          {request.service || "Consultation"}

                          {request.date
                            ? ` · ${new Date(
                                request.date
                              ).toLocaleDateString()}`
                            : ""}

                          {request.time
                            ? ` · ${request.time}`
                            : ""}
                        </div>

                        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[#6a6a6a]">
                          {request.phone && (
                            <span>
                              Phone: {request.phone}
                            </span>
                          )}

                          {request.email && (
                            <span>
                              Email: {request.email}
                            </span>
                          )}
                        </div>

                        {request.returning !== undefined &&
                          request.returning !== null && (
                            <div className="text-xs text-[#6a6a6a] mt-1">
                              {request.returning
                                ? "Returning patient"
                                : "New patient"}
                            </div>
                          )}
                      </div>

                      <div className="flex flex-col items-start gap-3 md:items-end">
                        <span className="inline-flex self-start md:self-end rounded-full bg-[#f1ead8] border border-[#e0d6bc] px-2.5 py-1 text-[10px] uppercase tracking-wider text-[#8a6a3c]">
                          New
                        </span>

                        <div className="flex flex-wrap gap-2 md:justify-end">
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-8 rounded-full border-[#7a2a2a] text-[#7a2a2a] hover:bg-[#f8eeee]"
                            disabled={
                              requestActionBusy ||
                              Boolean(archiveBusyId)
                            }
                            onClick={() =>
                              openRequestAction(
                                request,
                                "decline"
                              )
                            }
                            data-testid={`request-decline-${request.id}`}
                          >
                            <XCircle
                              size={13}
                              className="mr-1"
                            />
                            Decline
                          </Button>

                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-8 rounded-full border-[#c19a4b] text-[#8a6a3c] hover:bg-[#f8f2df]"
                            disabled={
                              requestActionBusy ||
                              Boolean(archiveBusyId)
                            }
                            onClick={() =>
                              openRequestAction(
                                request,
                                "reschedule"
                              )
                            }
                            data-testid={`request-reschedule-${request.id}`}
                          >
                            <Clock
                              size={13}
                              className="mr-1"
                            />
                            Suggest Another Time
                          </Button>

                          <Button
                            type="button"
                            size="sm"
                            className="h-8 rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
                            disabled={
                              requestActionBusy ||
                              Boolean(archiveBusyId)
                            }
                            onClick={() =>
                              approveRequest(request)
                            }
                            data-testid={`request-approve-${request.id}`}
                          >
                            <CheckCircle2
                              size={13}
                              className="mr-1"
                            />
                            Approve
                          </Button>

                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-8 rounded-full border-[#9b8d75] text-[#6a6255] hover:bg-[#f2eee6]"
                            disabled={
                              requestActionBusy ||
                              Boolean(archiveBusyId)
                            }
                            onClick={() =>
                              archiveRequest(request)
                            }
                            data-testid={`request-archive-${request.id}`}
                          >
                            <Archive
                              size={13}
                              className="mr-1"
                            />
                            {archiveBusyId === request.id
                              ? "Archiving…"
                              : "Archive"}
                          </Button>
                        </div>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )
          ) : archivedRequests.length === 0 ? (
            <div
              className="rounded-lg bg-white/60 border border-[#e6d38a] px-4 py-5 text-sm text-[#6a6a6a]"
              data-testid="frontdesk-no-archived-requests"
            >
              No archived appointment requests.
            </div>
          ) : (
            <ul className="space-y-3">
              {normalizeArray(archivedRequests).map(
                (request) => (
                  <li
                    key={request.id}
                    className="rounded-xl bg-white/75 border border-[#e6d38a] px-4 py-3"
                    data-testid={`frontdesk-archived-request-${request.id}`}
                  >
                    <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                      <div className="min-w-0">
                        <div className="font-medium text-[#1f2a22]">
                          {request.fullName ||
                            request.full_name ||
                            "Appointment request"}
                        </div>

                        <div className="text-xs text-[#6a6a6a] mt-1">
                          {request.service || "Consultation"}

                          {request.date
                            ? ` · ${new Date(
                                request.date
                              ).toLocaleDateString()}`
                            : ""}

                          {request.time
                            ? ` · ${request.time}`
                            : ""}
                        </div>

                        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[#6a6a6a]">
                          {request.phone && (
                            <span>
                              Phone: {request.phone}
                            </span>
                          )}

                          {request.email && (
                            <span>
                              Email: {request.email}
                            </span>
                          )}
                        </div>

                        {request.archived_at && (
                          <div className="text-xs text-[#8a6a3c] mt-2">
                            Archived{" "}
                            {new Date(
                              request.archived_at
                            ).toLocaleString()}
                          </div>
                        )}
                      </div>

                      <div className="flex flex-col items-start gap-3 md:items-end">
                        <span className="inline-flex self-start md:self-end rounded-full bg-[#eee9df] border border-[#d9d0bf] px-2.5 py-1 text-[10px] uppercase tracking-wider text-[#6a6255]">
                          {request.status || "Archived"}
                        </span>

                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="h-8 rounded-full border-[#2f4a3a] text-[#2f4a3a] hover:bg-[#edf3ee]"
                          disabled={Boolean(archiveBusyId)}
                          onClick={() =>
                            restoreRequest(request)
                          }
                          data-testid={`request-restore-${request.id}`}
                        >
                          <RotateCcw
                            size={13}
                            className="mr-1"
                          />
                          {archiveBusyId === request.id
                            ? "Restoring…"
                            : "Restore"}
                        </Button>
                      </div>
                    </div>
                  </li>
                )
              )}
            </ul>
          )}
        </div>

<Input
        placeholder="Search by patient name…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="mb-4 max-w-sm bg-[#f6f1e6] border-[#e0d6bc]"
        data-testid="frontdesk-search-input"
      />

      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden" data-testid="frontdesk-table">
        <table className="w-full text-sm">
          <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
            <tr>
              <th className="text-left py-3 px-4">Patient</th>
              <th className="text-left py-3 px-4">Status</th>
              <th className="text-left py-3 px-4">Room</th>
              <th className="text-left py-3 px-4">Type</th>
              <th className="text-left py-3 px-4">Check-in</th>
              <th className="text-left py-3 px-4">Check-out</th>
              <th className="text-right py-3 px-4">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={7} className="py-8 text-center text-[#6a6a6a]">Loading…</td></tr>}
            {!loading && filtered.length === 0 && (
              <tr><td colSpan={7} className="py-10 text-center text-[#6a6a6a]">No visits today.</td></tr>
            )}
            {filtered.map((v) => (
              <tr key={v.id} className="border-t border-[#e7dfc9]" data-testid={`fd-row-${v.id}`}>
                <td className="py-3 px-4">
                  <div className="font-medium text-[#1f2a22]">{v.client_name || v.client_id}</div>
                  <ReadinessChips visit={v} />
                </td>
                <td className="py-3 px-4">
                  <Select value={v.status} onValueChange={(val) => updateVisit(v.id, { status: val })}>
                    <SelectTrigger className="h-8 w-36 bg-[#f6f1e6] border-[#e0d6bc] text-xs"><SelectValue /></SelectTrigger>
                    <SelectContent>{STATUSES.map((s) => <SelectItem key={s.v} value={s.v}>{s.label}</SelectItem>)}</SelectContent>
                  </Select>
                </td>
                <td className="py-3 px-4">
                  <Input
                    className="h-8 w-24 bg-[#f6f1e6] border-[#e0d6bc] text-xs"
                    defaultValue={v.room || ""}
                    onBlur={(e) => e.target.value !== (v.room || "") && updateVisit(v.id, { room: e.target.value || null })}
                    placeholder="—"
                    data-testid={`fd-room-input-${v.id}`}
                  />
                </td>
                <td className="py-3 px-4 text-xs">
                  {v.walk_in ? (
                    <span className="inline-block px-2 py-0.5 rounded-full bg-[#c19a4b] text-[#1f2a22]">Walk-in</span>
                  ) : (
                    <span className="text-[#6a6a6a]">Scheduled</span>
                  )}
                </td>
                <td className="py-3 px-4 text-[#6a6a6a] text-xs">
                  {v.checked_in_at ? new Date(v.checked_in_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}
                </td>
                <td className="py-3 px-4 text-[#6a6a6a] text-xs">
                  {v.checked_out_at ? new Date(v.checked_out_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}
                </td>
                <td className="py-3 px-4 text-right">
                  {v.transaction_id ? (
                    <span className="inline-flex items-center gap-1 text-[11px] text-[#3d6b52]"
                          data-testid={`fd-paid-${v.id}`}>
                      <CheckCircle2 size={12} /> Paid
                    </span>
                  ) : v.status !== "checked_out" ? (
                    <Button
                      size="sm"
                      className="h-7 rounded-full text-xs bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
                      onClick={() => goToCheckout(v)}
                      data-testid={`fd-checkout-btn-${v.id}`}
                    >
                      <CreditCard size={12} className="mr-1" /> Checkout
                    </Button>
                  ) : (
                    <span className="text-[11px] text-[#8a6a3c]">Completed</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog
        open={Boolean(requestAction)}
        onOpenChange={(open) => {
          if (!open) closeRequestAction();
        }}
      >
        <DialogContent
          className="bg-[#fbf7ee] border-[#e7dfc9] max-w-lg"
          data-testid="appointment-request-action-dialog"
        >
          <DialogHeader>
            <DialogTitle>
              {requestAction?.action === "reschedule"
                ? "Suggest Another Time"
                : "Decline Appointment Request"}
            </DialogTitle>

            <DialogDescription>
              {requestAction?.action === "reschedule"
                ? "Choose an alternative date and time. The patient will receive a notification after you send it."
                : "You may include a brief reason for declining this appointment request."}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="rounded-xl border border-[#e7dfc9] bg-white/60 px-4 py-3 text-sm">
              <div className="font-medium text-[#1f2a22]">
                {requestAction?.request?.fullName ||
                  requestAction?.request?.full_name ||
                  "Appointment request"}
              </div>

              <div className="mt-1 text-xs text-[#6a6a6a]">
                {requestAction?.request?.service ||
                  "Consultation"}

                {requestAction?.request?.date
                  ? ` · ${requestAction.request.date}`
                  : ""}

                {requestAction?.request?.time
                  ? ` · ${requestAction.request.time}`
                  : ""}
              </div>
            </div>

            {requestAction?.action === "reschedule" ? (
              <div>
                <Label htmlFor="request-suggested-time">
                  Proposed date and time
                </Label>

                <Input
                  id="request-suggested-time"
                  type="datetime-local"
                  className="mt-2 bg-white border-[#e0d6bc]"
                  value={requestActionValue}
                  onChange={(e) =>
                    setRequestActionValue(
                      e.target.value
                    )
                  }
                  data-testid="request-suggested-time"
                />
              </div>
            ) : (
              <div>
                <Label htmlFor="request-decline-reason">
                  Reason (optional)
                </Label>

                <textarea
                  id="request-decline-reason"
                  className="mt-2 min-h-28 w-full rounded-md border border-[#e0d6bc] bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[#5b6f5b]/30"
                  value={requestActionValue}
                  onChange={(e) =>
                    setRequestActionValue(
                      e.target.value
                    )
                  }
                  placeholder="Optional note for the patient"
                  data-testid="request-decline-reason"
                />
              </div>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={requestActionBusy}
              onClick={closeRequestAction}
            >
              Cancel
            </Button>

            <Button
              type="button"
              disabled={
                requestActionBusy ||
                (
                  requestAction?.action ===
                    "reschedule" &&
                  !requestActionValue.trim()
                )
              }
              onClick={submitRequestAction}
              className={
                requestAction?.action === "decline"
                  ? "bg-[#7a2a2a] hover:bg-[#642222] text-white"
                  : "bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
              }
              data-testid="request-action-submit"
            >
              {requestActionBusy
                ? "Saving…"
                : requestAction?.action ===
                    "reschedule"
                  ? "Send Proposed Time"
                  : "Decline Request"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showCheckin} onOpenChange={setShowCheckin}>
        <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9]">
          <DialogHeader>
            <DialogTitle>Check in patient</DialogTitle>
            <DialogDescription>Record a scheduled or walk-in visit and assign a room.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>Patient</Label>
              <Select value={form.client_id} onValueChange={(v) => setForm({ ...form, client_id: v })}>
                <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="checkin-client-select">
                  <SelectValue placeholder="Select patient…" />
                </SelectTrigger>
                <SelectContent>
                  {normalizeArray(clients).map((c) => (
                    <SelectItem key={c.id} value={c.id}>{c.full_name || c.email || c.id}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Room (optional)</Label>
              <Input
                className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"
                value={form.room}
                onChange={(e) => setForm({ ...form, room: e.target.value })}
                placeholder="e.g. Room 2"
                data-testid="checkin-room-input"
              />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.walk_in}
                onChange={(e) => setForm({ ...form, walk_in: e.target.checked })}
                data-testid="checkin-walkin-cb"
              />
              Walk-in (no scheduled appointment)
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCheckin(false)}>Cancel</Button>
            <Button onClick={checkIn} className="bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]" data-testid="checkin-confirm-btn">
              <LogIn size={16} className="mr-2" /> Check in
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PortalLayout>
  );
}


// Handoff #2: three tiny chips summarising intake / forms / documents
// readiness. Values come from the hydrated /front-desk/today response.
function ReadinessChips({ visit }) {
  const intake = visit.intake_complete;
  const forms = visit.forms_pending;
  const docs = visit.documents_ready;
  const chip = (ok, label, Icon, testid, muted = "not on file") => (
    <span
      data-testid={testid}
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wider border ${
        ok
          ? "bg-[#eaf2ec] text-[#3d6b52] border-[#cfe0d3]"
          : "bg-[#f1ead8] text-[#8a6a3c] border-[#e0d6bc]"
      }`}
      title={ok ? label : `${label}: ${muted}`}
    >
      <Icon size={10} /> {label}
    </span>
  );
  return (
    <div className="mt-1 flex flex-wrap gap-1" data-testid={`fd-readiness-${visit.id}`}>
      {chip(!!intake, "Intake", ClipboardCheck, `fd-readiness-intake-${visit.id}`)}
      {chip((forms || 0) === 0, forms ? `${forms} forms open` : "Forms", FileText,
            `fd-readiness-forms-${visit.id}`, "pending completion")}
      {chip(!!docs, "Docs", FolderOpen, `fd-readiness-docs-${visit.id}`, "none uploaded")}
    </div>
  );
}
