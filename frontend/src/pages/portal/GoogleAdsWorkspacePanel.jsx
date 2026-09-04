import React from "react";
import {
  Activity,
  BarChart3,
  ChevronDown,
  ChevronRight,
  CircleDollarSign,
  ExternalLink,
  Eye,
  MousePointerClick,
  RefreshCw,
  Target,
} from "lucide-react";

import { api } from "../../lib/api";


function asArray(value) {
  return Array.isArray(value)
    ? value
    : [];
}


function number(value) {
  const parsed = Number(value);

  return Number.isFinite(parsed)
    ? parsed
    : 0;
}


function money(value) {
  return new Intl.NumberFormat(
    "en-US",
    {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }
  ).format(
    number(value)
  );
}


function integer(value) {
  return new Intl.NumberFormat(
    "en-US",
    {
      maximumFractionDigits: 0,
    }
  ).format(
    number(value)
  );
}


function percent(value) {
  const parsed = Number(value);

  if (!Number.isFinite(parsed)) {
    return "—";
  }

  return `${(
    parsed * 100
  ).toFixed(2)}%`;
}


function ratio(value) {
  const parsed = Number(value);

  if (!Number.isFinite(parsed)) {
    return "—";
  }

  return `${parsed.toFixed(2)}x`;
}


function statusClass(status) {
  const normalized = String(
    status || ""
  ).toUpperCase();

  if (normalized === "ENABLED") {
    return (
      "border-[#bfd3c2] " +
      "bg-[#eef6ef] " +
      "text-[#2f5a39]"
    );
  }

  if (normalized === "PAUSED") {
    return (
      "border-[#e4d5aa] " +
      "bg-[#fff8e8] " +
      "text-[#7a5a1f]"
    );
  }

  return (
    "border-[#dedede] " +
    "bg-[#f7f7f7] " +
    "text-[#666]"
  );
}


function StatusBadge({
  status,
}) {
  return (
    <span
      className={
        "inline-flex items-center rounded-full " +
        "border px-2.5 py-1 text-xs font-semibold " +
        statusClass(status)
      }
    >
      {status || "Unknown"}
    </span>
  );
}


function MetricCard({
  label,
  value,
  icon: Icon,
}) {
  return (
    <div
      className={
        "rounded-2xl border border-[#e7dfc9] " +
        "bg-white p-4"
      }
    >
      <div className="flex items-center gap-2">
        {Icon ? (
          <Icon
            size={16}
            className="text-[#8a6a3c]"
          />
        ) : null}

        <div
          className={
            "text-[10px] font-semibold uppercase " +
            "tracking-[0.16em] text-[#8a6a3c]"
          }
        >
          {label}
        </div>
      </div>

      <div
        className={
          "mt-2 text-xl font-semibold text-[#1f2a22]"
        }
      >
        {value}
      </div>
    </div>
  );
}


function Empty({
  children,
}) {
  return (
    <div
      className={
        "rounded-xl border border-dashed border-[#d8cba9] " +
        "bg-[#fffdf8] px-4 py-6 text-center " +
        "text-sm text-[#6a6a6a]"
      }
    >
      {children}
    </div>
  );
}


function DetailTable({
  columns,
  rows,
  empty,
}) {
  const items = asArray(rows);

  if (!items.length) {
    return (
      <Empty>
        {empty}
      </Empty>
    );
  }

  return (
    <div
      className={
        "overflow-x-auto rounded-xl border " +
        "border-[#e7dfc9] bg-white"
      }
    >
      <table className="min-w-full text-sm">
        <thead className="bg-[#f8f3e8]">
          <tr>
            {columns.map(
              (column) => (
                <th
                  key={column.key}
                  className={
                    "whitespace-nowrap px-3 py-2 " +
                    "text-left text-[10px] font-semibold " +
                    "uppercase tracking-widest text-[#7a6845]"
                  }
                >
                  {column.label}
                </th>
              )
            )}
          </tr>
        </thead>

        <tbody>
          {items.map(
            (row, index) => (
              <tr
                key={
                  row.id ||
                  row.ad_group_id ||
                  row.ad_id ||
                  row.criterion_id ||
                  row.conversion_action_id ||
                  index
                }
                className="border-t border-[#eee7d6]"
              >
                {columns.map(
                  (column) => (
                    <td
                      key={column.key}
                      className={
                        "whitespace-nowrap px-3 py-3 " +
                        "align-top text-[#343a35]"
                      }
                    >
                      {
                        column.render
                          ? column.render(row)
                          : row[column.key] ?? "—"
                      }
                    </td>
                  )
                )}
              </tr>
            )
          )}
        </tbody>
      </table>
    </div>
  );
}


export default function GoogleAdsWorkspacePanel() {
  const [days, setDays] =
    React.useState(30);

  const [loading, setLoading] =
    React.useState(true);

  const [refreshing, setRefreshing] =
    React.useState(false);

  const [error, setError] =
    React.useState("");

  const [overview, setOverview] =
    React.useState(null);

  const [campaigns, setCampaigns] =
    React.useState([]);

  const [selectedId, setSelectedId] =
    React.useState(null);

  const [detail, setDetail] =
    React.useState(null);

  const [detailLoading, setDetailLoading] =
    React.useState(false);


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
          overviewResponse,
          campaignsResponse,
        ] = await Promise.all([
          api.get(
            `/marketing-os/google-ads/overview?days=${days}`
          ),
          api.get(
            `/marketing-os/google-ads/campaigns?days=${days}`
          ),
        ]);

        const overviewData =
          overviewResponse?.data || {};

        const campaignsData =
          campaignsResponse?.data || {};

        setOverview(
          overviewData
        );

        setCampaigns(
          asArray(
            campaignsData.items
          )
        );

      } catch (err) {
        setError(
          err?.response?.data?.detail?.message ||
          err?.response?.data?.detail ||
          err?.message ||
          "Could not load live Google Ads data."
        );

      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [days]
  );


  React.useEffect(() => {
    load();
  }, [load]);


  async function toggleDetail(
    campaign
  ) {
    const campaignId =
      campaign?.campaign_id;

    if (!campaignId) {
      return;
    }

    if (
      String(selectedId) ===
      String(campaignId)
    ) {
      setSelectedId(null);
      setDetail(null);
      return;
    }

    setSelectedId(
      campaignId
    );

    setDetail(null);
    setDetailLoading(true);
    setError("");

    try {
      const response = await api.get(
        `/marketing-os/google-ads/campaigns/${campaignId}?days=${days}`
      );

      setDetail(
        response?.data || null
      );

    } catch (err) {
      setError(
        err?.response?.data?.detail?.message ||
        err?.response?.data?.detail ||
        err?.message ||
        "Could not load Google campaign details."
      );

    } finally {
      setDetailLoading(false);
    }
  }


  const metrics =
    overview?.metrics || {};

  const account =
    overview?.account || {};

  const adGroups =
    detail?.ad_groups || [];

  const ads =
    detail?.ads || [];

  const keywords =
    detail?.keywords || [];

  const conversionActions =
    detail?.conversion_actions || [];


  return (
    <section
      className={
        "rounded-3xl border border-[#dccfae] " +
        "bg-[#fbf7ee] p-5 md:p-6"
      }
      data-testid="google-ads-workspace"
    >
      <div
        className={
          "flex flex-col gap-4 md:flex-row " +
          "md:items-start md:justify-between"
        }
      >
        <div>
          <div
            className={
              "text-xs font-semibold uppercase " +
              "tracking-[0.18em] text-[#8a6a3c]"
            }
          >
            Live provider workspace
          </div>

          <h2
            className={
              "mt-1 text-2xl font-semibold text-[#1f2a22]"
            }
          >
            Google Ads
          </h2>

          <p
            className={
              "mt-2 max-w-3xl text-sm leading-6 " +
              "text-[#64645f]"
            }
          >
            Live account state from Google Ads.
            Campaign inventory is read directly from Google,
            including paused and zero-activity campaigns.
          </p>

          {account?.external_account_id ? (
            <div
              className={
                "mt-3 flex flex-wrap items-center gap-2 " +
                "text-xs text-[#6a6a6a]"
              }
            >
              <span>
                {account.account_name ||
                  "Google Ads account"}
              </span>

              <span>•</span>

              <span>
                {account.external_account_id}
              </span>

              {account.write_enabled ? (
                <>
                  <span>•</span>

                  <span
                    className={
                      "font-semibold text-[#2f5a39]"
                    }
                  >
                    Governed execution enabled
                  </span>
                </>
              ) : null}
            </div>
          ) : null}
        </div>

        <div
          className={
            "flex flex-wrap items-center gap-2"
          }
        >
          <select
            value={days}
            onChange={
              (event) => {
                setSelectedId(null);
                setDetail(null);
                setDays(
                  Number(
                    event.target.value
                  )
                );
              }
            }
            className={
              "rounded-xl border border-[#d8cba9] " +
              "bg-white px-3 py-2 text-sm text-[#343a35]"
            }
            aria-label="Google Ads date window"
          >
            <option value={7}>
              Last 7 days
            </option>

            <option value={30}>
              Last 30 days
            </option>

            <option value={60}>
              Last 60 days
            </option>

            <option value={90}>
              Last 90 days
            </option>

            <option value={365}>
              Last 12 months
            </option>
          </select>

          <button
            type="button"
            onClick={
              () => load({
                manual: true,
              })
            }
            disabled={
              refreshing ||
              loading
            }
            className={
              "inline-flex items-center gap-2 rounded-xl " +
              "border border-[#ccb987] bg-white px-3 py-2 " +
              "text-sm font-semibold text-[#5f4b27] " +
              "hover:bg-[#fffaf0] disabled:opacity-50"
            }
          >
            <RefreshCw
              size={15}
              className={
                refreshing
                  ? "animate-spin"
                  : ""
              }
            />

            Refresh from Google
          </button>
        </div>
      </div>


      {error ? (
        <div
          className={
            "mt-4 rounded-xl border border-[#e4b9b9] " +
            "bg-[#fff2f2] px-4 py-3 text-sm " +
            "text-[#7a3030]"
          }
        >
          {
            typeof error === "string"
              ? error
              : JSON.stringify(error)
          }
        </div>
      ) : null}


      {loading ? (
        <div
          className={
            "mt-5 rounded-xl border border-[#e7dfc9] " +
            "bg-white px-4 py-8 text-center text-sm " +
            "text-[#6a6a6a]"
          }
        >
          Loading live Google Ads account…
        </div>
      ) : (
        <>
          <div
            className={
              "mt-5 grid grid-cols-2 gap-3 " +
              "md:grid-cols-4 xl:grid-cols-8"
            }
          >
            <MetricCard
              label="Spend"
              value={
                money(
                  metrics.spend
                )
              }
              icon={CircleDollarSign}
            />

            <MetricCard
              label="Impressions"
              value={
                integer(
                  metrics.impressions
                )
              }
              icon={Eye}
            />

            <MetricCard
              label="Clicks"
              value={
                integer(
                  metrics.clicks
                )
              }
              icon={MousePointerClick}
            />

            <MetricCard
              label="CTR"
              value={
                percent(
                  metrics.ctr
                )
              }
              icon={Activity}
            />

            <MetricCard
              label="Avg CPC"
              value={
                metrics.average_cpc == null
                  ? "—"
                  : money(
                      metrics.average_cpc
                    )
              }
              icon={CircleDollarSign}
            />

            <MetricCard
              label="Conversions"
              value={
                number(
                  metrics.conversions
                ).toFixed(1)
              }
              icon={Target}
            />

            <MetricCard
              label="CPA"
              value={
                metrics.cpa == null
                  ? "—"
                  : money(
                      metrics.cpa
                    )
              }
              icon={Target}
            />

            <MetricCard
              label="ROAS"
              value={
                ratio(
                  metrics.roas
                )
              }
              icon={BarChart3}
            />
          </div>


          <div
            className={
              "mt-4 flex flex-wrap gap-3 text-sm"
            }
          >
            <div
              className={
                "rounded-xl border border-[#e7dfc9] " +
                "bg-white px-3 py-2"
              }
            >
              <span className="text-[#777]">
                Campaigns:
              </span>{" "}

              <strong>
                {
                  overview?.campaign_count ??
                  campaigns.length
                }
              </strong>
            </div>

            <div
              className={
                "rounded-xl border border-[#cde0d0] " +
                "bg-[#f0f8f1] px-3 py-2"
              }
            >
              <span className="text-[#55705d]">
                Enabled:
              </span>{" "}

              <strong>
                {
                  overview?.enabled_campaigns ??
                  0
                }
              </strong>
            </div>

            <div
              className={
                "rounded-xl border border-[#eadbb5] " +
                "bg-[#fff9eb] px-3 py-2"
              }
            >
              <span className="text-[#7a6845]">
                Paused:
              </span>{" "}

              <strong>
                {
                  overview?.paused_campaigns ??
                  0
                }
              </strong>
            </div>

            {overview?.start_date &&
            overview?.end_date ? (
              <div
                className={
                  "rounded-xl border border-[#e7dfc9] " +
                  "bg-white px-3 py-2 text-[#666]"
                }
              >
                {overview.start_date}
                {" → "}
                {overview.end_date}
              </div>
            ) : null}
          </div>


          <div className="mt-6">
            <div
              className={
                "mb-3 flex items-center justify-between gap-3"
              }
            >
              <div>
                <h3
                  className={
                    "text-lg font-semibold text-[#1f2a22]"
                  }
                >
                  Campaigns
                </h3>

                <p
                  className={
                    "mt-1 text-xs text-[#777]"
                  }
                >
                  Live provider state. Click a campaign
                  to inspect its Google Ads details.
                </p>
              </div>
            </div>


            {campaigns.length === 0 ? (
              <Empty>
                Google Ads is connected, but no
                non-removed campaigns were returned.
              </Empty>
            ) : (
              <div
                className={
                  "overflow-hidden rounded-2xl border " +
                  "border-[#e1d7be] bg-white"
                }
              >
                <div className="overflow-x-auto">
                  <table className="min-w-[1100px] w-full text-sm">
                    <thead className="bg-[#f6f0e3]">
                      <tr>
                        {[
                          "",
                          "Campaign",
                          "Status",
                          "Type",
                          "Budget",
                          "Spend",
                          "Impressions",
                          "Clicks",
                          "CTR",
                          "Conv.",
                          "ROAS",
                        ].map(
                          (heading) => (
                            <th
                              key={heading || "open"}
                              className={
                                "px-3 py-3 text-left text-[10px] " +
                                "font-semibold uppercase tracking-widest " +
                                "text-[#806c43]"
                              }
                            >
                              {heading}
                            </th>
                          )
                        )}
                      </tr>
                    </thead>

                    <tbody>
                      {asArray(campaigns).map(
                        (campaign) => {
                          const campaignMetrics =
                            campaign?.metrics || {};

                          const isOpen =
                            String(selectedId) ===
                            String(
                              campaign.campaign_id
                            );

                          return (
                            <React.Fragment
                              key={
                                campaign.campaign_id
                              }
                            >
                              <tr
                                className={
                                  "border-t border-[#eee7d6] " +
                                  "hover:bg-[#fffdf8]"
                                }
                              >
                                <td className="px-3 py-3">
                                  <button
                                    type="button"
                                    onClick={
                                      () =>
                                        toggleDetail(
                                          campaign
                                        )
                                    }
                                    className={
                                      "rounded-lg p-1.5 " +
                                      "text-[#806c43] " +
                                      "hover:bg-[#f5eedc]"
                                    }
                                    aria-label={
                                      `Open ${campaign.campaign_name}`
                                    }
                                  >
                                    {isOpen ? (
                                      <ChevronDown
                                        size={17}
                                      />
                                    ) : (
                                      <ChevronRight
                                        size={17}
                                      />
                                    )}
                                  </button>
                                </td>

                                <td className="px-3 py-3">
                                  <div
                                    className={
                                      "font-semibold text-[#253128]"
                                    }
                                  >
                                    {
                                      campaign.campaign_name ||
                                      "Unnamed campaign"
                                    }
                                  </div>

                                  <div
                                    className={
                                      "mt-1 text-[11px] text-[#888]"
                                    }
                                  >
                                    ID{" "}
                                    {
                                      campaign.campaign_id
                                    }
                                  </div>
                                </td>

                                <td className="px-3 py-3">
                                  <StatusBadge
                                    status={
                                      campaign.status
                                    }
                                  />
                                </td>

                                <td
                                  className={
                                    "px-3 py-3 text-[#555]"
                                  }
                                >
                                  {
                                    campaign.channel_type ||
                                    "—"
                                  }
                                </td>

                                <td
                                  className={
                                    "px-3 py-3 font-medium"
                                  }
                                >
                                  {
                                    money(
                                      campaign?.budget
                                        ?.daily_budget
                                    )
                                  }
                                  /day

                                  {
                                    Number(
                                      campaign?.budget
                                        ?.reference_count ||
                                      0
                                    ) > 1
                                      ? (
                                        <div
                                          className={
                                            "mt-1 text-[10px] " +
                                            "font-semibold text-[#8a6a3c]"
                                          }
                                        >
                                          Shared by{" "}
                                          {
                                            campaign.budget
                                              .reference_count
                                          }{" "}
                                          campaigns
                                        </div>
                                      )
                                      : null
                                  }
                                </td>

                                <td className="px-3 py-3">
                                  {
                                    money(
                                      campaignMetrics.spend
                                    )
                                  }
                                </td>

                                <td className="px-3 py-3">
                                  {
                                    integer(
                                      campaignMetrics
                                        .impressions
                                    )
                                  }
                                </td>

                                <td className="px-3 py-3">
                                  {
                                    integer(
                                      campaignMetrics
                                        .clicks
                                    )
                                  }
                                </td>

                                <td className="px-3 py-3">
                                  {
                                    percent(
                                      campaignMetrics.ctr
                                    )
                                  }
                                </td>

                                <td className="px-3 py-3">
                                  {
                                    number(
                                      campaignMetrics
                                        .conversions
                                    ).toFixed(1)
                                  }
                                </td>

                                <td className="px-3 py-3">
                                  {
                                    ratio(
                                      campaignMetrics.roas
                                    )
                                  }
                                </td>
                              </tr>


                              {isOpen ? (
                                <tr
                                  className={
                                    "border-t border-[#e8dfca] " +
                                    "bg-[#fdfaf3]"
                                  }
                                >
                                  <td
                                    colSpan={11}
                                    className="p-4"
                                  >
                                    {detailLoading ? (
                                      <div
                                        className={
                                          "py-8 text-center " +
                                          "text-sm text-[#777]"
                                        }
                                      >
                                        Loading campaign details
                                        from Google…
                                      </div>
                                    ) : detail ? (
                                      <div className="space-y-5">
                                        <div
                                          className={
                                            "grid gap-3 md:grid-cols-2 " +
                                            "xl:grid-cols-4"
                                          }
                                        >
                                          <MetricCard
                                            label="Daily budget"
                                            value={
                                              money(
                                                detail?.campaign
                                                  ?.budget
                                                  ?.daily_budget
                                              )
                                            }
                                          />

                                          <MetricCard
                                            label="Avg CPC"
                                            value={
                                              detail?.campaign
                                                ?.metrics
                                                ?.average_cpc ==
                                              null
                                                ? "—"
                                                : money(
                                                    detail
                                                      .campaign
                                                      .metrics
                                                      .average_cpc
                                                  )
                                            }
                                          />

                                          <MetricCard
                                            label="CPA"
                                            value={
                                              detail?.campaign
                                                ?.metrics
                                                ?.cpa ==
                                              null
                                                ? "—"
                                                : money(
                                                    detail
                                                      .campaign
                                                      .metrics
                                                      .cpa
                                                  )
                                            }
                                          />

                                          <MetricCard
                                            label="Conversion value"
                                            value={
                                              money(
                                                detail?.campaign
                                                  ?.metrics
                                                  ?.conversion_value
                                              )
                                            }
                                          />
                                        </div>


                                        <div
                                          className={
                                            "rounded-xl border " +
                                            "border-[#e7dfc9] " +
                                            "bg-white p-4"
                                          }
                                        >
                                          <div
                                            className={
                                              "grid gap-3 text-xs " +
                                              "md:grid-cols-2 xl:grid-cols-4"
                                            }
                                          >
                                            <div>
                                              <div
                                                className={
                                                  "uppercase tracking-widest " +
                                                  "text-[#927844]"
                                                }
                                              >
                                                Campaign resource
                                              </div>

                                              <div
                                                className={
                                                  "mt-1 break-all text-[#555]"
                                                }
                                              >
                                                {
                                                  detail?.campaign
                                                    ?.campaign_resource_name ||
                                                  "—"
                                                }
                                              </div>
                                            </div>

                                            <div>
                                              <div
                                                className={
                                                  "uppercase tracking-widest " +
                                                  "text-[#927844]"
                                                }
                                              >
                                                Budget resource
                                              </div>

                                              <div
                                                className={
                                                  "mt-1 break-all text-[#555]"
                                                }
                                              >
                                                {
                                                  detail?.campaign
                                                    ?.budget
                                                    ?.resource_name ||
                                                  "—"
                                                }
                                              </div>
                                            </div>

                                            <div>
                                              <div
                                                className={
                                                  "uppercase tracking-widest " +
                                                  "text-[#927844]"
                                                }
                                              >
                                                Budget references
                                              </div>

                                              <div
                                                className={
                                                  "mt-1 text-[#555]"
                                                }
                                              >
                                                {
                                                  detail?.campaign
                                                    ?.budget
                                                    ?.reference_count ??
                                                  "—"
                                                }
                                              </div>
                                            </div>

                                            <div>
                                              <div
                                                className={
                                                  "uppercase tracking-widest " +
                                                  "text-[#927844]"
                                                }
                                              >
                                                EU political ads
                                              </div>

                                              <div
                                                className={
                                                  "mt-1 text-[#555]"
                                                }
                                              >
                                                {
                                                  detail?.campaign
                                                    ?.eu_political_advertising ||
                                                  "—"
                                                }
                                              </div>
                                            </div>
                                          </div>
                                        </div>


                                        <div>
                                          <h4
                                            className={
                                              "mb-2 font-semibold " +
                                              "text-[#253128]"
                                            }
                                          >
                                            Ad groups
                                          </h4>

                                          <DetailTable
                                            rows={adGroups}
                                            empty={
                                              "No ad groups returned for this campaign."
                                            }
                                            columns={[
                                              {
                                                key: "name",
                                                label: "Ad group",
                                              },
                                              {
                                                key: "status",
                                                label: "Status",
                                                render:
                                                  (row) => (
                                                    <StatusBadge
                                                      status={
                                                        row.status
                                                      }
                                                    />
                                                  ),
                                              },
                                              {
                                                key: "type",
                                                label: "Type",
                                              },
                                              {
                                                key: "impressions",
                                                label: "Impressions",
                                                render:
                                                  (row) =>
                                                    integer(
                                                      row.impressions
                                                    ),
                                              },
                                              {
                                                key: "clicks",
                                                label: "Clicks",
                                                render:
                                                  (row) =>
                                                    integer(
                                                      row.clicks
                                                    ),
                                              },
                                              {
                                                key: "spend",
                                                label: "Spend",
                                                render:
                                                  (row) =>
                                                    money(
                                                      row.spend
                                                    ),
                                              },
                                              {
                                                key: "conversions",
                                                label: "Conversions",
                                              },
                                            ]}
                                          />
                                        </div>


                                        <div>
                                          <h4
                                            className={
                                              "mb-2 font-semibold " +
                                              "text-[#253128]"
                                            }
                                          >
                                            Ads
                                          </h4>

                                          <DetailTable
                                            rows={ads}
                                            empty={
                                              "No ads returned for this campaign."
                                            }
                                            columns={[
                                              {
                                                key: "ad_name",
                                                label: "Ad",
                                                render:
                                                  (row) => (
                                                    <div>
                                                      <div
                                                        className={
                                                          "font-medium"
                                                        }
                                                      >
                                                        {
                                                          row.ad_name ||
                                                          `Ad ${row.ad_id}`
                                                        }
                                                      </div>

                                                      <div
                                                        className={
                                                          "mt-1 text-[11px] " +
                                                          "text-[#888]"
                                                        }
                                                      >
                                                        {
                                                          row.ad_type
                                                        }
                                                      </div>
                                                    </div>
                                                  ),
                                              },
                                              {
                                                key: "status",
                                                label: "Status",
                                                render:
                                                  (row) => (
                                                    <StatusBadge
                                                      status={
                                                        row.status
                                                      }
                                                    />
                                                  ),
                                              },
                                              {
                                                key: "ad_group_name",
                                                label: "Ad group",
                                              },
                                              {
                                                key: "impressions",
                                                label: "Impressions",
                                                render:
                                                  (row) =>
                                                    integer(
                                                      row.impressions
                                                    ),
                                              },
                                              {
                                                key: "clicks",
                                                label: "Clicks",
                                                render:
                                                  (row) =>
                                                    integer(
                                                      row.clicks
                                                    ),
                                              },
                                              {
                                                key: "spend",
                                                label: "Spend",
                                                render:
                                                  (row) =>
                                                    money(
                                                      row.spend
                                                    ),
                                              },
                                              {
                                                key: "final_urls",
                                                label: "Destination",
                                                render:
                                                  (row) => {
                                                    const url =
                                                      asArray(
                                                        row.final_urls
                                                      )[0];

                                                    return url ? (
                                                      <a
                                                        href={url}
                                                        target="_blank"
                                                        rel="noreferrer"
                                                        className={
                                                          "inline-flex items-center " +
                                                          "gap-1 text-[#6f572a] " +
                                                          "underline"
                                                        }
                                                      >
                                                        Open
                                                        <ExternalLink
                                                          size={12}
                                                        />
                                                      </a>
                                                    ) : "—";
                                                  },
                                              },
                                            ]}
                                          />
                                        </div>


                                        <div>
                                          <h4
                                            className={
                                              "mb-2 font-semibold " +
                                              "text-[#253128]"
                                            }
                                          >
                                            Keywords
                                          </h4>

                                          <DetailTable
                                            rows={keywords}
                                            empty={
                                              "No Google keyword criteria returned for this campaign."
                                            }
                                            columns={[
                                              {
                                                key: "keyword",
                                                label: "Keyword",
                                              },
                                              {
                                                key: "match_type",
                                                label: "Match type",
                                              },
                                              {
                                                key: "status",
                                                label: "Status",
                                                render:
                                                  (row) => (
                                                    <StatusBadge
                                                      status={
                                                        row.status
                                                      }
                                                    />
                                                  ),
                                              },
                                              {
                                                key: "ad_group_name",
                                                label: "Ad group",
                                              },
                                              {
                                                key: "impressions",
                                                label: "Impressions",
                                                render:
                                                  (row) =>
                                                    integer(
                                                      row.impressions
                                                    ),
                                              },
                                              {
                                                key: "clicks",
                                                label: "Clicks",
                                                render:
                                                  (row) =>
                                                    integer(
                                                      row.clicks
                                                    ),
                                              },
                                              {
                                                key: "spend",
                                                label: "Spend",
                                                render:
                                                  (row) =>
                                                    money(
                                                      row.spend
                                                    ),
                                              },
                                            ]}
                                          />
                                        </div>


                                        <div>
                                          <h4
                                            className={
                                              "mb-2 font-semibold " +
                                              "text-[#253128]"
                                            }
                                          >
                                            Conversion actions
                                          </h4>

                                          <DetailTable
                                            rows={
                                              conversionActions
                                            }
                                            empty={
                                              "No conversion actions returned."
                                            }
                                            columns={[
                                              {
                                                key: "name",
                                                label: "Conversion",
                                              },
                                              {
                                                key: "status",
                                                label: "Status",
                                                render:
                                                  (row) => (
                                                    <StatusBadge
                                                      status={
                                                        row.status
                                                      }
                                                    />
                                                  ),
                                              },
                                              {
                                                key: "category",
                                                label: "Category",
                                              },
                                              {
                                                key: "type",
                                                label: "Type",
                                              },
                                              {
                                                key: "primary_for_goal",
                                                label: "Primary",
                                                render:
                                                  (row) =>
                                                    row.primary_for_goal
                                                      ? "Yes"
                                                      : "No",
                                              },
                                            ]}
                                          />
                                        </div>


                                        <div
                                          className={
                                            "rounded-xl border " +
                                            "border-[#d7cab0] bg-[#fffaf0] " +
                                            "px-4 py-3 text-xs leading-5 " +
                                            "text-[#685938]"
                                          }
                                        >
                                          This panel is displaying live
                                          Google Ads provider state. Any
                                          campaign-changing action remains
                                          governed by the NMS execution
                                          policy and approval workflow.
                                        </div>
                                      </div>
                                    ) : (
                                      <Empty>
                                        No campaign detail available.
                                      </Empty>
                                    )}
                                  </td>
                                </tr>
                              ) : null}
                            </React.Fragment>
                          );
                        }
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}
