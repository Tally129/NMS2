import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { TestTube2, Upload } from "lucide-react";
import { Button } from "../../components/ui/button";
import { useToast } from "../../hooks/use-toast";
import { getErrorMessage } from "../../lib/errors";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceArea } from "recharts";

export default function PatientLabs() {
  const { toast } = useToast();
  const [labs, setLabs] = React.useState([]);
  const [presets, setPresets] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState("");
  const [uploading, setUploading] = React.useState(false);
  const inputRef = React.useRef(null);

  React.useEffect(() => {
    const load = async () => {
      setLoading(true);
      setLoadError("");

      try {
        const [labsResponse, presetsResponse] = await Promise.all([
          api.get("/lab-values"),
          api.get("/labs/presets"),
        ]);

        setLabs(labsResponse.data || []);
        setPresets(presetsResponse.data?.presets || []);
      } catch (error) {
        setLabs([]);
        setPresets([]);
        setLoadError(
          error?.response?.data?.detail?.message ||
          error?.response?.data?.detail ||
          "Could not load your lab results."
        );
      } finally {
        setLoading(false);
      }
    };

    load();
  }, []);

  const uploadOutsideLab = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setUploading(true);

    try {
      const form = new FormData();
      form.append("file", file);
      form.append("category", "lab");

      await api.post("/files/upload", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });

      toast({
        title: "Outside lab report uploaded",
        description: "Your care team can now review this report.",
      });

      event.target.value = "";
    } catch (error) {
      toast({
        title: "Upload failed",
        description: getErrorMessage(error) || "Please try again.",
      });
    } finally {
      setUploading(false);
    }
  };

  const byTest = React.useMemo(() => {
    const g = {};
    for (const l of labs) {
      (g[l.test_name] = g[l.test_name] || []).push({
        date: new Date(l.measured_at).toLocaleDateString(),
        t: new Date(l.measured_at).getTime(),
        value: l.value,
        ref_low: l.reference_low,
        ref_high: l.reference_high,
        unit: l.unit,
      });
    }
    Object.values(g).forEach((arr) => arr.sort((a, b) => a.t - b.t));
    return g;
  }, [labs]);

  return (
    <PortalLayout>
      <PortalHeader
        title="Lab Results"
        subtitle="View verified results and securely share outside lab reports with your care team."
      />

      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.png,.jpg,.jpeg"
        onChange={uploadOutsideLab}
        className="hidden"
      />

      <div className="mb-6 rounded-2xl border border-[#e7dfc9] bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="font-display text-xl text-[#1f2a22]">
              Upload an outside lab report
            </h2>

            <p className="mt-1 max-w-2xl text-sm leading-6 text-[#6a6a6a]">
              Share a PDF or image from another laboratory or provider. Your
              care team will review the report before any values are added to
              your verified lab history.
            </p>
          </div>

          <Button
            onClick={() => inputRef.current?.click()}
            disabled={uploading}
            className="h-11 rounded-full bg-[#2f4a3a] text-white hover:bg-[#263d30]"
          >
            <Upload size={16} className="mr-2" />
            {uploading ? "Uploading…" : "Upload report"}
          </Button>
        </div>
      </div>
      {loading ? (
        <div className="text-[#6a6a6a]">Loading lab results…</div>
      ) : loadError ? (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-6 text-center">
          <div className="text-sm text-amber-900">{loadError}</div>
        </div>
      ) : Object.keys(byTest).length === 0 ? (
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-10 text-center text-[#6a6a6a]">
          <TestTube2 size={28} className="mx-auto text-[#c19a4b]" />
          <div className="mt-3">No lab results yet.</div>
        </div>
      ) : (
        <div className="space-y-5">
          {Object.entries(byTest).map(([name, data]) => {
            const latest = data[data.length - 1];
            return (
              <div key={name} className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5">
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <div className="font-display text-xl text-[#1f2a22]">{name}</div>
                    <div className="text-xs text-[#6a6a6a]">Latest: {latest.value} {latest.unit || ""} on {latest.date}</div>
                  </div>
                  {latest.ref_low != null && latest.ref_high != null && (
                    <div className="text-xs text-[#8a6a3c]">ref {latest.ref_low} – {latest.ref_high}</div>
                  )}
                </div>
                <div style={{ width: "100%", height: 180 }}>
                  <ResponsiveContainer>
                    <LineChart data={data} margin={{ top: 10, right: 16, bottom: 10, left: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e7dfc9" />
                      <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#6a6a6a" }} />
                      <YAxis tick={{ fontSize: 11, fill: "#6a6a6a" }} />
                      {latest.ref_low != null && latest.ref_high != null && (
                        <ReferenceArea y1={latest.ref_low} y2={latest.ref_high} fill="#c19a4b" fillOpacity={0.12} />
                      )}
                      <Tooltip contentStyle={{ background: "#fbf7ee", border: "1px solid #e7dfc9", borderRadius: 8, fontSize: 12 }} />
                      <Line type="monotone" dataKey="value" stroke="#2f4a3a" strokeWidth={2} dot={{ r: 4, fill: "#c19a4b" }} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </PortalLayout>
  );
}
