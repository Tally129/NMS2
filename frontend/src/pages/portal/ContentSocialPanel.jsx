import React from "react";

import api from "../../lib/api";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "../../components/ui/select";
import {
  PenSquare, Loader2, RefreshCw, ShieldCheck, Sparkles, CalendarDays,
  Hash, Plus,
} from "lucide-react";

const CHANNELS = ["blog", "tiktok", "instagram", "facebook", "linkedin",
  "email"];
const INTENTS = ["informational", "commercial", "transactional",
  "navigational"];
const STAGES = ["awareness", "consideration", "decision", "retention"];

function Stat({ label, value }) {
  return (
    <div className="rounded-xl border border-[#d8cba9] bg-white p-3">
      <div className="text-[10px] uppercase tracking-widest text-[#8a6a3c]">
        {label}
      </div>
      <div className="mt-1 text-xl font-semibold text-[#3f3320]">{value}</div>
    </div>
  );
}

function slugify(v) {
  return (v || "").toLowerCase().trim().replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "").slice(0, 60);
}

export default function ContentSocialPanel() {
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [overview, setOverview] = React.useState(null);
  const [topics, setTopics] = React.useState([]);
  const [briefs, setBriefs] = React.useState([]);
  const [calendar, setCalendar] = React.useState([]);
  const [busy, setBusy] = React.useState(false);

  // new topic form
  const [tTopic, setTTopic] = React.useState("");
  const [tKeyword, setTKeyword] = React.useState("");
  const [tIntent, setTIntent] = React.useState("commercial");
  const [tStage, setTStage] = React.useState("decision");

  // new brief form
  const [bTitle, setBTitle] = React.useState("");
  const [bChannel, setBChannel] = React.useState("blog");
  const [bTopicId, setBTopicId] = React.useState("");
  const [drafts, setDrafts] = React.useState({});

  const load = React.useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [ov, tp, br, cal] = await Promise.all([
        api.get("/marketing-os/content/overview"),
        api.get("/marketing-os/content/topics"),
        api.get("/marketing-os/content/briefs"),
        api.get("/marketing-os/content/calendar"),
      ]);
      setOverview(ov.data);
      setTopics(tp.data?.topics || []);
      setBriefs(br.data?.briefs || []);
      setCalendar(cal.data?.items || []);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to load content data");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const createTopic = async () => {
    if (!tTopic.trim()) return;
    setBusy(true);
    try {
      await api.post("/marketing-os/content/topics", {
        topic: tTopic.trim(),
        slug: slugify(tTopic) || `topic-${Date.now()}`,
        target_keyword: tKeyword.trim() || null,
        search_intent: tIntent,
        funnel_stage: tStage,
        metrics: {},
      });
      setTTopic(""); setTKeyword("");
      await load();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to create topic");
    } finally {
      setBusy(false);
    }
  };

  const createBrief = async () => {
    if (!bTitle.trim()) return;
    setBusy(true);
    try {
      await api.post("/marketing-os/content/briefs", {
        title: bTitle.trim(),
        channel: bChannel,
        content_type: bChannel === "blog" ? "article" : "post",
        topic_id: bTopicId || null,
      });
      setBTitle(""); setBTopicId("");
      await load();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to create brief");
    } finally {
      setBusy(false);
    }
  };

  const generateDraft = async (briefId) => {
    setBusy(true);
    try {
      const r = await api.post(
        `/marketing-os/content/briefs/${briefId}/drafts`, {});
      setDrafts((d) => ({ ...d, [briefId]: r.data }));
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to generate draft");
    } finally {
      setBusy(false);
    }
  };

  const counts = overview?.counts || {};

  return (
    <section
      className="rounded-2xl border border-[#d8cba9] bg-[#fbf7ee] p-5"
      data-testid="content-social-panel"
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="rounded-xl border border-[#d8cba9] bg-white p-2 text-[#8a6a3c]">
            <PenSquare size={18} />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-[#3f3320]">
              Content &amp; Social Intelligence
            </h3>
            <p className="mt-1 max-w-3xl text-sm text-[#806837]">
              SEO topic prioritization, content briefs, deterministic draft
              scaffolds, and a planning-only content calendar.
            </p>
          </div>
        </div>
        <Button type="button" variant="outline" onClick={load}
          data-testid="content-refresh-btn">
          <RefreshCw size={16} className="mr-1" /> Refresh
        </Button>
      </div>

      <div
        className="mb-4 flex flex-wrap items-center gap-2 rounded-xl border border-[#d8cba9] bg-white px-4 py-3 text-xs text-[#5f5330]"
        data-testid="content-safety"
      >
        <ShieldCheck size={16} className="text-emerald-700" />
        <span className="font-medium">
          Planning only — nothing is published automatically.
        </span>
        <span>
          No social/blog/email/SMS writes · deterministic drafts (no AI) ·
          human approval required · no PHI.
        </span>
      </div>

      {error ? (
        <div className="mb-3 rounded-lg bg-rose-50 px-4 py-2 text-sm text-rose-700"
          data-testid="content-error">
          {typeof error === "string" ? error : JSON.stringify(error)}
        </div>
      ) : null}

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-[#806837]">
          <Loader2 size={16} className="animate-spin" /> Loading…
        </div>
      ) : (
        <div className="grid gap-5">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5"
            data-testid="content-stats">
            <Stat label="Topics" value={counts.topics ?? 0} />
            <Stat label="Briefs" value={counts.briefs ?? 0} />
            <Stat label="Drafts" value={counts.drafts ?? 0} />
            <Stat label="Social plans" value={counts.social_plans ?? 0} />
            <Stat label="Calendar" value={counts.calendar_items ?? 0} />
          </div>

          {/* Topics */}
          <div>
            <h4 className="mb-2 flex items-center gap-1 text-sm font-semibold text-[#3f3320]">
              <Hash size={15} className="text-[#8a6a3c]" />
              Prioritized SEO / content topics
            </h4>
            <div className="mb-3 grid gap-2 rounded-xl border border-[#e2dac5] bg-white p-3 sm:grid-cols-5">
              <Input placeholder="Topic idea" value={tTopic}
                onChange={(e) => setTTopic(e.target.value)}
                data-testid="topic-title-input" />
              <Input placeholder="Target keyword" value={tKeyword}
                onChange={(e) => setTKeyword(e.target.value)}
                data-testid="topic-keyword-input" />
              <Select value={tIntent} onValueChange={setTIntent}>
                <SelectTrigger data-testid="topic-intent-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {INTENTS.map((i) => (
                    <SelectItem key={i} value={i}>{i}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={tStage} onValueChange={setTStage}>
                <SelectTrigger data-testid="topic-stage-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {STAGES.map((s) => (
                    <SelectItem key={s} value={s}>{s}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button type="button" onClick={createTopic} disabled={busy}
                data-testid="topic-create-btn">
                <Plus size={16} className="mr-1" /> Add topic
              </Button>
            </div>
            {topics.length === 0 ? (
              <div className="rounded-lg border border-dashed border-[#c9b98e] px-4 py-5 text-center text-sm text-[#806837]">
                No topics yet. Add one to get a deterministic priority score.
              </div>
            ) : (
              <div className="grid gap-2" data-testid="topic-list">
                {topics.slice(0, 12).map((t) => (
                  <div key={t.id}
                    className="flex items-start justify-between gap-3 rounded-xl border border-[#e2dac5] bg-white px-4 py-3"
                    data-testid="topic-row">
                    <div>
                      <div className="text-sm font-medium text-[#3f3320]">
                        {t.topic}
                      </div>
                      <div className="text-[11px] text-[#806837]">
                        {t.target_keyword ? `“${t.target_keyword}” · ` : ""}
                        {t.search_intent || "—"} · {t.funnel_stage || "—"} ·{" "}
                        {t.status}
                      </div>
                    </div>
                    <span className="flex-shrink-0 rounded-full bg-[#2f4a3a] px-2.5 py-0.5 text-[11px] font-semibold text-white"
                      data-testid="topic-priority">
                      P{t.priority}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Briefs + drafts */}
          <div>
            <h4 className="mb-2 flex items-center gap-1 text-sm font-semibold text-[#3f3320]">
              <Sparkles size={15} className="text-[#8a6a3c]" />
              Content briefs &amp; draft scaffolds
            </h4>
            <div className="mb-3 grid gap-2 rounded-xl border border-[#e2dac5] bg-white p-3 sm:grid-cols-4">
              <Input placeholder="Brief title" value={bTitle}
                onChange={(e) => setBTitle(e.target.value)}
                data-testid="brief-title-input" />
              <Select value={bChannel} onValueChange={setBChannel}>
                <SelectTrigger data-testid="brief-channel-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CHANNELS.map((c) => (
                    <SelectItem key={c} value={c}>{c}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={bTopicId || "none"}
                onValueChange={(v) => setBTopicId(v === "none" ? "" : v)}>
                <SelectTrigger data-testid="brief-topic-select">
                  <SelectValue placeholder="Link topic (optional)" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">No topic</SelectItem>
                  {topics.map((t) => (
                    <SelectItem key={t.id} value={t.id}>{t.topic}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button type="button" onClick={createBrief} disabled={busy}
                data-testid="brief-create-btn">
                <Plus size={16} className="mr-1" /> Add brief
              </Button>
            </div>
            {briefs.length === 0 ? (
              <div className="rounded-lg border border-dashed border-[#c9b98e] px-4 py-5 text-center text-sm text-[#806837]">
                No briefs yet.
              </div>
            ) : (
              <div className="grid gap-2" data-testid="brief-list">
                {briefs.slice(0, 12).map((b) => (
                  <div key={b.id}
                    className="rounded-xl border border-[#e2dac5] bg-white px-4 py-3"
                    data-testid="brief-row">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-medium text-[#3f3320]">
                          {b.title}
                        </div>
                        <div className="text-[11px] text-[#806837]">
                          <Badge variant="outline" className="mr-1">
                            {b.channel}
                          </Badge>
                          {b.content_type} · {b.status}
                        </div>
                      </div>
                      <Button type="button" size="sm" variant="outline"
                        disabled={busy}
                        onClick={() => generateDraft(b.id)}
                        data-testid="brief-generate-draft-btn">
                        <Sparkles size={14} className="mr-1" /> Draft
                      </Button>
                    </div>
                    {drafts[b.id] ? (
                      <div className="mt-2 rounded-lg bg-[#f6f0e2] px-3 py-2 text-[11px] text-[#5f5330]"
                        data-testid="brief-draft-preview">
                        {drafts[b.id].hook ? (
                          <div><b>Hook:</b> {drafts[b.id].hook}</div>
                        ) : null}
                        {drafts[b.id].body ? (
                          <div>{drafts[b.id].body}</div>
                        ) : null}
                        {drafts[b.id].script ? (
                          <div><b>Script:</b> {drafts[b.id].script}</div>
                        ) : null}
                        <div className="mt-1 italic text-[#8a6a3c]">
                          CTA: {drafts[b.id].cta} · deterministic scaffold
                          (draft only)
                        </div>
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Calendar */}
          <div>
            <h4 className="mb-2 flex items-center gap-1 text-sm font-semibold text-[#3f3320]">
              <CalendarDays size={15} className="text-[#8a6a3c]" />
              Content calendar (planning only)
            </h4>
            {calendar.length === 0 ? (
              <div className="rounded-lg border border-dashed border-[#c9b98e] px-4 py-5 text-center text-sm text-[#806837]">
                No planned items. Calendar dates are planning metadata only —
                no auto-publishing.
              </div>
            ) : (
              <div className="grid gap-2" data-testid="calendar-list">
                {calendar.slice(0, 12).map((c) => (
                  <div key={c.id}
                    className="flex items-center justify-between gap-3 rounded-xl border border-[#e2dac5] bg-white px-4 py-3"
                    data-testid="calendar-row">
                    <div className="text-sm font-medium text-[#3f3320]">
                      {c.title}
                    </div>
                    <div className="flex items-center gap-2 text-[11px] text-[#806837]">
                      <Badge variant="outline">{c.channel}</Badge>
                      <span>{c.planned_publish_at || "unscheduled"}</span>
                      <span>· {c.status}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="text-[11px] text-[#806837]">
            <Badge variant="outline">advisory</Badge> All drafts and plans are
            deterministic and require human approval before any external use.
          </div>
        </div>
      )}
    </section>
  );
}
