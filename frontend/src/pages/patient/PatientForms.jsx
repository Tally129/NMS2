import React from "react";
import { Link } from "react-router-dom";
import {
  ClipboardList,
  CheckCircle2,
  Clock3,
  AlertTriangle,
  FileSignature,
  ChevronRight,
  RefreshCw,
} from "lucide-react";

import PortalLayout, {
  PortalHeader,
  StatCard,
} from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { useToast } from "../../hooks/use-toast";
import { getErrorMessage } from "../../lib/errors";
import { normalizeArray } from "../../lib/collections";

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

function getFormUrl(submission) {
  if (submission?.submit_url) {
    return submission.submit_url;
  }

  if (submission?.token) {
    return `/forms/respond/${submission.token}`;
  }

  return null;
}

function StatusBadge({ status }) {
  const config = {
    sent: {
      label: "Pending",
      className:
        "border-[#e6d38a] bg-[#fbf3df] text-[#8a6a3c]",
    },
    submitted: {
      label: "Completed",
      className:
        "border-[#cfe0d3] bg-[#eaf2ec] text-[#3d6b52]",
    },
    expired: {
      label: "Expired",
      className:
        "border-[#e5c7c7] bg-[#fff5f5] text-[#7a2a2a]",
    },
  };

  const selected = config[status] || {
    label: status || "Unknown",
    className:
      "border-[#e0d6bc] bg-[#f6f1e6] text-[#6a6a6a]",
  };

  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-medium ${selected.className}`}
    >
      {selected.label}
    </span>
  );
}

function FormCard({ submission, onViewCompleted}) {
  const status = submission.status || "sent";
  const formUrl = getFormUrl(submission);
  const isPending = status === "sent";
  const title =
    submission.template_title ||
    submission.title ||
    "Assigned form";

  return (
    <div
      className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5"
      data-testid={`patient-form-${submission.id}`}
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <div className="font-display text-xl text-[#1f2a22]">
              {title}
            </div>

            <StatusBadge status={status} />
          </div>

          <div className="mt-2 text-sm text-[#6a6a6a]">
            {submission.template_category
              ? `${submission.template_category
                  .replaceAll("_", " ")
                  .replace(/\b\w/g, (letter) =>
                    letter.toUpperCase()
                  )} · `
              : ""}
            Assigned {formatDate(submission.created_at)}
          </div>

          {submission.expires_at && isPending && (
            <div className="mt-2 text-xs text-[#8a6a3c]">
              Complete by {formatDate(submission.expires_at)}
            </div>
          )}

          {submission.submitted_at && status === "submitted" && (
            <div className="mt-2 text-xs text-[#3d6b52]">
              Completed {formatDate(submission.submitted_at)}
            </div>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          {isPending && formUrl ? (
            <Button
              asChild
              className="rounded-full bg-[#2f4a3a] text-[#f6f1e6] hover:bg-[#263d30]"
              data-testid={`patient-form-open-${submission.id}`}
            >
              <Link to={formUrl}>
                <FileSignature size={15} className="mr-2" />
                Complete form
              </Link>
            </Button>
          ) : status === "submitted" ? (
            <Button
              type="button"
              variant="outline"
              className="rounded-full border-[#2f4a3a] text-[#2f4a3a]"
              onClick={() => onViewCompleted?.(submission)}
              data-testid={`patient-form-view-${submission.id}`}
            >
              View form
              <ChevronRight size={14} className="ml-1" />
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export default function PatientForms() {
  const { toast } = useToast();
  const [submissions, setSubmissions] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState("");
  const [completedViewer, setCompletedViewer] = React.useState(null);
  const [completedViewerLoading, setCompletedViewerLoading] =
    React.useState(false);

  const openCompletedSubmission = async (submission) => {
    if (!submission?.id) return;

    setCompletedViewerLoading(true);

    try {
      const response = await api.get(
        `/forms/submissions/${submission.id}`
      );

      setCompletedViewer(response.data);
    } catch (error) {
      const detail = error?.response?.data?.detail;

      toast({
        title: "Unable to open form",
        description:
          typeof detail === "string"
            ? detail
            : detail?.message ||
              "The completed form could not be loaded.",
        variant: "destructive",
      });
    } finally {
      setCompletedViewerLoading(false);
    }
  };

  const loadForms = React.useCallback(async () => {
    setLoading(true);
    setLoadError("");

    try {
      const response = await api.get("/forms/submissions");

      setSubmissions(
        normalizeArray(response.data, [
          "submissions",
          "forms",
          "items",
        ])
      );
    } catch (error) {
      const message =
        getErrorMessage(error) ||
        "Assigned forms could not be loaded.";

      setLoadError(message);

      toast({
        title: "Could not load forms",
        description: message,
      });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  React.useEffect(() => {
    loadForms();
  }, [loadForms]);

  const pending = normalizeArray(submissions).filter(
    (submission) =>
      !submission.status ||
      submission.status === "sent"
  );

  const completed = normalizeArray(submissions).filter(
    (submission) =>
      submission.status === "submitted"
  );

  const expired = normalizeArray(submissions).filter(
    (submission) =>
      submission.status === "expired"
  );



  return (
    <PortalLayout>
      <PortalHeader
        title="Forms & Consents"
        subtitle="Complete forms assigned by your care team and review prior submissions."
        actions={
          <Button
            type="button"
            variant="outline"
            onClick={loadForms}
            disabled={loading}
            className="rounded-full border-[#8a6a3c] text-[#8a6a3c]"
          >
            <RefreshCw
              size={15}
              className={`mr-2 ${
                loading ? "animate-spin" : ""
              }`}
            />
            Refresh
          </Button>
        }
      />

      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <StatCard
          label="Pending"
          value={pending.length}
          icon={Clock3}
          accent={
            pending.length
              ? "text-[#8a6a3c]"
              : ""
          }
        />

        <StatCard
          label="Completed"
          value={completed.length}
          icon={CheckCircle2}
        />

        <StatCard
          label="Expired"
          value={expired.length}
          icon={AlertTriangle}
          accent={
            expired.length
              ? "text-[#7a2a2a]"
              : ""
          }
        />
      </div>

      {loadError && (
        <div className="mb-6 rounded-2xl border border-[#e5c7c7] bg-[#fff5f5] p-5">
          <div className="flex items-start gap-3">
            <AlertTriangle
              size={19}
              className="mt-0.5 text-[#7a2a2a]"
            />

            <div>
              <div className="font-medium text-[#7a2a2a]">
                Forms could not be loaded
              </div>

              <div className="mt-1 text-sm text-[#6a6a6a]">
                {loadError}
              </div>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-10 text-center text-sm text-[#6a6a6a]">
          Loading assigned forms…
        </div>
      ) : submissions.length === 0 ? (
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-10 text-center">
          <ClipboardList
            size={34}
            className="mx-auto text-[#c19a4b]"
          />

          <div className="mt-4 font-display text-2xl text-[#1f2a22]">
            No assigned forms
          </div>

          <div className="mx-auto mt-2 max-w-md text-sm text-[#6a6a6a]">
            Forms assigned by your care team will appear here.
          </div>
        </div>
      ) : (
        <div className="space-y-8">
          <section>
            <div className="mb-3 flex items-center justify-between">
              <div>
                <div className="eyebrow text-[#8a6a3c]">
                  Action needed
                </div>

                <h2 className="font-display text-2xl text-[#1f2a22]">
                  Pending forms
                </h2>
              </div>

              <span className="text-sm text-[#6a6a6a]">
                {pending.length}
              </span>
            </div>

            {pending.length === 0 ? (
              <div className="rounded-2xl border border-[#cfe0d3] bg-[#eaf2ec] p-5 text-sm text-[#3d6b52]">
                You have no forms awaiting completion.
              </div>
            ) : (
              <div className="space-y-3">
                {pending.map((submission) => (
                  <FormCard
                    key={submission.id}
                    submission={submission}
                  onViewCompleted={openCompletedSubmission}
                  />
                ))}
              </div>
            )}
          </section>

          <section>
            <div className="mb-3 flex items-center justify-between">
              <div>
                <div className="eyebrow text-[#8a6a3c]">
                  History
                </div>

                <h2 className="font-display text-2xl text-[#1f2a22]">
                  Completed forms
                </h2>
              </div>

              <span className="text-sm text-[#6a6a6a]">
                {completed.length}
              </span>
            </div>

            {completed.length === 0 ? (
              <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5 text-sm text-[#6a6a6a]">
                No completed forms yet.
              </div>
            ) : (
              <div className="space-y-3">
                {completed.map((submission) => (
                  <FormCard
                    key={submission.id}
                    submission={submission}
                  onViewCompleted={openCompletedSubmission}
                  />
                ))}
              </div>
            )}
          </section>

          {expired.length > 0 && (
            <section>
              <div className="mb-3">
                <div className="eyebrow text-[#8a6a3c]">
                  Inactive
                </div>

                <h2 className="font-display text-2xl text-[#1f2a22]">
                  Expired forms
                </h2>
              </div>

              <div className="space-y-3">
                {expired.map(
                  (submission) => (
                    <FormCard
                      key={submission.id}
                      submission={submission}
                    onViewCompleted={openCompletedSubmission}
                  />
                  )
                )}
              </div>
            </section>
          )}
        </div>
      )}
    
      {completedViewer && (
        <div
          className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-label="Completed form"
        >
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-3xl max-h-[90vh] overflow-y-auto">
            <div className="sticky top-0 z-10 bg-white border-b border-[#e7dfc9] px-6 py-4 flex items-start justify-between gap-4">
              <div>
                <h2 className="text-xl font-semibold text-[#1f2a22]">
                  {completedViewer.template?.title ||
                    completedViewer.template_title ||
                    "Completed form"}
                </h2>

                <p className="text-sm text-[#6a6a6a] mt-1">
                  {completedViewer.submitted_at
                    ? `Completed ${new Date(
                        completedViewer.submitted_at
                      ).toLocaleString()}`
                    : "Completed form"}
                </p>
              </div>

              <Button
                type="button"
                variant="outline"
                onClick={() => setCompletedViewer(null)}
              >
                Close
              </Button>
            </div>

            <div className="p-6 space-y-5">
              {(completedViewer.template?.fields || []).map(
                (field) => {
                  if (field.type === "signature") {
                    const signature =
                      completedViewer.signature_data ||
                      completedViewer.answers?.[field.id];

                    return (
                      <div
                        key={field.id}
                        className="border-b border-[#eee7d6] pb-4"
                      >
                        <div className="text-sm font-medium text-[#1f2a22] mb-2">
                          {field.label || "Patient signature"}
                        </div>

                        {signature ? (
                          String(signature).startsWith(
                            "data:image"
                          ) ? (
                            <img
                              src={signature}
                              alt="Patient signature"
                              className="max-h-32 border rounded-lg bg-white"
                            />
                          ) : (
                            <div className="text-sm text-[#4f584f]">
                              Signature recorded
                            </div>
                          )
                        ) : (
                          <div className="text-sm text-[#6a6a6a]">
                            No signature recorded
                          </div>
                        )}
                      </div>
                    );
                  }

                  const value =
                    completedViewer.answers?.[field.id];

                  const displayValue = Array.isArray(value)
                    ? value.join(", ")
                    : typeof value === "boolean"
                    ? value
                      ? "Yes"
                      : "No"
                    : value === null ||
                      value === undefined ||
                      value === ""
                    ? "—"
                    : String(value);

                  return (
                    <div
                      key={field.id}
                      className="border-b border-[#eee7d6] pb-4"
                    >
                      <div className="text-sm font-medium text-[#1f2a22]">
                        {field.label || field.id}
                      </div>

                      <div className="mt-1 text-sm text-[#4f584f] whitespace-pre-wrap">
                        {displayValue}
                      </div>
                    </div>
                  );
                }
              )}

              {(!completedViewer.template?.fields ||
                completedViewer.template.fields.length === 0) &&
                Object.entries(
                  completedViewer.answers || {}
                ).map(([key, value]) => (
                  <div
                    key={key}
                    className="border-b border-[#eee7d6] pb-4"
                  >
                    <div className="text-sm font-medium text-[#1f2a22]">
                      {key}
                    </div>

                    <div className="mt-1 text-sm text-[#4f584f] whitespace-pre-wrap">
                      {Array.isArray(value)
                        ? value.join(", ")
                        : typeof value === "boolean"
                        ? value
                          ? "Yes"
                          : "No"
                        : value === null ||
                          value === undefined ||
                          value === ""
                        ? "—"
                        : String(value)}
                    </div>
                  </div>
                ))}
            </div>
          </div>
        </div>
      )}

      {completedViewerLoading && (
        <div className="fixed inset-0 z-[60] bg-black/20 flex items-center justify-center">
          <div className="bg-white rounded-xl px-5 py-3 shadow-lg text-sm text-[#1f2a22]">
            Loading completed form…
          </div>
        </div>
      )}

</PortalLayout>
  );
}
