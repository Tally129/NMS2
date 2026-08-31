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
  Loader2,
  Pencil,
  Plus,
  Power,
  RotateCcw,
  Target,
} from "lucide-react";


const EMPTY_FORM = {
  name: "",
  goal_type: "",
  target_value: "",
  target_unit: "",
  start_date: "",
  end_date: "",
  service_line: "",
};


function cleanOptional(value) {
  const cleaned = String(
    value ?? ""
  ).trim();

  return cleaned || null;
}


function cleanNumber(value) {
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


function displayTarget(goal) {
  if (
    goal?.target_value === null ||
    goal?.target_value === undefined ||
    goal?.target_value === ""
  ) {
    return "No numeric target";
  }

  const number = Number(
    goal.target_value
  );

  const formatted =
    Number.isFinite(number)
      ? number.toLocaleString()
      : String(goal.target_value);

  return goal?.target_unit
    ? `${formatted} ${goal.target_unit}`
    : formatted;
}


function formatDateRange(goal) {
  const start =
    goal?.start_date || null;

  const end =
    goal?.end_date || null;

  if (!start && !end) {
    return "No date range";
  }

  if (start && end) {
    return `${start} → ${end}`;
  }

  if (start) {
    return `Starts ${start}`;
  }

  return `Ends ${end}`;
}


function getApiError(error) {
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


function GoalStatus({
  status,
}) {
  const normalized = String(
    status || "active"
  ).toLowerCase();

  const active =
    normalized === "active";

  return (
    <span
      className={
        "inline-flex items-center " +
        "rounded-full border px-2.5 py-1 " +
        "text-[11px] font-semibold " +
        (
          active
            ? (
              "border-[#b9d2bf] " +
              "bg-[#edf5ef] " +
              "text-[#2f6a4a]"
            )
            : (
              "border-[#d8cba9] " +
              "bg-[#f7f1e4] " +
              "text-[#8a6a3c]"
            )
        )
      }
    >
      {status || "active"}
    </span>
  );
}


export default function MarketingGoalsPanel({
  goals,
  onChanged,
}) {
  const [dialogOpen, setDialogOpen] =
    React.useState(false);

  const [editingGoal, setEditingGoal] =
    React.useState(null);

  const [form, setForm] =
    React.useState(EMPTY_FORM);

  const [saving, setSaving] =
    React.useState(false);

  const [busyGoalId, setBusyGoalId] =
    React.useState(null);

  const [error, setError] =
    React.useState("");


  const safeGoals =
    normalizeArray(goals);


  const openCreate = () => {
    setEditingGoal(null);

    setForm({
      ...EMPTY_FORM,
    });

    setError("");
    setDialogOpen(true);
  };


  const openEdit = (goal) => {
    setEditingGoal(goal);

    setForm({
      name:
        goal?.name || "",

      goal_type:
        goal?.goal_type || "",

      target_value:
        goal?.target_value ??
        "",

      target_unit:
        goal?.target_unit || "",

      start_date:
        goal?.start_date || "",

      end_date:
        goal?.end_date || "",

      service_line:
        goal?.service_line || "",
    });

    setError("");
    setDialogOpen(true);
  };


  const closeDialog = () => {
    if (saving) {
      return;
    }

    setDialogOpen(false);
    setEditingGoal(null);

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


  const submit = async () => {
    const name =
      form.name.trim();

    const goalType =
      form.goal_type.trim();

    if (name.length < 2) {
      setError(
        "Goal name must contain at least 2 characters."
      );
      return;
    }

    if (!goalType) {
      setError(
        "Goal type is required."
      );
      return;
    }

    if (
      form.start_date &&
      form.end_date &&
      form.end_date < form.start_date
    ) {
      setError(
        "End date must be on or after start date."
      );
      return;
    }

    const targetValue =
      cleanNumber(
        form.target_value
      );

    if (
      form.target_value !== "" &&
      targetValue === null
    ) {
      setError(
        "Target value must be a valid number."
      );
      return;
    }

    const payload = {
      name,
      goal_type: goalType,

      target_value:
        targetValue,

      target_unit:
        cleanOptional(
          form.target_unit
        ),

      start_date:
        cleanOptional(
          form.start_date
        ),

      end_date:
        cleanOptional(
          form.end_date
        ),

      service_line:
        cleanOptional(
          form.service_line
        ),
    };

    if (!editingGoal) {
      payload.status = "active";
    }

    setSaving(true);
    setError("");

    try {
      const response =
        editingGoal
          ? await api.patch(
              `/marketing-os/goals/${
                editingGoal.id
              }`,
              payload
            )
          : await api.post(
              "/marketing-os/goals",
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
      setEditingGoal(null);

      setForm({
        ...EMPTY_FORM,
      });

      if (onChanged) {
        await onChanged();
      }

    } catch (requestError) {
      setError(
        getApiError(
          requestError
        )
      );

    } finally {
      setSaving(false);
    }
  };


  const toggleStatus = async (
    goal
  ) => {
    if (!goal?.id) {
      return;
    }

    const currentStatus =
      String(
        goal.status || "active"
      ).toLowerCase();

    const nextStatus =
      currentStatus === "active"
        ? "inactive"
        : "active";

    setBusyGoalId(goal.id);
    setError("");

    try {
      const response =
        await api.patch(
          `/marketing-os/goals/${
            goal.id
          }`,
          {
            status: nextStatus,
          }
        );

      if (
        response?.__isAuthDenied
      ) {
        throw new Error(
          response.__errorMessage ||
          "You do not have access."
        );
      }

      if (onChanged) {
        await onChanged();
      }

    } catch (requestError) {
      setError(
        getApiError(
          requestError
        )
      );

    } finally {
      setBusyGoalId(null);
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
        data-testid="marketing-goals"
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
              Strategy
            </div>

            <div
              className={
                "flex items-center gap-2 " +
                "font-display text-xl " +
                "text-[#1f2a22]"
              }
            >
              <Target
                size={18}
                className="text-[#2f4a3a]"
              />
              Goals
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
            data-testid="marketing-new-goal"
          >
            <Plus
              size={14}
              className="mr-1.5"
            />
            New Goal
          </Button>
        </div>


        {error && !dialogOpen && (
          <div
            className={
              "mb-4 rounded-xl border " +
              "border-[#d9b7b7] " +
              "bg-[#f9eeee] px-3 py-2 " +
              "text-xs text-[#7a2a2a]"
            }
          >
            {error}
          </div>
        )}


        {safeGoals.length === 0 ? (
          <div
            className={
              "rounded-xl border border-dashed " +
              "border-[#d8cba9] px-4 py-8 " +
              "text-center text-sm " +
              "text-[#6a6a6a]"
            }
          >
            No marketing goals have been
            created yet.
          </div>

        ) : (
          <div className="space-y-3">
            {normalizeArray(
              safeGoals
            ).map(
              (goal) => {
                const active =
                  String(
                    goal?.status ||
                    "active"
                  ).toLowerCase() ===
                  "active";

                const busy =
                  busyGoalId ===
                  goal.id;

                return (
                  <div
                    key={goal.id}
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
                              goal.name ||
                              "Marketing goal"
                            }
                          </div>

                          <GoalStatus
                            status={
                              goal.status ||
                              "active"
                            }
                          />
                        </div>

                        <div
                          className={
                            "mt-2 text-xs " +
                            "text-[#6a6a6a]"
                          }
                        >
                          {
                            goal.goal_type ||
                            "Goal"
                          }

                          {
                            goal.service_line
                              ? ` · ${
                                  goal.service_line
                                }`
                              : ""
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
                              Target
                            </div>

                            <div
                              className={
                                "mt-1 text-sm " +
                                "font-semibold " +
                                "text-[#1f2a22]"
                              }
                            >
                              {
                                displayTarget(
                                  goal
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
                              Timeline
                            </div>

                            <div
                              className={
                                "mt-1 text-sm " +
                                "font-semibold " +
                                "text-[#1f2a22]"
                              }
                            >
                              {
                                formatDateRange(
                                  goal
                                )
                              }
                            </div>
                          </div>
                        </div>
                      </div>

                      <div
                        className={
                          "flex shrink-0 " +
                          "flex-wrap gap-2"
                        }
                      >
                        <Button
                          type="button"
                          variant="outline"
                          disabled={busy}
                          onClick={() =>
                            openEdit(goal)
                          }
                          className={
                            "h-8 rounded-full " +
                            "border-[#d8cba9] " +
                            "text-[#8a6a3c]"
                          }
                          data-testid={
                            `marketing-goal-edit-${
                              goal.id
                            }`
                          }
                        >
                          <Pencil
                            size={12}
                            className="mr-1.5"
                          />
                          Edit
                        </Button>

                        <Button
                          type="button"
                          variant="outline"
                          disabled={busy}
                          onClick={() =>
                            toggleStatus(goal)
                          }
                          className={
                            active
                              ? (
                                "h-8 rounded-full " +
                                "border-[#d9b7b7] " +
                                "text-[#7a2a2a]"
                              )
                              : (
                                "h-8 rounded-full " +
                                "border-[#b9d2bf] " +
                                "text-[#2f6a4a]"
                              )
                          }
                          data-testid={
                            `marketing-goal-status-${
                              goal.id
                            }`
                          }
                        >
                          {
                            busy
                              ? (
                                <Loader2
                                  size={12}
                                  className={
                                    "mr-1.5 animate-spin"
                                  }
                                />
                              )
                              : active
                                ? (
                                  <Power
                                    size={12}
                                    className="mr-1.5"
                                  />
                                )
                                : (
                                  <RotateCcw
                                    size={12}
                                    className="mr-1.5"
                                  />
                                )
                          }

                          {
                            active
                              ? "Deactivate"
                              : "Reactivate"
                          }
                        </Button>
                      </div>
                    </div>
                  </div>
                );
              }
            )}
          </div>
        )}
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
          data-testid="marketing-goal-dialog"
        >
          <DialogHeader>
            <DialogTitle
              className={
                "font-display text-2xl " +
                "text-[#1f2a22]"
              }
            >
              {
                editingGoal
                  ? "Edit Marketing Goal"
                  : "New Marketing Goal"
              }
            </DialogTitle>

            <DialogDescription>
              Define the business objective the
              Marketing Director should evaluate.
              This does not create or modify an
              advertising campaign.
            </DialogDescription>
          </DialogHeader>


          <div
            className={
              "grid gap-4 py-2 " +
              "sm:grid-cols-2"
            }
          >
            <div className="sm:col-span-2">
              <Label htmlFor="marketing-goal-name">
                Goal name
              </Label>

              <Input
                id="marketing-goal-name"
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
                  "e.g. Weight Management Growth"
                }
                data-testid="marketing-goal-name"
              />
            </div>


            <div>
              <Label htmlFor="marketing-goal-type">
                Goal type
              </Label>

              <Input
                id="marketing-goal-type"
                value={form.goal_type}
                onChange={(event) =>
                  updateField(
                    "goal_type",
                    event.target.value
                  )
                }
                className={
                  "mt-2 bg-white " +
                  "border-[#e0d6bc]"
                }
                placeholder={
                  "e.g. revenue"
                }
                data-testid="marketing-goal-type"
              />
            </div>


            <div>
              <Label htmlFor="marketing-service-line">
                Service line
              </Label>

              <Input
                id="marketing-service-line"
                value={form.service_line}
                onChange={(event) =>
                  updateField(
                    "service_line",
                    event.target.value
                  )
                }
                className={
                  "mt-2 bg-white " +
                  "border-[#e0d6bc]"
                }
                placeholder={
                  "e.g. Weight Management"
                }
                data-testid="marketing-service-line"
              />
            </div>


            <div>
              <Label htmlFor="marketing-target-value">
                Target value
              </Label>

              <Input
                id="marketing-target-value"
                type="number"
                step="any"
                value={form.target_value}
                onChange={(event) =>
                  updateField(
                    "target_value",
                    event.target.value
                  )
                }
                className={
                  "mt-2 bg-white " +
                  "border-[#e0d6bc]"
                }
                placeholder="25000"
                data-testid="marketing-target-value"
              />
            </div>


            <div>
              <Label htmlFor="marketing-target-unit">
                Target unit
              </Label>

              <Input
                id="marketing-target-unit"
                value={form.target_unit}
                onChange={(event) =>
                  updateField(
                    "target_unit",
                    event.target.value
                  )
                }
                className={
                  "mt-2 bg-white " +
                  "border-[#e0d6bc]"
                }
                placeholder={
                  "e.g. USD revenue"
                }
                data-testid="marketing-target-unit"
              />
            </div>


            <div>
              <Label htmlFor="marketing-start-date">
                Start date
              </Label>

              <Input
                id="marketing-start-date"
                type="date"
                value={form.start_date}
                onChange={(event) =>
                  updateField(
                    "start_date",
                    event.target.value
                  )
                }
                className={
                  "mt-2 bg-white " +
                  "border-[#e0d6bc]"
                }
                data-testid="marketing-start-date"
              />
            </div>


            <div>
              <Label htmlFor="marketing-end-date">
                End date
              </Label>

              <Input
                id="marketing-end-date"
                type="date"
                value={form.end_date}
                onChange={(event) =>
                  updateField(
                    "end_date",
                    event.target.value
                  )
                }
                className={
                  "mt-2 bg-white " +
                  "border-[#e0d6bc]"
                }
                data-testid="marketing-end-date"
              />
            </div>
          </div>


          {error && (
            <div
              className={
                "rounded-xl border " +
                "border-[#d9b7b7] " +
                "bg-[#f9eeee] px-3 py-2 " +
                "text-sm text-[#7a2a2a]"
              }
              data-testid="marketing-goal-error"
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
              data-testid="marketing-goal-save"
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
                editingGoal
                  ? "Save Changes"
                  : "Create Goal"
              }
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
