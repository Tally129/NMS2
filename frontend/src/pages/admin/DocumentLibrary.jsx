import React from "react";
import { useNavigate } from "react-router-dom";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Label } from "../../components/ui/label";
import { Input } from "../../components/ui/input";
import { Textarea } from "../../components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../../components/ui/dialog";
import { useToast } from "../../hooks/use-toast";
import { useAuth } from "../../lib/auth";
import { getErrorMessage } from "../../lib/errors";
import {
  FileUp, Sparkles, FileText, Activity, ClipboardList, Pill,
  Loader2, ArrowRight, CheckCircle2, AlertCircle, Trash2,
} from "lucide-react";
import { normalizeArray } from "../../lib/collections";

const TYPE_META = {
  form:       { label: "Form / Consent", color: "#c19a4b", icon: ClipboardList, dest: "/portal/admin/forms" },
  protocol:   { label: "Protocol",       color: "#5b6f5b", icon: Activity,      dest: "/portal/admin/protocols" },
  soap:       { label: "SOAP Template",  color: "#2f4a3a", icon: FileText,      dest: "/portal/admin/soap" },
  supplement: { label: "Supplement Sheet",color: "#8a6a3c", icon: Pill,          dest: null /* lives in library */ },
  other:      { label: "Other",          color: "#6a6a6a", icon: FileText,      dest: null },
};

/**
 * Universal AI ingest — drop ANY clinical PDF/DOCX/TXT and the AI auto-classifies
 * it into form / protocol / SOAP template / supplement directions, then runs the
 * matching transcription path. The user can review the draft and route it to the
 * right destination.
 */
export default function DocumentLibrary() {
  const { user } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [file, setFile] = React.useState(null);
  const [analyzing, setAnalyzing] = React.useState(false);
  const [result, setResult] = React.useState(null);
  const [supplements, setSupplements] = React.useState([]);
  const [forms, setForms] = React.useState([]);
  const [protocols, setProtocols] = React.useState([]);
  const [soapTemplates, setSoapTemplates] = React.useState([]);
  const [librarySearch, setLibrarySearch] = React.useState("");
  const [libraryType, setLibraryType] = React.useState("all");
  const [savingSupp, setSavingSupp] = React.useState(false);

  const loadSupplements = async () => {
    try { const r = await api.get("/library/supplements"); setSupplements(normalizeArray(r.data, ["supplements"])); } catch {}
  };
  const loadLibrary = async () => {
    const results = await Promise.allSettled([
      api.get("/forms/templates"),
      api.get("/protocols/templates"),
      api.get("/soap-templates"),
      api.get("/library/supplements"),
    ]);

    const [formsR, protocolsR, soapR, supplementsR] = results;

    if (formsR.status === "fulfilled") {
      setForms(normalizeArray(formsR.value.data, ["templates", "forms"]));
    }

    if (protocolsR.status === "fulfilled") {
      setProtocols(normalizeArray(protocolsR.value.data, ["templates", "protocols"]));
    }

    if (soapR.status === "fulfilled") {
      setSoapTemplates(normalizeArray(soapR.value.data, ["templates"]));
    }

    if (supplementsR.status === "fulfilled") {
      setSupplements(normalizeArray(supplementsR.value.data, ["supplements"]));
    }
  };

  React.useEffect(() => { loadLibrary(); }, []);

  const libraryItems = React.useMemo(() => {
    const items = [
      ...normalizeArray(forms).map((item) => ({
        ...item,
        library_type: "form",
      })),
      ...normalizeArray(protocols).map((item) => ({
        ...item,
        library_type: "protocol",
      })),
      ...normalizeArray(soapTemplates).map((item) => ({
        ...item,
        library_type: "soap",
      })),
      ...normalizeArray(supplements).map((item) => ({
        ...item,
        library_type: "supplement",
      })),
    ];

    const q = librarySearch.trim().toLowerCase();

    return items.filter((item) => {
      if (
        libraryType !== "all" &&
        item.library_type !== libraryType
      ) {
        return false;
      }

      if (!q) return true;

      return [
        item.title,
        item.description,
        item.summary,
        item.category,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(q);
    });
  }, [
    forms,
    protocols,
    soapTemplates,
    supplements,
    librarySearch,
    libraryType,
  ]);

  const onPick = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setFile(f);
    setResult(null);
  };

  const analyze = async () => {
    if (!file) return;
    setAnalyzing(true);
    setResult(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await api.post("/library/classify", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setResult(r.data);
      const t = r.data?.classification?.type;
      toast({
        title: t === "other" ? "Couldn't classify" : `Detected: ${TYPE_META[t]?.label || t}`,
        description: r.data?.classification?.reasoning || "",
      });
    } catch (e) {
      toast({ title: "Analysis failed", description: getErrorMessage(e) || "Try a smaller PDF/DOCX." });
    } finally { setAnalyzing(false); }
  };

  const route = async () => {
    if (!result) return;
    const t = result.classification.type;
    const draft = result.draft || {};
    try {
      if (t === "form") {
        const body = {
          title: draft.title || "Imported form",
          description: draft.description || "",
          category: draft.category || "other",
          fields: draft.fields || [],
          active: true,
        };
        const r = await api.post("/forms/templates", body);
        toast({ title: "Form template saved", description: `${(r.data.fields || []).length} fields imported.` });
        navigate("/portal/admin/forms");
      } else if (t === "protocol") {
        const body = {
          title: draft.title || "Imported protocol",
          description: draft.description || "",
          weeks: draft.weeks || 4,
          sessions_per_week: draft.sessions_per_week || 1,
          daily_outline: draft.daily_outline || "",
          foods_recommended: draft.foods_recommended || [],
          foods_avoid: draft.foods_avoid || [],
          supplements: draft.supplements || [],
          lifestyle: draft.lifestyle || "",
          treatment_label: draft.treatment_label || "Treatment session",
          active: true,
        };
        await api.post("/protocols/templates", body);
        toast({ title: "Protocol template saved" });
        navigate("/portal/admin/protocols");
      } else if (t === "soap") {
        const body = {
          title: draft.title || "Imported SOAP template",
          description: draft.description || "",
          subjective: draft.subjective || "",
          objective: draft.objective || "",
          assessment: draft.assessment || "",
          plan: draft.plan || "",
          visit_type: draft.visit_type || null,
          active: true,
        };
        await api.post("/soap-templates", body);
        toast({ title: "SOAP template saved" });
        navigate("/portal/admin/soap");
      } else if (t === "supplement") {
        setSavingSupp(true);
        try {
          await api.post("/library/supplements", {
            title: draft.title || "Imported supplement directions",
            summary: draft.summary || "",
            items: draft.items || [],
          });
          toast({ title: "Supplement sheet saved" });
          setResult(null); setFile(null);
          loadSupplements();
        } finally { setSavingSupp(false); }
      } else {
        toast({ title: "Document saved as note", description: "Couldn't classify cleanly — review the raw text." });
      }
    } catch (e) {
      toast({ title: "Save failed", description: getErrorMessage(e) || "" });
    }
  };

  const removeSupp = async (id) => {
    if (!window.confirm("Delete this supplement sheet?")) return;
    try { await api.delete(`/library/supplements/${id}`); loadSupplements(); }
    catch (e) { toast({ title: "Failed", description: getErrorMessage(e) || "" }); }
  };

  return (
    <PortalLayout>
      <PortalHeader
        title="Document Library"
        subtitle="Drop any clinical PDF, DOCX, or TXT — AI classifies and routes it to the right place."
      />

      {/* Drop zone */}
      <div className="rounded-2xl border-2 border-dashed border-[#c19a4b] bg-[#fbf7ee] p-8 text-center" data-testid="library-drop-zone">
        <FileUp size={32} className="mx-auto text-[#c19a4b] mb-3" />
        <h3 className="font-display text-xl text-[#1f2a22]">Upload a document</h3>
        <p className="text-sm text-[#6a6a6a] mt-1 max-w-md mx-auto">
          Forms, consents, detox protocols, SOAP templates, supplement directions — Claude 4.5 will figure out what it is.
        </p>
        <div className="mt-5 flex flex-col sm:flex-row items-center justify-center gap-3">
          <input
            type="file"
            accept=".pdf,.docx,.txt"
            onChange={onPick}
            className="text-sm file:mr-3 file:rounded-full file:border-0 file:bg-[#2f4a3a] file:text-[#f6f1e6] file:px-4 file:py-2 file:cursor-pointer"
            data-testid="library-file-input"
          />
          <Button
            onClick={analyze}
            disabled={!file || analyzing}
            className="rounded-full bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22] h-10 px-6"
            data-testid="library-analyze-btn"
          >
            {analyzing ? <Loader2 size={14} className="mr-2 animate-spin" /> : <Sparkles size={14} className="mr-2" />}
            {analyzing ? "Analyzing…" : "Analyze with AI"}
          </Button>
        </div>
        {file && !analyzing && !result && (
          <div className="mt-3 text-xs text-[#6a6a6a]">{file.name} · {(file.size / 1024).toFixed(1)} KB</div>
        )}
      </div>

      {/* Result */}
      {result && (
        <div className="mt-6" data-testid="library-result">
          <ClassificationCard result={result} onRoute={route} savingSupp={savingSupp} />
        </div>
      )}

      {/* Unified document library */}
      <div className="mt-10" data-testid="unified-document-library">
        <div className="flex flex-col gap-4">
          <div>
            <h2 className="font-display text-2xl text-[#1f2a22]">
              Clinical document library
            </h2>
            <p className="mt-1 text-sm text-[#6a6a6a]">
              Browse forms, consents, protocols, SOAP templates, and supplement directions.
            </p>
          </div>

          <Input
            value={librarySearch}
            onChange={(e) => setLibrarySearch(e.target.value)}
            placeholder="Search documents..."
            className="max-w-xl bg-[#fbf7ee] border-[#e0d6bc]"
            data-testid="library-search"
          />

          <div className="flex flex-wrap gap-2">
            {[
              ["all", "All"],
              ["form", "Forms & Consents"],
              ["protocol", "Protocols"],
              ["soap", "SOAP Templates"],
              ["supplement", "Supplements"],
            ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setLibraryType(value)}
                className={`rounded-full border px-4 py-2 text-xs uppercase tracking-wide ${
                  libraryType === value
                    ? "bg-[#2f4a3a] border-[#2f4a3a] text-[#f6f1e6]"
                    : "bg-[#fbf7ee] border-[#e0d6bc] text-[#3a3a3a]"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-5">
          {libraryItems.length === 0 ? (
            <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-8 text-center text-sm text-[#6a6a6a]">
              No documents match this filter.
            </div>
          ) : (
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {libraryItems.map((item) => {
                const meta = TYPE_META[item.library_type] || TYPE_META.other;
                const Icon = meta.icon;

                return (
                  <div
                    key={`${item.library_type}-${item.id}`}
                    className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5"
                  >
                    <div className="flex items-start gap-3">
                      <Icon
                        size={18}
                        style={{ color: meta.color }}
                        className="mt-1 flex-shrink-0"
                      />

                      <div className="min-w-0 flex-1">
                        <div
                          className="text-[10px] uppercase tracking-widest"
                          style={{ color: meta.color }}
                        >
                          {meta.label}
                        </div>

                        <h3 className="mt-1 font-display text-lg text-[#1f2a22]">
                          {item.title || "Untitled document"}
                        </h3>

                        {(item.description || item.summary) && (
                          <p className="mt-2 line-clamp-2 text-sm text-[#6a6a6a]">
                            {item.description || item.summary}
                          </p>
                        )}

                        {meta.dest ? (
                          <button
                            type="button"
                            onClick={() => navigate(meta.dest)}
                            className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-[#2f4a3a] hover:underline"
                          >
                            Open
                            <ArrowRight size={13} />
                          </button>
                        ) : (
                          <span className="mt-4 inline-block text-xs text-[#8a6a3c]">
                            Stored in Document Library
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

    </PortalLayout>
  );
}

function ClassificationCard({ result, onRoute, savingSupp }) {
  const c = result.classification || {};
  const t = c.type || "other";
  const meta = TYPE_META[t] || TYPE_META.other;
  const Icon = meta.icon;
  const conf = Math.round((c.confidence || 0) * 100);
  const draft = result.draft || {};

  return (
    <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-6" style={{ borderTopColor: meta.color, borderTopWidth: 4 }}>
      <div className="flex items-start gap-4 mb-4">
        <div className="rounded-full p-3 flex-shrink-0" style={{ backgroundColor: `${meta.color}22`, color: meta.color }}>
          <Icon size={22} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-display text-2xl text-[#1f2a22]">{c.title_guess || "Untitled"}</h3>
            <span className="text-[10px] uppercase tracking-widest px-2 py-1 rounded-full text-white" style={{ backgroundColor: meta.color }}>
              {meta.label}
            </span>
            <span className="text-[10px] uppercase tracking-widest px-2 py-1 rounded-full bg-[#f1ead8] border border-[#e0d6bc] text-[#8a6a3c]">
              {conf}% confidence
            </span>
          </div>
          {c.reasoning && <p className="text-sm text-[#5a5a5a] mt-2">{c.reasoning}</p>}
        </div>
      </div>

      <DraftPreview type={t} draft={draft} />

      <div className="mt-5 flex items-center gap-3">
        {t !== "other" ? (
          <Button onClick={onRoute} disabled={savingSupp} className="rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]" data-testid="library-route-btn">
            {savingSupp ? <Loader2 size={14} className="mr-2 animate-spin" /> : <CheckCircle2 size={14} className="mr-2" />}
            Save to {meta.label}
            {meta.dest && <ArrowRight size={14} className="ml-2" />}
          </Button>
        ) : (
          <div className="text-xs text-[#7a2a2a] inline-flex items-center gap-1.5">
            <AlertCircle size={12} /> Couldn't auto-route. Try a clearer document.
          </div>
        )}
      </div>
    </div>
  );
}

function DraftPreview({ type, draft }) {
  if (!draft) return null;
  if (type === "form") {
    return (
      <div className="rounded-xl bg-[#f6f1e6] border border-[#e0d6bc] p-4 text-sm">
        <div className="text-xs uppercase tracking-widest text-[#8a6a3c] mb-1">{(draft.fields || []).length} fields detected</div>
        <ul className="space-y-1">
          {(draft.fields || []).slice(0, 8).map((f, idx) => (
            <li key={idx} className="text-[#3a3a3a] truncate">
              <span className="text-xs uppercase tracking-wider text-[#8a6a3c] mr-2">{f.type}</span>{f.label}
            </li>
          ))}
          {(draft.fields || []).length > 8 && <li className="text-xs text-[#6a6a6a]">+{draft.fields.length - 8} more</li>}
        </ul>
      </div>
    );
  }
  if (type === "protocol") {
    return (
      <div className="rounded-xl bg-[#f6f1e6] border border-[#e0d6bc] p-4 text-sm">
        <div className="flex flex-wrap gap-2 mb-3 text-[10px] uppercase tracking-widest">
          <span className="px-2 py-1 rounded-full bg-[#fbf7ee] border border-[#e0d6bc] text-[#8a6a3c]">{draft.weeks || 4} wk</span>
          <span className="px-2 py-1 rounded-full bg-[#fbf7ee] border border-[#e0d6bc] text-[#8a6a3c]">{draft.sessions_per_week || 1}× / wk</span>
          <span className="px-2 py-1 rounded-full bg-[#fbf7ee] border border-[#e0d6bc] text-[#8a6a3c]">{(draft.foods_recommended || []).length} ✓ foods</span>
          <span className="px-2 py-1 rounded-full bg-[#fbf7ee] border border-[#e0d6bc] text-[#8a6a3c]">{(draft.foods_avoid || []).length} ✗ foods</span>
        </div>
        {draft.description && <p className="text-[#3a3a3a] text-sm line-clamp-3">{draft.description}</p>}
      </div>
    );
  }
  if (type === "soap") {
    return (
      <div className="rounded-xl bg-[#f6f1e6] border border-[#e0d6bc] p-4 text-sm grid grid-cols-2 gap-3">
        {["subjective", "objective", "assessment", "plan"].map((k) => (
          <div key={k}>
            <div className="text-xs uppercase tracking-widest text-[#8a6a3c] mb-1">{k.charAt(0).toUpperCase()}</div>
            <div className="text-[#3a3a3a] text-xs line-clamp-3">{draft[k] || "—"}</div>
          </div>
        ))}
      </div>
    );
  }
  if (type === "supplement") {
    return (
      <div className="rounded-xl bg-[#f6f1e6] border border-[#e0d6bc] p-4 text-sm">
        <div className="text-xs uppercase tracking-widest text-[#8a6a3c] mb-2">{(draft.items || []).length} supplements</div>
        <ul className="text-[#3a3a3a] space-y-1">
          {(draft.items || []).slice(0, 6).map((it, idx) => (
            <li key={idx} className="flex justify-between gap-3">
              <span className="font-medium truncate">{it.name}</span>
              <span className="text-[#6a6a6a] text-xs flex-shrink-0">{it.dose} · {it.frequency}</span>
            </li>
          ))}
          {(draft.items || []).length > 6 && <li className="text-xs text-[#6a6a6a]">+{draft.items.length - 6} more</li>}
        </ul>
      </div>
    );
  }
  return (
    <div className="rounded-xl bg-[#f6f1e6] border border-[#e0d6bc] p-4 text-sm text-[#6a6a6a] line-clamp-5">
      {draft.raw_text || "No preview available."}
    </div>
  );
}