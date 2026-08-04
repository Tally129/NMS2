import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Textarea } from "../../components/ui/textarea";
import { Label } from "../../components/ui/label";
import { useToast } from "../../hooks/use-toast";
import { getErrorMessage } from "../../lib/errors";
import {
  Brain,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  FileText,
  Loader2,
  MessageSquare,
  Plus,
  RefreshCw,
  Send,
  Sparkles,
  Target,
} from "lucide-react";

const INITIAL_FORM = {
  name: "",
  goal: "",
  services: "",
  audiences: "",
  brand_voice: "Educational, professional, premium, warm, non-pushy",
  channels: "email, instagram, facebook, blog",
  duration_days: 30,
  posts_per_week: 4,
  emails_per_month: 2,
  objective_notes: "",
  call_to_action: "",
  offer_details: "",
  compliance_notes: "",
};

function splitValues(value) {
  return String(value || "")
    .split(/[,;\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatDate(value) {
  if (!value) return "";

  try {
    return new Date(value).toLocaleString();
  } catch {
    return "";
  }
}

export default function ContentStrategist() {
  const { toast } = useToast();

  const [strategies, setStrategies] = React.useState([]);
  const [selected, setSelected] = React.useState(null);
  const [form, setForm] = React.useState(INITIAL_FORM);
  const [message, setMessage] = React.useState("");
  const [loadingList, setLoadingList] = React.useState(true);
  const [creating, setCreating] = React.useState(false);
  const [loadingStrategy, setLoadingStrategy] = React.useState(false);
  const [sendingMessage, setSendingMessage] = React.useState(false);
  const [generating, setGenerating] = React.useState(false);
  const [showCreate, setShowCreate] = React.useState(false);

  const loadStrategies = React.useCallback(async () => {
    setLoadingList(true);

    try {
      const response = await api.get("/content-strategies", {
        params: { limit: 200 },
      });

      const rows = Array.isArray(response.data)
        ? response.data
        : [];

      setStrategies(rows);

      if (!selected && rows.length > 0) {
        setSelected(rows[0]);
      }
    } catch (error) {
      toast({
        title: "Could not load strategies",
        description:
          getErrorMessage(error) ||
          "Please refresh and try again.",
        variant: "destructive",
      });
    } finally {
      setLoadingList(false);
    }
  }, [selected, toast]);

  React.useEffect(() => {
    loadStrategies();
  }, [loadStrategies]);

  const openStrategy = async (strategyId) => {
    setLoadingStrategy(true);

    try {
      const response = await api.get(
        `/content-strategies/${strategyId}`
      );

      setSelected(response.data);
      setShowCreate(false);
    } catch (error) {
      toast({
        title: "Could not open strategy",
        description:
          getErrorMessage(error) ||
          "The strategy could not be loaded.",
        variant: "destructive",
      });
    } finally {
      setLoadingStrategy(false);
    }
  };

  const createStrategy = async () => {
    if (!form.name.trim() || !form.goal.trim()) {
      toast({
        title: "Name and business goal are required",
      });
      return;
    }

    setCreating(true);

    try {
      const response = await api.post(
        "/content-strategies",
        {
          name: form.name.trim(),
          goal: form.goal.trim(),
          services: splitValues(form.services),
          audiences: splitValues(form.audiences),
          brand_voice: splitValues(form.brand_voice),
          channels: splitValues(form.channels),
          duration_days: Number(form.duration_days),
          posts_per_week: Number(form.posts_per_week),
          emails_per_month: Number(form.emails_per_month),
          objective_notes:
            form.objective_notes.trim() || undefined,
          call_to_action:
            form.call_to_action.trim() || undefined,
          offer_details:
            form.offer_details.trim() || undefined,
          compliance_notes:
            form.compliance_notes.trim() || undefined,
        }
      );

      setSelected(response.data);
      setStrategies((current) => [
        response.data,
        ...current.filter(
          (item) => item.id !== response.data.id
        ),
      ]);
      setForm(INITIAL_FORM);
      setShowCreate(false);

      toast({
        title: "Strategy workspace created",
        description:
          "Add planning notes or generate the first strategy plan.",
      });
    } catch (error) {
      toast({
        title: "Could not create strategy",
        description:
          getErrorMessage(error) ||
          "Review the strategy information and try again.",
        variant: "destructive",
      });
    } finally {
      setCreating(false);
    }
  };

  const refreshSelected = async () => {
    if (!selected?.id) return;
    await openStrategy(selected.id);
    await loadStrategies();
  };

  const addMessage = async () => {
    if (!selected?.id || !message.trim()) return;

    setSendingMessage(true);

    try {
      const response = await api.post(
        `/content-strategies/${selected.id}/messages`,
        {
          body: message.trim(),
        }
      );

      setSelected((current) => ({
        ...current,
        messages: [
          ...(current?.messages || []),
          response.data,
        ],
      }));

      setMessage("");
    } catch (error) {
      toast({
        title: "Could not save planning note",
        description:
          getErrorMessage(error) ||
          "Please try again.",
        variant: "destructive",
      });
    } finally {
      setSendingMessage(false);
    }
  };

  const generatePlan = async () => {
    if (!selected?.id) return;

    setGenerating(true);

    try {
      const response = await api.post(
        `/content-strategies/${selected.id}/generate`
      );

      setSelected((current) => ({
        ...current,
        plan: response.data?.plan || null,
        status: "generated",
        human_review_required: true,
      }));

      await loadStrategies();

      toast({
        title: "Content strategy generated",
        description:
          "Review every recommendation before using or publishing it.",
      });
    } catch (error) {
      toast({
        title: "Could not generate strategy",
        description:
          getErrorMessage(error) ||
          "Bedrock could not complete the strategy.",
        variant: "destructive",
      });
    } finally {
      setGenerating(false);
    }
  };

  return (
    <PortalLayout>
      <PortalHeader
        title="AI Content Strategist"
        subtitle="Plan, generate, save, and review coordinated marketing strategies"
        actions={
          <Button
            type="button"
            onClick={() => {
              setShowCreate(true);
              setSelected(null);
            }}
            className="h-11 rounded-full bg-[#2f4a3a] text-[#f6f1e6] hover:bg-[#263d30]"
          >
            <Plus size={16} className="mr-2" />
            New strategy
          </Button>
        }
      />

      <div className="mb-5 rounded-2xl border border-[#d8cba9] bg-[#f7f1e4] p-5">
        <div className="flex gap-3">
          <Brain
            size={24}
            className="mt-0.5 shrink-0 text-[#2f4a3a]"
          />

          <div>
            <div className="font-semibold text-[#1f2a22]">
              Your clinic’s persistent AI marketing workspace
            </div>

            <p className="mt-1 text-sm leading-6 text-[#6a6a6a]">
              Strategies, planning conversations, generated plans,
              and future content assets are saved for later review.
              Nothing is published or sent automatically.
            </p>
          </div>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="self-start rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] xl:sticky xl:top-5">
          <div className="border-b border-[#e7dfc9] p-4">
            <div className="eyebrow text-[#8a6a3c]">
              Saved strategies
            </div>

            <div className="mt-1 text-xs text-[#6a6a6a]">
              {strategies.length} workspace
              {strategies.length === 1 ? "" : "s"}
            </div>
          </div>

          <div className="max-h-[calc(100vh-260px)] overflow-y-auto p-2">
            {loadingList && (
              <div className="p-6 text-center text-sm text-[#6a6a6a]">
                <Loader2
                  size={16}
                  className="mr-2 inline animate-spin"
                />
                Loading…
              </div>
            )}

            {!loadingList && strategies.length === 0 && (
              <div className="p-6 text-center text-sm text-[#6a6a6a]">
                No saved strategies yet.
              </div>
            )}

            {strategies.map((strategy) => {
              const active =
                selected?.id === strategy.id &&
                !showCreate;

              return (
                <button
                  key={strategy.id}
                  type="button"
                  onClick={() => openStrategy(strategy.id)}
                  className={`mb-2 w-full rounded-xl border p-3 text-left transition ${
                    active
                      ? "border-[#2f4a3a] bg-[#e7efe9]"
                      : "border-transparent hover:border-[#e0d6bc] hover:bg-[#f1ead8]"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate font-medium text-[#1f2a22]">
                        {strategy.name || "Untitled strategy"}
                      </div>

                      <div className="mt-1 line-clamp-2 text-xs text-[#6a6a6a]">
                        {strategy.goal || "No goal entered"}
                      </div>
                    </div>

                    <ChevronRight
                      size={15}
                      className="mt-1 shrink-0 text-[#8a6a3c]"
                    />
                  </div>

                  <div className="mt-3 flex items-center justify-between text-[11px] text-[#8a6a3c]">
                    <span className="capitalize">
                      {(strategy.status || "draft").replace(
                        /_/g,
                        " "
                      )}
                    </span>

                    <span>
                      {strategy.duration_days || 30} days
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </aside>

        <main className="min-w-0">
          {showCreate || (!selected && !loadingStrategy) ? (
            <CreateStrategyForm
              form={form}
              setForm={setForm}
              creating={creating}
              onCreate={createStrategy}
            />
          ) : loadingStrategy ? (
            <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-12 text-center text-[#6a6a6a]">
              <Loader2
                size={18}
                className="mr-2 inline animate-spin"
              />
              Loading strategy…
            </div>
          ) : (
            <StrategyWorkspace
              strategy={selected}
              message={message}
              setMessage={setMessage}
              sendingMessage={sendingMessage}
              generating={generating}
              onAddMessage={addMessage}
              onGenerate={generatePlan}
              onRefresh={refreshSelected}
            />
          )}
        </main>
      </div>
    </PortalLayout>
  );
}

function CreateStrategyForm({
  form,
  setForm,
  creating,
  onCreate,
}) {
  const update = (field, value) => {
    setForm((current) => ({
      ...current,
      [field]: value,
    }));
  };

  return (
    <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-6">
      <div className="flex items-center gap-3">
        <Target size={22} className="text-[#2f4a3a]" />

        <div>
          <h2 className="font-display text-2xl text-[#1f2a22]">
            Create a strategy brief
          </h2>

          <p className="mt-1 text-sm text-[#6a6a6a]">
            Give the strategist enough business context to
            create a practical plan.
          </p>
        </div>
      </div>

      <div className="mt-6 grid gap-5 md:grid-cols-2">
        <Field label="Strategy name">
          <Input
            value={form.name}
            onChange={(event) =>
              update("name", event.target.value)
            }
            placeholder="August Athlete Recovery Strategy"
          />
        </Field>

        <Field label="Duration">
          <select
            value={form.duration_days}
            onChange={(event) =>
              update(
                "duration_days",
                Number(event.target.value)
              )
            }
            className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
          >
            {[7, 14, 30, 60, 90].map((days) => (
              <option key={days} value={days}>
                {days} days
              </option>
            ))}
          </select>
        </Field>

        <div className="md:col-span-2">
          <Field label="Primary business goal">
            <Textarea
              value={form.goal}
              onChange={(event) =>
                update("goal", event.target.value)
              }
              rows={3}
              placeholder="Increase bookings for athlete recovery services and introduce monthly recovery memberships."
            />
          </Field>
        </div>

        <Field label="Services">
          <Textarea
            value={form.services}
            onChange={(event) =>
              update("services", event.target.value)
            }
            rows={3}
            placeholder="Hyperbaric oxygen, IV hydration, B12 injections"
          />
        </Field>

        <Field label="Generalized audiences">
          <Textarea
            value={form.audiences}
            onChange={(event) =>
              update("audiences", event.target.value)
            }
            rows={3}
            placeholder="Student athletes, runners, CrossFit members, weekend warriors"
          />
        </Field>

        <Field label="Brand voice">
          <Textarea
            value={form.brand_voice}
            onChange={(event) =>
              update("brand_voice", event.target.value)
            }
            rows={3}
          />
        </Field>

        <Field label="Channels">
          <Textarea
            value={form.channels}
            onChange={(event) =>
              update("channels", event.target.value)
            }
            rows={3}
            placeholder="email, instagram, facebook, blog"
          />
        </Field>

        <Field label="Posts per week">
          <Input
            type="number"
            min="0"
            max="21"
            value={form.posts_per_week}
            onChange={(event) =>
              update(
                "posts_per_week",
                Number(event.target.value)
              )
            }
          />
        </Field>

        <Field label="Emails per month">
          <Input
            type="number"
            min="0"
            max="20"
            value={form.emails_per_month}
            onChange={(event) =>
              update(
                "emails_per_month",
                Number(event.target.value)
              )
            }
          />
        </Field>

        <Field label="Preferred call to action">
          <Input
            value={form.call_to_action}
            onChange={(event) =>
              update("call_to_action", event.target.value)
            }
            placeholder="Book an athlete recovery consultation"
          />
        </Field>

        <Field label="Offer details">
          <Input
            value={form.offer_details}
            onChange={(event) =>
              update("offer_details", event.target.value)
            }
            placeholder="Only include offers the clinic has approved"
          />
        </Field>

        <div className="md:col-span-2">
          <Field label="Additional objectives">
            <Textarea
              value={form.objective_notes}
              onChange={(event) =>
                update(
                  "objective_notes",
                  event.target.value
                )
              }
              rows={3}
              placeholder="Build awareness first, then introduce consultations and memberships."
            />
          </Field>
        </div>

        <div className="md:col-span-2">
          <Field label="Compliance notes">
            <Textarea
              value={form.compliance_notes}
              onChange={(event) =>
                update(
                  "compliance_notes",
                  event.target.value
                )
              }
              rows={3}
              placeholder="Avoid cure claims. Do not promise athletic performance improvements."
            />
          </Field>
        </div>
      </div>

      <div className="mt-6 flex justify-end">
        <Button
          type="button"
          onClick={onCreate}
          disabled={creating}
          className="h-11 rounded-full bg-[#2f4a3a] px-6 text-[#f6f1e6] hover:bg-[#263d30]"
        >
          {creating ? (
            <>
              <Loader2
                size={16}
                className="mr-2 animate-spin"
              />
              Creating…
            </>
          ) : (
            <>
              <Sparkles size={16} className="mr-2" />
              Create workspace
            </>
          )}
        </Button>
      </div>
    </div>
  );
}

function StrategyWorkspace({
  strategy,
  message,
  setMessage,
  sendingMessage,
  generating,
  onAddMessage,
  onGenerate,
  onRefresh,
}) {
  const plan = strategy?.plan || null;
  const messages = strategy?.messages || [];
  const [notesOpen, setNotesOpen] = React.useState(false);

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="min-w-0">
            <div className="inline-flex items-center rounded-full border border-[#d8cba9] bg-[#f6f1e6] px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-[#8a6a3c]">
              Natural Medical Solutions · Content HQ
            </div>

            <h2 className="mt-1 font-display text-3xl text-[#1f2a22]">
              {strategy.name}
            </h2>

            <p className="mt-2 max-w-4xl text-sm leading-6 text-[#6a6a6a]">
              {strategy.goal}
            </p>

            <div className="mt-3 flex flex-wrap gap-2">
              {(strategy.channels || []).map((channel) => (
                <span
                  key={channel}
                  className="rounded-full bg-[#e7efe9] px-3 py-1 text-xs capitalize text-[#2f4a3a]"
                >
                  {channel.replace(/_/g, " ")}
                </span>
              ))}
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => setNotesOpen(true)}
              className="rounded-full"
            >
              <MessageSquare size={14} className="mr-2" />
              Planning notes
              {messages.length > 0
                ? ` (${messages.length})`
                : ""}
            </Button>

            <Button
              type="button"
              variant="outline"
              onClick={onRefresh}
              className="rounded-full"
            >
              <RefreshCw size={14} className="mr-2" />
              Refresh
            </Button>

            <Button
              type="button"
              onClick={onGenerate}
              disabled={generating}
              className="rounded-full bg-[#2f4a3a] text-white hover:bg-[#263d30]"
            >
              {generating ? (
                <>
                  <Loader2
                    size={15}
                    className="mr-2 animate-spin"
                  />
                  Strategizing…
                </>
              ) : (
                <>
                  <Sparkles size={15} className="mr-2" />
                  {plan ? "Regenerate" : "Generate plan"}
                </>
              )}
            </Button>
          </div>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <SummaryCard
            label="Duration"
            value={`${strategy.duration_days || 30} days`}
          />
          <SummaryCard
            label="Publishing cadence"
            value={`${strategy.posts_per_week || 0} posts/week`}
          />
          <SummaryCard
            label="Email cadence"
            value={`${strategy.emails_per_month || 0} emails/month`}
          />
        </div>
      </div>

      {plan ? (
        <StrategyPlan
          plan={plan}
          strategyId={strategy.id}
        />
      ) : (
        <div className="rounded-2xl border border-dashed border-[#c8b990] bg-[#fbf7ee] p-12 text-center">
          <Brain
            size={36}
            className="mx-auto text-[#2f4a3a]"
          />

          <h3 className="mt-4 font-display text-2xl text-[#1f2a22]">
            Build your content execution plan
          </h3>

          <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-[#6a6a6a]">
            Generate a strategy to create weekly content tasks,
            campaign ideas, channel recommendations, and a
            publishing calendar.
          </p>

          <Button
            type="button"
            onClick={onGenerate}
            disabled={generating}
            className="mt-5 rounded-full bg-[#2f4a3a] text-white hover:bg-[#263d30]"
          >
            {generating ? (
              <>
                <Loader2
                  size={15}
                  className="mr-2 animate-spin"
                />
                Building strategy…
              </>
            ) : (
              <>
                <Sparkles size={15} className="mr-2" />
                Generate strategy
              </>
            )}
          </Button>
        </div>
      )}

      {notesOpen && (
        <PlanningNotesDrawer
          messages={messages}
          message={message}
          setMessage={setMessage}
          sendingMessage={sendingMessage}
          onAddMessage={onAddMessage}
          onClose={() => setNotesOpen(false)}
        />
      )}
    </div>
  );
}


function PlanningNotesDrawer({
  messages,
  message,
  setMessage,
  sendingMessage,
  onAddMessage,
  onClose,
}) {
  return (
    <div className="fixed inset-0 z-[80]">
      <button
        type="button"
        aria-label="Close planning notes"
        onClick={onClose}
        className="absolute inset-0 bg-black/30"
      />

      <div className="absolute bottom-0 right-0 top-0 flex w-full max-w-md flex-col border-l border-[#e7dfc9] bg-[#fbf7ee] shadow-2xl">
        <div className="flex items-center justify-between border-b border-[#e7dfc9] p-5">
          <div>
            <div className="flex items-center gap-2 font-semibold text-[#1f2a22]">
              <MessageSquare size={17} />
              Planning notes
            </div>

            <p className="mt-1 text-xs text-[#6a6a6a]">
              Add context before regenerating the strategy.
            </p>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="flex h-9 w-9 items-center justify-center rounded-full border border-[#e7dfc9] text-xl text-[#6a6a6a] hover:bg-[#f1ead8]"
          >
            ×
          </button>
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {messages.length === 0 && (
            <div className="rounded-xl bg-[#f1ead8] p-4 text-sm leading-6 text-[#6a6a6a]">
              Add upcoming events, available promotions,
              audiences, seasonal opportunities, or topics
              the strategist should avoid.
            </div>
          )}

          {messages.map((item) => (
            <div
              key={item.id}
              className={`rounded-xl p-3 text-sm ${
                item.role === "assistant"
                  ? "bg-[#e7efe9] text-[#254232]"
                  : "bg-[#e7efe9] text-[#254232]"
              }`}
            >
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider opacity-70">
                {item.role === "assistant"
                  ? "Strategist"
                  : item.created_by_name || "Team"}
              </div>

              <div className="whitespace-pre-wrap leading-6">
                {item.body}
              </div>

              <div className="mt-2 text-[10px] opacity-60">
                {formatDate(item.created_at)}
              </div>
            </div>
          ))}
        </div>

        <div className="border-t border-[#e7dfc9] p-4">
          <Textarea
            value={message}
            onChange={(event) =>
              setMessage(event.target.value)
            }
            rows={4}
            placeholder="Example: Football season begins in two weeks. Focus first on education and trust."
          />

          <Button
            type="button"
            onClick={onAddMessage}
            disabled={
              sendingMessage || !message.trim()
            }
            className="mt-3 w-full rounded-full bg-[#2f4a3a] text-[#f6f1e6]"
          >
            {sendingMessage ? (
              <Loader2
                size={15}
                className="mr-2 animate-spin"
              />
            ) : (
              <Send size={15} className="mr-2" />
            )}
            Save planning note
          </Button>
        </div>
      </div>
    </div>
  );
}


function StrategyPlan({ plan, strategyId }) {
  const { toast } = useToast();
  const [tab, setTab] = React.useState("execution");
  const [draftRequest, setDraftRequest] = React.useState(null);
  const [generatedDraft, setGeneratedDraft] = React.useState(null);
  const [draftLoading, setDraftLoading] = React.useState(false);
  const [savingDraft, setSavingDraft] = React.useState(false);
  const [selectedVariation, setSelectedVariation] = React.useState(0);
  const weeks = Array.isArray(plan.weekly_plan)
    ? plan.weekly_plan
    : [];

  const [weekIndex, setWeekIndex] = React.useState(0);

  const completionKey =
    `nms-content-hq-completed-${strategyId}`;

  const [completed, setCompleted] = React.useState(() => {
    try {
      return JSON.parse(
        window.localStorage.getItem(completionKey) || "{}"
      );
    } catch {
      return {};
    }
  });

  React.useEffect(() => {
    window.localStorage.setItem(
      completionKey,
      JSON.stringify(completed)
    );
  }, [completed, completionKey]);

  const toggleComplete = (id) => {
    setCompleted((current) => ({
      ...current,
      [id]: !current[id],
    }));
  };

  const openDraftGenerator = ({
    topic,
    contentType,
    platform,
    callToAction,
  }) => {
    setDraftRequest({
      topic: String(topic || "").trim(),
      contentType: contentType || "social_post",
      platform: platform || "",
      callToAction: callToAction || "",
    });
    setGeneratedDraft(null);
    setSelectedVariation(0);
  };

  const closeDraftGenerator = () => {
    if (draftLoading || savingDraft) return;
    setDraftRequest(null);
    setGeneratedDraft(null);
    setSelectedVariation(0);
  };

  const generateInlineDraft = async () => {
    if (!draftRequest?.topic) return;

    setDraftLoading(true);
    setGeneratedDraft(null);

    try {
      const response = await api.post(
        "/campaigns/ai-draft",
        {
          content_type: draftRequest.contentType,
          service_or_topic: draftRequest.topic,
          platform: draftRequest.platform || undefined,
          objective:
            "Create an implementation-ready content draft from the approved content strategy.",
          call_to_action:
            draftRequest.callToAction || undefined,
          requested_length:
            draftRequest.contentType === "video_prompt"
              ? "60 to 90 seconds with 6 to 10 detailed scenes"
              : undefined,
          tone:
            "Professional, educational, warm, premium, and non-pushy",
          compliance_notes:
            draftRequest.contentType === "video_prompt"
              ? "Create a full scene-by-scene AI video-generation prompt. Include timestamps, setting, action, camera direction, lighting, voiceover, on-screen text, sound, transitions, CTA, and a negative prompt. Avoid guarantees, cure claims, testimonials, invented outcomes, and individualized medical advice."
              : "Avoid guarantees, cure claims, invented statistics, individualized medical advice, and unapproved pricing or promotions.",
          number_of_variations:
            draftRequest.contentType === "video_prompt"
              ? 2
              : 3,
        }
      );

      setGeneratedDraft(response.data || null);
      setSelectedVariation(0);
    } catch (error) {
      toast({
        title: "Could not generate draft",
        description:
          getErrorMessage(error) ||
          "The AI draft could not be generated.",
        variant: "destructive",
      });
    } finally {
      setDraftLoading(false);
    }
  };

  const activeDraftCopy = React.useMemo(() => {
    if (!generatedDraft) return "";

    const variations = Array.isArray(
      generatedDraft.variations
    )
      ? generatedDraft.variations
      : [];

    return (
      variations[selectedVariation] ||
      generatedDraft.draft ||
      ""
    );
  }, [generatedDraft, selectedVariation]);

  const saveGeneratedAsset = async () => {
    if (!generatedDraft || !activeDraftCopy.trim()) return;

    setSavingDraft(true);

    try {
      const response = await api.post(
        "/content-assets",
        {
          strategy_id: strategyId,
          content_type: draftRequest.contentType,
          title:
            generatedDraft.title ||
            draftRequest.topic.slice(0, 200),
          body: activeDraftCopy,
          subject:
            Array.isArray(generatedDraft.subject_lines) &&
            generatedDraft.subject_lines.length > 0
              ? generatedDraft.subject_lines[0]
              : undefined,
          platform:
            draftRequest.platform || undefined,
          status: "draft",
          tags: [
            draftRequest.contentType,
            draftRequest.platform,
          ].filter(Boolean),
          metadata: {
            topic: draftRequest.topic,
            call_to_action:
              draftRequest.callToAction || "",
            source: "content_strategist",
            subject_lines:
              generatedDraft.subject_lines || [],
            calls_to_action:
              generatedDraft.calls_to_action || [],
            hashtags:
              generatedDraft.hashtags || [],
            compliance_notes:
              generatedDraft.compliance_notes || [],
            human_review_required: true,
          },
        }
      );

      toast({
        title: "Draft saved to Content Library",
        description:
          response.data?.title ||
          "The generated content was saved for review.",
      });

      closeDraftGenerator();
    } catch (error) {
      toast({
        title: "Could not save draft",
        description:
          getErrorMessage(error) ||
          "The generated draft could not be saved.",
        variant: "destructive",
      });
    } finally {
      setSavingDraft(false);
    }
  };

  const tabs = [
    { id: "execution", label: "Execution board" },
    { id: "calendar", label: "Calendar" },
    { id: "ideas", label: "Idea bank" },
    { id: "overview", label: "Strategy" },
    { id: "review", label: "Review" },
  ];

  const currentWeek = weeks[weekIndex] || null;

  const tasks = currentWeek
    ? buildWeekTasks(currentWeek, weekIndex)
    : [];

  const completedCount = tasks.filter(
    (task) => completed[task.id]
  ).length;

  return (
    <div className="min-w-0">
      <div className="mb-4 overflow-x-auto rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-2">
        <div className="flex min-w-max gap-2">
          {tabs.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              className={`rounded-full px-4 py-2 text-sm font-medium transition ${
                tab === item.id
                  ? "bg-[#2f4a3a] text-[#f6f1e6] shadow-sm"
                  : "text-[#6a6a6a] hover:bg-[#f1ead8] hover:text-[#2f4a3a]"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {tab === "execution" && (
        <div className="space-y-4">
          <div className="flex flex-col gap-3 rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="eyebrow text-[#8a6a3c]">
                Execution board
              </div>

              <h3 className="mt-1 font-display text-2xl text-[#1f2a22]">
                {currentWeek
                  ? `Week ${currentWeek.week || weekIndex + 1}: ${
                      currentWeek.theme || "Content plan"
                    }`
                  : "No weekly plan"}
              </h3>

              {currentWeek?.objective && (
                <p className="mt-1 max-w-3xl text-sm leading-6 text-[#6a6a6a]">
                  {currentWeek.objective}
                </p>
              )}
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={weekIndex <= 0}
                onClick={() =>
                  setWeekIndex((current) =>
                    Math.max(0, current - 1)
                  )
                }
                className="rounded-full border border-[#d8cba9] px-4 py-2 text-sm text-[#2f4a3a] disabled:opacity-40"
              >
                ← Previous
              </button>

              <button
                type="button"
                disabled={weekIndex >= weeks.length - 1}
                onClick={() =>
                  setWeekIndex((current) =>
                    Math.min(
                      weeks.length - 1,
                      current + 1
                    )
                  )
                }
                className="rounded-full border border-[#d8cba9] px-4 py-2 text-sm text-[#2f4a3a] disabled:opacity-40"
              >
                Next →
              </button>
            </div>
          </div>

          {tasks.length > 0 ? (
            <>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="text-sm text-[#6a6a6a]">
                  {completedCount} of {tasks.length} tasks complete
                </div>

                <div className="h-2 w-full max-w-xs overflow-hidden rounded-full bg-[#e7dfc9]">
                  <div
                    className="h-full rounded-full bg-[#2f4a3a] transition-all"
                    style={{
                      width: `${
                        tasks.length
                          ? (completedCount / tasks.length) * 100
                          : 0
                      }%`,
                    }}
                  />
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {tasks.map((task) => (
                  <ExecutionCard
                    key={task.id}
                    task={task}
                    completed={Boolean(completed[task.id])}
                    onToggle={() =>
                      toggleComplete(task.id)
                    }
                    onGenerate={() =>
                      openDraftGenerator(task)
                    }
                  />
                ))}
              </div>
            </>
          ) : (
            <EmptyPlanState text="No execution tasks were generated for this week." />
          )}
        </div>
      )}

      {tab === "calendar" && (
        <CalendarBoard
          items={plan.content_calendar}
          strategyId={strategyId}
          completed={completed}
          onToggle={toggleComplete}
          onGenerate={openDraftGenerator}
        />
      )}

      {tab === "ideas" && (
        <IdeaBank
          plan={plan}
          onGenerate={openDraftGenerator}
        />
      )}

      {tab === "overview" && (
        <div className="grid gap-4 xl:grid-cols-2">
          <PlanSection icon={Target} title="Executive strategy">
            <p className="whitespace-pre-wrap text-sm leading-7 text-[#3a3a3a]">
              {plan.executive_summary ||
                "No executive summary was generated."}
            </p>
          </PlanSection>

          <PlanSection icon={Target} title="Positioning">
            <p className="whitespace-pre-wrap text-sm leading-7 text-[#3a3a3a]">
              {plan.positioning ||
                "No positioning statement was generated."}
            </p>
          </PlanSection>

          <ListSection
            title="Campaign themes"
            items={plan.campaign_themes}
          />

          <ListSection
            title="Audience insights"
            items={plan.audience_insights}
          />

          <ListSection
            title="Recommended offers"
            items={plan.recommended_offers}
          />

          <ListSection
            title="Next actions"
            items={plan.next_actions}
          />
        </div>
      )}

      {tab === "review" && (
        <div className="grid gap-4 xl:grid-cols-2">
          <ListSection
            title="Success metrics"
            items={plan.success_metrics}
          />

          <ListSection
            title="Compliance considerations"
            items={plan.compliance_considerations}
          />

          <div className="xl:col-span-2 rounded-2xl border border-[#d9a6a6] bg-[#fff4f4] p-5 text-sm leading-6 text-[#7a2a2a]">
            AI-generated strategy. Verify every service,
            promotion, statistic, credential, health claim,
            offer, price, and disclaimer before publishing.
          </div>
        </div>
      )}

      {draftRequest && (
        <InlineDraftGenerator
          request={draftRequest}
          draft={generatedDraft}
          loading={draftLoading}
          saving={savingDraft}
          selectedVariation={selectedVariation}
          setSelectedVariation={setSelectedVariation}
          activeCopy={activeDraftCopy}
          onGenerate={generateInlineDraft}
          onSave={saveGeneratedAsset}
          onClose={closeDraftGenerator}
        />
      )}
    </div>
  );
}


function InlineDraftGenerator({
  request,
  draft,
  loading,
  saving,
  selectedVariation,
  setSelectedVariation,
  activeCopy,
  onGenerate,
  onSave,
  onClose,
}) {
  const { toast } = useToast();

  const variations = Array.isArray(draft?.variations)
    ? draft.variations
    : [];

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center p-4">
      <button
        type="button"
        aria-label="Close draft generator"
        onClick={onClose}
        className="absolute inset-0 bg-[#1f2a22]/45"
      />

      <div className="relative z-10 flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-3xl border border-[#d8cba9] bg-[#fbf7ee] shadow-2xl">
        <div className="flex items-start justify-between border-b border-[#e7dfc9] p-5">
          <div className="min-w-0">
            <div className="inline-flex rounded-full border border-[#d8cba9] bg-[#f6f1e6] px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-[#8a6a3c]">
              AI Content Studio
            </div>

            <h3 className="mt-3 font-display text-2xl text-[#1f2a22]">
              {request.topic}
            </h3>

            <div className="mt-2 flex flex-wrap gap-2">
              <span className="rounded-full bg-[#e7efe9] px-3 py-1 text-xs capitalize text-[#2f4a3a]">
                {request.contentType.replace(/_/g, " ")}
              </span>

              {request.platform && (
                <span className="rounded-full bg-[#f1ead8] px-3 py-1 text-xs capitalize text-[#8a6a3c]">
                  {request.platform}
                </span>
              )}
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            disabled={loading || saving}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[#d8cba9] text-xl text-[#6a6a6a] hover:bg-[#f1ead8]"
          >
            ×
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {!draft && !loading && (
            <div className="rounded-2xl border border-dashed border-[#c8b990] bg-white p-10 text-center">
              <Sparkles
                size={32}
                className="mx-auto text-[#2f4a3a]"
              />

              <h4 className="mt-4 font-semibold text-[#1f2a22]">
                Ready to create this content
              </h4>

              <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-[#6a6a6a]">
                The strategist will create three draft options.
                Nothing will be sent or published automatically.
              </p>

              <Button
                type="button"
                onClick={onGenerate}
                className="mt-5 rounded-full bg-[#2f4a3a] px-6 text-[#f6f1e6] hover:bg-[#263d30]"
              >
                <Sparkles size={15} className="mr-2" />
                Generate content
              </Button>
            </div>
          )}

          {loading && (
            <div className="p-12 text-center">
              <Loader2
                size={28}
                className="mx-auto animate-spin text-[#2f4a3a]"
              />

              <div className="mt-4 font-medium text-[#1f2a22]">
                Creating your draft…
              </div>

              <div className="mt-1 text-sm text-[#6a6a6a]">
                This may take a moment.
              </div>
            </div>
          )}

          {draft && !loading && (
            <div className="space-y-4">
              {variations.length > 1 && (
                <div className="flex flex-wrap gap-2">
                  {variations.map((_, index) => (
                    <button
                      key={index}
                      type="button"
                      onClick={() =>
                        setSelectedVariation(index)
                      }
                      className={`rounded-full border px-4 py-2 text-sm ${
                        selectedVariation === index
                          ? "border-[#2f4a3a] bg-[#2f4a3a] text-[#f6f1e6]"
                          : "border-[#d8cba9] bg-white text-[#6a6a6a] hover:bg-[#f1ead8]"
                      }`}
                    >
                      Option {index + 1}
                    </button>
                  ))}
                </div>
              )}

              {Array.isArray(draft.subject_lines) &&
                draft.subject_lines.length > 0 && (
                  <div className="rounded-2xl border border-[#e7dfc9] bg-white p-4">
                    <div className="text-xs font-semibold uppercase tracking-wider text-[#8a6a3c]">
                      Suggested subject
                    </div>

                    <div className="mt-2 font-medium text-[#1f2a22]">
                      {draft.subject_lines[0]}
                    </div>
                  </div>
                )}

              <div className="rounded-2xl border border-[#e7dfc9] bg-white p-5">
                <div className="text-xs font-semibold uppercase tracking-wider text-[#8a6a3c]">
                  Draft
                </div>

                <div className="mt-3 whitespace-pre-wrap text-sm leading-7 text-[#3a3a3a]">
                  {activeCopy ||
                    "The model did not return draft copy."}
                </div>
              </div>

              {Array.isArray(draft.hashtags) &&
                draft.hashtags.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {draft.hashtags.map((tag, index) => (
                      <span
                        key={index}
                        className="rounded-full bg-[#e7efe9] px-3 py-1 text-xs text-[#2f4a3a]"
                      >
                        {String(tag).startsWith("#")
                          ? tag
                          : `#${tag}`}
                      </span>
                    ))}
                  </div>
                )}

              <div className="rounded-2xl border border-[#d8cba9] bg-[#f6f1e6] p-4 text-xs leading-5 text-[#6a6a6a]">
                Human review is required. Verify all claims,
                services, offers, pricing, credentials, and
                disclaimers before publishing.
              </div>
            </div>
          )}
        </div>

        <div className="flex flex-wrap justify-end gap-2 border-t border-[#e7dfc9] p-4">
          <Button
            type="button"
            variant="outline"
            onClick={onClose}
            disabled={loading || saving}
            className="rounded-full"
          >
            Close
          </Button>

          {draft && (
            <>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  navigator.clipboard?.writeText(
                    activeCopy
                  );
                  toast({
                    title: "Draft copied",
                  });
                }}
                className="rounded-full"
              >
                Copy
              </Button>

              <Button
                type="button"
                variant="outline"
                onClick={onGenerate}
                disabled={loading || saving}
                className="rounded-full"
              >
                <RefreshCw size={14} className="mr-2" />
                Regenerate
              </Button>

              <Button
                type="button"
                onClick={onSave}
                disabled={
                  saving || !activeCopy.trim()
                }
                className="rounded-full bg-[#2f4a3a] px-5 text-[#f6f1e6] hover:bg-[#263d30]"
              >
                {saving ? (
                  <Loader2
                    size={14}
                    className="mr-2 animate-spin"
                  />
                ) : (
                  <FileText size={14} className="mr-2" />
                )}
                Save to Content Library
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}


function buildWeekTasks(week, weekIndex) {
  const groups = [
    {
      key: "email_topics",
      label: "Email",
      contentType: "email",
      platform: "email",
    },
    {
      key: "social_topics",
      label: "Social",
      contentType: "social_post",
      platform: "social media",
    },
    {
      key: "blog_topics",
      label: "Blog",
      contentType: "blog_article",
      platform: "blog",
    },
    {
      key: "video_topics",
      label: "Video",
      contentType: "video_prompt",
      platform: "short-form vertical video",
    },
  ];

  const callsToAction = Array.isArray(week.calls_to_action)
    ? week.calls_to_action
    : [];

  const output = [];

  groups.forEach((group) => {
    const items = Array.isArray(week[group.key])
      ? week[group.key]
      : [];

    items.forEach((topic, index) => {
      output.push({
        id: `week-${weekIndex}-${group.key}-${index}`,
        channel: group.label,
        topic,
        contentType: group.contentType,
        platform: group.platform,
        callToAction:
          callsToAction[index] ||
          callsToAction[0] ||
          "",
      });
    });
  });

  return output;
}


function ExecutionCard({
  task,
  completed,
  onToggle,
  onGenerate,
}) {
  return (
    <article
      className={`flex min-h-[220px] flex-col rounded-2xl border p-4 transition ${
        completed
          ? "border-[#b8cfbe] bg-[#f1f7f2]"
          : "border-[#e7dfc9] bg-[#fbf7ee] hover:border-[#c8b990]"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <span className="rounded-full border border-[#d8cba9] bg-[#f6f1e6] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-[#8a6a3c]">
          {task.channel}
        </span>

        <button
          type="button"
          onClick={onToggle}
          className={`flex h-7 w-7 items-center justify-center rounded-full border ${
            completed
              ? "border-[#2f4a3a] bg-[#2f4a3a] text-white"
              : "border-[#c8b990] text-transparent hover:text-[#2f4a3a]"
          }`}
          aria-label={
            completed
              ? "Mark incomplete"
              : "Mark complete"
          }
        >
          ✓
        </button>
      </div>

      <h4
        className={`mt-4 text-base font-semibold leading-6 ${
          completed
            ? "text-[#5f7264] line-through"
            : "text-[#1f2a22]"
        }`}
      >
        {task.topic}
      </h4>

      {task.callToAction && (
        <div className="mt-3 text-xs leading-5 text-[#6a6a6a]">
          <span className="font-semibold text-[#8a6a3c]">
            CTA:
          </span>{" "}
          {task.callToAction}
        </div>
      )}

      <div className="mt-auto flex gap-2 pt-5">
        <Button
          type="button"
          onClick={onGenerate}
          className="flex-1 rounded-full bg-[#2f4a3a] text-[#f6f1e6] shadow-sm hover:bg-[#263d30]"
        >
          <Sparkles size={14} className="mr-2" />
          {task.contentType === "video_prompt"
            ? "Generate video prompt"
            : "Generate draft"}
        </Button>

        <Button
          type="button"
          variant="outline"
          onClick={onToggle}
          className="rounded-full"
        >
          {completed ? "Reopen" : "Complete"}
        </Button>
      </div>
    </article>
  );
}


function CalendarBoard({
  items,
  strategyId,
  completed,
  onToggle,
  onGenerate,
}) {
  const safeItems = Array.isArray(items) ? items : [];

  if (safeItems.length === 0) {
    return (
      <EmptyPlanState text="No calendar items were generated." />
    );
  }

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {safeItems.map((item, index) => {
        const id = `calendar-${strategyId}-${index}`;

        return (
          <article
            key={id}
            className={`rounded-2xl border p-4 ${
              completed[id]
                ? "border-[#b8cfbe] bg-[#f1f7f2]"
                : "border-[#e7dfc9] bg-[#fbf7ee]"
            }`}
          >
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs font-semibold uppercase tracking-wider text-[#8a6a3c]">
                {item.day_or_date || `Item ${index + 1}`}
              </span>

              <span className="rounded-full bg-[#e7efe9] px-2 py-1 text-[10px] capitalize text-[#2f4a3a]">
                {item.channel || "content"}
              </span>
            </div>

            <h4 className="mt-3 font-semibold leading-6 text-[#1f2a22]">
              {item.topic || "Untitled content item"}
            </h4>

            {item.objective && (
              <p className="mt-2 text-sm leading-6 text-[#6a6a6a]">
                {item.objective}
              </p>
            )}

            <div className="mt-4 flex gap-2">
              <Button
                type="button"
                size="sm"
                onClick={() =>
                  onGenerate({
                    topic: item.topic,
                    contentType:
                      item.content_type || "social_post",
                    platform: item.channel || "",
                    callToAction:
                      item.call_to_action || "",
                  })
                }
                className="rounded-full bg-[#2f4a3a] text-[#f6f1e6] hover:bg-[#263d30]"
              >
                Generate
              </Button>

              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => onToggle(id)}
                className="rounded-full"
              >
                {completed[id] ? "Reopen" : "Complete"}
              </Button>
            </div>
          </article>
        );
      })}
    </div>
  );
}


function IdeaBank({ plan, onGenerate }) {
  const groups = [
    {
      title: "Email campaigns",
      items: plan.email_campaign_ideas,
      contentType: "email",
      platform: "email",
    },
    {
      title: "Social series",
      items: plan.social_series_ideas,
      contentType: "social_series",
      platform: "social media",
    },
    {
      title: "Blog ideas",
      items: plan.blog_ideas,
      contentType: "blog_article",
      platform: "blog",
    },
    {
      title: "Video ideas",
      items: plan.short_video_ideas,
      contentType: "video_prompt",
      platform: "short-form vertical video",
    },
  ];

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      {groups.map((group) => (
        <section
          key={group.title}
          className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5"
        >
          <h3 className="font-display text-xl text-[#1f2a22]">
            {group.title}
          </h3>

          <div className="mt-4 space-y-3">
            {(Array.isArray(group.items)
              ? group.items
              : []
            ).map((item, index) => (
              <div
                key={index}
                className="flex items-start justify-between gap-3 rounded-xl border border-[#e7dfc9] bg-white p-3"
              >
                <div className="text-sm leading-6 text-[#3a3a3a]">
                  {item}
                </div>

                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    onGenerate({
                      topic: item,
                      contentType: group.contentType,
                      platform: group.platform,
                      callToAction: "",
                    })
                  }
                  className="shrink-0 rounded-full"
                >
                  Generate
                </Button>
              </div>
            ))}

            {(!Array.isArray(group.items) ||
              group.items.length === 0) && (
              <div className="text-sm text-[#8a8a8a]">
                No ideas generated.
              </div>
            )}
          </div>
        </section>
      ))}
    </div>
  );
}


function EmptyPlanState({ text }) {
  return (
    <div className="rounded-2xl border border-dashed border-[#d8cba9] bg-[#fbf7ee] p-10 text-center text-sm text-[#6a6a6a]">
      {text}
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <Label>{label}</Label>
      <div className="mt-1">{children}</div>
    </div>
  );
}

function SummaryCard({ label, value }) {
  return (
    <div className="rounded-xl bg-[#f1ead8] p-4">
      <div className="text-xs uppercase tracking-wider text-[#8a6a3c]">
        {label}
      </div>

      <div className="mt-1 font-semibold text-[#1f2a22]">
        {value}
      </div>
    </div>
  );
}

function PlanSection({ icon: Icon, title, children }) {
  return (
    <section className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5">
      <div className="mb-4 flex items-center gap-2">
        {Icon && <Icon size={18} className="text-[#2f4a3a]" />}

        <h3 className="font-display text-xl text-[#1f2a22]">
          {title}
        </h3>
      </div>

      {children}
    </section>
  );
}

function ListSection({ title, items }) {
  return (
    <PlanSection icon={FileText} title={title}>
      <MiniList items={items} />
    </PlanSection>
  );
}

function MiniList({ label, items }) {
  const safeItems = Array.isArray(items) ? items : [];

  if (safeItems.length === 0) {
    return (
      <div className="text-sm text-[#8a8a8a]">
        {label ? `${label}: ` : ""}
        No recommendations generated.
      </div>
    );
  }

  return (
    <div>
      {label && (
        <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-[#8a6a3c]">
          {label}
        </div>
      )}

      <ul className="space-y-2">
        {safeItems.map((item, index) => (
          <li
            key={index}
            className="flex gap-2 text-sm leading-6 text-[#3a3a3a]"
          >
            <CheckCircle2
              size={14}
              className="mt-1.5 shrink-0 text-[#2f4a3a]"
            />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
