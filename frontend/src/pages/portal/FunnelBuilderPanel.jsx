import React from "react";

import api from "../../lib/api";
import { normalizeArray } from "../../lib/collections";

import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../components/ui/select";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "../../components/ui/tabs";
import { Textarea } from "../../components/ui/textarea";

import {
  Boxes,
  ClipboardCheck,
  GitBranch,
  Layers3,
  Loader2,
  MapPin,
  Plus,
  RefreshCw,
  Sparkles,
  Target,
} from "lucide-react";


const SAFE_FIELDS = [
  {
    key: "service_interest",
    label: "Service interest",
  },
  {
    key: "urgency",
    label: "Urgency",
  },
  {
    key: "preferred_location",
    label: "Preferred location",
  },
  {
    key: "preferred_contact_window",
    label: "Preferred contact window",
  },
  {
    key: "appointment_readiness",
    label: "Appointment readiness",
  },
  {
    key: "timeline",
    label: "Timeline",
  },
  {
    key: "contact_consent",
    label: "Contact consent",
  },
];


const INITIAL_OFFER = {
  name: "",
  slug: "",
  status: "draft",
  service_interest: "",
  description: "",
  min_qualification_score: "70",
  eligible_locations: "",
};


const INITIAL_FORM = {
  name: "",
  slug: "",
  status: "draft",
  fields: [
    "service_interest",
    "preferred_location",
    "appointment_readiness",
    "contact_consent",
  ],
  qualify_at: "70",
  review_at: "40",
};


const INITIAL_FUNNEL = {
  name: "",
  slug: "",
  status: "draft",
  landing_page: "",
  qualification_form_id: "none",
  default_offer_id: "none",
};


const INITIAL_STEP = {
  funnel_id: "none",
  step_key: "",
  step_type: "qualification",
  position: "1",
  title: "",
};


function slugify(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 160);
}


function errorMessage(error, fallback) {
  const detail = error?.response?.data?.detail;

  if (typeof detail === "string") {
    return detail;
  }

  if (detail?.message) {
    return detail.message;
  }

  return fallback;
}


function statusBadge(status) {
  const normalized = String(status || "draft").toLowerCase();

  if (normalized === "active") {
    return "border-green-200 bg-green-50 text-green-700";
  }

  return "border-[#d8cba9] bg-[#f7f1e4] text-[#806837]";
}


function SectionCard({
  title,
  subtitle,
  icon: Icon,
  actions,
  children,
  testId,
}) {
  return (
    <section
      className="rounded-2xl border border-[#d8cba9] bg-[#fbf7ee] p-5"
      data-testid={testId}
    >
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          {Icon ? (
            <div className="rounded-xl border border-[#d8cba9] bg-white p-2 text-[#8a6a3c]">
              <Icon size={18} />
            </div>
          ) : null}

          <div>
            <h3 className="text-lg font-semibold text-[#3f3320]">
              {title}
            </h3>

            {subtitle ? (
              <p className="mt-1 max-w-3xl text-sm text-[#806837]">
                {subtitle}
              </p>
            ) : null}
          </div>
        </div>

        {actions}
      </div>

      {children}
    </section>
  );
}


function EmptyState({ children }) {
  return (
    <div className="rounded-xl border border-dashed border-[#c9b98e] bg-white px-4 py-6 text-center text-sm text-[#806837]">
      {children}
    </div>
  );
}


function FieldCheckbox({ field, selected, onToggle }) {
  return (
    <label
      className={
        "flex cursor-pointer items-center gap-2 rounded-xl border px-3 py-2 " +
        (selected
          ? "border-[#c19a4b] bg-[#f7f1e4]"
          : "border-[#e2dac5] bg-white")
      }
    >
      <input
        type="checkbox"
        checked={selected}
        onChange={() => onToggle(field.key)}
        className="h-4 w-4 accent-[#8a6a3c]"
      />

      <span className="text-sm text-[#3f3320]">
        {field.label}
      </span>
    </label>
  );
}


export default function FunnelBuilderPanel() {
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [success, setSuccess] = React.useState("");

  const [offers, setOffers] = React.useState([]);
  const [forms, setForms] = React.useState([]);
  const [funnels, setFunnels] = React.useState([]);

  const [offerDraft, setOfferDraft] =
    React.useState(INITIAL_OFFER);

  const [formDraft, setFormDraft] =
    React.useState(INITIAL_FORM);

  const [funnelDraft, setFunnelDraft] =
    React.useState(INITIAL_FUNNEL);

  const [stepDraft, setStepDraft] =
    React.useState(INITIAL_STEP);


  const load = React.useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const [
        offersResponse,
        formsResponse,
        funnelsResponse,
      ] = await Promise.all([
        api.getList("/marketing-os/offers"),
        api.getList("/marketing-os/qualification-forms"),
        api.getList("/marketing-os/funnels"),
      ]);

      setOffers(
        normalizeArray(
          offersResponse.data,
          ["offers"]
        )
      );

      setForms(
        normalizeArray(
          formsResponse.data,
          ["forms"]
        )
      );

      setFunnels(
        normalizeArray(
          funnelsResponse.data,
          ["funnels"]
        )
      );
    } catch (err) {
      setError(
        errorMessage(
          err,
          "Unable to load Funnel Builder"
        )
      );
    } finally {
      setLoading(false);
    }
  }, []);


  React.useEffect(() => {
    load();
  }, [load]);


  const resetMessages = () => {
    setError("");
    setSuccess("");
  };


  const createOffer = async (event) => {
    event.preventDefault();
    resetMessages();

    if (!offerDraft.name.trim()) {
      setError("Offer name is required.");
      return;
    }

    const slug =
      offerDraft.slug.trim() ||
      slugify(offerDraft.name);

    if (!slug) {
      setError("Offer slug is required.");
      return;
    }

    const minimum = Number(
      offerDraft.min_qualification_score
    );

    if (
      !Number.isFinite(minimum) ||
      minimum < 0 ||
      minimum > 100
    ) {
      setError(
        "Minimum qualification score must be between 0 and 100."
      );
      return;
    }

    const locations = offerDraft.eligible_locations
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);

    setBusy(true);

    try {
      await api.post("/marketing-os/offers", {
        name: offerDraft.name.trim(),
        slug,
        status: offerDraft.status,
        service_interest:
          offerDraft.service_interest.trim() || null,
        description:
          offerDraft.description.trim() || null,
        min_qualification_score: minimum,
        eligible_locations: locations,
        match_config: {},
      });

      setOfferDraft(INITIAL_OFFER);
      setSuccess("Offer created.");
      await load();
    } catch (err) {
      setError(
        errorMessage(
          err,
          "Unable to create offer"
        )
      );
    } finally {
      setBusy(false);
    }
  };


  const toggleField = (key) => {
    setFormDraft((current) => {
      const exists = current.fields.includes(key);

      return {
        ...current,
        fields: exists
          ? current.fields.filter(
              (field) => field !== key
            )
          : [...current.fields, key],
      };
    });
  };


  const buildScoringRules = (fields) => {
    const rules = [];

    if (fields.includes("appointment_readiness")) {
      rules.push({
        field: "appointment_readiness",
        operator: "equals",
        value: "ready_now",
        points: 40,
      });
    }

    if (fields.includes("urgency")) {
      rules.push({
        field: "urgency",
        operator: "in",
        values: ["high", "urgent"],
        points: 20,
      });
    }

    if (fields.includes("timeline")) {
      rules.push({
        field: "timeline",
        operator: "in",
        values: ["now", "within_30_days"],
        points: 20,
      });
    }

    if (fields.includes("contact_consent")) {
      rules.push({
        field: "contact_consent",
        operator: "truthy",
        points: 20,
      });
    }

    return rules;
  };


  const createForm = async (event) => {
    event.preventDefault();
    resetMessages();

    if (!formDraft.name.trim()) {
      setError(
        "Qualification form name is required."
      );
      return;
    }

    if (formDraft.fields.length === 0) {
      setError(
        "Select at least one marketing-safe field."
      );
      return;
    }

    const slug =
      formDraft.slug.trim() ||
      slugify(formDraft.name);

    const qualifyAt = Number(
      formDraft.qualify_at
    );

    const reviewAt = Number(
      formDraft.review_at
    );

    if (
      !Number.isFinite(qualifyAt) ||
      !Number.isFinite(reviewAt) ||
      qualifyAt < 0 ||
      qualifyAt > 100 ||
      reviewAt < 0 ||
      reviewAt > 100
    ) {
      setError(
        "Qualification thresholds must be between 0 and 100."
      );
      return;
    }

    if (qualifyAt < reviewAt) {
      setError(
        "Qualified threshold must be greater than or equal to review threshold."
      );
      return;
    }

    setBusy(true);

    try {
      await api.post(
        "/marketing-os/qualification-forms",
        {
          name: formDraft.name.trim(),
          slug,
          status: formDraft.status,
          schema: {
            fields: formDraft.fields,
          },
          scoring_rules:
            buildScoringRules(
              formDraft.fields
            ),
          qualification_config: {
            qualify_at: qualifyAt,
            review_at: reviewAt,
          },
        }
      );

      setFormDraft(INITIAL_FORM);
      setSuccess(
        "Marketing qualification form created."
      );
      await load();
    } catch (err) {
      setError(
        errorMessage(
          err,
          "Unable to create qualification form"
        )
      );
    } finally {
      setBusy(false);
    }
  };


  const createFunnel = async (event) => {
    event.preventDefault();
    resetMessages();

    if (!funnelDraft.name.trim()) {
      setError("Funnel name is required.");
      return;
    }

    const slug =
      funnelDraft.slug.trim() ||
      slugify(funnelDraft.name);

    setBusy(true);

    try {
      await api.post("/marketing-os/funnels", {
        name: funnelDraft.name.trim(),
        slug,
        status: funnelDraft.status,
        landing_page:
          funnelDraft.landing_page.trim() ||
          null,
        qualification_form_id:
          funnelDraft.qualification_form_id ===
          "none"
            ? null
            : funnelDraft
                .qualification_form_id,
        default_offer_id:
          funnelDraft.default_offer_id ===
          "none"
            ? null
            : funnelDraft.default_offer_id,
        config: {},
      });

      setFunnelDraft(INITIAL_FUNNEL);
      setSuccess("Funnel created.");
      await load();
    } catch (err) {
      setError(
        errorMessage(
          err,
          "Unable to create funnel"
        )
      );
    } finally {
      setBusy(false);
    }
  };


  const addStep = async (event) => {
    event.preventDefault();
    resetMessages();

    if (stepDraft.funnel_id === "none") {
      setError(
        "Select a funnel before adding a step."
      );
      return;
    }

    if (!stepDraft.step_key.trim()) {
      setError("Step key is required.");
      return;
    }

    const position = Number(
      stepDraft.position
    );

    if (
      !Number.isInteger(position) ||
      position < 0
    ) {
      setError(
        "Step position must be a non-negative whole number."
      );
      return;
    }

    setBusy(true);

    try {
      await api.post(
        `/marketing-os/funnels/${stepDraft.funnel_id}/steps`,
        {
          step_key:
            slugify(stepDraft.step_key),
          step_type:
            stepDraft.step_type,
          position,
          title:
            stepDraft.title.trim() ||
            null,
          config: {},
        }
      );

      setStepDraft(INITIAL_STEP);
      setSuccess("Funnel step added.");
      await load();
    } catch (err) {
      setError(
        errorMessage(
          err,
          "Unable to add funnel step"
        )
      );
    } finally {
      setBusy(false);
    }
  };


  return (
    <SectionCard
      title="Funnel Builder"
      subtitle={
        "Build marketing funnels, qualification forms, and offer rules " +
        "that feed the existing Lead CRM. Marketing data only — no PHI."
      }
      icon={GitBranch}
      testId="marketing-funnel-builder"
      actions={
        <Button
          type="button"
          variant="outline"
          onClick={load}
          disabled={loading || busy}
          className="h-9 rounded-full border-[#c19a4b] text-[#8a6a3c]"
          data-testid="funnel-builder-refresh"
        >
          <RefreshCw
            size={14}
            className={
              "mr-2 " +
              (loading ? "animate-spin" : "")
            }
          />
          Refresh
        </Button>
      }
    >
      {error ? (
        <div
          className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
          data-testid="funnel-builder-error"
        >
          {error}
        </div>
      ) : null}

      {success ? (
        <div
          className="mb-4 rounded-xl border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700"
          data-testid="funnel-builder-success"
        >
          {success}
        </div>
      ) : null}

      {loading ? (
        <div className="flex items-center gap-2 py-8 text-sm text-[#806837]">
          <Loader2
            size={16}
            className="animate-spin"
          />
          Loading funnel workspace…
        </div>
      ) : (
        <Tabs
          defaultValue="funnels"
          className="space-y-5"
        >
          <TabsList className="grid h-auto w-full grid-cols-1 gap-2 bg-transparent p-0 sm:grid-cols-3">
            <TabsTrigger
              value="funnels"
              className="rounded-xl border border-[#d8cba9] bg-white px-4 py-3 data-[state=active]:bg-[#f1e7ce] data-[state=active]:text-[#5f491f]"
            >
              <GitBranch
                size={15}
                className="mr-2"
              />
              Funnels ({funnels.length})
            </TabsTrigger>

            <TabsTrigger
              value="forms"
              className="rounded-xl border border-[#d8cba9] bg-white px-4 py-3 data-[state=active]:bg-[#f1e7ce] data-[state=active]:text-[#5f491f]"
            >
              <ClipboardCheck
                size={15}
                className="mr-2"
              />
              Qualification Forms ({forms.length})
            </TabsTrigger>

            <TabsTrigger
              value="offers"
              className="rounded-xl border border-[#d8cba9] bg-white px-4 py-3 data-[state=active]:bg-[#f1e7ce] data-[state=active]:text-[#5f491f]"
            >
              <Target
                size={15}
                className="mr-2"
              />
              Offer Library ({offers.length})
            </TabsTrigger>
          </TabsList>


          <TabsContent
            value="funnels"
            className="space-y-5"
          >
            <div className="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
              <form
                onSubmit={createFunnel}
                className="space-y-4 rounded-2xl border border-[#d8cba9] bg-white p-5"
              >
                <div>
                  <div className="flex items-center gap-2 font-semibold text-[#3f3320]">
                    <Plus size={16} />
                    Create Funnel
                  </div>
                  <p className="mt-1 text-xs text-[#806837]">
                    Connect a landing page to a marketing qualification form
                    and default offer.
                  </p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="funnel-name">
                    Funnel name
                  </Label>
                  <Input
                    id="funnel-name"
                    value={funnelDraft.name}
                    onChange={(event) =>
                      setFunnelDraft(
                        (current) => ({
                          ...current,
                          name:
                            event.target.value,
                        })
                      )
                    }
                    placeholder="Wellness Consultation Funnel"
                    data-testid="funnel-name"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="funnel-slug">
                    Slug
                  </Label>
                  <Input
                    id="funnel-slug"
                    value={funnelDraft.slug}
                    onChange={(event) =>
                      setFunnelDraft(
                        (current) => ({
                          ...current,
                          slug:
                            event.target.value,
                        })
                      )
                    }
                    placeholder="Auto-generated from name"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="landing-page">
                    Landing page
                  </Label>
                  <Input
                    id="landing-page"
                    value={
                      funnelDraft.landing_page
                    }
                    onChange={(event) =>
                      setFunnelDraft(
                        (current) => ({
                          ...current,
                          landing_page:
                            event.target.value,
                        })
                      )
                    }
                    placeholder="/wellness"
                  />
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label>
                      Qualification form
                    </Label>
                    <Select
                      value={
                        funnelDraft
                          .qualification_form_id
                      }
                      onValueChange={(value) =>
                        setFunnelDraft(
                          (current) => ({
                            ...current,
                            qualification_form_id:
                              value,
                          })
                        )
                      }
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="none">
                          None
                        </SelectItem>
                        {forms.map((form) => (
                          <SelectItem
                            key={form.id}
                            value={form.id}
                          >
                            {form.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-2">
                    <Label>
                      Default offer
                    </Label>
                    <Select
                      value={
                        funnelDraft
                          .default_offer_id
                      }
                      onValueChange={(value) =>
                        setFunnelDraft(
                          (current) => ({
                            ...current,
                            default_offer_id:
                              value,
                          })
                        )
                      }
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="none">
                          None
                        </SelectItem>
                        {offers.map((offer) => (
                          <SelectItem
                            key={offer.id}
                            value={offer.id}
                          >
                            {offer.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="space-y-2">
                  <Label>Status</Label>
                  <Select
                    value={funnelDraft.status}
                    onValueChange={(value) =>
                      setFunnelDraft(
                        (current) => ({
                          ...current,
                          status: value,
                        })
                      )
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="draft">
                        Draft
                      </SelectItem>
                      <SelectItem value="active">
                        Active
                      </SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <Button
                  type="submit"
                  disabled={busy}
                  className="w-full bg-[#8a6a3c] text-white hover:bg-[#72572f]"
                  data-testid="create-funnel"
                >
                  {busy ? (
                    <Loader2
                      size={15}
                      className="mr-2 animate-spin"
                    />
                  ) : (
                    <Plus
                      size={15}
                      className="mr-2"
                    />
                  )}
                  Create Funnel
                </Button>
              </form>


              <form
                onSubmit={addStep}
                className="space-y-4 rounded-2xl border border-[#d8cba9] bg-white p-5"
              >
                <div>
                  <div className="flex items-center gap-2 font-semibold text-[#3f3320]">
                    <Layers3 size={16} />
                    Add Funnel Step
                  </div>
                  <p className="mt-1 text-xs text-[#806837]">
                    Steps are internal funnel structure only. No external
                    publishing occurs here.
                  </p>
                </div>

                <div className="space-y-2">
                  <Label>Funnel</Label>
                  <Select
                    value={stepDraft.funnel_id}
                    onValueChange={(value) =>
                      setStepDraft(
                        (current) => ({
                          ...current,
                          funnel_id: value,
                        })
                      )
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">
                        Select funnel
                      </SelectItem>

                      {funnels.map((funnel) => (
                        <SelectItem
                          key={funnel.id}
                          value={funnel.id}
                        >
                          {funnel.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="step-key">
                      Step key
                    </Label>
                    <Input
                      id="step-key"
                      value={stepDraft.step_key}
                      onChange={(event) =>
                        setStepDraft(
                          (current) => ({
                            ...current,
                            step_key:
                              event.target.value,
                          })
                        )
                      }
                      placeholder="qualification"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="step-position">
                      Position
                    </Label>
                    <Input
                      id="step-position"
                      type="number"
                      min="0"
                      value={stepDraft.position}
                      onChange={(event) =>
                        setStepDraft(
                          (current) => ({
                            ...current,
                            position:
                              event.target.value,
                          })
                        )
                      }
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <Label>Step type</Label>
                  <Select
                    value={stepDraft.step_type}
                    onValueChange={(value) =>
                      setStepDraft(
                        (current) => ({
                          ...current,
                          step_type: value,
                        })
                      )
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="landing">
                        Landing
                      </SelectItem>
                      <SelectItem value="qualification">
                        Qualification
                      </SelectItem>
                      <SelectItem value="offer">
                        Offer
                      </SelectItem>
                      <SelectItem value="appointment">
                        Appointment
                      </SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="step-title">
                    Display title
                  </Label>
                  <Input
                    id="step-title"
                    value={stepDraft.title}
                    onChange={(event) =>
                      setStepDraft(
                        (current) => ({
                          ...current,
                          title:
                            event.target.value,
                        })
                      )
                    }
                    placeholder="Qualification"
                  />
                </div>

                <Button
                  type="submit"
                  variant="outline"
                  disabled={busy}
                  className="w-full border-[#c19a4b] text-[#72572f]"
                  data-testid="add-funnel-step"
                >
                  <Plus
                    size={15}
                    className="mr-2"
                  />
                  Add Step
                </Button>
              </form>
            </div>


            <div className="space-y-3">
              <div className="font-semibold text-[#3f3320]">
                Existing Funnels
              </div>

              {funnels.length === 0 ? (
                <EmptyState>
                  No funnels have been created yet.
                </EmptyState>
              ) : (
                funnels.map((funnel) => {
                  const steps = normalizeArray(
                    funnel.steps
                  );

                  return (
                    <div
                      key={funnel.id}
                      className="rounded-2xl border border-[#d8cba9] bg-white p-4"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-semibold text-[#3f3320]">
                              {funnel.name}
                            </span>

                            <Badge
                              variant="outline"
                              className={
                                statusBadge(
                                  funnel.status
                                )
                              }
                            >
                              {funnel.status}
                            </Badge>
                          </div>

                          <div className="mt-1 text-xs text-[#806837]">
                            {funnel.landing_page ||
                              "No landing page"}
                          </div>
                        </div>

                        <div className="text-xs text-[#806837]">
                          {steps.length} step
                          {steps.length === 1
                            ? ""
                            : "s"}
                        </div>
                      </div>

                      {steps.length > 0 ? (
                        <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
                          {steps.map((step) => (
                            <div
                              key={step.id}
                              className="rounded-xl border border-[#e2dac5] bg-[#fdfbf5] px-3 py-2"
                            >
                              <div className="text-xs font-semibold uppercase tracking-wide text-[#8a6a3c]">
                                {step.position}.{" "}
                                {step.step_type}
                              </div>
                              <div className="mt-1 text-sm text-[#3f3320]">
                                {step.title ||
                                  step.step_key}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  );
                })
              )}
            </div>
          </TabsContent>


          <TabsContent
            value="forms"
            className="space-y-5"
          >
            <div className="grid gap-5 xl:grid-cols-[1fr_1fr]">
              <form
                onSubmit={createForm}
                className="space-y-4 rounded-2xl border border-[#d8cba9] bg-white p-5"
              >
                <div>
                  <div className="flex items-center gap-2 font-semibold text-[#3f3320]">
                    <ClipboardCheck size={16} />
                    Create Qualification Form
                  </div>
                  <p className="mt-1 text-xs text-[#806837]">
                    Only approved marketing-safe fields are available.
                    Do not collect patient or clinical information here.
                  </p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="form-name">
                    Form name
                  </Label>
                  <Input
                    id="form-name"
                    value={formDraft.name}
                    onChange={(event) =>
                      setFormDraft(
                        (current) => ({
                          ...current,
                          name:
                            event.target.value,
                        })
                      )
                    }
                    placeholder="Consultation Qualification"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="form-slug">
                    Slug
                  </Label>
                  <Input
                    id="form-slug"
                    value={formDraft.slug}
                    onChange={(event) =>
                      setFormDraft(
                        (current) => ({
                          ...current,
                          slug:
                            event.target.value,
                        })
                      )
                    }
                    placeholder="Auto-generated from name"
                  />
                </div>

                <div className="space-y-2">
                  <Label>
                    Marketing-safe questions
                  </Label>

                  <div className="grid gap-2 sm:grid-cols-2">
                    {SAFE_FIELDS.map((field) => (
                      <FieldCheckbox
                        key={field.key}
                        field={field}
                        selected={
                          formDraft.fields.includes(
                            field.key
                          )
                        }
                        onToggle={toggleField}
                      />
                    ))}
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="qualify-at">
                      Qualified at
                    </Label>
                    <Input
                      id="qualify-at"
                      type="number"
                      min="0"
                      max="100"
                      value={
                        formDraft.qualify_at
                      }
                      onChange={(event) =>
                        setFormDraft(
                          (current) => ({
                            ...current,
                            qualify_at:
                              event.target.value,
                          })
                        )
                      }
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="review-at">
                      Review at
                    </Label>
                    <Input
                      id="review-at"
                      type="number"
                      min="0"
                      max="100"
                      value={
                        formDraft.review_at
                      }
                      onChange={(event) =>
                        setFormDraft(
                          (current) => ({
                            ...current,
                            review_at:
                              event.target.value,
                          })
                        )
                      }
                    />
                  </div>
                </div>

                <div className="rounded-xl border border-[#d8cba9] bg-[#f7f1e4] px-3 py-3 text-xs text-[#6b5836]">
                  <Sparkles
                    size={14}
                    className="mr-1 inline"
                  />
                  Deterministic scoring rules are generated from selected
                  fields. AI does not decide qualification.
                </div>

                <div className="space-y-2">
                  <Label>Status</Label>
                  <Select
                    value={formDraft.status}
                    onValueChange={(value) =>
                      setFormDraft(
                        (current) => ({
                          ...current,
                          status: value,
                        })
                      )
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="draft">
                        Draft
                      </SelectItem>
                      <SelectItem value="active">
                        Active
                      </SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <Button
                  type="submit"
                  disabled={busy}
                  className="w-full bg-[#8a6a3c] text-white hover:bg-[#72572f]"
                  data-testid="create-qualification-form"
                >
                  <Plus
                    size={15}
                    className="mr-2"
                  />
                  Create Form
                </Button>
              </form>


              <div className="space-y-3">
                <div className="font-semibold text-[#3f3320]">
                  Existing Qualification Forms
                </div>

                {forms.length === 0 ? (
                  <EmptyState>
                    No marketing qualification forms yet.
                  </EmptyState>
                ) : (
                  forms.map((form) => {
                    const fields =
                      normalizeArray(
                        form.schema?.fields
                      );

                    return (
                      <div
                        key={form.id}
                        className="rounded-2xl border border-[#d8cba9] bg-white p-4"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="font-semibold text-[#3f3320]">
                              {form.name}
                            </div>
                            <div className="mt-1 text-xs text-[#806837]">
                              {fields.length} safe field
                              {fields.length === 1
                                ? ""
                                : "s"}
                            </div>
                          </div>

                          <Badge
                            variant="outline"
                            className={
                              statusBadge(
                                form.status
                              )
                            }
                          >
                            {form.status}
                          </Badge>
                        </div>

                        <div className="mt-3 flex flex-wrap gap-2">
                          {fields.map((field) => (
                            <span
                              key={field}
                              className="rounded-full bg-[#f7f1e4] px-2 py-1 text-xs text-[#6b5836]"
                            >
                              {field}
                            </span>
                          ))}
                        </div>

                        <div className="mt-3 text-xs text-[#806837]">
                          Qualified:{" "}
                          {form
                            .qualification_config
                            ?.qualify_at ??
                            "—"}
                          {" · "}
                          Review:{" "}
                          {form
                            .qualification_config
                            ?.review_at ??
                            "—"}
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </TabsContent>


          <TabsContent
            value="offers"
            className="space-y-5"
          >
            <div className="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
              <form
                onSubmit={createOffer}
                className="space-y-4 rounded-2xl border border-[#d8cba9] bg-white p-5"
              >
                <div>
                  <div className="flex items-center gap-2 font-semibold text-[#3f3320]">
                    <Target size={16} />
                    Create Offer
                  </div>
                  <p className="mt-1 text-xs text-[#806837]">
                    Offers are matched deterministically to qualified
                    marketing leads.
                  </p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="offer-name">
                    Offer name
                  </Label>
                  <Input
                    id="offer-name"
                    value={offerDraft.name}
                    onChange={(event) =>
                      setOfferDraft(
                        (current) => ({
                          ...current,
                          name:
                            event.target.value,
                        })
                      )
                    }
                    placeholder="Wellness Consultation"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="offer-slug">
                    Slug
                  </Label>
                  <Input
                    id="offer-slug"
                    value={offerDraft.slug}
                    onChange={(event) =>
                      setOfferDraft(
                        (current) => ({
                          ...current,
                          slug:
                            event.target.value,
                        })
                      )
                    }
                    placeholder="Auto-generated from name"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="offer-service">
                    Service interest
                  </Label>
                  <Input
                    id="offer-service"
                    value={
                      offerDraft
                        .service_interest
                    }
                    onChange={(event) =>
                      setOfferDraft(
                        (current) => ({
                          ...current,
                          service_interest:
                            event.target.value,
                        })
                      )
                    }
                    placeholder="wellness"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="offer-score">
                    Minimum qualification score
                  </Label>
                  <Input
                    id="offer-score"
                    type="number"
                    min="0"
                    max="100"
                    value={
                      offerDraft
                        .min_qualification_score
                    }
                    onChange={(event) =>
                      setOfferDraft(
                        (current) => ({
                          ...current,
                          min_qualification_score:
                            event.target.value,
                        })
                      )
                    }
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="offer-locations">
                    Eligible locations
                  </Label>
                  <Input
                    id="offer-locations"
                    value={
                      offerDraft
                        .eligible_locations
                    }
                    onChange={(event) =>
                      setOfferDraft(
                        (current) => ({
                          ...current,
                          eligible_locations:
                            event.target.value,
                        })
                      )
                    }
                    placeholder="Roswell, Alpharetta"
                  />
                  <div className="text-xs text-[#806837]">
                    Separate locations with commas.
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="offer-description">
                    Description
                  </Label>
                  <Textarea
                    id="offer-description"
                    rows={3}
                    value={
                      offerDraft.description
                    }
                    onChange={(event) =>
                      setOfferDraft(
                        (current) => ({
                          ...current,
                          description:
                            event.target.value,
                        })
                      )
                    }
                    placeholder="Internal offer description"
                  />
                </div>

                <div className="space-y-2">
                  <Label>Status</Label>
                  <Select
                    value={offerDraft.status}
                    onValueChange={(value) =>
                      setOfferDraft(
                        (current) => ({
                          ...current,
                          status: value,
                        })
                      )
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="draft">
                        Draft
                      </SelectItem>
                      <SelectItem value="active">
                        Active
                      </SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <Button
                  type="submit"
                  disabled={busy}
                  className="w-full bg-[#8a6a3c] text-white hover:bg-[#72572f]"
                  data-testid="create-offer"
                >
                  <Plus
                    size={15}
                    className="mr-2"
                  />
                  Create Offer
                </Button>
              </form>


              <div className="space-y-3">
                <div className="font-semibold text-[#3f3320]">
                  Existing Offers
                </div>

                {offers.length === 0 ? (
                  <EmptyState>
                    No offers have been created yet.
                  </EmptyState>
                ) : (
                  offers.map((offer) => {
                    const locations =
                      normalizeArray(
                        offer
                          .eligible_locations
                      );

                    return (
                      <div
                        key={offer.id}
                        className="rounded-2xl border border-[#d8cba9] bg-white p-4"
                      >
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <div className="font-semibold text-[#3f3320]">
                              {offer.name}
                            </div>

                            <div className="mt-1 flex items-center gap-2 text-xs text-[#806837]">
                              <Boxes size={13} />
                              {offer.service_interest ||
                                "Any service"}
                            </div>
                          </div>

                          <Badge
                            variant="outline"
                            className={
                              statusBadge(
                                offer.status
                              )
                            }
                          >
                            {offer.status}
                          </Badge>
                        </div>

                        <div className="mt-4 grid gap-3 sm:grid-cols-2">
                          <div className="rounded-xl bg-[#fdfbf5] px-3 py-2">
                            <div className="text-xs uppercase tracking-wide text-[#8a6a3c]">
                              Minimum score
                            </div>
                            <div className="mt-1 font-semibold text-[#3f3320]">
                              {
                                offer
                                  .min_qualification_score
                              }
                            </div>
                          </div>

                          <div className="rounded-xl bg-[#fdfbf5] px-3 py-2">
                            <div className="flex items-center gap-1 text-xs uppercase tracking-wide text-[#8a6a3c]">
                              <MapPin size={12} />
                              Locations
                            </div>

                            <div className="mt-1 text-sm text-[#3f3320]">
                              {locations.length > 0
                                ? locations.join(
                                    ", "
                                  )
                                : "Any"}
                            </div>
                          </div>
                        </div>

                        {offer.description ? (
                          <p className="mt-3 text-sm text-[#806837]">
                            {offer.description}
                          </p>
                        ) : null}
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </TabsContent>
        </Tabs>
      )}
    </SectionCard>
  );
}
