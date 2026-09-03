import React from "react";
import {
  Activity,
  AlertCircle,
  Edit3,
  HeartPulse,
  Loader2,
  Plus,
  RefreshCw,
  Save,
  X,
} from "lucide-react";

import api from "../../lib/api";
import { normalizeArray } from "../../lib/collections";
import { getErrorMessage } from "../../lib/errors";
import { useToast } from "../../hooks/use-toast";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Textarea } from "../ui/textarea";

const EMPTY_FORM = {
  appointment_id: "",
  source: "staff_measured",
  visit_mode: "in_person",
  systolic: "",
  diastolic: "",
  pulse: "",
  respiratory_rate: "",
  temperature_f: "",
  oxygen_saturation: "",
  height_in: "",
  weight_lb: "",
  pain_score: "",
  blood_glucose: "",
  waist_in: "",
  notes: "",
};

const NUMERIC_FIELDS = [
  "systolic",
  "diastolic",
  "pulse",
  "respiratory_rate",
  "temperature_f",
  "oxygen_saturation",
  "height_in",
  "weight_lb",
  "pain_score",
  "blood_glucose",
  "waist_in",
];

function formatDateTime(value) {
  if (!value) return "—";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) return "—";

  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatAppointment(appointment) {
  const date = appointment.start
    ? new Date(appointment.start)
    : null;

  const dateLabel =
    date && !Number.isNaN(date.getTime())
      ? date.toLocaleString([], {
          month: "short",
          day: "numeric",
          year: "numeric",
          hour: "numeric",
          minute: "2-digit",
        })
      : "Unscheduled";

  return `${dateLabel} — ${
    appointment.service ||
    String(appointment.visit_mode || "visit").replace(/_/g, " ")
  }`;
}

function normalizeFormPayload(form, clientId) {
  const payload = {
    client_id: clientId,
    appointment_id: form.appointment_id || null,
    source: form.source,
    visit_mode: form.visit_mode,
    notes: form.notes.trim() || null,
  };

  NUMERIC_FIELDS.forEach((field) => {
    const raw = form[field];

    payload[field] =
      raw === "" || raw === null || raw === undefined
        ? null
        : Number(raw);
  });

  return payload;
}

function ReadingCard({
  label,
  value,
  suffix = "",
  dark = false,
}) {
  return (
    <div
      className={
        dark
          ? "rounded-xl border border-[#2f4a3a] bg-[#0e1a14] p-3"
          : "rounded-xl border border-[#e7dfc9] bg-[#f6f1e6] p-3"
      }
    >
      <div
        className={
          dark
            ? "text-[10px] uppercase tracking-widest text-[#8a9a8e]"
            : "text-[10px] uppercase tracking-widest text-[#8a6a3c]"
        }
      >
        {label}
      </div>

      <div
        className={
          dark
            ? "mt-1 font-display text-xl text-[#f6f1e6]"
            : "mt-1 font-display text-xl text-[#1f2a22]"
        }
      >
        {value === null ||
        value === undefined ||
        value === ""
          ? "—"
          : `${value}${suffix}`}
      </div>
    </div>
  );
}

export default function PatientVitalsPanel({
  clientId,
  appointmentId = null,
  visitMode = "in_person",
  editable = true,
  variant = "light",
  compact = false,
}) {
  const { toast } = useToast();
  const dark = variant === "dark";

  const [vitals, setVitals] = React.useState([]);
  const [appointments, setAppointments] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [loadError, setLoadError] = React.useState("");
  const [showForm, setShowForm] = React.useState(false);
  const [editing, setEditing] = React.useState(null);
  const [amendmentReason, setAmendmentReason] =
    React.useState("");
  const [form, setForm] = React.useState({
    ...EMPTY_FORM,
    appointment_id: appointmentId || "",
    visit_mode: visitMode,
  });

  const load = React.useCallback(async () => {
    if (!clientId) return;

    setLoading(true);
    setLoadError("");

    try {
      const [vitalsResponse, appointmentsResponse] =
        await Promise.all([
          api.get("/vitals", {
            params: {
              client_id: clientId,
              limit: 500,
            },
          }),
          appointmentId
            ? Promise.resolve({ data: [] })
            : api
                .get("/appointments", {
                  params: {
                    client_id: clientId,
                  },
                })
                .catch(() => ({ data: [] })),
        ]);

      setVitals(
        normalizeArray(vitalsResponse.data, [
          "vitals",
          "items",
        ])
      );

      setAppointments(
        normalizeArray(appointmentsResponse.data, [
          "appointments",
          "items",
        ])
      );
    } catch (error) {
      setLoadError(
        getErrorMessage(error) ||
          "Vitals could not be loaded."
      );
    } finally {
      setLoading(false);
    }
  }, [clientId, appointmentId]);

  React.useEffect(() => {
    load();
  }, [load]);

  React.useEffect(() => {
    setForm((current) => ({
      ...current,
      appointment_id:
        appointmentId || current.appointment_id || "",
      visit_mode: visitMode || current.visit_mode,
    }));
  }, [appointmentId, visitMode]);

  const latest = vitals[0] || null;

  const resetForm = () => {
    setEditing(null);
    setAmendmentReason("");
    setForm({
      ...EMPTY_FORM,
      appointment_id: appointmentId || "",
      visit_mode: visitMode,
    });
  };

  const openNew = () => {
    resetForm();
    setShowForm(true);
  };

  const openEdit = (record) => {
    setEditing(record);
    setAmendmentReason("");

    setForm({
      appointment_id:
        record.appointment_id || appointmentId || "",
      source: record.source || "staff_measured",
      visit_mode: record.visit_mode || visitMode,
      systolic: record.systolic ?? "",
      diastolic: record.diastolic ?? "",
      pulse: record.pulse ?? "",
      respiratory_rate:
        record.respiratory_rate ?? "",
      temperature_f: record.temperature_f ?? "",
      oxygen_saturation:
        record.oxygen_saturation ?? "",
      height_in: record.height_in ?? "",
      weight_lb: record.weight_lb ?? "",
      pain_score: record.pain_score ?? "",
      blood_glucose: record.blood_glucose ?? "",
      waist_in: record.waist_in ?? "",
      notes: record.notes || "",
    });

    setShowForm(true);
  };

  const save = async () => {
    if (!clientId) return;

    if (editing && amendmentReason.trim().length < 3) {
      toast({
        title: "Amendment reason required",
        description:
          "Explain why the prior vitals record is being corrected.",
      });
      return;
    }

    setSaving(true);

    try {
      const payload = normalizeFormPayload(
        form,
        clientId
      );

      if (editing) {
        await api.put(`/vitals/${editing.id}`, {
          ...payload,
          amendment_reason: amendmentReason.trim(),
        });

        toast({
          title: "Vitals amended",
          description:
            "The prior values were preserved in amendment history.",
        });
      } else {
        await api.post("/vitals", payload);

        toast({
          title: "Vitals recorded",
          description:
            "A new visit-based vitals record was added.",
        });
      }

      setShowForm(false);
      resetForm();
      await load();
    } catch (error) {
      toast({
        title: "Could not save vitals",
        description:
          getErrorMessage(error) || "Try again.",
      });
    } finally {
      setSaving(false);
    }
  };

  if (!clientId) {
    return (
      <div
        className={
          dark
            ? "p-4 text-sm text-[#8a9a8e]"
            : "rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-6 text-sm text-[#6a6a6a]"
        }
      >
        No patient is linked to this record.
      </div>
    );
  }

  return (
    <div
      className={
        dark
          ? "space-y-3 text-[#f6f1e6]"
          : "space-y-5"
      }
      data-testid="patient-vitals-panel"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div
            className={
              dark
                ? "text-xs uppercase tracking-widest text-[#c19a4b]"
                : "eyebrow text-[#8a6a3c]"
            }
          >
            Vitals
          </div>

          <div
            className={
              dark
                ? "mt-1 text-xs text-[#8a9a8e]"
                : "mt-1 text-sm text-[#6a6a6a]"
            }
          >
            Each visit creates a separate record.
          </div>
        </div>

        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={load}
            disabled={loading}
            className={
              dark
                ? "rounded-full border-[#2f4a3a] bg-transparent text-[#c19a4b] hover:bg-[#2f4a3a]"
                : "rounded-full border-[#8a6a3c] text-[#8a6a3c]"
            }
          >
            <RefreshCw
              size={13}
              className={
                loading ? "mr-1 animate-spin" : "mr-1"
              }
            />
            Refresh
          </Button>

          {editable && (
            <Button
              type="button"
              size="sm"
              onClick={openNew}
              className={
                dark
                  ? "rounded-full bg-[#c19a4b] text-[#1f2a22] hover:bg-[#a8853f]"
                  : "rounded-full bg-[#2f4a3a] text-[#f6f1e6] hover:bg-[#263d30]"
              }
              data-testid="vitals-new"
            >
              <Plus size={13} className="mr-1" />
              Record
            </Button>
          )}
        </div>
      </div>

      {loadError && (
        <div
          className={
            dark
              ? "rounded-xl border border-[#7a2a2a] bg-[#1a0e0e] p-3 text-sm text-[#e9b5b5]"
              : "rounded-xl border border-[#d6aaaa] bg-[#fff5f5] p-4 text-sm text-[#7a2a2a]"
          }
        >
          <AlertCircle size={15} className="mb-2" />
          {loadError}
        </div>
      )}

      {showForm && editable && (
        <div
          className={
            dark
              ? "rounded-xl border border-[#c19a4b] bg-[#0e1a14] p-4"
              : "rounded-2xl border border-[#c19a4b] bg-[#fbf7ee] p-5"
          }
        >
          <div className="mb-4 flex items-center justify-between">
            <div
              className={
                dark
                  ? "font-medium text-[#f6f1e6]"
                  : "font-display text-xl text-[#1f2a22]"
              }
            >
              {editing
                ? "Correct vitals record"
                : "Record visit vitals"}
            </div>

            <button
              type="button"
              onClick={() => {
                setShowForm(false);
                resetForm();
              }}
              className={
                dark
                  ? "rounded-full p-2 text-[#8a9a8e] hover:bg-[#2f4a3a]"
                  : "rounded-full p-2 text-[#6a6a6a] hover:bg-[#f1ead8]"
              }
            >
              <X size={16} />
            </button>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {!appointmentId && (
              <div className="sm:col-span-2 lg:col-span-4">
                <Label>Visit</Label>
                <select
                  value={form.appointment_id}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      appointment_id: event.target.value,
                    })
                  }
                  className={
                    dark
                      ? "mt-2 h-10 w-full rounded-md border border-[#2f4a3a] bg-[#1a2a22] px-3 text-sm text-[#f6f1e6]"
                      : "mt-2 h-10 w-full rounded-md border border-[#e0d6bc] bg-[#f6f1e6] px-3 text-sm"
                  }
                >
                  <option value="">
                    General chart entry
                  </option>

                  {normalizeArray(appointments).map((appointment) => (
                    <option
                      key={appointment.id}
                      value={appointment.id}
                    >
                      {formatAppointment(appointment)}
                    </option>
                  ))}
                </select>
              </div>
            )}

            <div>
              <Label>Source</Label>
              <select
                value={form.source}
                onChange={(event) =>
                  setForm({
                    ...form,
                    source: event.target.value,
                  })
                }
                className={
                  dark
                    ? "mt-2 h-10 w-full rounded-md border border-[#2f4a3a] bg-[#1a2a22] px-3 text-sm text-[#f6f1e6]"
                    : "mt-2 h-10 w-full rounded-md border border-[#e0d6bc] bg-[#f6f1e6] px-3 text-sm"
                }
              >
                <option value="staff_measured">
                  Measured by staff
                </option>
                <option value="patient_reported">
                  Patient reported
                </option>
                <option value="device_imported">
                  Device imported
                </option>
              </select>
            </div>

            <div>
              <Label>Visit mode</Label>
              <select
                value={form.visit_mode}
                disabled={!!appointmentId}
                onChange={(event) =>
                  setForm({
                    ...form,
                    visit_mode: event.target.value,
                  })
                }
                className={
                  dark
                    ? "mt-2 h-10 w-full rounded-md border border-[#2f4a3a] bg-[#1a2a22] px-3 text-sm text-[#f6f1e6]"
                    : "mt-2 h-10 w-full rounded-md border border-[#e0d6bc] bg-[#f6f1e6] px-3 text-sm"
                }
              >
                <option value="in_person">
                  In person
                </option>
                <option value="telehealth">
                  Telehealth
                </option>
                <option value="home">Home</option>
              </select>
            </div>

            {[
              ["systolic", "Systolic BP"],
              ["diastolic", "Diastolic BP"],
              ["pulse", "Pulse"],
              ["respiratory_rate", "Respirations"],
              ["temperature_f", "Temperature °F"],
              ["oxygen_saturation", "SpO₂ %"],
              ["height_in", "Height inches"],
              ["weight_lb", "Weight pounds"],
              ["pain_score", "Pain 0–10"],
              ["blood_glucose", "Blood glucose"],
              ["waist_in", "Waist inches"],
            ].map(([field, label]) => (
              <div key={field}>
                <Label>{label}</Label>
                <Input
                  type="number"
                  step={
                    [
                      "temperature_f",
                      "oxygen_saturation",
                      "height_in",
                      "weight_lb",
                      "blood_glucose",
                      "waist_in",
                    ].includes(field)
                      ? "0.1"
                      : "1"
                  }
                  value={form[field]}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      [field]: event.target.value,
                    })
                  }
                  className={
                    dark
                      ? "mt-2 border-[#2f4a3a] bg-[#1a2a22] text-[#f6f1e6]"
                      : "mt-2 border-[#e0d6bc] bg-[#f6f1e6]"
                  }
                />
              </div>
            ))}

            <div className="sm:col-span-2 lg:col-span-4">
              <Label>Notes</Label>
              <Textarea
                value={form.notes}
                onChange={(event) =>
                  setForm({
                    ...form,
                    notes: event.target.value,
                  })
                }
                className={
                  dark
                    ? "mt-2 min-h-20 border-[#2f4a3a] bg-[#1a2a22] text-[#f6f1e6]"
                    : "mt-2 min-h-20 border-[#e0d6bc] bg-[#f6f1e6]"
                }
              />
            </div>

            {editing && (
              <div className="sm:col-span-2 lg:col-span-4">
                <Label>Reason for correction</Label>
                <Textarea
                  value={amendmentReason}
                  onChange={(event) =>
                    setAmendmentReason(
                      event.target.value
                    )
                  }
                  placeholder="Explain why this record is being amended."
                  className={
                    dark
                      ? "mt-2 min-h-20 border-[#7a2a2a] bg-[#1a2a22] text-[#f6f1e6]"
                      : "mt-2 min-h-20 border-[#d6aaaa] bg-[#fffafa]"
                  }
                />
              </div>
            )}
          </div>

          <div className="mt-4 flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setShowForm(false);
                resetForm();
              }}
            >
              Cancel
            </Button>

            <Button
              type="button"
              onClick={save}
              disabled={saving}
              className={
                dark
                  ? "bg-[#c19a4b] text-[#1f2a22] hover:bg-[#a8853f]"
                  : "bg-[#2f4a3a] text-[#f6f1e6] hover:bg-[#263d30]"
              }
            >
              {saving ? (
                <Loader2
                  size={14}
                  className="mr-2 animate-spin"
                />
              ) : (
                <Save size={14} className="mr-2" />
              )}
              {editing ? "Save correction" : "Save vitals"}
            </Button>
          </div>
        </div>
      )}

      {loading && vitals.length === 0 ? (
        <div
          className={
            dark
              ? "py-8 text-center text-sm text-[#8a9a8e]"
              : "rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-8 text-center text-sm text-[#6a6a6a]"
          }
        >
          <Loader2
            size={16}
            className="mr-2 inline animate-spin"
          />
          Loading vitals…
        </div>
      ) : latest ? (
        <>
          <div
            className={`grid gap-2 ${
              compact
                ? "grid-cols-2"
                : "grid-cols-2 md:grid-cols-4"
            }`}
          >
            <ReadingCard
              label="Blood pressure"
              value={
                latest.systolic && latest.diastolic
                  ? `${latest.systolic}/${latest.diastolic}`
                  : null
              }
              dark={dark}
            />
            <ReadingCard
              label="Pulse"
              value={latest.pulse}
              suffix=" bpm"
              dark={dark}
            />
            <ReadingCard
              label="SpO₂"
              value={latest.oxygen_saturation}
              suffix="%"
              dark={dark}
            />
            <ReadingCard
              label="Temperature"
              value={latest.temperature_f}
              suffix="°F"
              dark={dark}
            />
            <ReadingCard
              label="Respirations"
              value={latest.respiratory_rate}
              suffix="/min"
              dark={dark}
            />
            <ReadingCard
              label="Weight"
              value={latest.weight_lb}
              suffix=" lb"
              dark={dark}
            />
            <ReadingCard
              label="BMI"
              value={latest.bmi}
              dark={dark}
            />
            <ReadingCard
              label="Pain"
              value={latest.pain_score}
              suffix="/10"
              dark={dark}
            />
          </div>

          <div
            className={
              dark
                ? "rounded-xl border border-[#2f4a3a] bg-[#0e1a14] p-3"
                : "rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5"
            }
          >
            <div className="mb-3 flex items-center gap-2">
              <HeartPulse
                size={15}
                className={
                  dark
                    ? "text-[#c19a4b]"
                    : "text-[#8a6a3c]"
                }
              />
              <div
                className={
                  dark
                    ? "text-xs uppercase tracking-widest text-[#c19a4b]"
                    : "font-medium text-[#1f2a22]"
                }
              >
                Vitals history
              </div>
            </div>

            <div className="space-y-3">
              {normalizeArray(vitals).map((record) => (
                <div
                  key={record.id}
                  className={
                    dark
                      ? "rounded-lg bg-[#1a2a22] p-3 text-xs"
                      : "rounded-xl border border-[#eee6d4] bg-[#f6f1e6] p-4 text-sm"
                  }
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div
                        className={
                          dark
                            ? "text-[#f6f1e6]"
                            : "font-medium text-[#1f2a22]"
                        }
                      >
                        {formatDateTime(
                          record.recorded_at ||
                            record.created_at
                        )}
                      </div>

                      <div
                        className={
                          dark
                            ? "mt-1 text-[#8a9a8e]"
                            : "mt-1 text-xs text-[#6a6a6a]"
                        }
                      >
                        {String(
                          record.visit_mode ||
                            "in_person"
                        ).replace(/_/g, " ")}
                        {" · "}
                        {String(
                          record.source ||
                            "staff_measured"
                        ).replace(/_/g, " ")}
                        {record.recorded_by_name
                          ? ` · ${record.recorded_by_name}`
                          : ""}
                      </div>
                    </div>

                    {editable && (
                      <button
                        type="button"
                        onClick={() => openEdit(record)}
                        className={
                          dark
                            ? "rounded-full p-2 text-[#c19a4b] hover:bg-[#2f4a3a]"
                            : "rounded-full p-2 text-[#8a6a3c] hover:bg-[#eee6d4]"
                        }
                        title="Correct record"
                      >
                        <Edit3 size={13} />
                      </button>
                    )}
                  </div>

                  <div
                    className={
                      dark
                        ? "mt-3 grid grid-cols-2 gap-2 text-[#c8d4cc]"
                        : "mt-3 grid grid-cols-2 gap-2 text-xs text-[#3a3a3a] md:grid-cols-4"
                    }
                  >
                    <div>
                      BP{" "}
                      {record.systolic &&
                      record.diastolic
                        ? `${record.systolic}/${record.diastolic}`
                        : "—"}
                    </div>
                    <div>
                      Pulse {record.pulse ?? "—"}
                    </div>
                    <div>
                      SpO₂{" "}
                      {record.oxygen_saturation ??
                        "—"}
                    </div>
                    <div>
                      Weight {record.weight_lb ?? "—"}
                    </div>
                    <div>
                      Temp{" "}
                      {record.temperature_f ?? "—"}
                    </div>
                    <div>
                      Resp{" "}
                      {record.respiratory_rate ?? "—"}
                    </div>
                    <div>
                      BMI {record.bmi ?? "—"}
                    </div>
                    <div>
                      Pain {record.pain_score ?? "—"}
                    </div>
                  </div>

                  {record.notes && (
                    <div
                      className={
                        dark
                          ? "mt-3 text-[#c8d4cc]"
                          : "mt-3 text-xs text-[#6a6a6a]"
                      }
                    >
                      {record.notes}
                    </div>
                  )}

                  {record.amended_at && (
                    <div
                      className={
                        dark
                          ? "mt-3 text-[10px] text-[#d7b878]"
                          : "mt-3 text-xs text-[#8a6a3c]"
                      }
                    >
                      Corrected{" "}
                      {formatDateTime(record.amended_at)}
                      {record.amendment_reason
                        ? ` — ${record.amendment_reason}`
                        : ""}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </>
      ) : (
        <div
          className={
            dark
              ? "rounded-xl border border-[#2f4a3a] bg-[#0e1a14] p-6 text-center text-sm text-[#8a9a8e]"
              : "rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-8 text-center text-[#6a6a6a]"
          }
        >
          <Activity
            size={22}
            className="mx-auto mb-3 opacity-60"
          />
          No vitals have been recorded yet.
        </div>
      )}
    </div>
  );
}
