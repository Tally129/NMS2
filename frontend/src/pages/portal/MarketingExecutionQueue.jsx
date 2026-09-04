import React from "react";

import {
  AlertTriangle,
  Ban,
  Check,
  ChevronDown,
  ChevronUp,
  Clock3,
  Play,
  Plus,
  RefreshCw,
  Settings2,
  ShieldCheck,
  X,
} from "lucide-react";

import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { normalizeArray } from "../../lib/collections";


const PROVIDER_LABELS = {
  google_ads: "Google Ads",
  meta_ads: "Meta Ads",
  microsoft_ads: "Microsoft Ads",
};


const ACTION_LABELS = {
  "campaign.pause": "Pause Campaign",
  "campaign.resume": "Resume Campaign",
  "campaign.create": "Create Campaign",
  "budget.update": "Update Budget",
  "ad.create": "Create Ad",
  "ad.update": "Update Ad",
};


function asArray(value) {
  return Array.isArray(value) ? value : [];
}


function formatDate(value) {
  if (!value) {
    return "—";
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "—";
  }

  return date.toLocaleString();
}


function humanize(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/\./g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}


function providerLabel(provider) {
  return PROVIDER_LABELS[provider] || humanize(provider);
}


function actionLabel(action) {
  return ACTION_LABELS[action] || humanize(action);
}


function statusTone(status) {
  switch (status) {
    case "approved":
      return "border-emerald-200 bg-emerald-50 text-emerald-700";

    case "pending_approval":
      return "border-amber-200 bg-amber-50 text-amber-700";

    case "rejected":
    case "failed":
    case "cancelled":
      return "border-red-200 bg-red-50 text-red-700";

    case "executed":
    case "dry_run_succeeded":
      return "border-emerald-200 bg-emerald-50 text-emerald-700";

    case "policy_blocked":
      return "border-orange-200 bg-orange-50 text-orange-700";

    default:
      return "border-[#ddd4bf] bg-[#f8f3e8] text-[#686962]";
  }
}


function Badge({ children, status }) {
  return (
    <span
      className={
        "inline-flex rounded-full border px-2.5 py-1 " +
        "text-[11px] font-semibold " +
        statusTone(status)
      }
    >
      {children}
    </span>
  );
}


function JsonBlock({ value }) {
  return (
    <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-[#e8dfca] bg-[#fbf8f0] p-3 text-xs leading-6 text-[#525650]">
      {JSON.stringify(value || {}, null, 2)}
    </pre>
  );
}


function PolicyCard({
  provider,
  policy,
  supportedActions,
  onSaved,
}) {
  const [enabled, setEnabled] = React.useState(
    Boolean(policy?.enabled)
  );

  const [actions, setActions] = React.useState(
    asArray(policy?.allowed_actions)
  );

  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    setEnabled(Boolean(policy?.enabled));
    setActions(asArray(policy?.allowed_actions));
  }, [policy]);

  function toggleAction(action) {
    setActions((current) => {
      if (current.includes(action)) {
        return current.filter((item) => item !== action);
      }

      return [...current, action];
    });
  }

  async function save() {
    setSaving(true);
    setError("");

    try {
      await api.put(
        `/marketing-os/execution/policies/${provider}`,
        {
          enabled,
          allowed_actions: actions,
        }
      );

      if (onSaved) {
        await onSaved();
      }
    } catch (err) {
      setError(
        err?.response?.data?.detail?.message ||
        err?.response?.data?.detail ||
        err?.message ||
        "Unable to update provider policy."
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-xl border border-[#e7dfc9] bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-semibold text-[#1f2a22]">
            {providerLabel(provider)}
          </div>

          <div className="mt-1 text-xs text-[#777870]">
            Dry-run policy
          </div>
        </div>

        <Badge status={enabled ? "approved" : "draft"}>
          {enabled ? "Enabled" : "Disabled"}
        </Badge>
      </div>

      <label className="mt-4 flex cursor-pointer items-center gap-2 text-sm text-[#555952]">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => setEnabled(event.target.checked)}
        />
        Enable approved dry-run validation
      </label>

      <div className="mt-4 text-xs font-semibold uppercase tracking-wide text-[#8a6a3c]">
        Allowed actions
      </div>

      <div className="mt-2 space-y-2">
        {normalizeArray(supportedActions).map((action) => (
          <label
            key={action}
            className="flex cursor-pointer items-center gap-2 text-sm text-[#555952]"
          >
            <input
              type="checkbox"
              checked={actions.includes(action)}
              onChange={() => toggleAction(action)}
            />

            {actionLabel(action)}
          </label>
        ))}
      </div>

      {error && (
        <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-700">
          {String(error)}
        </div>
      )}

      <Button
        className="mt-4"
        variant="outline"
        disabled={saving}
        onClick={save}
      >
        <Settings2 size={14} className="mr-2" />
        {saving ? "Saving..." : "Save Policy"}
      </Button>

      <div className="mt-3 text-[11px] leading-5 text-[#7a7d77]">
        Live execution remains disabled regardless of this setting.
      </div>
    </div>
  );
}


function RequestDetails({
  request,
  onRefresh,
}) {
  const [expanded, setExpanded] = React.useState(false);
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState("");
  const [approvals, setApprovals] = React.useState([]);
  const [attempts, setAttempts] = React.useState([]);
  const [historyLoaded, setHistoryLoaded] = React.useState(false);

  async function loadHistory() {
    if (!request?.id) {
      return;
    }

    try {
      const [approvalResponse, attemptResponse] =
        await Promise.all([
          api.get(
            `/marketing-os/execution/requests/${request.id}/approvals`
          ),
          api.get(
            `/marketing-os/execution/requests/${request.id}/attempts`
          ),
        ]);

      setApprovals(
        asArray(
          approvalResponse?.data?.items ||
          approvalResponse?.items
        )
      );

      setAttempts(
        asArray(
          attemptResponse?.data?.items ||
          attemptResponse?.items
        )
      );

      setHistoryLoaded(true);
    } catch (err) {
      setError(
        err?.response?.data?.detail?.message ||
        err?.response?.data?.detail ||
        err?.message ||
        "Unable to load request history."
      );
    }
  }

  async function toggleExpanded() {
    const next = !expanded;
    setExpanded(next);

    if (next && !historyLoaded) {
      await loadHistory();
    }
  }

  async function action(method, path, body, name) {
    setBusy(name);
    setError("");

    try {
      if (method === "post") {
        await api.post(path, body);
      }

      await Promise.all([
        onRefresh ? onRefresh() : Promise.resolve(),
        loadHistory(),
      ]);
    } catch (err) {
      setError(
        err?.response?.data?.detail?.message ||
        err?.response?.data?.detail ||
        err?.message ||
        "Request action failed."
      );
    } finally {
      setBusy("");
    }
  }

  async function executeLiveRequest() {
    const actionName =
      actionLabel(
        request.action_type
      );

    const target =
      request.target_id
        ? `${request.target_type} ${request.target_id}`
        : request.target_type;

    const confirmed = window.confirm(
      `EXECUTE LIVE: ${actionName}\n\n` +
      `Provider: ${providerLabel(request.provider)}\n` +
      `Target: ${target}\n\n` +
      "This is the step that can change the external " +
      "advertising account. Continue?"
    );

    if (!confirmed) {
      return;
    }

    await action(
      "post",
      `/marketing-os/execution/requests/${request.id}/execute`,
      {},
      "execute"
    );
  }


  const canSubmit = request.status === "draft";
  const canDecide = request.status === "pending_approval";

  const canDryRun =
    request.status === "approved" &&
    request.dry_run === true;

  const canExecute =
    request.status === "approved" &&
    request.dry_run === false;

  return (
    <div className="rounded-xl border border-[#e7dfc9] bg-white">
      <div className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="font-semibold text-[#1f2a22]">
              {actionLabel(request.action_type)}
            </div>

            <div className="mt-1 text-sm text-[#666962]">
              {providerLabel(request.provider)}
              {" • "}
              {humanize(request.target_type)}
              {request.target_id
                ? ` • ${request.target_id}`
                : ""}
            </div>
          </div>

          <Badge status={request.status}>
            {humanize(request.status)}
          </Badge>
        </div>

        <div className="mt-3 grid gap-2 text-xs text-[#777870] sm:grid-cols-2 lg:grid-cols-4">
          <div>
            Created: {formatDate(request.created_at)}
          </div>

          <div>
            Dry run: {request.dry_run ? "Yes" : "No"}
          </div>

          <div>
            Human approval:{" "}
            {request.human_approval_required
              ? "Required"
              : "No"}
          </div>

          <div>
            Mode:{" "}
            {
              request.dry_run
                ? "Approved simulation"
                : "Governed live execution"
            }
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {canSubmit && (
            <Button
              disabled={Boolean(busy)}
              onClick={() =>
                action(
                  "post",
                  `/marketing-os/execution/requests/${request.id}/submit`,
                  {},
                  "submit"
                )
              }
            >
              <Clock3 size={14} className="mr-2" />
              {busy === "submit"
                ? "Submitting..."
                : "Submit for Approval"}
            </Button>
          )}

          {canDecide && (
            <>
              <Button
                disabled={Boolean(busy)}
                onClick={() =>
                  action(
                    "post",
                    `/marketing-os/execution/requests/${request.id}/decision`,
                    {
                      decision: "approve",
                      reason:
                        "Approved through Marketing OS execution queue.",
                    },
                    "approve"
                  )
                }
              >
                <Check size={14} className="mr-2" />
                {busy === "approve"
                  ? "Approving..."
                  : "Approve"}
              </Button>

              <Button
                variant="outline"
                disabled={Boolean(busy)}
                onClick={() =>
                  action(
                    "post",
                    `/marketing-os/execution/requests/${request.id}/decision`,
                    {
                      decision: "reject",
                      reason:
                        "Rejected through Marketing OS execution queue.",
                    },
                    "reject"
                  )
                }
              >
                <X size={14} className="mr-2" />
                {busy === "reject"
                  ? "Rejecting..."
                  : "Reject"}
              </Button>
            </>
          )}

          {canExecute && (
            <Button
              disabled={Boolean(busy)}
              onClick={executeLiveRequest}
            >
              <Play size={14} className="mr-2" />

              {
                busy === "execute"
                  ? "Executing..."
                  : "Execute Approved Live Action"
              }
            </Button>
          )}

          {canDryRun && (
            <Button
              disabled={Boolean(busy)}
              onClick={() =>
                action(
                  "post",
                  `/marketing-os/execution/requests/${request.id}/dry-run`,
                  {},
                  "dry-run"
                )
              }
            >
              <Play size={14} className="mr-2" />
              {busy === "dry-run"
                ? "Running..."
                : "Run Approved Dry Run"}
            </Button>
          )}

          <Button
            type="button"
            variant="outline"
            onClick={toggleExpanded}
          >
            {expanded ? (
              <ChevronUp size={14} className="mr-2" />
            ) : (
              <ChevronDown size={14} className="mr-2" />
            )}

            {expanded ? "Hide Details" : "View Details"}
          </Button>
        </div>

        {error && (
          <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {String(error)}
          </div>
        )}
      </div>

      {expanded && (
        <div className="border-t border-[#ebe3d0] bg-[#fdfbf6] p-4">
          <div className="grid gap-4 lg:grid-cols-2">
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-[#8a6a3c]">
                Request Payload
              </div>

              <JsonBlock value={request.request_payload} />
            </div>

            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-[#8a6a3c]">
                Request Metadata
              </div>

              <JsonBlock
                value={{
                  id: request.id,
                  provider: request.provider,
                  action_type: request.action_type,
                  target_type: request.target_type,
                  target_id: request.target_id,
                  idempotency_key:
                    request.idempotency_key,
                  approved_by:
                    request.approved_by,
                  approved_at:
                    request.approved_at,
                }}
              />
            </div>
          </div>

          <div className="mt-5 grid gap-4 lg:grid-cols-2">
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-[#8a6a3c]">
                Approval History
              </div>

              {approvals.length ? (
                <div className="space-y-2">
                  {normalizeArray(approvals).map((item) => (
                    <div
                      key={item.id}
                      className="rounded-lg border border-[#e7dfc9] bg-white p-3"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <Badge
                          status={
                            item.decision === "approve"
                              ? "approved"
                              : "rejected"
                          }
                        >
                          {humanize(item.decision)}
                        </Badge>

                        <span className="text-xs text-[#777870]">
                          {formatDate(item.created_at)}
                        </span>
                      </div>

                      {item.reason && (
                        <div className="mt-2 text-sm text-[#60635d]">
                          {item.reason}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-sm text-[#777870]">
                  No approval decisions recorded.
                </div>
              )}
            </div>

            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-[#8a6a3c]">
                Execution Attempts
              </div>

              {attempts.length ? (
                <div className="space-y-2">
                  {normalizeArray(attempts).map((item) => (
                    <div
                      key={item.id}
                      className="rounded-lg border border-[#e7dfc9] bg-white p-3"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <Badge status={item.status}>
                          {humanize(item.status)}
                        </Badge>

                        <span className="text-xs text-[#777870]">
                          Attempt {item.attempt_number}
                        </span>
                      </div>

                      <div className="mt-2 text-xs text-[#777870]">
                        {formatDate(item.started_at)}
                      </div>

                      {item.response_snapshot && (
                        <div className="mt-3">
                          <JsonBlock
                            value={item.response_snapshot}
                          />
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-sm text-[#777870]">
                  No execution attempts recorded.
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


export default function MarketingExecutionQueue() {
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  const [requests, setRequests] = React.useState([]);
  const [policies, setPolicies] = React.useState([]);
  const [providers, setProviders] = React.useState([]);
  const [supportedActions, setSupportedActions] =
    React.useState([]);

  const [showCreate, setShowCreate] = React.useState(false);
  const [showPolicies, setShowPolicies] =
    React.useState(false);

  const [creating, setCreating] = React.useState(false);
  const operationTokenRef = React.useRef(null);
  const operationFingerprintRef = React.useRef(null);

  const [form, setForm] = React.useState({
    provider: "google_ads",
    action_type: "campaign.pause",
    target_type: "campaign",
    target_id: "",
    payload: "{}",
  });

  const load = React.useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const [
        requestResponse,
        policyResponse,
        providerResponse,
      ] = await Promise.all([
        api.get("/marketing-os/execution/requests?limit=100"),
        api.get("/marketing-os/execution/policies"),
        api.get("/marketing-os/execution/providers"),
      ]);

      setRequests(
        asArray(
          requestResponse?.data?.items ||
          requestResponse?.items
        )
      );

      setPolicies(
        asArray(
          policyResponse?.data?.items ||
          policyResponse?.items
        )
      );

      const providerData =
        providerResponse?.data ||
        providerResponse ||
        {};

      setProviders(
        asArray(providerData.providers)
      );

      setSupportedActions(
        asArray(providerData.supported_actions)
      );
    } catch (err) {
      setError(
        err?.response?.data?.detail?.message ||
        err?.response?.data?.detail ||
        err?.message ||
        "Unable to load execution queue."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  function policyFor(provider) {
    return normalizeArray(policies).find(
      (item) => item.provider === provider
    );
  }

  async function createRequest() {
    setCreating(true);
    setError("");

    try {
      let payload = {};

      try {
        payload = JSON.parse(form.payload || "{}");
      } catch {
        throw new Error(
          "Request payload must be valid JSON."
        );
      }

      const operationFingerprint = JSON.stringify({
        provider: form.provider,
        action_type: form.action_type,
        target_type: form.target_type,
        target_id: form.target_id.trim() || null,
        payload,
      });

      if (
        operationFingerprintRef.current !== null &&
        operationFingerprintRef.current !== operationFingerprint
      ) {
        operationTokenRef.current = null;
      }

      if (!operationTokenRef.current) {
        if (
          typeof crypto === "undefined" ||
          typeof crypto.randomUUID !== "function"
        ) {
          throw new Error(
            "Secure operation token generation is unavailable."
          );
        }

        operationTokenRef.current = crypto.randomUUID();
        operationFingerprintRef.current =
          operationFingerprint;
      }

      await api.post(
        "/marketing-os/execution/requests",
        {
          provider: form.provider,
          action_type: form.action_type,
          target_type: form.target_type,
          target_id:
            form.target_id.trim() || null,
          payload,
          operation_token:
            operationTokenRef.current,
          dry_run: true,
        }
      );

      // The operation completed successfully. A future
      // intentional create must receive a fresh token.
      operationTokenRef.current = null;
      operationFingerprintRef.current = null;

      setShowCreate(false);

      setForm((current) => ({
        ...current,
        target_id: "",
        payload: "{}",
      }));

      await load();
    } catch (err) {
      setError(
        err?.response?.data?.detail?.message ||
        err?.response?.data?.detail ||
        err?.message ||
        "Unable to create execution request."
      );
    } finally {
      setCreating(false);
    }
  }

  const pendingCount = normalizeArray(requests).filter(
    (item) => item.status === "pending_approval"
  ).length;

  const approvedCount = normalizeArray(requests).filter(
    (item) => item.status === "approved"
  ).length;

  return (
    <section
      className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5"
      data-testid="marketing-execution-queue"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-widest text-[#8a6a3c]">
            Phase 14
          </div>

          <div className="flex items-center gap-2 font-display text-xl text-[#1f2a22]">
            <ShieldCheck
              size={20}
              className="text-[#466653]"
            />

            Controlled Execution Queue
          </div>

          <div className="mt-1 max-w-3xl text-sm leading-6 text-[#666962]">
            Review, approve, and simulate marketing provider
            changes before any external execution capability
            is introduced.
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            disabled={loading}
            onClick={load}
          >
            <RefreshCw
              size={14}
              className={
                loading
                  ? "mr-2 animate-spin"
                  : "mr-2"
              }
            />

            Refresh
          </Button>

          <Button
            variant="outline"
            onClick={() =>
              setShowPolicies((value) => !value)
            }
          >
            <Settings2 size={14} className="mr-2" />
            Provider Policies
          </Button>

          <Button
            onClick={() =>
              setShowCreate((value) => !value)
            }
          >
            <Plus size={14} className="mr-2" />
            New Request
          </Button>
        </div>
      </div>

      <div className="mt-5 flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4">
        <AlertTriangle
          size={19}
          className="mt-0.5 shrink-0 text-amber-700"
        />

        <div>
          <div className="font-semibold text-amber-900">
            Governed live advertising execution
          </div>

          <div className="mt-1 text-sm leading-6 text-amber-800">
            Live provider changes require a live request,
            human approval, and a separate explicit Execute step.
            Approval alone does not modify the advertising account.
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-[#e7dfc9] bg-white p-4">
          <div className="text-xs uppercase tracking-wide text-[#8a6a3c]">
            Total Requests
          </div>

          <div className="mt-2 text-2xl font-semibold text-[#1f2a22]">
            {requests.length}
          </div>
        </div>

        <div className="rounded-xl border border-[#e7dfc9] bg-white p-4">
          <div className="text-xs uppercase tracking-wide text-[#8a6a3c]">
            Awaiting Approval
          </div>

          <div className="mt-2 text-2xl font-semibold text-[#1f2a22]">
            {pendingCount}
          </div>
        </div>

        <div className="rounded-xl border border-[#e7dfc9] bg-white p-4">
          <div className="text-xs uppercase tracking-wide text-[#8a6a3c]">
            Approved Requests
          </div>

          <div className="mt-2 text-2xl font-semibold text-[#1f2a22]">
            {approvedCount}
          </div>
        </div>
      </div>

      {error && (
        <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {String(error)}
        </div>
      )}

      {showCreate && (
        <div className="mt-5 rounded-xl border border-[#d8cba9] bg-white p-4">
          <div className="mb-4 font-semibold text-[#1f2a22]">
            Create Dry-Run Execution Request
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <label className="text-sm text-[#555952]">
              <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-[#8a6a3c]">
                Provider
              </span>

              <select
                className="w-full rounded-lg border border-[#d9d0ba] bg-white px-3 py-2"
                value={form.provider}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    provider: event.target.value,
                  }))
                }
              >
                {(providers.length
                  ? providers
                  : [
                      "google_ads",
                      "meta_ads",
                      "microsoft_ads",
                    ]
                ).map((provider) => (
                  <option
                    key={provider}
                    value={provider}
                  >
                    {providerLabel(provider)}
                  </option>
                ))}
              </select>
            </label>

            <label className="text-sm text-[#555952]">
              <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-[#8a6a3c]">
                Action
              </span>

              <select
                className="w-full rounded-lg border border-[#d9d0ba] bg-white px-3 py-2"
                value={form.action_type}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    action_type: event.target.value,
                  }))
                }
              >
                {(supportedActions.length
                  ? supportedActions
                  : Object.keys(ACTION_LABELS)
                ).map((action) => (
                  <option
                    key={action}
                    value={action}
                  >
                    {actionLabel(action)}
                  </option>
                ))}
              </select>
            </label>

            <label className="text-sm text-[#555952]">
              <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-[#8a6a3c]">
                Target Type
              </span>

              <input
                className="w-full rounded-lg border border-[#d9d0ba] px-3 py-2"
                value={form.target_type}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    target_type: event.target.value,
                  }))
                }
              />
            </label>

            <label className="text-sm text-[#555952]">
              <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-[#8a6a3c]">
                Target ID
              </span>

              <input
                className="w-full rounded-lg border border-[#d9d0ba] px-3 py-2"
                placeholder="Campaign or ad ID"
                value={form.target_id}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    target_id: event.target.value,
                  }))
                }
              />
            </label>
          </div>

          <label className="mt-4 block text-sm text-[#555952]">
            <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-[#8a6a3c]">
              Request Payload — JSON
            </span>

            <textarea
              rows={7}
              className="w-full rounded-lg border border-[#d9d0ba] px-3 py-2 font-mono text-xs"
              value={form.payload}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  payload: event.target.value,
                }))
              }
            />
          </label>

          <div className="mt-4 flex flex-wrap gap-2">
            <Button
              disabled={creating}
              onClick={createRequest}
            >
              <Plus size={14} className="mr-2" />
              {creating
                ? "Creating..."
                : "Create Dry-Run Request"}
            </Button>

            <Button
              variant="outline"
              onClick={() => setShowCreate(false)}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}

      {showPolicies && (
        <div className="mt-5">
          <div className="mb-3 flex items-center gap-2 font-semibold text-[#1f2a22]">
            <Settings2 size={17} />
            Provider Dry-Run Policies
          </div>

          <div className="grid gap-3 lg:grid-cols-3">
            {(providers.length
              ? providers
              : [
                  "google_ads",
                  "meta_ads",
                  "microsoft_ads",
                ]
            ).map((provider) => (
              <PolicyCard
                key={provider}
                provider={provider}
                policy={policyFor(provider)}
                supportedActions={supportedActions}
                onSaved={load}
              />
            ))}
          </div>
        </div>
      )}

      <div className="mt-6">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="font-semibold text-[#1f2a22]">
            Execution Requests
          </div>

          <div className="flex items-center gap-1 text-xs text-[#777870]">
            <Ban size={13} />
            External writes disabled
          </div>
        </div>

        {loading ? (
          <div className="rounded-xl border border-[#e7dfc9] bg-white p-8 text-center text-sm text-[#777870]">
            Loading execution queue...
          </div>
        ) : requests.length ? (
          <div className="space-y-3">
            {normalizeArray(requests).map((request) => (
              <RequestDetails
                key={request.id}
                request={request}
                onRefresh={load}
              />
            ))}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-[#d8cba9] bg-white p-8 text-center text-sm text-[#777870]">
            No controlled execution requests yet.
          </div>
        )}
      </div>
    </section>
  );
}
