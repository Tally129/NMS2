import React from "react";
import PortalLayout, {
  PortalHeader,
} from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { useToast } from "../../hooks/use-toast";
import {
  AlertCircle,
  CheckCircle2,
  FileSpreadsheet,
  Loader2,
  RotateCcw,
  Upload,
} from "lucide-react";
import { getErrorMessage } from "../../lib/errors";

export default function ImportClients() {
  const { toast } = useToast();

  const [file, setFile] = React.useState(null);
  const [preview, setPreview] = React.useState(null);
  const [result, setResult] = React.useState(null);
  const [previewing, setPreviewing] =
    React.useState(false);
  const [submitting, setSubmitting] =
    React.useState(false);

  const reset = () => {
    setFile(null);
    setPreview(null);
    setResult(null);
  };

  const previewFile = async (selectedFile) => {
    setFile(selectedFile);
    setPreview(null);
    setResult(null);

    if (!selectedFile) return;

    setPreviewing(true);

    try {
      const formData = new FormData();
      formData.append("file", selectedFile);

      const response = await api.post(
        "/clients/import/preview",
        formData
      );

      setPreview(response.data);
    } catch (error) {
      toast({
        title: "Could not preview CSV",
        description:
          getErrorMessage(error) ||
          "Verify the file format and headers.",
        variant: "destructive",
      });
    } finally {
      setPreviewing(false);
    }
  };

  const importPatients = async () => {
    if (!file || !preview?.can_import) return;

    const confirmed = window.confirm(
      `Import ${preview.valid_rows} valid patient record${
        preview.valid_rows === 1 ? "" : "s"
      }?`
    );

    if (!confirmed) return;

    setSubmitting(true);

    try {
      const formData = new FormData();
      formData.append("file", file);

      const response = await api.post(
        "/clients/import",
        formData
      );

      setResult(response.data);

      toast({
        title: "Patient import complete",
        description:
          `${response.data.imported} imported · ` +
          `${response.data.skipped} skipped`,
      });
    } catch (error) {
      toast({
        title: "Import failed",
        description:
          getErrorMessage(error) ||
          "The patients could not be imported.",
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
    }
  };

  const mappings = Object.entries(
    preview?.recognized_headers || {}
  );

  return (
    <PortalLayout>
      <PortalHeader
        title="Import Patients"
        subtitle="Preview, validate, and import patients from CSV"
        actions={
          (file || result) && (
            <Button
              type="button"
              variant="outline"
              onClick={reset}
              className="rounded-full"
            >
              <RotateCcw size={14} className="mr-2" />
              Start over
            </Button>
          )
        }
      />

      <div className="mb-6 rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-6">
        <div className="eyebrow mb-3 text-[#8a6a3c]">
          Patient Importer
        </div>

        <div className="grid gap-3 text-sm text-[#3a3a3a] md:grid-cols-3">
          <div>
            <strong>1. Select CSV</strong>
            <div className="mt-1 text-xs text-[#6a6a6a]">
              Upload a UTF-8 CSV with a header row.
            </div>
          </div>

          <div>
            <strong>2. Review validation</strong>
            <div className="mt-1 text-xs text-[#6a6a6a]">
              Confirm mappings, duplicates, and errors.
            </div>
          </div>

          <div>
            <strong>3. Confirm import</strong>
            <div className="mt-1 text-xs text-[#6a6a6a]">
              Only valid rows will be created.
            </div>
          </div>
        </div>
      </div>

      <div
        className="mb-6 rounded-2xl border-2 border-dashed border-[#c19a4b] bg-[#fbf7ee] p-8 text-center"
        data-testid="import-dropzone"
      >
        <FileSpreadsheet
          size={38}
          className="mx-auto mb-3 text-[#8a6a3c]"
        />

        <input
          type="file"
          accept=".csv,text/csv"
          onChange={(event) =>
            previewFile(
              event.target.files?.[0] || null
            )
          }
          className="block mx-auto text-sm"
          data-testid="import-file-input"
        />

        {file && (
          <div className="mt-3 text-sm text-[#3a3a3a]">
            Selected: <strong>{file.name}</strong>{" "}
            ({Math.round(file.size / 1024)} KB)
          </div>
        )}

        {previewing && (
          <div className="mt-4 text-sm text-[#6a6a6a]">
            <Loader2
              size={15}
              className="mr-2 inline animate-spin"
            />
            Reading and validating patient records…
          </div>
        )}
      </div>

      {preview && !result && (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-3">
            <SummaryCard
              label="Rows detected"
              value={preview.total_rows}
            />

            <SummaryCard
              label="Ready to import"
              value={preview.valid_rows}
              positive
            />

            <SummaryCard
              label="Will be skipped"
              value={preview.skipped_rows}
              warning={preview.skipped_rows > 0}
            />
          </div>

          <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5">
            <div className="eyebrow mb-3 text-[#8a6a3c]">
              Recognized column mappings
            </div>

            <div className="flex flex-wrap gap-2">
              {mappings.map(([source, target]) => (
                <div
                  key={source}
                  className="rounded-full bg-[#e7efe9] px-3 py-1 text-xs text-[#2f4a3a]"
                >
                  {source} → <strong>{target}</strong>
                </div>
              ))}
            </div>

            {preview.unrecognized_headers?.length >
              0 && (
              <div className="mt-4">
                <div className="text-xs font-medium text-[#8a6a3c]">
                  Ignored columns
                </div>

                <div className="mt-2 flex flex-wrap gap-2">
                  {preview.unrecognized_headers.map(
                    (header) => (
                      <code
                        key={header}
                        className="rounded bg-[#f1ead8] px-2 py-1 text-xs text-[#6a6a6a]"
                      >
                        {header}
                      </code>
                    )
                  )}
                </div>
              </div>
            )}
          </div>

          {preview.sample?.length > 0 && (
            <div className="overflow-auto rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5">
              <div className="eyebrow mb-3 text-[#8a6a3c]">
                Valid patient preview
              </div>

              <table className="w-full min-w-[700px] text-xs">
                <thead className="bg-[#f1ead8] text-[#8a6a3c]">
                  <tr>
                    <th className="px-3 py-2 text-left">
                      Row
                    </th>
                    <th className="px-3 py-2 text-left">
                      Name
                    </th>
                    <th className="px-3 py-2 text-left">
                      Email
                    </th>
                    <th className="px-3 py-2 text-left">
                      Phone
                    </th>
                    <th className="px-3 py-2 text-left">
                      DOB
                    </th>
                    <th className="px-3 py-2 text-left">
                      Primary concern
                    </th>
                  </tr>
                </thead>

                <tbody>
                  {preview.sample.map((row) => (
                    <tr
                      key={row.row}
                      className="border-t border-[#e7dfc9]"
                    >
                      <td className="px-3 py-2">
                        {row.row}
                      </td>
                      <td className="px-3 py-2">
                        {row.full_name || "—"}
                      </td>
                      <td className="px-3 py-2">
                        {row.email || "—"}
                      </td>
                      <td className="px-3 py-2">
                        {row.phone || "—"}
                      </td>
                      <td className="px-3 py-2">
                        {row.dob || "—"}
                      </td>
                      <td className="px-3 py-2">
                        {row.primary_concern || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {preview.issues?.length > 0 && (
            <div className="rounded-2xl border border-[#d9a6a6] bg-[#fff4f4] p-5">
              <div className="flex items-center gap-2 font-semibold text-[#7a2a2a]">
                <AlertCircle size={17} />
                Rows that will be skipped
              </div>

              <div className="mt-3 max-h-72 space-y-3 overflow-y-auto">
                {preview.issues.map((issue) => (
                  <div
                    key={`${issue.row}-${issue.email}`}
                    className="rounded-xl border border-[#eacaca] bg-white p-3 text-xs"
                  >
                    <div className="font-medium text-[#5e1f1f]">
                      Row {issue.row}
                      {issue.name
                        ? ` — ${issue.name}`
                        : ""}
                    </div>

                    <ul className="mt-1 list-disc pl-5 text-[#7a2a2a]">
                      {issue.reasons.map((reason) => (
                        <li key={reason}>{reason}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              onClick={importPatients}
              disabled={
                submitting || !preview.can_import
              }
              className="h-11 rounded-full bg-[#2f4a3a] text-[#f6f1e6] hover:bg-[#263d30]"
              data-testid="import-upload-btn"
            >
              {submitting ? (
                <>
                  <Loader2
                    size={16}
                    className="mr-2 animate-spin"
                  />
                  Importing…
                </>
              ) : (
                <>
                  <Upload size={16} className="mr-2" />
                  Import {preview.valid_rows} patient
                  {preview.valid_rows === 1 ? "" : "s"}
                </>
              )}
            </Button>

            {!preview.can_import && (
              <div className="text-sm text-[#7a2a2a]">
                No valid patient records are available
                to import.
              </div>
            )}
          </div>
        </div>
      )}

      {result && (
        <div
          className="rounded-2xl border border-[#b8cfbd] bg-[#f0f7f1] p-6"
          data-testid="import-result"
        >
          <div className="flex items-center gap-2 text-lg font-semibold text-[#2f4a3a]">
            <CheckCircle2 size={21} />
            Import complete
          </div>

          <div className="mt-5 grid gap-4 sm:grid-cols-3">
            <SummaryCard
              label="Imported"
              value={result.imported}
              positive
            />

            <SummaryCard
              label="Skipped"
              value={result.skipped}
              warning={result.skipped > 0}
            />

            <SummaryCard
              label="Total processed"
              value={result.total_rows}
            />
          </div>

          {result.errors?.length > 0 && (
            <div className="mt-5">
              <div className="font-medium text-[#7a2a2a]">
                Import details
              </div>

              <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-[#5e1f1f]">
                {result.errors.map((error, index) => (
                  <li key={index}>
                    Row {error.row}: {error.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="mt-6 flex flex-wrap gap-3">
            <Button
              type="button"
              onClick={reset}
              className="rounded-full bg-[#2f4a3a] text-[#f6f1e6]"
            >
              Import another file
            </Button>

            <a href="/portal/provider/patients">
              <Button
                type="button"
                variant="outline"
                className="rounded-full border-[#2f4a3a] text-[#2f4a3a]"
              >
                View patients
              </Button>
            </a>
          </div>
        </div>
      )}
    </PortalLayout>
  );
}

function SummaryCard({
  label,
  value,
  positive = false,
  warning = false,
}) {
  return (
    <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5">
      <div className="text-xs uppercase tracking-widest text-[#8a6a3c]">
        {label}
      </div>

      <div
        className={`mt-2 font-display text-3xl ${
          warning
            ? "text-[#8b2f2f]"
            : positive
              ? "text-[#2f4a3a]"
              : "text-[#1f2a22]"
        }`}
      >
        {value}
      </div>
    </div>
  );
}
