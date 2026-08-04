import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api, { downloadBlob } from "../../lib/api";
import { Button } from "../../components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../components/ui/select";
import { Upload, Download, FolderOpen } from "lucide-react";
import { useToast } from "../../hooks/use-toast";
import { getErrorMessage } from "../../lib/errors";

export default function PatientFiles({ clientIdProp }) {
  const { toast } = useToast();
  const [files, setFiles] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [uploading, setUploading] = React.useState(false);
  const [category, setCategory] = React.useState("doc");
  const inputRef = React.useRef(null);

  const [loadError, setLoadError] = React.useState(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      // The backend automatically resolves the signed-in patient's record.
      // Do not submit or trust a patient-provided client_id.
      const r = await api.get("/files");
      setFiles(r.data || []);
    } catch (e) {
      setFiles([]);
      setLoadError(e?.response?.data?.detail?.message || e?.message || "Could not load your files.");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  const onPick = () => inputRef.current?.click();
  const onFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("category", category);
      await api.post("/files/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast({ title: "Uploaded", description: file.name });
      e.target.value = "";
      load();
    } catch (err) {
      toast({ title: "Upload failed", description: getErrorMessage(err) || "Try again." });
    } finally {
      setUploading(false);
    }
  };

  const download = async (f) => {
    try {
      await downloadBlob(`/files/${f.id}/download`, { filename: f.filename });
    } catch (e) {
      toast({
        title: "Download failed",
        description: e?.isAuthDenied ? "You no longer have access to this file." : (e.message || "Try again."),
      });
    }
  };

  return (
    <PortalLayout>
      <PortalHeader
        title="My Documents"
        subtitle="Upload personal records, outside reports, forms, and images to share securely with your care team."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Select value={category} onValueChange={setCategory}>
              <SelectTrigger className="h-11 w-56 bg-white border-[#e0d6bc]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="lab">Outside lab report</SelectItem>
                <SelectItem value="doc">Medical record or document</SelectItem>
                <SelectItem value="image">Image or scan</SelectItem>
                <SelectItem value="intake">Intake paperwork</SelectItem>
                <SelectItem value="other">Other document</SelectItem>
              </SelectContent>
            </Select>

            <Button
              onClick={onPick}
              disabled={uploading}
              className="btn-lift h-11 rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
            >
              <Upload size={16} className="mr-2" />
              {uploading ? "Uploading…" : "Upload document"}
            </Button>
          </div>
        }
      />
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.png,.jpg,.jpeg,.doc,.docx,.txt,.csv"
        onChange={onFile}
        className="hidden"
      />

      {loading ? (
        <div className="text-[#6a6a6a]">Loading…</div>
      ) : loadError ? (
        <div className="rounded-2xl border border-[#c19a4b] bg-[#fbf3df] p-6 text-center" data-testid="patient-files-error">
          <div className="text-sm text-[#7a2a2a] mb-3">{loadError}</div>
          <Button
            onClick={load}
            variant="outline"
            className="rounded-full border-[#8a6a3c] text-[#8a6a3c]"
            data-testid="patient-files-retry"
          >
            Try again
          </Button>
        </div>
      ) : files.length === 0 ? (
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-10 text-center text-[#6a6a6a]">
          <FolderOpen size={28} className="mx-auto text-[#c19a4b]" />
          <div className="mt-3">No documents yet. Upload a personal record, report, image, or form to share with your care team.</div>
        </div>
      ) : (
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
              <tr>
                <th className="text-left py-3 px-4">File</th>
                <th className="text-left py-3 px-4">Category</th>
                <th className="text-left py-3 px-4">Uploaded</th>
                <th className="text-left py-3 px-4">By</th>
                <th className="text-right py-3 px-4">Action</th>
              </tr>
            </thead>
            <tbody>
              {files.map((f) => (
                <tr key={f.id} className="border-t border-[#e7dfc9]">
                  <td className="py-3 px-4 text-[#2a2a2a]">{f.filename}</td>
                  <td className="py-3 px-4 text-[#6a6a6a] capitalize">{f.category}</td>
                  <td className="py-3 px-4 text-[#6a6a6a]">{new Date(f.created_at).toLocaleDateString()}</td>
                  <td className="py-3 px-4 text-[#6a6a6a]">{f.uploaded_by_name || "—"}</td>
                  <td className="py-3 px-4 text-right">
                    <Button size="sm" variant="outline" onClick={() => download(f)} className="rounded-full border-[#2f4a3a] text-[#2f4a3a] hover:bg-[#2f4a3a] hover:text-[#f6f1e6]">
                      <Download size={14} className="mr-1" /> Download
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PortalLayout>
  );
}