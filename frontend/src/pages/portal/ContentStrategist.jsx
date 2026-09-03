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
import { normalizeArray } from "../../lib/collections";

const INITIAL_FORM = {
  name: "",
  goal: "",
  services: "",
  audiences: "",
  brand_voice: "Educational, professional, premium, warm, non-pushy",
  channels: "email, instagram, facebook, tiktok, blog",
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

            {normalizeArray(strategies).map((strategy) => {
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
            placeholder="email, instagram, facebook, tiktok, blog"
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

  const [contentAssets, setContentAssets] = React.useState([]);
  const [loadingAssets, setLoadingAssets] = React.useState(false);
  const [assetActionId, setAssetActionId] = React.useState(null);
  const [editingAsset, setEditingAsset] = React.useState(null);
  const [generatingWeek, setGeneratingWeek] = React.useState(false);

  // Content Library review controls.
  const [libraryWeekFilter, setLibraryWeekFilter] =
    React.useState("all");
  const [libraryTypeFilter, setLibraryTypeFilter] =
    React.useState("all");
  const [libraryStatusFilter, setLibraryStatusFilter] =
    React.useState("all");
  const [selectedAssetIds, setSelectedAssetIds] =
    React.useState([]);
  const [bulkAssetAction, setBulkAssetAction] =
    React.useState(null);

  // Publishing Queue controls.
  const [publishingQueue, setPublishingQueue] =
    React.useState([]);
  const [
    loadingPublishingQueue,
    setLoadingPublishingQueue,
  ] = React.useState(false);
  const [
    publishingQueueActionId,
    setPublishingQueueActionId,
  ] = React.useState(null);

  const [
    publishingScheduleInputs,
    setPublishingScheduleInputs,
  ] = React.useState({});

  const [
    publishingStatusFilter,
    setPublishingStatusFilter,
  ] = React.useState("all");

  const [
    publishingPlatformFilter,
    setPublishingPlatformFilter,
  ] = React.useState("all");

  const filteredPublishingQueue = React.useMemo(
    () =>
      normalizeArray(publishingQueue).filter(
        (item) => {
          const statusMatches =
            publishingStatusFilter === "all" ||
            item?.status ===
              publishingStatusFilter;

          const platformMatches =
            publishingPlatformFilter === "all" ||
            String(
              item?.platform || ""
            ).toLowerCase() ===
              publishingPlatformFilter;

          return (
            statusMatches &&
            platformMatches
          );
        }
      ),
    [
      publishingQueue,
      publishingStatusFilter,
      publishingPlatformFilter,
    ]
  );

  const loadPublishingQueue = React.useCallback(
    async () => {
      setLoadingPublishingQueue(true);

      try {
        const response = await api.get(
          "/publishing-queue",
          {
            params: {
              strategy_id: strategyId,
              limit: 200,
            },
          }
        );

        setPublishingQueue(
          normalizeArray(response.data)
        );
      } catch (error) {
        toast({
          title: "Could not load Publishing Queue",
          description:
            getErrorMessage(error) ||
            "Publishing Queue could not be loaded.",
          variant: "destructive",
        });
      } finally {
        setLoadingPublishingQueue(false);
      }
    },
    [strategyId, toast]
  );

  const sendAssetToPublishingQueue = async (
    asset
  ) => {
    if (
      !asset?.id ||
      publishingQueueActionId
    ) {
      return;
    }

    setPublishingQueueActionId(asset.id);

    try {
      const response = await api.post(
        `/content-assets/${asset.id}/publishing-queue`,
        {
          platform:
            asset.platform ||
            asset.metadata?.strategy_source
              ?.channel ||
            null,
        }
      );

      toast({
        title: "Added to Publishing Queue",
        description:
          asset.title ||
          "Approved content was added to the queue.",
      });

      await loadPublishingQueue();

      if (response.data) {
        setTab("publishing");
      }
    } catch (error) {
      toast({
        title: "Could not add to Publishing Queue",
        description:
          getErrorMessage(error) ||
          "The approved content could not be queued.",
        variant: "destructive",
      });
    } finally {
      setPublishingQueueActionId(null);
    }
  };

  const publishingLocalDateTime = (
    value
  ) => {
    if (!value) return "";

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
      return "";
    }

    const offset =
      date.getTimezoneOffset() * 60 * 1000;

    return new Date(
      date.getTime() - offset
    )
      .toISOString()
      .slice(0, 16);
  };

  const schedulePublishingItem = async (
    queueItem,
    scheduledAt
  ) => {
    if (
      !queueItem?.id ||
      !scheduledAt ||
      publishingQueueActionId
    ) {
      return;
    }

    setPublishingQueueActionId(queueItem.id);

    try {
      const scheduledDate = new Date(scheduledAt);

      if (Number.isNaN(scheduledDate.getTime())) {
        throw new Error(
          "Please choose a valid publishing date and time."
        );
      }

      if (scheduledDate.getTime() <= Date.now()) {
        throw new Error(
          "Publishing must be scheduled for a future date and time."
        );
      }

      await api.patch(
        `/publishing-queue/${queueItem.id}/schedule`,
        {
          scheduled_at: scheduledDate.toISOString(),
        }
      );

      toast({
        title: "Publishing scheduled",
        description:
          queueItem.title ||
          "The content has been scheduled.",
      });

      setPublishingScheduleInputs(
        (current) => {
          const next = { ...current };
          delete next[queueItem.id];
          return next;
        }
      );

      await loadPublishingQueue();
    } catch (error) {
      toast({
        title: "Could not schedule content",
        description:
          getErrorMessage(error) ||
          "The publishing date could not be saved.",
        variant: "destructive",
      });
    } finally {
      setPublishingQueueActionId(null);
    }
  };

  const retryFailedPublishingItem = async (
    queueItem
  ) => {
    if (
      !queueItem?.id ||
      publishingQueueActionId
    ) {
      return;
    }

    setPublishingQueueActionId(queueItem.id);

    try {
      await api.post(
        `/publishing-queue/${queueItem.id}/retry`
      );

      toast({
        title: "Publishing retry scheduled",
        description:
          queueItem.title ||
          "The failed item has been returned to the publishing worker.",
      });

      await loadPublishingQueue();
    } catch (error) {
      toast({
        title: "Could not retry publishing",
        description:
          getErrorMessage(error) ||
          "The failed publishing item could not be retried.",
        variant: "destructive",
      });
    } finally {
      setPublishingQueueActionId(null);
    }
  };

  const requeuePublishingItem = async (
    queueItem
  ) => {
    if (
      !queueItem?.id ||
      publishingQueueActionId
    ) {
      return;
    }

    setPublishingQueueActionId(queueItem.id);

    try {
      await api.post(
        `/publishing-queue/${queueItem.id}/requeue`
      );

      toast({
        title: "Content returned to queue",
        description:
          queueItem.title ||
          "The cancelled item is ready to schedule again.",
      });

      await loadPublishingQueue();
    } catch (error) {
      toast({
        title: "Could not requeue content",
        description:
          getErrorMessage(error) ||
          "The cancelled publishing item could not be restored.",
        variant: "destructive",
      });
    } finally {
      setPublishingQueueActionId(null);
    }
  };

  const cancelPublishingItem = async (
    queueItem
  ) => {
    if (
      !queueItem?.id ||
      publishingQueueActionId
    ) {
      return;
    }

    setPublishingQueueActionId(queueItem.id);

    try {
      await api.post(
        `/publishing-queue/${queueItem.id}/cancel`
      );

      toast({
        title: "Publishing item cancelled",
        description:
          "The content remains available in the Content Library.",
      });

      await loadPublishingQueue();
    } catch (error) {
      toast({
        title: "Could not cancel publishing item",
        description:
          getErrorMessage(error) ||
          "The publishing item could not be cancelled.",
        variant: "destructive",
      });
    } finally {
      setPublishingQueueActionId(null);
    }
  };

  const filteredContentAssets = React.useMemo(() => {
    return normalizeArray(contentAssets).filter((asset) => {
      const source =
        asset?.metadata?.strategy_source || {};

      const rawWeekIndex =
        asset?.generated_from_week_index ??
        source?.week_index;

      const weekMatches =
        libraryWeekFilter === "all" ||
        String(rawWeekIndex) === libraryWeekFilter;

      const typeMatches =
        libraryTypeFilter === "all" ||
        asset?.content_type === libraryTypeFilter;

      const statusMatches =
        libraryStatusFilter === "all" ||
        (asset?.status || "draft") ===
          libraryStatusFilter;

      return (
        weekMatches &&
        typeMatches &&
        statusMatches
      );
    });
  }, [
    contentAssets,
    libraryWeekFilter,
    libraryTypeFilter,
    libraryStatusFilter,
  ]);

  const visibleAssetIds = React.useMemo(
    () =>
      filteredContentAssets
        .map((asset) => asset?.id)
        .filter(Boolean),
    [filteredContentAssets]
  );

  const allVisibleAssetsSelected =
    visibleAssetIds.length > 0 &&
    visibleAssetIds.every((id) =>
      selectedAssetIds.includes(id)
    );

  const toggleAssetSelection = (assetId) => {
    if (!assetId || bulkAssetAction) return;

    setSelectedAssetIds((current) =>
      current.includes(assetId)
        ? current.filter((id) => id !== assetId)
        : [...current, assetId]
    );
  };

  const toggleAllVisibleAssets = () => {
    if (bulkAssetAction) return;

    if (allVisibleAssetsSelected) {
      setSelectedAssetIds((current) =>
        current.filter(
          (id) => !visibleAssetIds.includes(id)
        )
      );
      return;
    }

    setSelectedAssetIds((current) =>
      Array.from(
        new Set([
          ...current,
          ...visibleAssetIds,
        ])
      )
    );
  };

  const clearAssetSelection = () => {
    if (bulkAssetAction) return;
    setSelectedAssetIds([]);
  };


  React.useEffect(() => {
    setSelectedAssetIds([]);
  }, [
    libraryWeekFilter,
    libraryTypeFilter,
    libraryStatusFilter,
  ]);

  const bulkUpdateAssetStatus = async (status) => {
    if (
      bulkAssetAction ||
      selectedAssetIds.length === 0
    ) {
      return;
    }

    const ids = [...selectedAssetIds];
    setBulkAssetAction(status);

    let succeeded = 0;
    const failed = [];

    try {
      for (const assetId of ids) {
        try {
          await api.patch(
            `/content-assets/${assetId}/status`,
            { status }
          );
          succeeded += 1;
        } catch (error) {
          failed.push({
            assetId,
            error: getErrorMessage(error),
          });
        }
      }

      toast({
        title:
          status === "approved"
            ? "Selected content approved"
            : "Selected content rejected",
        description:
          `${succeeded} updated` +
          (failed.length
            ? `, ${failed.length} failed.`
            : "."),
        variant:
          failed.length > 0
            ? "destructive"
            : undefined,
      });

      setSelectedAssetIds(
        failed.map((item) => item.assetId)
      );

      await loadContentAssets();
    } finally {
      setBulkAssetAction(null);
    }
  };

  const generateCurrentWeek = async () => {
    if (generatingWeek) return;

    setGeneratingWeek(true);

    try {
      const response = await api.post(
        `/content-strategies/${strategyId}/generate-week`,
        {
          week_index: weekIndex,
        }
      );

      const result = response.data || {};

      toast({
        title: "Weekly drafts generated",
        description:
          `${result.created_count || 0} created, ` +
          `${result.skipped_count || 0} skipped, ` +
          `${result.error_count || 0} errors.`,
      });

      await loadContentAssets();
      setTab("library");
    } catch (error) {
      toast({
        title: "Could not generate weekly drafts",
        description:
          getErrorMessage(error) ||
          "The weekly content batch could not be generated.",
        variant: "destructive",
      });
    } finally {
      setGeneratingWeek(false);
    }
  };

  const loadContentAssets = React.useCallback(async () => {
    if (!strategyId) return;

    setLoadingAssets(true);

    try {
      const response = await api.get(
        "/content-assets",
        {
          params: {
            strategy_id: strategyId,
            limit: 200,
          },
        }
      );

      setContentAssets(
        Array.isArray(response.data)
          ? response.data
          : []
      );
    } catch (error) {
      toast({
        title: "Could not load Content Library",
        description:
          getErrorMessage(error) ||
          "The saved content drafts could not be loaded.",
        variant: "destructive",
      });
    } finally {
      setLoadingAssets(false);
    }
  }, [strategyId, toast]);

  const updateAssetStatus = async (assetId, status) => {
    if (!assetId || assetActionId) return;

    setAssetActionId(assetId);

    try {
      await api.patch(
        `/content-assets/${assetId}/status`,
        { status }
      );

      toast({
        title:
          status === "approved"
            ? "Content approved"
            : "Content rejected",
        description:
          status === "approved"
            ? "This draft is approved and can now be prepared for the website."
            : "This draft has been marked as rejected.",
      });

      await loadContentAssets();
    } catch (error) {
      toast({
        title: "Could not update content",
        description:
          getErrorMessage(error) ||
          "The content status could not be updated.",
        variant: "destructive",
      });
    } finally {
      setAssetActionId(null);
    }
  };

  const prepareAssetForWebsite = async (assetId) => {
    if (!assetId || assetActionId) return;

    setAssetActionId(assetId);

    try {
      const response = await api.post(
        `/content-assets/${assetId}/website-export`
      );

      toast({
        title: "Prepared for website",
        description:
          response.data?.batch_id
            ? `S3 batch ${response.data.batch_id} was created.`
            : "The approved content was written to the website handoff bucket.",
      });

      await loadContentAssets();
    } catch (error) {
      toast({
        title: "Could not prepare website content",
        description:
          getErrorMessage(error) ||
          "The content could not be written to the website handoff bucket.",
        variant: "destructive",
      });
    } finally {
      setAssetActionId(null);
    }
  };

  const openAssetEditor = (asset) => {
    const metadata = asset?.metadata || {};
    const seo = metadata?.seo || {};

    setEditingAsset({
      id: asset.id,
      title: asset.title || "",
      body: asset.body || "",
      subject: asset.subject || "",
      platform: asset.platform || "",
      tags: Array.isArray(asset.tags)
        ? asset.tags.join(", ")
        : "",
      metadata: {
        ...metadata,
        slug: metadata.slug || "",
        summary: metadata.summary || "",
        category: metadata.category || "",
        publish_date: metadata.publish_date || "",
        seo: {
          ...seo,
          title: seo.title || "",
          description: seo.description || "",
        },
      },
    });
  };

  const closeAssetEditor = () => {
    if (assetActionId) return;
    setEditingAsset(null);
  };

  const saveAssetEdits = async () => {
    if (!editingAsset?.id || assetActionId) return;

    if (!editingAsset.title.trim()) {
      toast({
        title: "Title required",
        variant: "destructive",
      });
      return;
    }

    if (!editingAsset.body.trim()) {
      toast({
        title: "Content required",
        variant: "destructive",
      });
      return;
    }

    setAssetActionId(editingAsset.id);

    try {
      const response = await api.patch(
        `/content-assets/${editingAsset.id}`,
        {
          title: editingAsset.title.trim(),
          body: editingAsset.body,
          subject:
            editingAsset.subject.trim() || null,
          platform:
            editingAsset.platform.trim() || null,
          tags: editingAsset.tags
            .split(",")
            .map((value) => value.trim())
            .filter(Boolean),
          metadata: editingAsset.metadata,
        }
      );

      toast({
        title: "Content updated",
        description:
          "Your changes were saved. The asset returned to draft status for review.",
      });

      setEditingAsset(null);
      await loadContentAssets();

      return response.data;
    } catch (error) {
      toast({
        title: "Could not save changes",
        description:
          getErrorMessage(error) ||
          "The content could not be updated.",
        variant: "destructive",
      });
    } finally {
      setAssetActionId(null);
    }
  };

  React.useEffect(() => {
    loadContentAssets();
  }, [loadContentAssets]);


  React.useEffect(() => {
    loadPublishingQueue();
  }, [loadPublishingQueue]);
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
    calendarIndex = null,
  }) => {
    setDraftRequest({
      topic: String(topic || "").trim(),
      contentType: contentType || "social_post",
      platform: platform || "",
      callToAction: callToAction || "",
      calendarIndex,
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
      const rawType = String(
        draftRequest.contentType || ""
      ).toLowerCase();

      const rawPlatform = String(
        draftRequest.platform || ""
      ).toLowerCase();

      let canonicalAssetType = null;

      if (
        rawType.includes("blog") ||
        rawPlatform === "blog"
      ) {
        canonicalAssetType = "blog_post";
      } else if (
        rawType.includes("newsletter") ||
        rawType === "email" ||
        rawPlatform === "email"
      ) {
        canonicalAssetType =
          "newsletter_spotlight";
      } else if (
        rawType.includes("package")
      ) {
        canonicalAssetType = "package";
      }

      const hasCalendarIndex =
        Number.isInteger(
          draftRequest.calendarIndex
        );

      if (
        canonicalAssetType &&
        hasCalendarIndex
      ) {
        const response = await api.post(
          `/content-strategies/${strategyId}/generate-asset`,
          {
            calendar_index:
              draftRequest.calendarIndex,
            asset_type:
              canonicalAssetType,
          }
        );

        const asset =
          response.data?.asset || null;

        if (!asset?.id) {
          throw new Error(
            "The content draft was not saved."
          );
        }

        setGeneratedDraft({
          canonicalAsset: true,
          asset,
          title: asset.title || "",
          draft: asset.body || "",
          variations: [],
          subject_lines:
            asset.subject
              ? [asset.subject]
              : [],
          hashtags: [],
        });

        setSelectedVariation(0);

        toast({
          title: "Content draft created",
          description:
            "Saved to the Content Library as a draft for human review.",
        });

        return;
      }

      const response = await api.post(
        "/campaigns/ai-draft",
        {
          content_type:
            draftRequest.contentType,
          service_or_topic:
            draftRequest.topic,
          platform:
            draftRequest.platform ||
            undefined,
          objective:
            "Create an implementation-ready content draft from the approved content strategy.",
          call_to_action:
            draftRequest.callToAction ||
            undefined,
          requested_length:
            draftRequest.contentType ===
            "video_prompt"
              ? "60 to 90 seconds with 6 to 10 detailed scenes"
              : undefined,
          tone:
            "Professional, educational, warm, premium, and non-pushy",
          compliance_notes:
            draftRequest.contentType ===
            "video_prompt"
              ? "Create a full scene-by-scene AI video-generation prompt. Include timestamps, setting, action, camera direction, lighting, voiceover, on-screen text, sound, transitions, CTA, and a negative prompt. Avoid guarantees, cure claims, testimonials, invented outcomes, and individualized medical advice."
              : "Avoid guarantees, cure claims, invented statistics, individualized medical advice, and unapproved pricing or promotions.",
          number_of_variations:
            draftRequest.contentType ===
            "video_prompt"
              ? 2
              : 3,
        }
      );

      setGeneratedDraft(
        response.data || null
      );
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

    if (generatedDraft.canonicalAsset) {
      toast({
        title: "Draft already saved",
        description:
          "This content is already in the Content Library and is awaiting human review.",
      });

      closeDraftGenerator();
      return;
    }

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
    {
      id: "library",
      label: `Content Library (${contentAssets.length})`,
    },
    {
      id: "publishing",
      label: `Publishing Queue (${publishingQueue.length})`,
    },
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

            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                onClick={generateCurrentWeek}
                disabled={generatingWeek || !currentWeek}
                className="rounded-full bg-[#2f4a3a] text-[#f6f1e6] hover:bg-[#263d30]"
              >
                {generatingWeek ? (
                  <Loader2
                    size={15}
                    className="mr-2 animate-spin"
                  />
                ) : (
                  <Sparkles
                    size={15}
                    className="mr-2"
                  />
                )}
                Generate This Week
              </Button>

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

      {tab === "library" && (
        <div className="space-y-4">
          <div className="flex flex-col gap-3 rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="eyebrow text-[#8a6a3c]">
                Content Library
              </div>

              <h3 className="mt-1 font-display text-2xl text-[#1f2a22]">
                Review generated content
              </h3>

              <p className="mt-1 max-w-3xl text-sm leading-6 text-[#6a6a6a]">
                AI-generated content stays in draft status
                until a staff member reviews and approves it.
              </p>
            </div>

            <Button
              type="button"
              variant="outline"
              onClick={loadContentAssets}
              disabled={loadingAssets}
              className="rounded-full"
            >
              {loadingAssets ? (
                <Loader2
                  size={15}
                  className="mr-2 animate-spin"
                />
              ) : (
                <RefreshCw
                  size={15}
                  className="mr-2"
                />
              )}
              Refresh
            </Button>
          </div>

                      <div className="rounded-2xl border border-[#e7dfc9] bg-white p-4">
              <div className="grid gap-3 md:grid-cols-3">
                <div>
                  <label className="mb-1 block text-xs font-medium text-[#6a6a6a]">
                    Week
                  </label>

                  <select
                    value={libraryWeekFilter}
                    onChange={(event) =>
                      setLibraryWeekFilter(
                        event.target.value
                      )
                    }
                    className="w-full rounded-xl border border-[#d8cba9] bg-white px-3 py-2 text-sm text-[#2f4a3a]"
                  >
                    <option value="all">
                      All weeks
                    </option>

                    {normalizeArray(weeks).map(
                      (week, index) => (
                        <option
                          key={`library-week-${index}`}
                          value={String(index)}
                        >
                          Week {week?.week || index + 1}
                        </option>
                      )
                    )}
                  </select>
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium text-[#6a6a6a]">
                    Content type
                  </label>

                  <select
                    value={libraryTypeFilter}
                    onChange={(event) =>
                      setLibraryTypeFilter(
                        event.target.value
                      )
                    }
                    className="w-full rounded-xl border border-[#d8cba9] bg-white px-3 py-2 text-sm text-[#2f4a3a]"
                  >
                    <option value="all">
                      All types
                    </option>
                    <option value="blog_post">
                      Blog
                    </option>
                    <option value="newsletter_spotlight">
                      Newsletter
                    </option>
                    <option value="social_post">
                      Social post
                    </option>
                    <option value="video_prompt">
                      Video prompt
                    </option>
                    <option value="package">
                      Package
                    </option>
                  </select>
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium text-[#6a6a6a]">
                    Status
                  </label>

                  <select
                    value={libraryStatusFilter}
                    onChange={(event) =>
                      setLibraryStatusFilter(
                        event.target.value
                      )
                    }
                    className="w-full rounded-xl border border-[#d8cba9] bg-white px-3 py-2 text-sm text-[#2f4a3a]"
                  >
                    <option value="all">
                      All statuses
                    </option>
                    <option value="draft">
                      Draft
                    </option>
                    <option value="approved">
                      Approved
                    </option>
                    <option value="rejected">
                      Rejected
                    </option>
                  </select>
                </div>
              </div>

              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-[#eee7d6] pt-4">
                <div className="flex flex-wrap items-center gap-3">
                  <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-[#2f4a3a]">
                    <input
                      type="checkbox"
                      checked={allVisibleAssetsSelected}
                      onChange={toggleAllVisibleAssets}
                      disabled={
                        visibleAssetIds.length === 0 ||
                        Boolean(bulkAssetAction)
                      }
                    />
                    Select all visible
                  </label>

                  <span className="text-xs text-[#8a8a8a]">
                    Showing{" "}
                    {filteredContentAssets.length} of{" "}
                    {contentAssets.length}
                  </span>

                  {selectedAssetIds.length > 0 && (
                    <span className="rounded-full bg-[#f1ead8] px-3 py-1 text-xs font-medium text-[#6a5637]">
                      {selectedAssetIds.length} selected
                    </span>
                  )}
                </div>

                {selectedAssetIds.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      size="sm"
                      onClick={() =>
                        bulkUpdateAssetStatus(
                          "approved"
                        )
                      }
                      disabled={Boolean(
                        bulkAssetAction
                      )}
                      className="rounded-full bg-[#2f4a3a] text-[#f6f1e6] hover:bg-[#263d30]"
                    >
                      {bulkAssetAction ===
                        "approved" && (
                        <Loader2
                          size={14}
                          className="mr-2 animate-spin"
                        />
                      )}
                      Approve Selected
                    </Button>

                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        bulkUpdateAssetStatus(
                          "rejected"
                        )
                      }
                      disabled={Boolean(
                        bulkAssetAction
                      )}
                      className="rounded-full"
                    >
                      {bulkAssetAction ===
                        "rejected" && (
                        <Loader2
                          size={14}
                          className="mr-2 animate-spin"
                        />
                      )}
                      Reject Selected
                    </Button>

                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={clearAssetSelection}
                      disabled={Boolean(
                        bulkAssetAction
                      )}
                    >
                      Clear
                    </Button>
                  </div>
                )}
              </div>
            </div>

{loadingAssets && contentAssets.length === 0 ? (
            <div className="rounded-2xl border border-[#e7dfc9] bg-white p-8 text-center text-sm text-[#6a6a6a]">
              Loading Content Library...
            </div>
          ) : contentAssets.length === 0 ? (
            <EmptyPlanState
              text="No content drafts have been generated for this strategy yet."
            />
          ) : (
            <div className="space-y-4">
              {normalizeArray(filteredContentAssets).map((asset) => (
                <div
                  key={asset.id}
                  className="rounded-2xl border border-[#e7dfc9] bg-white p-5"
                >
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                    <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-[#2f4a3a]">
                      <input
                        type="checkbox"
                        checked={selectedAssetIds.includes(
                          asset.id
                        )}
                        onChange={() =>
                          toggleAssetSelection(
                            asset.id
                          )
                        }
                        disabled={Boolean(
                          bulkAssetAction
                        )}
                        aria-label={`Select ${
                          asset.title ||
                          "content asset"
                        }`}
                      />
                      Select
                    </label>

                    <div className="flex flex-wrap items-center gap-1 text-xs text-[#8a8a8a]">
                      {(
                        asset.generated_from_week_index ??
                        asset.metadata?.strategy_source
                          ?.week_index
                      ) != null && (
                        <span>
                          Week{" "}
                          {Number(
                            asset.generated_from_week_index ??
                            asset.metadata
                              ?.strategy_source
                              ?.week_index
                          ) + 1}
                        </span>
                      )}

                      {asset.metadata?.strategy_source
                        ?.day_or_date && (
                        <span>
                          •{" "}
                          {
                            asset.metadata
                              .strategy_source
                              .day_or_date
                          }
                        </span>
                      )}

                      {asset.metadata?.strategy_source
                        ?.channel && (
                        <span>
                          •{" "}
                          {
                            asset.metadata
                              .strategy_source
                              .channel
                          }
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap gap-2 text-xs">
                        <span className="rounded-full bg-[#e7efe9] px-3 py-1 font-medium text-[#2f4a3a]">
                          {asset.content_type || "content"}
                        </span>

                        <span className="rounded-full bg-[#f1ead8] px-3 py-1 font-medium text-[#6a5637]">
                          {asset.status || "draft"}
                        </span>
                      </div>

                      <h4 className="mt-3 font-display text-xl text-[#1f2a22]">
                        {asset.title || "Untitled content"}
                      </h4>

                      {asset.metadata?.summary && (
                        <p className="mt-2 max-w-4xl text-sm leading-6 text-[#6a6a6a]">
                          {asset.metadata.summary}
                        </p>
                      )}
                    </div>

                    <div className="shrink-0 text-xs text-[#8a8a8a]">
                      {formatDate(
                        asset.updated_at ||
                        asset.created_at
                      )}
                    </div>
                  </div>

                  <div className="mt-4 max-h-72 overflow-y-auto whitespace-pre-wrap rounded-xl bg-[#fbf7ee] p-4 text-sm leading-6 text-[#3a3a3a]">
                    {asset.body || "No content body."}
                  </div>

                  {asset.human_review_required && (
                    <div className="mt-4 text-xs font-medium text-[#8a6a3c]">
                      Human review required
                    </div>
                  )}

                  <div className="mt-4 flex flex-wrap gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        openAssetEditor(asset)
                      }
                      disabled={
                        assetActionId === asset.id
                      }
                      className="rounded-full"
                    >
                      Edit
                    </Button>
                    {asset.status !== "approved" && (
                      <Button
                        type="button"
                        size="sm"
                        onClick={() =>
                          updateAssetStatus(
                            asset.id,
                            "approved"
                          )
                        }
                        disabled={
                          assetActionId === asset.id
                        }
                        className="rounded-full bg-[#2f4a3a] text-[#f6f1e6] hover:bg-[#263d30]"
                      >
                        {assetActionId === asset.id && (
                          <Loader2
                            size={14}
                            className="mr-2 animate-spin"
                          />
                        )}
                        Approve
                      </Button>
                    )}

                    {asset.status !== "rejected" && (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          updateAssetStatus(
                            asset.id,
                            "rejected"
                          )
                        }
                        disabled={
                          assetActionId === asset.id
                        }
                        className="rounded-full"
                      >
                        Reject
                      </Button>
                    )}

                    {asset.status === "approved" &&
                        [
                          "blog_post",
                          "newsletter_spotlight",
                          "package",
                        ].includes(asset.content_type) && (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          prepareAssetForWebsite(
                            asset.id
                          )
                        }
                        disabled={
                          assetActionId === asset.id
                        }
                        className="rounded-full"
                      >
                        {assetActionId === asset.id && (
                          <Loader2
                            size={14}
                            className="mr-2 animate-spin"
                          />
                        )}
                        Prepare for Website
                      </Button>
                    )}

                    {asset.status === "approved" &&
                      [
                        "social_post",
                        "video_prompt",
                      ].includes(
                        asset.content_type
                      ) && (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          sendAssetToPublishingQueue(
                            asset
                          )
                        }
                        disabled={
                          publishingQueueActionId ===
                          asset.id
                        }
                        className="rounded-full"
                      >
                        {publishingQueueActionId ===
                          asset.id && (
                          <Loader2
                            size={14}
                            className="mr-2 animate-spin"
                          />
                        )}
                        Send to Publishing Queue
                      </Button>
                    )}

                    {asset.website_export?.status ===
                      "prepared" && (
                      <span className="inline-flex items-center rounded-full bg-[#e7efe9] px-3 py-1 text-xs font-medium text-[#2f4a3a]">
                        S3 prepared
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === "publishing" && (
        <div className="space-y-4">
          <div className="flex flex-col gap-3 rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="eyebrow text-[#8a6a3c]">
                Publishing Queue
              </div>

              <h3 className="mt-1 font-display text-2xl text-[#1f2a22]">
                Approved social content
              </h3>

              <p className="mt-1 max-w-3xl text-sm leading-6 text-[#6a6a6a]">
                Queue approved social posts and video prompts
                for controlled scheduling. Nothing is
                published automatically.
              </p>
            </div>

            <Button
              type="button"
              variant="outline"
              onClick={loadPublishingQueue}
              disabled={loadingPublishingQueue}
              className="rounded-full"
            >
              {loadingPublishingQueue ? (
                <Loader2
                  size={15}
                  className="mr-2 animate-spin"
                />
              ) : (
                <RefreshCw
                  size={15}
                  className="mr-2"
                />
              )}
              Refresh
            </Button>
          </div>

          <div className="grid gap-3 rounded-2xl border border-[#e7dfc9] bg-white p-4 md:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-[#6a6a6a]">
                Queue status
              </label>

              <select
                value={publishingStatusFilter}
                onChange={(event) =>
                  setPublishingStatusFilter(
                    event.target.value
                  )
                }
                className="w-full rounded-xl border border-[#d8cba9] bg-white px-3 py-2 text-sm text-[#2f4a3a]"
              >
                <option value="all">
                  All statuses
                </option>
                <option value="ready">
                  Ready
                </option>
                <option value="scheduled">
                  Scheduled
                </option>
                <option value="cancelled">
                  Cancelled
                </option>
                <option value="publishing">
                  Publishing
                </option>
                <option value="published">
                  Published
                </option>
                <option value="failed">
                  Failed
                </option>
              </select>
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-[#6a6a6a]">
                Platform
              </label>

              <select
                value={publishingPlatformFilter}
                onChange={(event) =>
                  setPublishingPlatformFilter(
                    event.target.value
                  )
                }
                className="w-full rounded-xl border border-[#d8cba9] bg-white px-3 py-2 text-sm text-[#2f4a3a]"
              >
                <option value="all">
                  All platforms
                </option>
                <option value="instagram">
                  Instagram
                </option>
                <option value="facebook">
                  Facebook
                </option>
                <option value="tiktok">
                  TikTok
                </option>
                <option value="linkedin">
                  LinkedIn
                </option>
                <option value="threads">
                  Threads
                </option>
                <option value="short_video">
                  Short video
                </option>
              </select>
            </div>

            <div className="md:col-span-2 text-xs text-[#8a8a8a]">
              Showing{" "}
              {filteredPublishingQueue.length} of{" "}
              {publishingQueue.length} queue items
            </div>
          </div>

          {loadingPublishingQueue &&
          publishingQueue.length === 0 ? (
            <div className="rounded-2xl border border-[#e7dfc9] bg-white p-8 text-center text-sm text-[#6a6a6a]">
              Loading Publishing Queue...
            </div>
          ) : publishingQueue.length === 0 ? (
            <EmptyPlanState
              text="No approved social or video content has been queued yet."
            />
          ) : filteredPublishingQueue.length === 0 ? (
            <EmptyPlanState
              text="No Publishing Queue items match the selected filters."
            />
          ) : (
            <div className="space-y-4">
              {normalizeArray(
                filteredPublishingQueue
              ).map((item) => (
                <div
                  key={item.id}
                  className="rounded-2xl border border-[#e7dfc9] bg-white p-5"
                >
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap gap-2 text-xs">
                        <span className="rounded-full bg-[#e7efe9] px-3 py-1 font-medium text-[#2f4a3a]">
                          {item.platform ||
                            "platform"}
                        </span>

                        <span className="rounded-full bg-[#f1ead8] px-3 py-1 font-medium text-[#6a5637]">
                          {item.status ||
                            "ready"}
                        </span>

                        <span className="rounded-full bg-[#f5f5f5] px-3 py-1 font-medium text-[#666]">
                          {item.content_type ||
                            "content"}
                        </span>
                      </div>

                      <h4 className="mt-3 font-display text-xl text-[#1f2a22]">
                        {item.title ||
                          "Untitled content"}
                      </h4>

                      <div className="mt-2 flex flex-wrap gap-2 text-xs text-[#8a8a8a]">
                        {item.week_index != null && (
                          <span>
                            Week{" "}
                            {Number(
                              item.week_index
                            ) + 1}
                          </span>
                        )}

                        {item.source_channel && (
                          <span>
                            • {item.source_channel}
                          </span>
                        )}

                        {item.scheduled_at && (
                          <span>
                            • Scheduled{" "}
                            {formatDate(
                              item.scheduled_at
                            )}
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="shrink-0 text-xs text-[#8a8a8a]">
                      {formatDate(
                        item.updated_at ||
                        item.created_at
                      )}
                    </div>
                  </div>

                  <div className="mt-4 max-h-72 overflow-y-auto whitespace-pre-wrap rounded-xl bg-[#fbf7ee] p-4 text-sm leading-6 text-[#3a3a3a]">
                    {item.body ||
                      "No content body."}
                  </div>

                  <div className="mt-4 flex flex-wrap items-end gap-2">
                    {[
                      "ready",
                      "scheduled",
                    ].includes(item.status) && (
                      <div className="min-w-[240px]">
                        <label className="mb-1 block text-xs font-medium text-[#6a6a6a]">
                          Schedule date & time
                        </label>

                        <input
                          type="datetime-local"
                          value={
                            publishingScheduleInputs[
                              item.id
                            ] ??
                            publishingLocalDateTime(
                              item.scheduled_at
                            )
                          }
                          onChange={(event) =>
                            setPublishingScheduleInputs(
                              (current) => ({
                                ...current,
                                [item.id]:
                                  event.target.value,
                              })
                            )
                          }
                          disabled={
                            publishingQueueActionId ===
                            item.id
                          }
                          className="w-full rounded-xl border border-[#d8cba9] bg-white px-3 py-2 text-sm text-[#2f4a3a]"
                        />
                      </div>
                    )}

                    {[
                      "ready",
                      "scheduled",
                    ].includes(item.status) && (
                      <Button
                        type="button"
                        size="sm"
                        onClick={() =>
                          schedulePublishingItem(
                            item,
                            publishingScheduleInputs[
                              item.id
                            ]
                          )
                        }
                        disabled={
                          publishingQueueActionId ===
                            item.id ||
                          !publishingScheduleInputs[
                            item.id
                          ]
                        }
                        className="rounded-full bg-[#2f4a3a] text-[#f6f1e6] hover:bg-[#263d30]"
                      >
                        {publishingQueueActionId ===
                          item.id && (
                          <Loader2
                            size={14}
                            className="mr-2 animate-spin"
                          />
                        )}
                        {item.status === "scheduled"
                          ? "Reschedule"
                          : "Schedule"}
                      </Button>
                    )}

                    {item.status === "failed" && (
                      <Button
                        type="button"
                        size="sm"
                        onClick={() =>
                          retryFailedPublishingItem(
                            item
                          )
                        }
                        disabled={
                          publishingQueueActionId ===
                          item.id
                        }
                        className="rounded-full bg-[#2f4a3a] text-[#f6f1e6] hover:bg-[#263d30]"
                      >
                        {publishingQueueActionId ===
                          item.id && (
                          <Loader2
                            size={14}
                            className="mr-2 animate-spin"
                          />
                        )}
                        Retry Failed
                      </Button>
                    )}

                    {item.status === "cancelled" && (
                      <Button
                        type="button"
                        size="sm"
                        onClick={() =>
                          requeuePublishingItem(
                            item
                          )
                        }
                        disabled={
                          publishingQueueActionId ===
                          item.id
                        }
                        className="rounded-full bg-[#2f4a3a] text-[#f6f1e6] hover:bg-[#263d30]"
                      >
                        {publishingQueueActionId ===
                          item.id && (
                          <Loader2
                            size={14}
                            className="mr-2 animate-spin"
                          />
                        )}
                        Requeue
                      </Button>
                    )}

                    {[
                      "ready",
                      "scheduled",
                    ].includes(
                      item.status
                    ) && (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          cancelPublishingItem(
                            item
                          )
                        }
                        disabled={
                          publishingQueueActionId ===
                          item.id
                        }
                        className="rounded-full"
                      >
                        {publishingQueueActionId ===
                          item.id && (
                          <Loader2
                            size={14}
                            className="mr-2 animate-spin"
                          />
                        )}
                        Cancel
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
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

      {editingAsset && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="max-h-[92vh] w-full max-w-4xl overflow-y-auto rounded-3xl bg-[#fffdf8] shadow-2xl">
            <div className="flex items-center justify-between border-b border-[#e7dfc9] px-6 py-5">
              <div>
                <div className="eyebrow text-[#8a6a3c]">
                  Content Library
                </div>

                <h3 className="mt-1 font-display text-2xl text-[#1f2a22]">
                  Edit Content Draft
                </h3>
              </div>

              <button
                type="button"
                onClick={closeAssetEditor}
                disabled={Boolean(assetActionId)}
                className="flex h-10 w-10 items-center justify-center rounded-full border border-[#e7dfc9] text-xl text-[#6a6a6a]"
              >
                ×
              </button>
            </div>

            <div className="space-y-5 p-6">
              <div>
                <Label>Title</Label>
                <Input
                  value={editingAsset.title}
                  onChange={(event) =>
                    setEditingAsset((current) => ({
                      ...current,
                      title: event.target.value,
                    }))
                  }
                  className="mt-2"
                />
              </div>

              {editingAsset.subject !== undefined && (
                <div>
                  <Label>Email subject</Label>
                  <Input
                    value={editingAsset.subject}
                    onChange={(event) =>
                      setEditingAsset((current) => ({
                        ...current,
                        subject: event.target.value,
                      }))
                    }
                    className="mt-2"
                  />
                </div>
              )}

              <div>
                <Label>Content</Label>
                <Textarea
                  value={editingAsset.body}
                  onChange={(event) =>
                    setEditingAsset((current) => ({
                      ...current,
                      body: event.target.value,
                    }))
                  }
                  rows={18}
                  className="mt-2 font-mono text-sm"
                />
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <Label>Slug</Label>
                  <Input
                    value={
                      editingAsset.metadata.slug || ""
                    }
                    onChange={(event) =>
                      setEditingAsset((current) => ({
                        ...current,
                        metadata: {
                          ...current.metadata,
                          slug: event.target.value,
                        },
                      }))
                    }
                    className="mt-2"
                  />
                </div>

                <div>
                  <Label>Category</Label>
                  <Input
                    value={
                      editingAsset.metadata.category || ""
                    }
                    onChange={(event) =>
                      setEditingAsset((current) => ({
                        ...current,
                        metadata: {
                          ...current.metadata,
                          category: event.target.value,
                        },
                      }))
                    }
                    className="mt-2"
                  />
                </div>
              </div>

              <div>
                <Label>Summary</Label>
                <Textarea
                  value={
                    editingAsset.metadata.summary || ""
                  }
                  onChange={(event) =>
                    setEditingAsset((current) => ({
                      ...current,
                      metadata: {
                        ...current.metadata,
                        summary: event.target.value,
                      },
                    }))
                  }
                  rows={4}
                  className="mt-2"
                />
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <Label>SEO title</Label>
                  <Input
                    value={
                      editingAsset.metadata.seo?.title ||
                      ""
                    }
                    onChange={(event) =>
                      setEditingAsset((current) => ({
                        ...current,
                        metadata: {
                          ...current.metadata,
                          seo: {
                            ...current.metadata.seo,
                            title: event.target.value,
                          },
                        },
                      }))
                    }
                    className="mt-2"
                  />
                </div>

                <div>
                  <Label>Publish date</Label>
                  <Input
                    type="date"
                    value={
                      editingAsset.metadata
                        .publish_date || ""
                    }
                    onChange={(event) =>
                      setEditingAsset((current) => ({
                        ...current,
                        metadata: {
                          ...current.metadata,
                          publish_date:
                            event.target.value,
                        },
                      }))
                    }
                    className="mt-2"
                  />
                </div>
              </div>

              <div>
                <Label>SEO description</Label>
                <Textarea
                  value={
                    editingAsset.metadata.seo
                      ?.description || ""
                  }
                  onChange={(event) =>
                    setEditingAsset((current) => ({
                      ...current,
                      metadata: {
                        ...current.metadata,
                        seo: {
                          ...current.metadata.seo,
                          description:
                            event.target.value,
                        },
                      },
                    }))
                  }
                  rows={3}
                  className="mt-2"
                />
              </div>

              <div>
                <Label>Tags</Label>
                <Input
                  value={editingAsset.tags}
                  onChange={(event) =>
                    setEditingAsset((current) => ({
                      ...current,
                      tags: event.target.value,
                    }))
                  }
                  placeholder="athlete recovery, wellness, education"
                  className="mt-2"
                />
              </div>

              <div className="rounded-xl border border-[#e7dfc9] bg-[#fbf7ee] p-4 text-xs leading-5 text-[#6a6a6a]">
                Saving editorial changes automatically returns
                this asset to draft status so it must be
                reviewed again before website preparation.
              </div>

              <div className="flex flex-wrap justify-end gap-3">
                <Button
                  type="button"
                  variant="outline"
                  onClick={closeAssetEditor}
                  disabled={Boolean(assetActionId)}
                  className="rounded-full"
                >
                  Cancel
                </Button>

                <Button
                  type="button"
                  onClick={saveAssetEdits}
                  disabled={Boolean(assetActionId)}
                  className="rounded-full bg-[#2f4a3a] text-[#f6f1e6]"
                >
                  {assetActionId ===
                    editingAsset.id && (
                    <Loader2
                      size={15}
                      className="mr-2 animate-spin"
                    />
                  )}
                  Save Changes
                </Button>
              </div>
            </div>
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
                    calendarIndex: index,
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
