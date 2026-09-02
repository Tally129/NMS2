import React from "react";

import api from "../../lib/api";
import { normalizeArray } from "../../lib/collections";

import { Button } from "../../components/ui/button";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../../components/ui/dialog";

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
  CircleDollarSign,
  Gauge,
  Loader2,
  Pencil,
  Plus,
} from "lucide-react";


const EMPTY_FORM = {
  goal_id: "none",
  name: "",
  period_start: "",
  period_end: "",
  currency: "USD",
  approved_amount: "0",
  daily_cap: "",
  target_cpl: "",
  target_cac: "",
  minimum_roas: "",
  status: "draft",
};


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
      maximumFractionDigits: 2,
    }
  );
}


function optionalNumber(value) {
  if (
    value === "" ||
    value === null ||
    value === undefined
  ) {
    return null;
  }

  const parsed = Number(value);

  return Number.isFinite(parsed)
    ? parsed
    : null;
}


function apiError(error) {
  const detail =
    error?.response?.data?.detail;

  if (typeof detail === "string") {
    return detail;
  }

  if (
    detail &&
    typeof detail === "object"
  ) {
    return (
      detail.message ||
      detail.code ||
      "The request could not be completed."
    );
  }

  return (
    error?.message ||
    "The request could not be completed."
  );
}


function BudgetStatus({
  status,
}) {
  const normalized = String(
    status || "draft"
  ).toLowerCase();

  let tone =
    "border-[#d8cba9] " +
    "bg-[#f7f1e4] " +
    "text-[#8a6a3c]";

  if (normalized === "active") {
    tone =
      "border-[#b9d2bf] " +
      "bg-[#edf5ef] " +
      "text-[#2f6a4a]";
  }

  if (normalized === "inactive") {
    tone =
      "border-[#e7dfc9] " +
      "bg-[#fbf7ee] " +
      "text-[#6a6a6a]";
  }

  return (
    <span
      className={
        "inline-flex items-center " +
        "rounded-full border px-2.5 py-1 " +
        "text-[11px] font-semibold " +
        tone
      }
    >
      {status || "draft"}
    </span>
  );
}


export default function MarketingBudgetsPanel({
  budgets,
  goals,
  totalSpend = 0,
  overallRoas = 0,
  onChanged,
}) {
  const safeBudgets =
    normalizeArray(budgets);

  const safeGoals =
    normalizeArray(goals);

  const [dialogOpen, setDialogOpen] =
    React.useState(false);

  const [editingBudget, setEditingBudget] =
    React.useState(null);

  const [form, setForm] =
    React.useState(EMPTY_FORM);

  const [saving, setSaving] =
    React.useState(false);

  const [error, setError] =
    React.useState("");


  const approvedTotal =
    normalizeArray(
      safeBudgets
    ).reduce(
      (sum, budget) =>
        sum +
        asNumber(
          budget?.approved_amount
        ),
      0
    );


  const recordedSpend =
    normalizeArray(
      safeBudgets
    ).reduce(
      (sum, budget) =>
        sum +
        asNumber(
          budget?.spent_amount
        ),
      0
    );


  const displaySpend =
    totalSpend ||
    recordedSpend;


  const remaining =
    Math.max(
      approvedTotal - displaySpend,
      0
    );


  const goalName = (
    goalId
  ) => {
    if (!goalId) {
      return "No linked goal";
    }

    const match =
      normalizeArray(
        safeGoals
      ).find(
        (goal) =>
          goal.id === goalId
      );

    return (
      match?.name ||
      "Linked goal"
    );
  };


  const openCreate = () => {
    setEditingBudget(null);

    setForm({
      ...EMPTY_FORM,
    });

    setError("");
    setDialogOpen(true);
  };


  const openEdit = (
    budget
  ) => {
    setEditingBudget(budget);

    setForm({
      goal_id:
        budget?.goal_id ||
        "none",

      name:
        budget?.name || "",

      period_start:
        budget?.period_start || "",

      period_end:
        budget?.period_end || "",

      currency:
        budget?.currency ||
        "USD",

      approved_amount:
        budget?.approved_amount ??
        "0",

      daily_cap:
        budget?.daily_cap ??
        "",

      target_cpl:
        budget?.target_cpl ??
        "",

      target_cac:
        budget?.target_cac ??
        "",

      minimum_roas:
        budget?.minimum_roas ??
        "",

      status:
        budget?.status ||
        "draft",
    });

    setError("");
    setDialogOpen(true);
  };


  const closeDialog = () => {
    if (saving) {
      return;
    }

    setDialogOpen(false);
    setEditingBudget(null);

    setForm({
      ...EMPTY_FORM,
    });

    setError("");
  };


  const updateField = (
    field,
    value
  ) => {
    setForm(
      (current) => ({
        ...current,
        [field]: value,
      })
    );
  };


  const validateNonnegative = (
    label,
    raw
  ) => {
    const parsed =
      optionalNumber(raw);

    if (
      raw !== "" &&
      (
        parsed === null ||
        parsed < 0
      )
    ) {
      setError(
        `${label} must be zero or greater.`
      );

      return {
        ok: false,
        value: null,
      };
    }

    return {
      ok: true,
      value: parsed,
    };
  };


  const submit = async () => {
    const name =
      form.name.trim();

    if (name.length < 2) {
      setError(
        "Budget name must contain at least 2 characters."
      );
      return;
    }

    if (
      !form.period_start ||
      !form.period_end
    ) {
      setError(
        "Budget start and end dates are required."
      );
      return;
    }

    if (
      form.period_end <
      form.period_start
    ) {
      setError(
        "Budget end date must be on or after its start date."
      );
      return;
    }

    const approved =
      validateNonnegative(
        "Approved amount",
        form.approved_amount
      );

    if (!approved.ok) {
      return;
    }

    const dailyCap =
      validateNonnegative(
        "Daily cap",
        form.daily_cap
      );

    if (!dailyCap.ok) {
      return;
    }

    const targetCpl =
      validateNonnegative(
        "Target CPL",
        form.target_cpl
      );

    if (!targetCpl.ok) {
      return;
    }

    const targetCac =
      validateNonnegative(
        "Target CAC",
        form.target_cac
      );

    if (!targetCac.ok) {
      return;
    }

    const minimumRoas =
      validateNonnegative(
        "Minimum ROAS",
        form.minimum_roas
      );

    if (!minimumRoas.ok) {
      return;
    }

    const payload = {
      goal_id:
        form.goal_id === "none"
          ? null
          : form.goal_id,

      name,

      period_start:
        form.period_start,

      period_end:
        form.period_end,

      currency:
        (
          form.currency ||
          "USD"
        ).toUpperCase(),

      approved_amount:
        approved.value ?? 0,

      daily_cap:
        dailyCap.value,

      target_cpl:
        targetCpl.value,

      target_cac:
        targetCac.value,

      minimum_roas:
        minimumRoas.value,

      status:
        form.status,
    };

    // Structured allocation/rule data is not edited
    // by this form. Preserve existing values on PATCH
    // by omitting these fields entirely.
    //
    // New budgets still receive explicit empty JSON
    // objects through the create request below.
    if (!editingBudget) {
      payload.allocation = {};
      payload.rules = {};
    }

    setSaving(true);
    setError("");

    try {
      const response =
        editingBudget
          ? await api.patch(
              `/marketing-os/budgets/${
                editingBudget.id
              }`,
              payload
            )
          : await api.post(
              "/marketing-os/budgets",
              payload
            );

      if (
        response?.__isAuthDenied
      ) {
        throw new Error(
          response.__errorMessage ||
          "You do not have access."
        );
      }

      setDialogOpen(false);
      setEditingBudget(null);

      setForm({
        ...EMPTY_FORM,
      });

      if (onChanged) {
        await onChanged();
      }

    } catch (requestError) {
      setError(
        apiError(
          requestError
        )
      );

    } finally {
      setSaving(false);
    }
  };


  return (
    <>
      <section
        className={
          "rounded-2xl border " +
          "border-[#e7dfc9] " +
          "bg-[#fbf7ee] p-5"
        }
        data-testid="marketing-budget-control"
      >
        <div
          className={
            "mb-4 flex items-start " +
            "justify-between gap-3"
          }
        >
          <div>
            <div
              className={
                "mb-1 text-[11px] uppercase " +
                "tracking-widest text-[#8a6a3c]"
              }
            >
              Financial guardrails
            </div>

            <div
              className={
                "flex items-center gap-2 " +
                "font-display text-xl " +
                "text-[#1f2a22]"
              }
            >
              <Gauge
                size={18}
                className="text-[#2f4a3a]"
              />
              Budget Center
            </div>
          </div>

          <Button
            type="button"
            onClick={openCreate}
            className={
              "h-9 rounded-full " +
              "bg-[#2f4a3a] " +
              "text-[#f6f1e6] " +
              "hover:bg-[#263d30]"
            }
            data-testid="marketing-new-budget"
          >
            <Plus
              size={14}
              className="mr-1.5"
            />
            New Budget
          </Button>
        </div>


        <div
          className={
            "mb-4 grid grid-cols-2 " +
            "gap-3 xl:grid-cols-4"
          }
        >
          <div
            className={
              "rounded-xl border " +
              "border-[#e7dfc9] " +
              "bg-white p-3"
            }
          >
            <div
              className={
                "text-[10px] uppercase " +
                "tracking-widest text-[#8a6a3c]"
              }
            >
              Approved
            </div>

            <div
              className={
                "mt-1 font-display " +
                "text-xl text-[#1f2a22]"
              }
            >
              {money(approvedTotal)}
            </div>
          </div>


          <div
            className={
              "rounded-xl border " +
              "border-[#e7dfc9] " +
              "bg-white p-3"
            }
          >
            <div
              className={
                "text-[10px] uppercase " +
                "tracking-widest text-[#8a6a3c]"
              }
            >
              Spend
            </div>

            <div
              className={
                "mt-1 font-display " +
                "text-xl text-[#1f2a22]"
              }
            >
              {money(displaySpend)}
            </div>
          </div>


          <div
            className={
              "rounded-xl border " +
              "border-[#e7dfc9] " +
              "bg-white p-3"
            }
          >
            <div
              className={
                "text-[10px] uppercase " +
                "tracking-widest text-[#8a6a3c]"
              }
            >
              Remaining
            </div>

            <div
              className={
                "mt-1 font-display " +
                "text-xl text-[#2f4a3a]"
              }
            >
              {money(remaining)}
            </div>
          </div>


          <div
            className={
              "rounded-xl border " +
              "border-[#e7dfc9] " +
              "bg-white p-3"
            }
          >
            <div
              className={
                "text-[10px] uppercase " +
                "tracking-widest text-[#8a6a3c]"
              }
            >
              Aggregate ROAS
            </div>

            <div
              className={
                "mt-1 font-display " +
                "text-xl text-[#2f4a3a]"
              }
            >
              {
                Number(
                  overallRoas || 0
                ).toFixed(2)
              }x
            </div>
          </div>
        </div>


        {safeBudgets.length === 0 ? (
          <div
            className={
              "rounded-xl border border-dashed " +
              "border-[#d8cba9] px-4 py-8 " +
              "text-center text-sm " +
              "text-[#6a6a6a]"
            }
          >
            No marketing budgets yet.
            Create one to define financial
            guardrails for a marketing goal.
          </div>

        ) : (
          <div className="space-y-3">
            {normalizeArray(
              safeBudgets
            ).map(
              (budget) => (
                <div
                  key={budget.id}
                  className={
                    "rounded-xl border " +
                    "border-[#e7dfc9] " +
                    "bg-white p-4"
                  }
                >
                  <div
                    className={
                      "flex flex-col gap-4 " +
                      "xl:flex-row " +
                      "xl:items-start " +
                      "xl:justify-between"
                    }
                  >
                    <div className="min-w-0">
                      <div
                        className={
                          "flex flex-wrap " +
                          "items-center gap-2"
                        }
                      >
                        <div
                          className={
                            "font-medium " +
                            "text-[#1f2a22]"
                          }
                        >
                          {
                            budget.name ||
                            "Marketing budget"
                          }
                        </div>

                        <BudgetStatus
                          status={
                            budget.status ||
                            "draft"
                          }
                        />
                      </div>

                      <div
                        className={
                          "mt-1 text-xs " +
                          "text-[#6a6a6a]"
                        }
                      >
                        {
                          goalName(
                            budget.goal_id
                          )
                        }
                        {" · "}
                        {
                          budget.period_start ||
                          "—"
                        }
                        {" → "}
                        {
                          budget.period_end ||
                          "—"
                        }
                      </div>

                      <div
                        className={
                          "mt-3 grid gap-2 " +
                          "sm:grid-cols-2"
                        }
                      >
                        <div
                          className={
                            "rounded-lg bg-[#f7f1e4] " +
                            "px-3 py-2"
                          }
                        >
                          <div
                            className={
                              "text-[10px] uppercase " +
                              "tracking-widest " +
                              "text-[#8a6a3c]"
                            }
                          >
                            Approved
                          </div>

                          <div
                            className={
                              "mt-1 text-sm " +
                              "font-semibold " +
                              "text-[#1f2a22]"
                            }
                          >
                            {
                              money(
                                budget
                                  .approved_amount
                              )
                            }
                          </div>
                        </div>

                        <div
                          className={
                            "rounded-lg bg-[#f7f1e4] " +
                            "px-3 py-2"
                          }
                        >
                          <div
                            className={
                              "text-[10px] uppercase " +
                              "tracking-widest " +
                              "text-[#8a6a3c]"
                            }
                          >
                            Recorded spend
                          </div>

                          <div
                            className={
                              "mt-1 text-sm " +
                              "font-semibold " +
                              "text-[#1f2a22]"
                            }
                          >
                            {
                              money(
                                budget
                                  .spent_amount
                              )
                            }
                          </div>
                        </div>
                      </div>

                      <div
                        className={
                          "mt-3 flex flex-wrap " +
                          "gap-x-4 gap-y-1 " +
                          "text-xs text-[#6a6a6a]"
                        }
                      >
                        {
                          budget.daily_cap !==
                            null &&
                          budget.daily_cap !==
                            undefined && (
                            <span>
                              Daily cap:
                              {" "}
                              {
                                money(
                                  budget.daily_cap
                                )
                              }
                            </span>
                          )
                        }

                        {
                          budget.target_cpl !==
                            null &&
                          budget.target_cpl !==
                            undefined && (
                            <span>
                              CPL target:
                              {" "}
                              {
                                money(
                                  budget.target_cpl
                                )
                              }
                            </span>
                          )
                        }

                        {
                          budget.target_cac !==
                            null &&
                          budget.target_cac !==
                            undefined && (
                            <span>
                              CAC target:
                              {" "}
                              {
                                money(
                                  budget.target_cac
                                )
                              }
                            </span>
                          )
                        }

                        {
                          budget.minimum_roas !==
                            null &&
                          budget.minimum_roas !==
                            undefined && (
                            <span>
                              Min ROAS:
                              {" "}
                              {
                                Number(
                                  budget
                                    .minimum_roas
                                ).toFixed(2)
                              }x
                            </span>
                          )
                        }
                      </div>
                    </div>


                    <Button
                      type="button"
                      variant="outline"
                      onClick={() =>
                        openEdit(budget)
                      }
                      className={
                        "h-8 shrink-0 rounded-full " +
                        "border-[#d8cba9] " +
                        "text-[#8a6a3c]"
                      }
                      data-testid={
                        `marketing-budget-edit-${
                          budget.id
                        }`
                      }
                    >
                      <Pencil
                        size={12}
                        className="mr-1.5"
                      />
                      Edit
                    </Button>
                  </div>
                </div>
              )
            )}
          </div>
        )}


        <p
          className={
            "mt-4 text-xs leading-5 " +
            "text-[#6a6a6a]"
          }
        >
          <CircleDollarSign
            size={12}
            className={
              "mr-1 inline text-[#2f4a3a]"
            }
          />
          Automatic budget changes remain
          disabled. Editing this budget changes
          only NMS internal planning guardrails;
          it does not alter Google Ads, Meta,
          TikTok, or another advertising account.
        </p>
      </section>


      <Dialog
        open={dialogOpen}
        onOpenChange={(open) => {
          if (!open) {
            closeDialog();
          }
        }}
      >
        <DialogContent
          className={
            "bg-[#fbf7ee] " +
            "border-[#e7dfc9] " +
            "max-w-2xl"
          }
          data-testid="marketing-budget-dialog"
        >
          <DialogHeader>
            <DialogTitle
              className={
                "font-display text-2xl " +
                "text-[#1f2a22]"
              }
            >
              {
                editingBudget
                  ? "Edit Marketing Budget"
                  : "New Marketing Budget"
              }
            </DialogTitle>

            <DialogDescription>
              Set internal marketing-spend
              guardrails. These values do not
              authorize automatic changes on an
              external advertising platform.
            </DialogDescription>
          </DialogHeader>


          <div
            className={
              "grid gap-4 py-2 " +
              "sm:grid-cols-2"
            }
          >
            <div className="sm:col-span-2">
              <Label htmlFor="marketing-budget-name">
                Budget name
              </Label>

              <Input
                id="marketing-budget-name"
                value={form.name}
                onChange={(event) =>
                  updateField(
                    "name",
                    event.target.value
                  )
                }
                className={
                  "mt-2 bg-white " +
                  "border-[#e0d6bc]"
                }
                placeholder={
                  "e.g. Weight Management Q4"
                }
                data-testid="marketing-budget-name"
              />
            </div>


            <div className="sm:col-span-2">
              <Label>
                Linked goal
              </Label>

              <Select
                value={form.goal_id}
                onValueChange={(value) =>
                  updateField(
                    "goal_id",
                    value
                  )
                }
              >
                <SelectTrigger
                  className={
                    "mt-2 bg-white " +
                    "border-[#e0d6bc]"
                  }
                  data-testid="marketing-budget-goal"
                >
                  <SelectValue
                    placeholder="Select goal"
                  />
                </SelectTrigger>

                <SelectContent>
                  <SelectItem value="none">
                    No linked goal
                  </SelectItem>

                  {normalizeArray(
                    safeGoals
                  ).map(
                    (goal) => (
                      <SelectItem
                        key={goal.id}
                        value={goal.id}
                      >
                        {
                          goal.name ||
                          goal.id
                        }
                      </SelectItem>
                    )
                  )}
                </SelectContent>
              </Select>
            </div>


            <div>
              <Label htmlFor="marketing-budget-start">
                Period start
              </Label>

              <Input
                id="marketing-budget-start"
                type="date"
                value={form.period_start}
                onChange={(event) =>
                  updateField(
                    "period_start",
                    event.target.value
                  )
                }
                className={
                  "mt-2 bg-white " +
                  "border-[#e0d6bc]"
                }
                data-testid="marketing-budget-start"
              />
            </div>


            <div>
              <Label htmlFor="marketing-budget-end">
                Period end
              </Label>

              <Input
                id="marketing-budget-end"
                type="date"
                value={form.period_end}
                onChange={(event) =>
                  updateField(
                    "period_end",
                    event.target.value
                  )
                }
                className={
                  "mt-2 bg-white " +
                  "border-[#e0d6bc]"
                }
                data-testid="marketing-budget-end"
              />
            </div>


            <div>
              <Label htmlFor="marketing-budget-approved">
                Approved budget
              </Label>

              <Input
                id="marketing-budget-approved"
                type="number"
                min="0"
                step="0.01"
                value={form.approved_amount}
                onChange={(event) =>
                  updateField(
                    "approved_amount",
                    event.target.value
                  )
                }
                className={
                  "mt-2 bg-white " +
                  "border-[#e0d6bc]"
                }
                data-testid="marketing-budget-approved"
              />
            </div>


            <div>
              <Label htmlFor="marketing-budget-daily-cap">
                Daily cap
              </Label>

              <Input
                id="marketing-budget-daily-cap"
                type="number"
                min="0"
                step="0.01"
                value={form.daily_cap}
                onChange={(event) =>
                  updateField(
                    "daily_cap",
                    event.target.value
                  )
                }
                className={
                  "mt-2 bg-white " +
                  "border-[#e0d6bc]"
                }
                placeholder="Optional"
                data-testid="marketing-budget-daily-cap"
              />
            </div>


            <div>
              <Label htmlFor="marketing-budget-cpl">
                Target CPL
              </Label>

              <Input
                id="marketing-budget-cpl"
                type="number"
                min="0"
                step="0.01"
                value={form.target_cpl}
                onChange={(event) =>
                  updateField(
                    "target_cpl",
                    event.target.value
                  )
                }
                className={
                  "mt-2 bg-white " +
                  "border-[#e0d6bc]"
                }
                placeholder="Optional"
                data-testid="marketing-budget-cpl"
              />
            </div>


            <div>
              <Label htmlFor="marketing-budget-cac">
                Target CAC
              </Label>

              <Input
                id="marketing-budget-cac"
                type="number"
                min="0"
                step="0.01"
                value={form.target_cac}
                onChange={(event) =>
                  updateField(
                    "target_cac",
                    event.target.value
                  )
                }
                className={
                  "mt-2 bg-white " +
                  "border-[#e0d6bc]"
                }
                placeholder="Optional"
                data-testid="marketing-budget-cac"
              />
            </div>


            <div>
              <Label htmlFor="marketing-budget-roas">
                Minimum ROAS
              </Label>

              <Input
                id="marketing-budget-roas"
                type="number"
                min="0"
                step="0.01"
                value={form.minimum_roas}
                onChange={(event) =>
                  updateField(
                    "minimum_roas",
                    event.target.value
                  )
                }
                className={
                  "mt-2 bg-white " +
                  "border-[#e0d6bc]"
                }
                placeholder="e.g. 3.00"
                data-testid="marketing-budget-roas"
              />
            </div>


            <div>
              <Label>
                Status
              </Label>

              <Select
                value={form.status}
                onValueChange={(value) =>
                  updateField(
                    "status",
                    value
                  )
                }
              >
                <SelectTrigger
                  className={
                    "mt-2 bg-white " +
                    "border-[#e0d6bc]"
                  }
                  data-testid="marketing-budget-status"
                >
                  <SelectValue />
                </SelectTrigger>

                <SelectContent>
                  <SelectItem value="draft">
                    Draft
                  </SelectItem>

                  <SelectItem value="active">
                    Active
                  </SelectItem>

                  <SelectItem value="inactive">
                    Inactive
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>


          {editingBudget && (
            <div
              className={
                "rounded-xl border " +
                "border-[#d8cba9] " +
                "bg-[#f7f1e4] px-3 py-2 " +
                "text-xs text-[#6a6a6a]"
              }
            >
              Recorded spend is
              {" "}
              <strong>
                {
                  money(
                    editingBudget
                      .spent_amount
                  )
                }
              </strong>
              {" "}
              and is read-only here.
            </div>
          )}


          {error && (
            <div
              className={
                "rounded-xl border " +
                "border-[#d9b7b7] " +
                "bg-[#f9eeee] px-3 py-2 " +
                "text-sm text-[#7a2a2a]"
              }
              data-testid="marketing-budget-error"
            >
              {error}
            </div>
          )}


          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={saving}
              onClick={closeDialog}
            >
              Cancel
            </Button>

            <Button
              type="button"
              disabled={saving}
              onClick={submit}
              className={
                "bg-[#2f4a3a] " +
                "text-[#f6f1e6] " +
                "hover:bg-[#263d30]"
              }
              data-testid="marketing-budget-save"
            >
              {saving && (
                <Loader2
                  size={14}
                  className={
                    "mr-1.5 animate-spin"
                  }
                />
              )}

              {
                editingBudget
                  ? "Save Changes"
                  : "Create Budget"
              }
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
