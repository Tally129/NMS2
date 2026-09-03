import React from "react";
import {
  AlertCircle,
  ExternalLink,
  FileText,
  FlaskConical,
  Loader2,
  RefreshCw,
  Stethoscope,
  UserRound,
} from "lucide-react";

import api from "../../lib/api";
import { normalizeArray } from "../../lib/collections";
import { Button } from "../ui/button";
import PatientVitalsPanel from "../clinical/PatientVitalsPanel";

function safeText(value, fallback = "—") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }

  if (Array.isArray(value)) {
    return value.length ? value.join(", ") : fallback;
  }

  if (typeof value === "object") {
    return Object.values(value).filter(Boolean).join(", ") || fallback;
  }

  return String(value);
}

function formatDate(value) {
  if (!value) return "—";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "—";
  }

  return date.toLocaleDateString([], {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function Section({ title, icon: Icon, children }) {
  return (
    <section className="rounded-xl border border-[#2f4a3a] bg-[#0e1a14] p-3">
      <div className="mb-3 flex items-center gap-2 text-xs font-medium uppercase tracking-widest text-[#c19a4b]">
        <Icon size={13} />
        {title}
      </div>

      {children}
    </section>
  );
}

export default function TelehealthClinicalPanel({
  clientId,
  appointmentId,
  patientName,
}) {
  const [tab, setTab] = React.useState("summary");
  const [loading, setLoading] = React.useState(false);
  const [loadError, setLoadError] = React.useState("");

  const [client, setClient] = React.useState(null);
  const [intake, setIntake] = React.useState(null);
  const [notes, setNotes] = React.useState([]);
  const [labs, setLabs] = React.useState([]);
  const [plans, setPlans] = React.useState([]);
  const [files, setFiles] = React.useState([]);

  const loadChart = React.useCallback(async () => {
    if (!clientId) return;

    setLoading(true);
    setLoadError("");

    const results = await Promise.allSettled([
      api.get(`/clients/${clientId}`),
      api.get(`/intake/${clientId}`),
      api.get("/notes", {
        params: { client_id: clientId },
      }),
      api.get("/lab-values", {
        params: { client_id: clientId },
      }),
      api.get("/treatment-plans", {
        params: { client_id: clientId },
      }),
      api.get("/files", {
        params: { client_id: clientId },
      }),
    ]);

    const [
      clientResult,
      intakeResult,
      notesResult,
      labsResult,
      plansResult,
      filesResult,
    ] = results;

    if (clientResult.status === "fulfilled") {
      setClient(clientResult.value.data || null);
    }

    if (intakeResult.status === "fulfilled") {
      setIntake(intakeResult.value.data || null);
    }

    if (notesResult.status === "fulfilled") {
      setNotes(
        normalizeArray(notesResult.value.data, [
          "notes",
          "items",
        ])
      );
    }

    if (labsResult.status === "fulfilled") {
      setLabs(
        normalizeArray(labsResult.value.data, [
          "labs",
          "lab_values",
          "items",
        ])
      );
    }

    if (plansResult.status === "fulfilled") {
      setPlans(
        normalizeArray(plansResult.value.data, [
          "plans",
          "treatment_plans",
          "items",
        ])
      );
    }

    if (filesResult.status === "fulfilled") {
      setFiles(
        normalizeArray(filesResult.value.data, [
          "files",
          "items",
        ])
      );
    }

    if (results.every((result) => result.status === "rejected")) {
      setLoadError("The patient chart could not be loaded.");
    }

    setLoading(false);
  }, [clientId]);

  React.useEffect(() => {
    loadChart();
  }, [loadChart]);

  const recentNotes = normalizeArray(notes)
    .slice()
    .sort(
      (a, b) =>
        new Date(b.created_at || 0) -
        new Date(a.created_at || 0)
    )
    .slice(0, 5);

  const recentLabs = normalizeArray(labs)
    .slice()
    .sort(
      (a, b) =>
        new Date(
          b.result_date ||
            b.collected_at ||
            b.created_at ||
            0
        ) -
        new Date(
          a.result_date ||
            a.collected_at ||
            a.created_at ||
            0
        )
    )
    .slice(0, 8);

  const activePlans = normalizeArray(plans)
    .filter(
      (plan) =>
        !["completed", "archived", "canceled"].includes(
          plan.status
        )
    )
    .slice(0, 5);

  const recentFiles = normalizeArray(files)
    .slice()
    .sort(
      (a, b) =>
        new Date(b.created_at || 0) -
        new Date(a.created_at || 0)
    )
    .slice(0, 8);

  const openFullChart = () => {
    if (!clientId) return;

    window.open(
      `/portal/provider/patients/${encodeURIComponent(
        clientId
      )}`,
      "_blank",
      "noopener,noreferrer"
    );
  };

  if (!clientId) {
    return (
      <div className="p-5 text-sm text-[#8a9a8e]">
        No patient chart is linked to this appointment.
      </div>
    );
  }

  return (
    <div
      className="flex h-full min-h-0 flex-col"
      data-testid="telehealth-clinical-panel"
    >
      <div className="border-b border-[#2f4a3a] p-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[10px] uppercase tracking-widest text-[#c19a4b]">
              Clinical workspace
            </div>

            <div className="mt-1 truncate font-medium text-[#f6f1e6]">
              {client?.full_name ||
                patientName ||
                "Patient chart"}
            </div>

            <div className="mt-1 text-xs text-[#8a9a8e]">
              MRN {client?.mrn || "—"}
              {appointmentId
                ? ` · Visit ${appointmentId.slice(0, 8)}`
                : ""}
            </div>
          </div>

          <button
            type="button"
            onClick={loadChart}
            disabled={loading}
            className="rounded-full p-2 text-[#c19a4b] hover:bg-[#2f4a3a]"
            title="Refresh chart"
          >
            <RefreshCw
              size={14}
              className={loading ? "animate-spin" : ""}
            />
          </button>
        </div>

        <div className="mt-3 grid grid-cols-4 gap-1">
          {[
            ["summary", "Summary"],
            ["intake", "Intake"],
            ["vitals", "Vitals"],
            ["notes", "Notes"],
            ["labs", "Labs"],
            ["plan", "Plan"],
            ["files", "Files"],
          ].map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setTab(value)}
              className={`rounded-lg px-1 py-2 text-[10px] uppercase tracking-wide ${
                tab === value
                  ? "bg-[#c19a4b] text-[#1f2a22]"
                  : "bg-[#0e1a14] text-[#c8d4cc] hover:bg-[#2f4a3a]"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        {loading && !client ? (
          <div className="py-10 text-center text-sm text-[#8a9a8e]">
            <Loader2
              size={16}
              className="mr-2 inline animate-spin"
            />
            Loading patient chart…
          </div>
        ) : loadError ? (
          <div className="rounded-xl border border-[#7a2a2a] bg-[#1a0e0e] p-4 text-sm text-[#e9b5b5]">
            <AlertCircle size={16} className="mb-2" />
            {loadError}
          </div>
        ) : null}

        {tab === "summary" && (
          <>
            <Section title="Patient snapshot" icon={UserRound}>
              <dl className="grid grid-cols-2 gap-x-3 gap-y-3 text-xs">
                <div>
                  <dt className="text-[#8a9a8e]">DOB</dt>
                  <dd className="mt-1 text-[#f6f1e6]">
                    {safeText(client?.dob)}
                  </dd>
                </div>

                <div>
                  <dt className="text-[#8a9a8e]">Phone</dt>
                  <dd className="mt-1 text-[#f6f1e6]">
                    {safeText(client?.phone)}
                  </dd>
                </div>

                <div className="col-span-2">
                  <dt className="text-[#8a9a8e]">Email</dt>
                  <dd className="mt-1 break-all text-[#f6f1e6]">
                    {safeText(client?.email)}
                  </dd>
                </div>

                <div className="col-span-2">
                  <dt className="text-[#8a9a8e]">
                    Primary concern
                  </dt>
                  <dd className="mt-1 text-[#f6f1e6]">
                    {safeText(client?.primary_concern)}
                  </dd>
                </div>
              </dl>
            </Section>

            <Section title="Safety information" icon={AlertCircle}>
              <div className="space-y-3 text-xs">
                <div>
                  <div className="text-[#8a9a8e]">
                    Allergies
                  </div>
                  <div className="mt-1 text-[#e9b5b5]">
                    {safeText(client?.allergies, "None recorded")}
                  </div>
                </div>

                <div>
                  <div className="text-[#8a9a8e]">
                    Current supplements
                  </div>
                  <div className="mt-1 text-[#f6f1e6]">
                    {safeText(
                      client?.current_supplements,
                      "None recorded"
                    )}
                  </div>
                </div>
              </div>
            </Section>

            <Section title="Quick overview" icon={Stethoscope}>
              <div className="grid grid-cols-2 gap-2 text-center text-xs">
                <div className="rounded-lg bg-[#1a2a22] p-3">
                  <div className="font-display text-xl text-[#f6f1e6]">
                    {notes.length}
                  </div>
                  <div className="text-[#8a9a8e]">Notes</div>
                </div>

                <div className="rounded-lg bg-[#1a2a22] p-3">
                  <div className="font-display text-xl text-[#f6f1e6]">
                    {labs.length}
                  </div>
                  <div className="text-[#8a9a8e]">Labs</div>
                </div>

                <div className="rounded-lg bg-[#1a2a22] p-3">
                  <div className="font-display text-xl text-[#f6f1e6]">
                    {activePlans.length}
                  </div>
                  <div className="text-[#8a9a8e]">
                    Active plans
                  </div>
                </div>

                <div className="rounded-lg bg-[#1a2a22] p-3">
                  <div className="font-display text-xl text-[#f6f1e6]">
                    {files.length}
                  </div>
                  <div className="text-[#8a9a8e]">Files</div>
                </div>
              </div>
            </Section>
          </>
        )}

        {tab === "intake" && (
          <Section title="Patient intake" icon={FileText}>
            {!intake ? (
              <div className="text-xs text-[#8a9a8e]">
                No intake has been submitted.
              </div>
            ) : (
              <div className="space-y-4 text-xs">
                {normalizeArray([
                  ["Demographics", intake.demographics],
                  ["Health history", intake.health_history],
                  ["Symptoms", intake.symptoms],
                  ["Lifestyle", intake.lifestyle],
                  ["Consent", intake.consent],
                ]).map(([title, data]) => (
                  <div key={title}>
                    <div className="mb-2 text-[#c19a4b]">
                      {title}
                    </div>

                    {!data ||
                    Object.keys(data).length === 0 ? (
                      <div className="text-[#8a9a8e]">
                        No information recorded.
                      </div>
                    ) : (
                      <dl className="space-y-2">
                        {Object.entries(data).map(
                          ([key, value]) => (
                            <div
                              key={key}
                              className="rounded-lg bg-[#1a2a22] p-2"
                            >
                              <dt className="text-[#8a9a8e]">
                                {String(key)
                                  .replace(/_/g, " ")
                                  .replace(
                                    /\b\w/g,
                                    (letter) =>
                                      letter.toUpperCase()
                                  )}
                              </dt>
                              <dd className="mt-1 text-[#f6f1e6]">
                                {safeText(value)}
                              </dd>
                            </div>
                          )
                        )}
                      </dl>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Section>
        )}

        {tab === "vitals" && (
          <PatientVitalsPanel
            clientId={clientId}
            appointmentId={appointmentId}
            visitMode="telehealth"
            editable
            variant="dark"
            compact
          />
        )}

        {tab === "notes" && (
          <Section title="Recent SOAP notes" icon={FileText}>
            {recentNotes.length === 0 ? (
              <div className="text-xs text-[#8a9a8e]">
                No prior notes found.
              </div>
            ) : (
              <div className="space-y-3">
                {recentNotes.map((note) => (
                  <div
                    key={note.id}
                    className="rounded-lg bg-[#1a2a22] p-3 text-xs"
                  >
                    <div className="text-[#c19a4b]">
                      {formatDate(note.created_at)}
                    </div>
                    <div className="mt-2 line-clamp-3 text-[#f6f1e6]">
                      {note.assessment ||
                        note.subjective ||
                        note.plan ||
                        "Clinical note"}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Section>
        )}

        {tab === "labs" && (
          <Section title="Recent labs" icon={FlaskConical}>
            {recentLabs.length === 0 ? (
              <div className="text-xs text-[#8a9a8e]">
                No lab results found.
              </div>
            ) : (
              <div className="space-y-2">
                {recentLabs.map((lab) => (
                  <div
                    key={lab.id}
                    className="flex items-start justify-between gap-3 rounded-lg bg-[#1a2a22] p-3 text-xs"
                  >
                    <div>
                      <div className="text-[#f6f1e6]">
                        {lab.test_name ||
                          lab.name ||
                          lab.marker ||
                          "Lab result"}
                      </div>
                      <div className="mt-1 text-[#8a9a8e]">
                        {formatDate(
                          lab.result_date ||
                            lab.collected_at ||
                            lab.created_at
                        )}
                      </div>
                    </div>

                    <div className="text-right text-[#c19a4b]">
                      {safeText(
                        lab.value ?? lab.result,
                        "View"
                      )}
                      {lab.unit ? ` ${lab.unit}` : ""}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Section>
        )}

        {tab === "plan" && (
          <Section title="Treatment plan" icon={Stethoscope}>
            {activePlans.length === 0 ? (
              <div className="text-xs text-[#8a9a8e]">
                No active treatment plan found.
              </div>
            ) : (
              <div className="space-y-3">
                {activePlans.map((plan) => (
                  <div
                    key={plan.id}
                    className="rounded-lg bg-[#1a2a22] p-3 text-xs"
                  >
                    <div className="text-[#f6f1e6]">
                      {plan.title ||
                        plan.name ||
                        "Treatment plan"}
                    </div>
                    <div className="mt-1 text-[#8a9a8e]">
                      {safeText(plan.status, "Active")}
                    </div>
                    {plan.summary && (
                      <div className="mt-2 line-clamp-4 text-[#c8d4cc]">
                        {plan.summary}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Section>
        )}

        {tab === "files" && (
          <Section title="Recent files" icon={FileText}>
            {recentFiles.length === 0 ? (
              <div className="text-xs text-[#8a9a8e]">
                No files found.
              </div>
            ) : (
              <div className="space-y-2">
                {recentFiles.map((file) => (
                  <div
                    key={file.id}
                    className="rounded-lg bg-[#1a2a22] p-3 text-xs"
                  >
                    <div className="truncate text-[#f6f1e6]">
                      {file.filename ||
                        file.name ||
                        "Patient file"}
                    </div>
                    <div className="mt-1 text-[#8a9a8e]">
                      {formatDate(file.created_at)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Section>
        )}
      </div>

      <div className="border-t border-[#2f4a3a] p-3">
        <Button
          type="button"
          variant="outline"
          onClick={openFullChart}
          className="w-full rounded-full border-[#c19a4b] text-[#c19a4b] hover:bg-[#c19a4b] hover:text-[#1f2a22]"
          data-testid="telehealth-open-full-chart"
        >
          <ExternalLink size={13} className="mr-2" />
          Open full chart
        </Button>
      </div>
    </div>
  );
}
