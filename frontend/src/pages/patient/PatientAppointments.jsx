import React from "react";
import { Link } from "react-router-dom";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../../components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Label } from "../../components/ui/label";
import { useToast } from "../../hooks/use-toast";
import { CalendarDays, Plus, X, Video, MapPin } from "lucide-react";
import { getErrorMessage } from "../../lib/errors";
import { normalizeArray } from "../../lib/collections";

export default function PatientAppointments() {
  const { toast } = useToast();
  const [items, setItems] = React.useState([]);
  const [open, setOpen] = React.useState(false);
  const [practitioners, setPractitioners] = React.useState([]);
  const [form, setForm] = React.useState({ practitioner_id: "", date: "", slot: "", visit_mode: "in_person", consent: false });
  const [slots, setSlots] = React.useState([]);

  const load = () => api.get("/appointments").then((r) => setItems(normalizeArray(r.data, ["items"])));
  React.useEffect(() => {
    load();
    api.get("/practitioners").then((r) => {
      setPractitioners(normalizeArray(r.data, ["practitioners"]));
      if (r.data?.[0]) setForm((f) => ({ ...f, practitioner_id: r.data[0].id }));
    });
  }, []);

  const loadSlots = React.useCallback(async () => {
    if (!form.practitioner_id || !form.date) return setSlots([]);
    const r = await api.get("/availability/slots", {
      params: { practitioner_id: form.practitioner_id, date: form.date, duration_min: 60 },
    });
    setSlots(r.data.slots || []);
  }, [form.practitioner_id, form.date]);

  React.useEffect(() => { loadSlots(); }, [loadSlots]);

  const book = async () => {
    if (!form.slot) return toast({ title: "Pick a time slot" });
    if (form.visit_mode === "telehealth" && !form.consent) {
      return toast({ title: "Please acknowledge the telehealth consent" });
    }
    const s = normalizeArray(slots).find((x) => x.start === form.slot);
    if (!s) return;
    try {
      const me = await api.get("/clients/me");
      await api.post("/appointments", {
        client_id: me.data.id,
        practitioner_id: form.practitioner_id,
        service: "Consultation",
        start: s.start,
        end: s.end,
        status: "requested",
        visit_mode: form.visit_mode,
        consent_telehealth: form.visit_mode === "telehealth" ? form.consent : false,
      });
      toast({ title: "Requested", description: form.visit_mode === "telehealth" ? "We'll send your video visit link." : "We'll confirm your appointment shortly." });
      setOpen(false);
      load();
    } catch (e) { toast({ title: "Failed", description: getErrorMessage(e) || "" }); }
  };

  const cancel = async (a) => {
    if (!window.confirm("Cancel this appointment?")) return;
    await api.put(`/appointments/${a.id}`, { status: "canceled" });
    load();
  };

  const [historyOpen, setHistoryOpen] = React.useState(false);
  const [historyFilter, setHistoryFilter] = React.useState("all");

  const upcoming = normalizeArray(items)
    .filter(
      (a) =>
        new Date(a.start) >= new Date() &&
        a.status !== "canceled"
    )
    .sort(
      (a, b) =>
        new Date(a.start) - new Date(b.start)
    );

  const nextAppointment = upcoming[0] || null;
  const laterUpcoming = upcoming.slice(1);

  const past = normalizeArray(items)
    .filter(
      (a) =>
        new Date(a.start) < new Date() ||
        a.status === "canceled"
    )
    .sort(
      (a, b) =>
        new Date(b.start) - new Date(a.start)
    );

  const filteredHistory = past.filter((a) => {
    if (historyFilter === "all") return true;
    if (historyFilter === "canceled") {
      return a.status === "canceled";
    }
    if (historyFilter === "completed") {
      return a.status === "completed";
    }
    return true;
  });

  const friendlyStatus = (status) => {
    const labels = {
      requested: "Requested",
      scheduled: "Scheduled",
      confirmed: "Confirmed",
      arrived: "Arrived",
      in_session: "In session",
      completed: "Completed",
      canceled: "Canceled",
    };

    return labels[status] || status || "Scheduled";
  };

  return (
    <PortalLayout>
      <PortalHeader
        title="Appointments"
        subtitle="Book or manage your visits"
        actions={<Button onClick={() => setOpen(true)} className="rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"><Plus size={16} className="mr-2" /> Book visit</Button>}
      />

      <section className="mb-8">
        <h2 className="eyebrow text-[#8a6a3c] mb-3">
          Next appointment
        </h2>

        {nextAppointment ? (
          <div className="rounded-2xl border border-[#c19a4b] bg-[#fbf7ee] p-5">
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
              <div>
                <div className="font-display text-xl text-[#1f2a22] flex items-center gap-2">
                  {nextAppointment.visit_mode === "telehealth" ? (
                    <Video size={18} className="text-[#2f4a3a]" />
                  ) : (
                    <MapPin size={18} className="text-[#2f4a3a]" />
                  )}

                  {new Date(nextAppointment.start).toLocaleString(
                    [],
                    {
                      weekday: "long",
                      month: "long",
                      day: "numeric",
                      hour: "numeric",
                      minute: "2-digit",
                    }
                  )}
                </div>

                <div className="mt-1 text-sm text-[#6a6a6a]">
                  {nextAppointment.service || "Consultation"}
                  {" · with "}
                  {nextAppointment.practitioner_name || "Practitioner"}
                  {" · "}
                  {nextAppointment.visit_mode === "telehealth"
                    ? "Telehealth"
                    : "In-person"}
                </div>

                <div className="mt-2">
                  <span className="inline-flex rounded-full bg-[#f1ead8] px-3 py-1 text-[11px] font-medium text-[#6b4a1c]">
                    {friendlyStatus(nextAppointment.status)}
                  </span>
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                {nextAppointment.visit_mode === "telehealth" &&
                  nextAppointment.status !== "canceled" && (
                    <Link to={`/portal/visit/${nextAppointment.id}`}>
                      <Button
                        size="sm"
                        className="rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
                      >
                        <Video size={14} className="mr-1" />
                        Join visit
                      </Button>
                    </Link>
                  )}

                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => cancel(nextAppointment)}
                  className="rounded-full border-[#7a2a2a] text-[#7a2a2a] hover:bg-[#7a2a2a] hover:text-[#f6f1e6]"
                >
                  <X size={14} className="mr-1" />
                  Cancel
                </Button>
              </div>
            </div>
          </div>
        ) : (
          <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-8 text-center text-[#6a6a6a]">
            <CalendarDays
              size={28}
              className="mx-auto text-[#c19a4b]"
            />
            <div className="mt-3">
              No upcoming appointments.
            </div>
          </div>
        )}
      </section>

      {laterUpcoming.length > 0 && (
        <section className="mb-8">
          <div className="flex items-center gap-2 mb-3">
            <h2 className="eyebrow text-[#8a6a3c]">
              Later appointments
            </h2>

            <span className="inline-flex min-w-[22px] h-[22px] items-center justify-center rounded-full bg-[#f1ead8] px-2 text-[11px] font-medium text-[#6b4a1c]">
              {laterUpcoming.length}
            </span>
          </div>

          <ul className="space-y-3">
            {laterUpcoming.map((a) => (
              <li
                key={a.id}
                className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5 flex flex-col md:flex-row md:items-center md:justify-between gap-3"
              >
                <div>
                  <div className="font-display text-lg text-[#1f2a22] flex items-center gap-2">
                    {a.visit_mode === "telehealth" ? (
                      <Video size={16} className="text-[#2f4a3a]" />
                    ) : (
                      <MapPin size={16} className="text-[#2f4a3a]" />
                    )}

                    {new Date(a.start).toLocaleString(
                      [],
                      {
                        weekday: "long",
                        month: "short",
                        day: "numeric",
                        hour: "numeric",
                        minute: "2-digit",
                      }
                    )}
                  </div>

                  <div className="text-sm text-[#6a6a6a]">
                    {a.service || "Consultation"}
                    {" · with "}
                    {a.practitioner_name || "Practitioner"}
                    {" · "}
                    {a.visit_mode === "telehealth"
                      ? "Telehealth"
                      : "In-person"}
                  </div>

                  <div className="text-xs text-[#8a6a3c] uppercase tracking-widest mt-1">
                    {friendlyStatus(a.status)}
                  </div>
                </div>

                <div className="flex gap-2">
                  {a.visit_mode === "telehealth" &&
                    a.status !== "canceled" && (
                      <Link to={`/portal/visit/${a.id}`}>
                        <Button
                          size="sm"
                          className="rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
                        >
                          <Video size={14} className="mr-1" />
                          Join visit
                        </Button>
                      </Link>
                    )}

                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => cancel(a)}
                    className="rounded-full border-[#7a2a2a] text-[#7a2a2a] hover:bg-[#7a2a2a] hover:text-[#f6f1e6]"
                  >
                    <X size={14} className="mr-1" />
                    Cancel
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="mt-10">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <button
            type="button"
            onClick={() => setHistoryOpen((value) => !value)}
            className="flex items-center gap-2 text-left"
            aria-expanded={historyOpen}
          >
            <h2 className="eyebrow text-[#8a6a3c]">
              Appointment history
            </h2>

            <span className="inline-flex min-w-[24px] h-6 items-center justify-center rounded-full bg-[#f1ead8] px-2 text-xs text-[#6b4a1c]">
              {past.length}
            </span>

            <span className="text-xs text-[#6a6a6a]">
              {historyOpen ? "Hide" : "View"}
            </span>
          </button>

          {historyOpen && (
            <div className="flex flex-wrap gap-2">
              {[
                ["all", "All"],
                ["completed", "Completed"],
                ["canceled", "Canceled"],
              ].map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setHistoryFilter(id)}
                  className={`rounded-full px-3 py-1.5 text-xs font-medium ${
                    historyFilter === id
                      ? "bg-[#2f4a3a] text-[#f6f1e6]"
                      : "bg-[#f1ead8] text-[#5d513d]"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>

        {historyOpen && (
          <div className="mt-3">
            {past.length === 0 ? (
              <div className="text-sm text-[#6a6a6a]">
                No appointment history.
              </div>
            ) : filteredHistory.length === 0 ? (
              <div className="text-sm text-[#6a6a6a]">
                No appointments match this filter.
              </div>
            ) : (
              <ul className="space-y-2">
                {filteredHistory.map((a) => (
                  <li
                    key={a.id}
                    className="rounded-xl border border-[#e7dfc9] bg-[#fbf7ee] p-4 text-sm flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2"
                  >
                    <span>
                      {new Date(a.start).toLocaleDateString()}
                      {" · "}
                      {a.service || "—"}
                      {" · "}
                      {a.practitioner_name || "—"}
                    </span>

                    <span className="uppercase text-[10px] tracking-widest text-[#8a6a3c]">
                      {friendlyStatus(a.status)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </section>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9]">
          <DialogHeader>
            <DialogTitle className="font-display text-2xl">Book a visit</DialogTitle>
            <DialogDescription>Choose a practitioner, date, and reason for your appointment.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Visit type</Label>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <button onClick={() => setForm({ ...form, visit_mode: "in_person", consent: false })}
                  className={`rounded-xl border p-3 text-left text-sm ${form.visit_mode === "in_person" ? "border-[#2f4a3a] bg-[#f1ead8]" : "border-[#e0d6bc] bg-[#fbf7ee]"}`}>
                  <MapPin size={16} className="text-[#2f4a3a] mb-1" />
                  <div className="font-medium">In-person</div>
                  <div className="text-xs text-[#6a6a6a]">At our Roswell clinic</div>
                </button>
                <button onClick={() => setForm({ ...form, visit_mode: "telehealth" })}
                  className={`rounded-xl border p-3 text-left text-sm ${form.visit_mode === "telehealth" ? "border-[#2f4a3a] bg-[#f1ead8]" : "border-[#e0d6bc] bg-[#fbf7ee]"}`}>
                  <Video size={16} className="text-[#2f4a3a] mb-1" />
                  <div className="font-medium">Telehealth</div>
                  <div className="text-xs text-[#6a6a6a]">Secure video visit</div>
                </button>
              </div>
            </div>
            <div><Label>Practitioner</Label>
              <Select value={form.practitioner_id} onValueChange={(v) => setForm({ ...form, practitioner_id: v, slot: "" })}>
                <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"><SelectValue /></SelectTrigger>
                <SelectContent>{normalizeArray(practitioners).map((p) => <SelectItem key={p.id} value={p.id}>{p.full_name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div><Label>Date</Label>
              <input type="date" min={new Date().toISOString().slice(0,10)} value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value, slot: "" })} className="mt-2 h-10 w-full rounded-md bg-[#f6f1e6] border border-[#e0d6bc] px-3 text-sm" />
            </div>
            {form.date && (
              <div>
                <Label>Available times</Label>
                {slots.length === 0 ? (
                  <div className="text-xs text-[#6a6a6a] mt-2">No open slots on this date.</div>
                ) : (
                  <div className="mt-2 grid grid-cols-3 gap-2">
                    {normalizeArray(slots).map((s) => (
                      <button
                        key={s.start}
                        onClick={() => setForm({ ...form, slot: s.start })}
                        className={`rounded-full px-3 py-2 text-xs border ${form.slot === s.start ? "bg-[#2f4a3a] text-[#f6f1e6] border-[#2f4a3a]" : "bg-[#fbf7ee] text-[#3a3a3a] border-[#e0d6bc] hover:border-[#c19a4b]"}`}
                      >
                        {new Date(s.start).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
            {form.visit_mode === "telehealth" && (
              <label className="flex items-start gap-2 text-xs text-[#3a3a3a] cursor-pointer rounded-xl border border-[#c19a4b] bg-[#fbf2d9] p-3">
                <input type="checkbox" checked={form.consent} onChange={(e) => setForm({ ...form, consent: e.target.checked })} className="mt-0.5 accent-[#2f4a3a]" />
                <span>I consent to a telehealth visit. I understand it does not replace emergency care and may be limited by technology.</span>
              </label>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={book} className="bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]">Request visit</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PortalLayout>
  );
}