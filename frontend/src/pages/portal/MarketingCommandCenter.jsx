import React from "react";

import PortalLayout, {
  PortalHeader,
  StatCard,
} from "../PortalLayout";

import api from "../../lib/api";

import MarketingGoalsPanel from "./MarketingGoalsPanel";
import MarketingBudgetsPanel from "./MarketingBudgetsPanel";
import SearchIntelligencePanel from "./SearchIntelligencePanel";

import { Button } from "../../components/ui/button";

import {
  BadgeDollarSign,
  BarChart3,
  Brain,
  CheckCircle2,
  CircleDollarSign,
  Loader2,
  Megaphone,
  RefreshCw,
  ShieldCheck,
  Target,
  TrendingUp,
  XCircle,
} from "lucide-react";


function asArray(value, keys = []) {
  if (Array.isArray(value)) {
    return value;
  }

  for (const key of keys) {
    if (Array.isArray(value?.[key])) {
      return value[key];
    }
  }

  return [];
}


function asNumber(value) {
  const number = Number(value);

  return Number.isFinite(number)
    ? number
    : 0;
}


function money(value) {
  return asNumber(value).toLocaleString(
    undefined,
    {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0,
    }
  );
}


function formatDate(value) {
  if (!value) {
    return "Never";
  }

  try {
    return new Date(value).toLocaleString();
  } catch {
    return String(value);
  }
}


function statusTone(status) {
  const normalized = String(
    status || ""
  ).toLowerCase();

  if (
    [
      "ready",
      "active",
      "approved",
      "connected",
      "healthy",
      "strong",
    ].includes(normalized)
  ) {
    return (
      "border-[#b9d2bf] " +
      "bg-[#edf5ef] " +
      "text-[#2f6a4a]"
    );
  }

  if (
    [
      "pending",
      "planned",
      "foundation_ready",
      "needs_attention",
    ].includes(normalized)
  ) {
    return (
      "border-[#d8cba9] " +
      "bg-[#f7f1e4] " +
      "text-[#8a6a3c]"
    );
  }

  if (
    [
      "blocked",
      "rejected",
      "weak",
      "unsafe_configuration",
    ].includes(normalized)
  ) {
    return (
      "border-[#d9b7b7] " +
      "bg-[#f9eeee] " +
      "text-[#7a2a2a]"
    );
  }

  return (
    "border-[#e7dfc9] " +
    "bg-[#fbf7ee] " +
    "text-[#6a6a6a]"
  );
}


function StatusPill({
  children,
  tone,
}) {
  return (
    <span
      className={
        "inline-flex items-center " +
        "rounded-full border px-2.5 py-1 " +
        "text-[11px] font-semibold " +
        (tone || statusTone(children))
      }
    >
      {children}
    </span>
  );
}


function SectionCard({
  title,
  eyebrow,
  icon: Icon,
  actions,
  children,
  testid,
}) {
  return (
    <section
      className={
        "rounded-2xl border " +
        "border-[#e7dfc9] " +
        "bg-[#fbf7ee] p-5"
      }
      data-testid={testid}
    >
      <div
        className={
          "mb-4 flex flex-wrap " +
          "items-start justify-between gap-3"
        }
      >
        <div>
          {eyebrow && (
            <div
              className={
                "mb-1 text-[11px] uppercase " +
                "tracking-widest text-[#8a6a3c]"
              }
            >
              {eyebrow}
            </div>
          )}

          <div
            className={
              "flex items-center gap-2 " +
              "font-display text-xl " +
              "text-[#1f2a22]"
            }
          >
            {Icon && (
              <Icon
                size={18}
                className="text-[#2f4a3a]"
              />
            )}

            {title}
          </div>
        </div>

        {actions}
      </div>

      {children}
    </section>
  );
}


function EmptyState({
  children,
}) {
  return (
    <div
      className={
        "rounded-xl border border-dashed " +
        "border-[#d8cba9] px-4 py-8 " +
        "text-center text-sm text-[#6a6a6a]"
      }
    >
      {children}
    </div>
  );
}


export default function MarketingCommandCenter() {
  const [loading, setLoading] =
    React.useState(true);

  const [refreshing, setRefreshing] =
    React.useState(false);

  const [error, setError] =
    React.useState("");

  const [capabilities, setCapabilities] =
    React.useState({});

  const [goals, setGoals] =
    React.useState([]);

  const [budgets, setBudgets] =
    React.useState([]);

  const [channels, setChannels] =
    React.useState([]);

  const [recommendations, setRecommendations] =
    React.useState([]);

  const [brief, setBrief] =
    React.useState(null);

  const [decisionBusy, setDecisionBusy] =
    React.useState(null);


  const load = React.useCallback(
    async ({
      manual = false,
    } = {}) => {
      if (manual) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }

      setError("");

      try {
        const [
          capabilitiesResponse,
          goalsResponse,
          budgetsResponse,
          channelsResponse,
          briefResponse,
        ] = await Promise.all([
          api.get(
            "/marketing-os/capabilities"
          ),
          api.get(
            "/marketing-os/goals"
          ),
          api.get(
            "/marketing-os/budgets"
          ),
          api.get(
            "/marketing-os/channel-accounts"
          ),
          api.get(
            "/marketing-os/director/brief"
          ),
        ]);

        setCapabilities(
          capabilitiesResponse.data || {}
        );

        setGoals(
          asArray(
            goalsResponse.data,
            ["goals", "items"]
          )
        );

        setBudgets(
          asArray(
            budgetsResponse.data,
            ["budgets", "items"]
          )
        );

        setChannels(
          asArray(
            channelsResponse.data,
            [
              "channel_accounts",
              "accounts",
              "items",
            ]
          )
        );

        setBrief(
          briefResponse.data || null
        );

        // Director brief persists advisory
        // recommendations. Fetch the canonical
        // list after the brief has completed.
        const recommendationResponse =
          await api.get(
            "/marketing-os/recommendations"
          );

        setRecommendations(
          asArray(
            recommendationResponse.data,
            [
              "recommendations",
              "items",
            ]
          )
        );

      } catch (loadError) {
        setError(
          loadError?.response?.data?.detail ||
          loadError?.message ||
          "Could not load Marketing Command Center."
        );

      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    []
  );


  React.useEffect(() => {
    load();
  }, [load]);


  const decide = async (
    recommendation,
    decision
  ) => {
    if (!recommendation?.id) {
      return;
    }

    let reason = "";

    if (decision === "rejected") {
      const entered = window.prompt(
        "Reason for rejecting this recommendation:",
        ""
      );

      if (entered === null) {
        return;
      }

      reason = entered.trim();
    } else {
      reason =
        "Approved in Marketing Command Center";
    }

    setDecisionBusy(
      recommendation.id
    );

    setError("");

    try {
      const response = await api.post(
        `/marketing-os/recommendations/${
          recommendation.id
        }/decision`,
        {
          decision,
          reason,
        }
      );

      const result =
        response.data || {};

      setRecommendations(
        (current) =>
          current.map(
            (item) =>
              item.id === recommendation.id
                ? {
                    ...item,
                    status:
                      result.decision ||
                      decision,
                    action_status:
                      result.action_status,
                    dry_run:
                      result.dry_run,
                  }
                : item
          )
      );

    } catch (decisionError) {
      setError(
        decisionError?.response?.data?.detail ||
        decisionError?.message ||
        "Could not record recommendation decision."
      );

    } finally {
      setDecisionBusy(null);
    }
  };


  const activeGoals =
    asArray(goals).filter(
      (goal) =>
        String(
          goal?.status || ""
        ).toLowerCase() === "active"
    ).length;


  const pendingRecommendations =
    asArray(recommendations).filter(
      (recommendation) =>
        String(
          recommendation?.status || ""
        ).toLowerCase() === "pending"
    );


  const approvedBudget =
    asArray(budgets).reduce(
      (sum, budget) =>
        sum +
        asNumber(
          budget?.approved_amount ??
          budget?.approved_budget ??
          budget?.approved ??
          budget?.amount
        ),
      0
    );


  const trackedSpend =
    asArray(budgets).reduce(
      (sum, budget) =>
        sum +
        asNumber(
          budget?.spent_amount ??
          budget?.spent ??
          budget?.actual_spend
        ),
      0
    );


  const channelAnalysis =
    asArray(
      brief?.channel_analysis
    );


  const attributedRevenue =
    channelAnalysis.reduce(
      (sum, channel) =>
        sum +
        asNumber(
          channel?.revenue ??
          channel?.conversion_value
        ),
      0
    );


  const spendFromBrief =
    channelAnalysis.reduce(
      (sum, channel) =>
        sum +
        asNumber(
          channel?.spend
        ),
      0
    );


  const totalSpend =
    spendFromBrief || trackedSpend;


  const overallRoas =
    totalSpend > 0
      ? attributedRevenue / totalSpend
      : 0;


  const directorStatus =
    brief?.status || "advisory";


  if (loading) {
    return (
      <PortalLayout>
        <PortalHeader
          title="Marketing Command Center"
          subtitle={
            "Performance, goals, budgets, " +
            "attribution, and AI recommendations"
          }
        />

        <div
          className={
            "flex items-center justify-center " +
            "py-24 text-[#6a6a6a]"
          }
        >
          <Loader2
            size={20}
            className="mr-2 animate-spin"
          />
          Loading marketing intelligence…
        </div>
      </PortalLayout>
    );
  }


  return (
    <PortalLayout>
      <PortalHeader
        title="Marketing Command Center"
        subtitle={
          "Performance, goals, budgets, " +
          "attribution, and AI recommendations"
        }
        actions={
          <Button
            type="button"
            variant="outline"
            disabled={refreshing}
            onClick={() =>
              load({
                manual: true,
              })
            }
            className={
              "h-10 rounded-full " +
              "border-[#c19a4b] " +
              "text-[#8a6a3c]"
            }
            data-testid="marketing-refresh"
          >
            <RefreshCw
              size={14}
              className={
                "mr-2 " +
                (
                  refreshing
                    ? "animate-spin"
                    : ""
                )
              }
            />
            Refresh
          </Button>
        }
      />

      <div
        className={
          "mb-6 rounded-2xl border " +
          "border-[#d8cba9] " +
          "bg-[#f7f1e4] p-5"
        }
      >
        <div className="flex gap-3">
          <Brain
            size={24}
            className={
              "mt-0.5 shrink-0 " +
              "text-[#2f4a3a]"
            }
          />

          <div>
            <div
              className={
                "font-semibold " +
                "text-[#1f2a22]"
              }
            >
              AI Marketing Director
              {" "}
              <StatusPill>
                {directorStatus}
              </StatusPill>
            </div>

            <p
              className={
                "mt-1 text-sm leading-6 " +
                "text-[#6a6a6a]"
              }
            >
              The Director analyzes marketing
              performance and creates advisory
              recommendations for human review.
              Approval does not execute an external
              advertising change.
            </p>
          </div>
        </div>
      </div>


      {error && (
        <div
          className={
            "mb-6 rounded-2xl border " +
            "border-[#d9b7b7] " +
            "bg-[#f9eeee] p-4 " +
            "text-sm text-[#7a2a2a]"
          }
          data-testid="marketing-error"
        >
          {String(error)}
        </div>
      )}


      <div
        className={
          "mb-8 grid gap-4 " +
          "sm:grid-cols-2 xl:grid-cols-5"
        }
      >
        <StatCard
          label="Active goals"
          value={activeGoals}
          icon={Target}
        />

        <StatCard
          label="Approved budget"
          value={money(approvedBudget)}
          icon={CircleDollarSign}
        />

        <StatCard
          label="Tracked spend"
          value={money(totalSpend)}
          icon={BadgeDollarSign}
        />

        <StatCard
          label="Attributed revenue"
          value={money(attributedRevenue)}
          icon={TrendingUp}
        />

        <StatCard
          label="Pending decisions"
          value={pendingRecommendations.length}
          icon={Brain}
          accent={
            pendingRecommendations.length
              ? "text-[#8a6a3c]"
              : "text-[#2f4a3a]"
          }
        />
      </div>


      <div
        className={
          "mb-8 space-y-6"
        }
      >
        <SectionCard
          title="Channel performance"
          eyebrow="Overview"
          icon={BarChart3}
          testid="marketing-channel-performance"
        >
          {channelAnalysis.length === 0 ? (
            <EmptyState>
              No synchronized marketing
              performance yet.
            </EmptyState>
          ) : (
            <div className="space-y-3">
              {channelAnalysis.map(
                (channel, index) => (
                  <div
                    key={
                      channel?.channel ||
                      index
                    }
                    className={
                      "rounded-xl border " +
                      "border-[#e7dfc9] " +
                      "bg-white p-4"
                    }
                  >
                    <div
                      className={
                        "flex items-center " +
                        "justify-between gap-3"
                      }
                    >
                      <div
                        className={
                          "font-medium " +
                          "capitalize " +
                          "text-[#1f2a22]"
                        }
                      >
                        {
                          channel?.channel ||
                          channel?.provider ||
                          "Unknown"
                        }
                      </div>

                      <StatusPill>
                        {
                          channel?.status ||
                          "monitoring"
                        }
                      </StatusPill>
                    </div>

                    <div
                      className={
                        "mt-3 grid grid-cols-3 " +
                        "gap-3 text-sm"
                      }
                    >
                      <div>
                        <div
                          className={
                            "text-[10px] uppercase " +
                            "tracking-widest " +
                            "text-[#8a6a3c]"
                          }
                        >
                          Spend
                        </div>
                        <div
                          className={
                            "mt-1 font-semibold " +
                            "text-[#1f2a22]"
                          }
                        >
                          {money(
                            channel?.spend
                          )}
                        </div>
                      </div>

                      <div>
                        <div
                          className={
                            "text-[10px] uppercase " +
                            "tracking-widest " +
                            "text-[#8a6a3c]"
                          }
                        >
                          Revenue
                        </div>
                        <div
                          className={
                            "mt-1 font-semibold " +
                            "text-[#1f2a22]"
                          }
                        >
                          {money(
                            channel?.revenue
                          )}
                        </div>
                      </div>

                      <div>
                        <div
                          className={
                            "text-[10px] uppercase " +
                            "tracking-widest " +
                            "text-[#8a6a3c]"
                          }
                        >
                          ROAS
                        </div>
                        <div
                          className={
                            "mt-1 font-semibold " +
                            "text-[#2f4a3a]"
                          }
                        >
                          {
                            asNumber(
                              channel?.roas
                            ).toFixed(2)
                          }x
                        </div>
                      </div>
                    </div>
                  </div>
                )
              )}
            </div>
          )}
        </SectionCard>


        <MarketingGoalsPanel
          goals={goals}
          onChanged={() =>
            load({
              manual: true,
            })
          }
        />

        <MarketingBudgetsPanel
          budgets={budgets}
          goals={goals}
          totalSpend={totalSpend}
          overallRoas={overallRoas}
          onChanged={() =>
            load({
              manual: true,
            })
          }
        />

        <SearchIntelligencePanel />
      </div>


      <div className="mb-8">
        <SectionCard
          title="AI recommendations"
          eyebrow="Human review queue"
          icon={Brain}
          testid="marketing-recommendations"
        >
          {recommendations.length === 0 ? (
            <EmptyState>
              No recommendations yet. The
              Marketing Director will create
              advisory recommendations as
              performance data becomes available.
            </EmptyState>
          ) : (
            <div className="space-y-4">
              {asArray(recommendations).map(
                (recommendation) => {
                  const pending =
                    String(
                      recommendation?.status ||
                      ""
                    ).toLowerCase() ===
                    "pending";

                  const busy =
                    decisionBusy ===
                    recommendation.id;

                  return (
                    <div
                      key={recommendation.id}
                      className={
                        "rounded-2xl border " +
                        "border-[#e7dfc9] " +
                        "bg-white p-5"
                      }
                      data-testid={
                        `marketing-recommendation-${
                          recommendation.id
                        }`
                      }
                    >
                      <div
                        className={
                          "flex flex-col gap-4 " +
                          "lg:flex-row " +
                          "lg:items-start " +
                          "lg:justify-between"
                        }
                      >
                        <div className="min-w-0">
                          <div
                            className={
                              "flex flex-wrap " +
                              "items-center gap-2"
                            }
                          >
                            <StatusPill>
                              {
                                recommendation.status ||
                                "pending"
                              }
                            </StatusPill>

                            <StatusPill
                              tone={
                                "border-[#e7dfc9] " +
                                "bg-[#fbf7ee] " +
                                "text-[#6a6a6a]"
                              }
                            >
                              {
                                recommendation.provider ||
                                recommendation.channel ||
                                "internal"
                              }
                            </StatusPill>
                          </div>

                          <h3
                            className={
                              "mt-3 font-display " +
                              "text-xl text-[#1f2a22]"
                            }
                          >
                            {
                              recommendation.title ||
                              "Marketing recommendation"
                            }
                          </h3>

                          <p
                            className={
                              "mt-2 max-w-3xl " +
                              "text-sm leading-6 " +
                              "text-[#6a6a6a]"
                            }
                          >
                            {
                              recommendation.reason ||
                              recommendation.summary ||
                              "No explanation provided."
                            }
                          </p>

                          {recommendation
                            ?.proposed_action && (
                            <div
                              className={
                                "mt-3 rounded-xl " +
                                "bg-[#f7f1e4] p-3 " +
                                "text-sm text-[#3a3a3a]"
                              }
                            >
                              <span
                                className={
                                  "font-semibold " +
                                  "text-[#1f2a22]"
                                }
                              >
                                Proposed action:
                              </span>
                              {" "}
                              {
                                typeof recommendation
                                  .proposed_action ===
                                "string"
                                  ? recommendation
                                      .proposed_action
                                  : recommendation
                                      .proposed_action
                                      ?.instruction ||
                                    "Review proposal"
                              }
                            </div>
                          )}

                          {recommendation
                            ?.action_status && (
                            <div
                              className={
                                "mt-3 text-xs " +
                                "text-[#7a2a2a]"
                              }
                            >
                              Action ledger:
                              {" "}
                              {
                                recommendation
                                  .action_status
                              }
                              {
                                recommendation
                                  .dry_run
                                  ? " · dry-run"
                                  : ""
                              }
                            </div>
                          )}
                        </div>

                        {pending && (
                          <div
                            className={
                              "flex shrink-0 gap-2"
                            }
                          >
                            <Button
                              type="button"
                              variant="outline"
                              disabled={busy}
                              onClick={() =>
                                decide(
                                  recommendation,
                                  "rejected"
                                )
                              }
                              className={
                                "rounded-full " +
                                "border-[#d9b7b7] " +
                                "text-[#7a2a2a]"
                              }
                              data-testid={
                                `marketing-reject-${
                                  recommendation.id
                                }`
                              }
                            >
                              <XCircle
                                size={14}
                                className="mr-1.5"
                              />
                              Reject
                            </Button>

                            <Button
                              type="button"
                              disabled={busy}
                              onClick={() =>
                                decide(
                                  recommendation,
                                  "approved"
                                )
                              }
                              className={
                                "rounded-full " +
                                "bg-[#2f4a3a] " +
                                "text-[#f6f1e6] " +
                                "hover:bg-[#263d30]"
                              }
                              data-testid={
                                `marketing-approve-${
                                  recommendation.id
                                }`
                              }
                            >
                              {
                                busy
                                  ? (
                                    <Loader2
                                      size={14}
                                      className={
                                        "mr-1.5 animate-spin"
                                      }
                                    />
                                  )
                                  : (
                                    <CheckCircle2
                                      size={14}
                                      className="mr-1.5"
                                    />
                                  )
                              }
                              Approve
                            </Button>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                }
              )}
            </div>
          )}
        </SectionCard>
      </div>


      <div
        className={
          "grid gap-6 xl:grid-cols-2"
        }
      >
        <SectionCard
          title="Channel connections"
          eyebrow="Integrations"
          icon={Megaphone}
          testid="marketing-channel-connections"
        >
          {channels.length === 0 ? (
            <EmptyState>
              No marketing channel account has
              been registered yet.
            </EmptyState>
          ) : (
            <div className="divide-y divide-[#e7dfc9]">
              {asArray(channels).map(
                (channel) => (
                  <div
                    key={channel.id}
                    className={
                      "flex flex-wrap " +
                      "items-center " +
                      "justify-between gap-3 py-3"
                    }
                  >
                    <div>
                      <div
                        className={
                          "font-medium " +
                          "capitalize " +
                          "text-[#1f2a22]"
                        }
                      >
                        {
                          channel.account_name ||
                          channel.provider ||
                          "Marketing account"
                        }
                      </div>

                      <div
                        className={
                          "mt-1 text-xs " +
                          "text-[#6a6a6a]"
                        }
                      >
                        {
                          channel.provider ||
                          "provider"
                        }
                        {" · "}
                        Last sync:
                        {" "}
                        {formatDate(
                          channel.last_sync_at
                        )}
                      </div>
                    </div>

                    <div
                      className={
                        "flex items-center gap-2"
                      }
                    >
                      <StatusPill>
                        {
                          channel.status ||
                          "disconnected"
                        }
                      </StatusPill>

                      <StatusPill
                        tone={
                          channel.write_enabled
                            ? (
                              "border-[#d9b7b7] " +
                              "bg-[#f9eeee] " +
                              "text-[#7a2a2a]"
                            )
                            : (
                              "border-[#b9d2bf] " +
                              "bg-[#edf5ef] " +
                              "text-[#2f6a4a]"
                            )
                        }
                      >
                        {
                          channel.write_enabled
                            ? "Writes enabled"
                            : "Read only"
                        }
                      </StatusPill>
                    </div>
                  </div>
                )
              )}
            </div>
          )}
        </SectionCard>


        <SectionCard
          title="Safety controls"
          eyebrow="Guarded autopilot"
          icon={ShieldCheck}
          testid="marketing-safety"
        >
          <div className="space-y-3">
            <SafetyRow
              label="External advertising writes"
              enabled={false}
              safeLabel="Disabled"
            />

            <SafetyRow
              label="Automatic budget changes"
              enabled={false}
              safeLabel="Disabled"
            />

            <SafetyRow
              label="Automatic campaign creation"
              enabled={false}
              safeLabel="Disabled"
            />

            <SafetyRow
              label="Automatic publishing"
              enabled={false}
              safeLabel="Disabled"
            />

            <SafetyRow
              label="Human approval"
              enabled={true}
              safeLabel="Required"
            />

            <SafetyRow
              label="Approved action execution"
              enabled={false}
              safeLabel="Blocked / dry-run"
            />
          </div>

          <div
            className={
              "mt-5 rounded-xl border " +
              "border-[#d8cba9] " +
              "bg-[#f7f1e4] p-4"
            }
          >
            <div
              className={
                "flex items-start gap-3"
              }
            >
              <ShieldCheck
                size={18}
                className={
                  "mt-0.5 shrink-0 " +
                  "text-[#2f4a3a]"
                }
              />

              <p
                className={
                  "text-sm leading-6 " +
                  "text-[#3a3a3a]"
                }
              >
                Recommendation approval records
                intent but does not permit Google
                Ads, Meta, TikTok, publishing, or
                budget mutation to execute.
              </p>
            </div>
          </div>

          {Object.keys(
            capabilities || {}
          ).length > 0 && (
            <div
              className={
                "mt-4 text-xs " +
                "text-[#6a6a6a]"
              }
            >
              Capability registry loaded
              successfully.
            </div>
          )}
        </SectionCard>
      </div>
    </PortalLayout>
  );
}


function SafetyRow({
  label,
  enabled,
  safeLabel,
}) {
  return (
    <div
      className={
        "flex items-center justify-between " +
        "gap-3 rounded-xl border " +
        "border-[#e7dfc9] bg-white p-3"
      }
    >
      <div
        className={
          "flex items-center gap-2 " +
          "text-sm text-[#1f2a22]"
        }
      >
        {
          enabled
            ? (
              <CheckCircle2
                size={15}
                className="text-[#2f6a4a]"
              />
            )
            : (
              <ShieldCheck
                size={15}
                className="text-[#2f4a3a]"
              />
            )
        }

        {label}
      </div>

      <span
        className={
          "text-xs font-semibold " +
          "text-[#2f6a4a]"
        }
      >
        {safeLabel}
      </span>
    </div>
  );
}
