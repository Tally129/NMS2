import React from "react";
import { Link, useNavigate } from "react-router-dom";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Input } from "../../components/ui/input";
import { Button } from "../../components/ui/button";
import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Circle,
  Download,
  Loader2,
  Mail,
  Search,
  UserPlus,
  X,
} from "lucide-react";
import { useToast } from "../../hooks/use-toast";
import AddPatientWizard from "../../components/AddPatientWizard";
import { getErrorMessage } from "../../lib/errors";

const STORAGE_KEY = "nms-patient-list-settings";
const PAGE_SIZE_OPTIONS = [25, 50, 100, 200];

function readSavedSettings() {
  try {
    const saved = JSON.parse(
      window.localStorage.getItem(STORAGE_KEY) || "{}"
    );

    return {
      q: typeof saved.q === "string" ? saved.q : "",
      page: Number(saved.page) >= 1 ? Number(saved.page) : 1,
      pageSize: PAGE_SIZE_OPTIONS.includes(Number(saved.pageSize))
        ? Number(saved.pageSize)
        : 50,
      sortBy: [
        "created_at",
        "full_name",
        "mrn",
        "dob",
      ].includes(saved.sortBy)
        ? saved.sortBy
        : "created_at",
      sortDir: saved.sortDir === "asc" ? "asc" : "desc",
    };
  } catch {
    return {
      q: "",
      page: 1,
      pageSize: 50,
      sortBy: "created_at",
      sortDir: "desc",
    };
  }
}

export default function PatientsList() {
  const { toast } = useToast();
  const navigate = useNavigate();
  const initial = React.useMemo(readSavedSettings, []);

  const [patients, setPatients] = React.useState([]);
  const [q, setQ] = React.useState(initial.q);
  const [debouncedQ, setDebouncedQ] = React.useState(
    initial.q.trim()
  );
  const [page, setPage] = React.useState(initial.page);
  const [pageSize, setPageSize] = React.useState(
    initial.pageSize
  );
  const [sortBy, setSortBy] = React.useState(initial.sortBy);
  const [sortDir, setSortDir] = React.useState(
    initial.sortDir
  );
  const [total, setTotal] = React.useState(0);
  const [pages, setPages] = React.useState(0);
  const [loading, setLoading] = React.useState(true);
  const [showWizard, setShowWizard] =
    React.useState(false);

  // Map preserves the patient data for selections made across pages.
  const [selectedPatients, setSelectedPatients] =
    React.useState({});

  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedQ(q.trim());
      setPage(1);
    }, 300);

    return () => window.clearTimeout(timer);
  }, [q]);

  React.useEffect(() => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        q,
        page,
        pageSize,
        sortBy,
        sortDir,
      })
    );
  }, [q, page, pageSize, sortBy, sortDir]);

  const load = React.useCallback(async () => {
    setLoading(true);

    try {
      const response = await api.get("/clients", {
        params: {
          page,
          page_size: pageSize,
          q: debouncedQ || undefined,
          sort_by: sortBy,
          sort_dir: sortDir,
        },
      });

      const data = response.data || {};

      setPatients(
        Array.isArray(data.items) ? data.items : []
      );
      setTotal(Number(data.total || 0));
      setPages(Number(data.pages || 0));

      if (
        data.pages > 0 &&
        page > data.pages
      ) {
        setPage(data.pages);
      }
    } catch (error) {
      setPatients([]);
      setTotal(0);
      setPages(0);

      toast({
        title: "Could not load patients",
        description:
          getErrorMessage(error) ||
          "Please refresh and try again.",
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  }, [
    page,
    pageSize,
    debouncedQ,
    sortBy,
    sortDir,
    toast,
  ]);

  React.useEffect(() => {
    load();
  }, [load]);

  const updateSort = (field) => {
    if (sortBy === field) {
      setSortDir((current) =>
        current === "asc" ? "desc" : "asc"
      );
    } else {
      setSortBy(field);
      setSortDir(
        field === "created_at" ? "desc" : "asc"
      );
    }

    setPage(1);
  };

  const sortIndicator = (field) => {
    if (sortBy !== field) return "";
    return sortDir === "asc" ? " ▲" : " ▼";
  };

  const firstRow =
    total === 0 ? 0 : (page - 1) * pageSize + 1;

  const lastRow = Math.min(page * pageSize, total);

  const selectedIds = React.useMemo(
    () => Object.keys(selectedPatients),
    [selectedPatients]
  );

  const selectedCount = selectedIds.length;

  const currentPageIds = patients.map(
    (patient) => patient.id
  );

  const allCurrentPageSelected =
    currentPageIds.length > 0 &&
    currentPageIds.every(
      (id) => Boolean(selectedPatients[id])
    );

  const someCurrentPageSelected =
    currentPageIds.some(
      (id) => Boolean(selectedPatients[id])
    );

  const togglePatient = (patient) => {
    setSelectedPatients((current) => {
      const next = { ...current };

      if (next[patient.id]) {
        delete next[patient.id];
      } else {
        next[patient.id] = patient;
      }

      return next;
    });
  };

  const toggleCurrentPage = () => {
    setSelectedPatients((current) => {
      const next = { ...current };

      if (allCurrentPageSelected) {
        patients.forEach((patient) => {
          delete next[patient.id];
        });
      } else {
        patients.forEach((patient) => {
          next[patient.id] = patient;
        });
      }

      return next;
    });
  };

  const clearSelection = () => {
    setSelectedPatients({});
  };

  const csvEscape = (value) => {
    const normalized = String(value ?? "");

    return `"${normalized.replace(/"/g, '""')}"`;
  };

  const exportSelectedCsv = () => {
    const selected = Object.values(selectedPatients);

    if (!selected.length) return;

    const headers = [
      "MRN",
      "Full Name",
      "DOB",
      "Email",
      "Phone",
      "Intake Completed",
    ];

    const rows = selected.map((patient) => [
      patient.mrn || "",
      patient.full_name || "",
      patient.dob || "",
      patient.email || "",
      patient.phone || "",
      patient.intake_completed ? "Yes" : "No",
    ]);

    const csv = [
      headers.map(csvEscape).join(","),
      ...rows.map((row) =>
        row.map(csvEscape).join(",")
      ),
    ].join("\r\n");

    const blob = new Blob(
      ["\ufeff" + csv],
      { type: "text/csv;charset=utf-8" }
    );

    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");

    anchor.href = url;
    anchor.download =
      `selected-patients-${new Date()
        .toISOString()
        .slice(0, 10)}.csv`;

    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);

    toast({
      title: "Patient export created",
      description:
        `${selected.length} selected patient` +
        `${selected.length === 1 ? "" : "s"} exported.`,
    });
  };

  const openEmailCampaign = () => {
    if (!selectedCount) return;

    const payload = {
      client_ids: selectedIds,
      recipients: Object.values(
        selectedPatients
      ).map((patient) => ({
        id: patient.id,
        full_name: patient.full_name || "",
        email: patient.email || "",
        mrn: patient.mrn || "",
      })),
      created_at: new Date().toISOString(),
    };

    window.localStorage.setItem(
      "nms-campaign-custom-list",
      JSON.stringify(payload)
    );

    navigate(
      "/portal/campaigns?source=patient-selection"
    );
  };

  return (
    <PortalLayout>
      <PortalHeader
        title="Patients"
        subtitle={`${total.toLocaleString()} total`}
        actions={
          <Button
            onClick={() => setShowWizard(true)}
            className="btn-lift h-11 rounded-full bg-[#2f4a3a] text-[#f6f1e6] hover:bg-[#263d30]"
            data-testid="patients-add-btn"
          >
            <UserPlus size={16} className="mr-2" />
            Add patient
          </Button>
        }
      />

      <AddPatientWizard
        open={showWizard}
        onOpenChange={setShowWizard}
        onCreated={() => {
          setPage(1);
          load();
        }}
      />

      {selectedCount > 0 && (
        <div
          className="mb-4 rounded-2xl border border-[#c19a4b] bg-[#f7f1e4] p-4"
          data-testid="patients-bulk-toolbar"
        >
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="font-semibold text-[#1f2a22]">
                {selectedCount.toLocaleString()} patient
                {selectedCount === 1 ? "" : "s"} selected
              </div>

              <div className="mt-1 text-xs text-[#6a6a6a]">
                Selection is preserved while moving between pages.
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={exportSelectedCsv}
                className="rounded-full border-[#2f4a3a] text-[#2f4a3a]"
              >
                <Download size={14} className="mr-2" />
                Export CSV
              </Button>

              <Button
                type="button"
                onClick={openEmailCampaign}
                className="rounded-full bg-[#2f4a3a] text-[#f6f1e6] hover:bg-[#263d30]"
              >
                <Mail size={14} className="mr-2" />
                Email campaign
              </Button>

              <Button
                type="button"
                variant="ghost"
                onClick={clearSelection}
                className="rounded-full text-[#6a6a6a]"
              >
                <X size={14} className="mr-2" />
                Clear
              </Button>
            </div>
          </div>
        </div>
      )}

      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="relative w-full max-w-md">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8a6a3c]"
          />

          <Input
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder="Search by name, email, phone, or MRN…"
            className="border-[#e0d6bc] bg-[#fbf7ee] pl-9"
          />

          {loading && (
            <Loader2
              size={14}
              className="absolute right-3 top-1/2 -translate-y-1/2 animate-spin text-[#8a6a3c]"
            />
          )}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <label className="text-sm text-[#6a6a6a]">
            Show{" "}
            <select
              value={pageSize}
              onChange={(event) => {
                setPageSize(Number(event.target.value));
                setPage(1);
              }}
              className="rounded-lg border border-[#e0d6bc] bg-[#fbf7ee] px-2 py-1.5 text-[#1f2a22]"
            >
              {PAGE_SIZE_OPTIONS.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>

          <div className="text-sm text-[#6a6a6a]">
            {total > 0
              ? `Showing ${firstRow.toLocaleString()}–${lastRow.toLocaleString()} of ${total.toLocaleString()}`
              : "No matching patients"}
          </div>
        </div>
      </div>

      <div className="overflow-x-auto rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee]">
        <table className="w-full min-w-[900px] text-sm">
          <thead className="bg-[#f1ead8] text-[11px] uppercase tracking-widest text-[#8a6a3c]">
            <tr>
              <th className="w-12 px-4 py-3 text-left">
                <input
                  type="checkbox"
                  checked={allCurrentPageSelected}
                  ref={(element) => {
                    if (element) {
                      element.indeterminate =
                        someCurrentPageSelected &&
                        !allCurrentPageSelected;
                    }
                  }}
                  onChange={toggleCurrentPage}
                  aria-label="Select current page"
                  data-testid="patients-select-page"
                />
              </th>

              <SortableHeader
                label="MRN"
                active={sortBy === "mrn"}
                onClick={() => updateSort("mrn")}
                indicator={sortIndicator("mrn")}
              />
              <SortableHeader
                label="Name"
                active={sortBy === "full_name"}
                onClick={() => updateSort("full_name")}
                indicator={sortIndicator("full_name")}
              />
              <SortableHeader
                label="DOB"
                active={sortBy === "dob"}
                onClick={() => updateSort("dob")}
                indicator={sortIndicator("dob")}
              />
              <th className="px-4 py-3 text-left">
                Email
              </th>
              <th className="px-4 py-3 text-left">
                Phone
              </th>
              <th className="px-4 py-3 text-left">
                Intake
              </th>
              <th className="px-4 py-3 text-right">
                Action
              </th>
            </tr>
          </thead>

          <tbody>
            {!loading && patients.length === 0 && (
              <tr>
                <td
                  colSpan={8}
                  className="py-10 text-center text-[#6a6a6a]"
                >
                  {debouncedQ
                    ? `No patients found for “${debouncedQ}”.`
                    : "No patients found."}
                </td>
              </tr>
            )}

            {loading && patients.length === 0 && (
              <tr>
                <td
                  colSpan={8}
                  className="py-10 text-center text-[#6a6a6a]"
                >
                  <Loader2
                    size={16}
                    className="mr-2 inline animate-spin"
                  />
                  Loading patients…
                </td>
              </tr>
            )}

            {patients.map((patient) => (
              <tr
                key={patient.id}
                className="border-t border-[#e7dfc9] hover:bg-[#f1ead8]/60"
              >
                <td className="w-12 px-4 py-3">
                  <input
                    type="checkbox"
                    checked={Boolean(
                      selectedPatients[patient.id]
                    )}
                    onChange={() =>
                      togglePatient(patient)
                    }
                    aria-label={`Select ${
                      patient.full_name ||
                      patient.email ||
                      "patient"
                    }`}
                    data-testid={`patient-select-${patient.id}`}
                  />
                </td>

                <td className="px-4 py-3 font-mono text-xs text-[#8a6a3c]">
                  {patient.mrn ||
                    patient.id?.slice(0, 8).toUpperCase() ||
                    "—"}
                </td>

                <td className="px-4 py-3 font-medium text-[#1f2a22]">
                  {patient.full_name || "—"}
                </td>

                <td className="px-4 py-3 text-xs text-[#6a6a6a]">
                  {patient.dob || "—"}
                </td>

                <td className="px-4 py-3 text-[#3a3a3a]">
                  {patient.email || "—"}
                </td>

                <td className="px-4 py-3 text-[#3a3a3a]">
                  {patient.phone || "—"}
                </td>

                <td className="px-4 py-3">
                  {patient.intake_completed ? (
                    <span className="inline-flex items-center gap-1 text-xs text-[#2f4a3a]">
                      <CheckCircle2 size={14} />
                      Complete
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-xs text-[#8a6a3c]">
                      <Circle size={14} />
                      Pending
                    </span>
                  )}
                </td>

                <td className="px-4 py-3 text-right">
                  <Link
                    to={`/portal/provider/patients/${patient.id}`}
                    className="text-sm text-[#2f4a3a] hover:underline"
                  >
                    Open chart
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <button
          type="button"
          onClick={() => updateSort("created_at")}
          className="text-left text-sm text-[#6a6a6a] hover:text-[#2f4a3a]"
        >
          Page {pages === 0 ? 0 : page} of {pages}
          {sortBy === "created_at"
            ? ` · ${sortDir === "desc" ? "Newest first" : "Oldest first"}`
            : ""}
        </button>

        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() =>
              setPage((current) =>
                Math.max(1, current - 1)
              )
            }
            disabled={loading || page <= 1}
            className="rounded-full border-[#2f4a3a] text-[#2f4a3a]"
          >
            <ChevronLeft size={15} className="mr-1" />
            Previous
          </Button>

          <Button
            type="button"
            variant="outline"
            onClick={() =>
              setPage((current) =>
                Math.min(pages || 1, current + 1)
              )
            }
            disabled={
              loading || pages === 0 || page >= pages
            }
            className="rounded-full border-[#2f4a3a] text-[#2f4a3a]"
          >
            Next
            <ChevronRight size={15} className="ml-1" />
          </Button>
        </div>
      </div>
    </PortalLayout>
  );
}

function SortableHeader({
  label,
  onClick,
  indicator,
  active,
}) {
  return (
    <th className="px-4 py-3 text-left">
      <button
        type="button"
        onClick={onClick}
        className={
          active
            ? "font-bold text-[#2f4a3a]"
            : "hover:text-[#2f4a3a]"
        }
      >
        {label}
        {indicator}
      </button>
    </th>
  );
}
