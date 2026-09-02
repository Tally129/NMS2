import React from "react";

import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Loader2, Plus, Users, GitCompareArrows, Link2, MapPin, Lightbulb } from "lucide-react";

const TABS = [
  { id: "competitors", label: "Competitors", icon: Users },
  { id: "gap", label: "Keyword Gap", icon: GitCompareArrows },
  { id: "backlinks", label: "Backlinks", icon: Link2 },
  { id: "local", label: "Local SEO", icon: MapPin },
  { id: "content", label: "Content Opportunities", icon: Lightbulb },
];

function NotConnected({ reason }) {
  return (
    <div
      className="rounded-lg border border-dashed border-[#c19a4b] bg-[#fdfbf5] p-3 text-sm text-[#6b5836]"
      data-testid="p3-not-connected"
    >
      Not connected{reason ? ` (${reason})` : ""}. No provider data is
      available yet — values are not fabricated.
    </div>
  );
}

export default function Phase3Section() {
  const [tab, setTab] = React.useState("competitors");
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [competitors, setCompetitors] = React.useState(null);
  const [gap, setGap] = React.useState(null);
  const [backlinks, setBacklinks] = React.useState(null);
  const [local, setLocal] = React.useState(null);
  const [content, setContent] = React.useState(null);
  const [domain, setDomain] = React.useState("");

  const load = React.useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [c, g, b, l, o] = await Promise.all([
        api.get("/marketing-os/search/competitors"),
        api.get("/marketing-os/search/keyword-gap"),
        api.get("/marketing-os/search/backlinks/overview"),
        api.get("/marketing-os/search/local"),
        api.get("/marketing-os/search/content-opportunities"),
      ]);
      setCompetitors(c.data);
      setGap(g.data);
      setBacklinks(b.data);
      setLocal(l.data);
      setContent(o.data);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to load intelligence");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  const addCompetitor = async () => {
    if (!domain.trim()) return;
    setBusy(true);
    setError("");
    try {
      await api.post("/marketing-os/search/competitors", {
        domain: domain.trim(),
      });
      setDomain("");
      await load();
    } catch (err) {
      setError(err?.response?.data?.detail || "Unable to add competitor");
    } finally {
      setBusy(false);
    }
  };

  const gapSummary = gap?.summary || {};

  return (
    <div className="mt-6 rounded-xl border border-[#d8cba9] bg-white p-4" data-testid="phase3-section">
      <h4 className="mb-3 font-semibold text-[#3f3320]">Competitor &amp; Off-Page Intelligence</h4>

      <div className="mb-4 flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            data-testid={`p3-tab-${t.id}`}
            className={
              "inline-flex items-center gap-1 rounded-full px-3 py-1 text-sm " +
              (tab === t.id
                ? "bg-[#c19a4b] text-white"
                : "bg-[#faf6ec] text-[#6b5836]")
            }
          >
            <t.icon size={14} />
            {t.label}
          </button>
        ))}
      </div>

      {error ? (
        <div className="mb-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>
      ) : null}

      {loading ? (
        <div className="flex items-center gap-2 text-[#8a6a3c]">
          <Loader2 size={16} className="animate-spin" /> Loading…
        </div>
      ) : (
        <>
          {tab === "competitors" && (
            <div data-testid="p3-competitors">
              <div className="mb-3 flex items-center gap-2">
                <Input
                  value={domain}
                  onChange={(e) => setDomain(e.target.value)}
                  placeholder="competitor-domain.com"
                  className="h-9 w-64 border-[#d8cba9]"
                  data-testid="p3-competitor-input"
                />
                <Button
                  type="button"
                  disabled={busy || !domain.trim()}
                  onClick={addCompetitor}
                  className="h-9 rounded-full bg-[#c19a4b] text-white"
                  data-testid="p3-add-competitor"
                >
                  <Plus size={14} className="mr-1" /> Add
                </Button>
              </div>
              {(competitors?.competitors || []).length === 0 ? (
                <div className="rounded-lg bg-[#faf6ec] p-3 text-sm text-[#8a6a3c]">
                  No competitors tracked yet.
                </div>
              ) : (
                <ul className="space-y-1 text-sm">
                  {competitors.competitors.map((c) => (
                    <li key={c.id} className="flex items-center justify-between rounded-lg border border-[#f0e8d5] px-3 py-2">
                      <span className="text-[#3f3320]">{c.domain}</span>
                      <span className={"text-xs " + (c.is_active ? "text-green-700" : "text-gray-500")}>
                        {c.is_active ? "active" : "inactive"}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {tab === "gap" && (
            <div data-testid="p3-gap">
              {!gap?.connected ? (
                <NotConnected reason={gap?.not_connected_reason} />
              ) : (
                <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
                  {["shared", "nms_only", "missing", "weak", "strong", "total"].map((k) => (
                    <div key={k} className="rounded-lg bg-[#faf6ec] p-3 text-center">
                      <div className="text-xl font-semibold text-[#3f3320]">{gapSummary[k] ?? 0}</div>
                      <div className="text-xs capitalize text-[#8a6a3c]">{k.replace("_", " ")}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {tab === "backlinks" && (
            <div data-testid="p3-backlinks">
              {!backlinks?.connected ? (
                <NotConnected reason={backlinks?.not_connected_reason} />
              ) : (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {[
                    ["Backlinks", backlinks.backlink_count],
                    ["Referring Domains", backlinks.referring_domains],
                    ["New", backlinks.new_backlinks],
                    ["Lost", backlinks.lost_backlinks],
                  ].map(([label, val]) => (
                    <div key={label} className="rounded-lg bg-[#faf6ec] p-3 text-center">
                      <div className="text-xl font-semibold text-[#3f3320]">{val ?? "—"}</div>
                      <div className="text-xs text-[#8a6a3c]">{label}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {tab === "local" && (
            <div data-testid="p3-local">
              {!local?.connected ? (
                <NotConnected reason={local?.not_connected_reason} />
              ) : (
                <ul className="space-y-1 text-sm">
                  {(local.locations || []).map((l) => (
                    <li key={l.id} className="rounded-lg border border-[#f0e8d5] px-3 py-2 text-[#3f3320]">
                      {l.target_keyword} — {l.city || "—"} ({l.local_rank ?? "—"})
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {tab === "content" && (
            <div data-testid="p3-content">
              <p className="mb-2 text-xs text-[#a99b7d]">
                Advisory only — requires human approval; no changes are made automatically.
              </p>
              {(content?.opportunities || []).length === 0 ? (
                <div className="rounded-lg bg-[#faf6ec] p-3 text-sm text-[#8a6a3c]">
                  No content opportunities yet.
                </div>
              ) : (
                <div className="space-y-2" data-testid="p3-content-list">
                  {content.opportunities.map((o, i) => (
                    <div key={i} className="rounded-lg border border-[#f0e8d5] p-3">
                      <div className="text-sm font-medium text-[#3f3320]">{o.title}</div>
                      <div className="text-xs text-[#6b5836]">{o.reason}</div>
                      <div className="mt-1 text-xs text-[#8a6a3c]">Recommended: {o.proposed_action}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
