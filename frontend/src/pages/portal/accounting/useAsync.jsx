import React from "react";
import { Button } from "../../../components/ui/button";
import { AlertCircle, Loader2, RefreshCw } from "lucide-react";
import api from "../../../lib/api";
import { getErrorMessage } from "../../../lib/errors";

/**
 * Small state-machine hook for accounting fetches.
 * Returns { data, loading, error, refetch }.
 *
 * `key` is a stable serializable value; the fetch only re-fires when key changes.
 * Prevents the infinite-render loop caused by inline `new Date().toISOString()`.
 */
export function useAsyncGet(url, params, key) {
  const [state, setState] = React.useState({ data: null, loading: !!url, error: null });
  const stableKey = typeof key === "string" ? key : JSON.stringify(key ?? params ?? url);
  const run = React.useCallback(async () => {
    // Passing url=null means "not ready to fetch yet" (e.g. before the user
    // picks an account for GL). Show empty/loading gracefully without
    // hitting the network.
    if (!url) {
      setState({ data: null, loading: false, error: null });
      return;
    }
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const r = await api.get(url, params ? { params } : undefined);
      // 403 sentinel from api.js returns { data: null } — treat as denied
      if (r?.__isAuthDenied) {
        setState({ data: null, loading: false, error: "permission_denied" });
        return;
      }
      setState({ data: r.data, loading: false, error: null });
    } catch (e) {
      setState({ data: null, loading: false, error: getErrorMessage(e) || "fetch_failed" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, stableKey]);
  React.useEffect(() => { run(); }, [run]);
  return { ...state, refetch: run };
}

/**
 * Wraps children with loading / empty / error / retry chrome.
 * `data` is used to decide the branch; children get raw `data`.
 */
export function AsyncPanel({
  data, loading, error, onRetry, empty,
  emptyMessage = "Nothing here yet.",
  errorMessage = "Couldn't load this section.",
  children,
  className = "",
}) {
  if (loading) {
    return (
      <div className={`rounded-2xl border border-[#e2ebe4] bg-white p-8 text-center text-slate-500 text-sm ${className}`} data-testid="async-loading">
        <Loader2 size={16} className="inline mr-2 animate-spin text-[#3d6b52]" /> Loading…
      </div>
    );
  }
  if (error) {
    return (
      <div className={`rounded-2xl border border-[#f4c9c9] bg-[#fdf5f5] p-6 text-[#7a2a2a] ${className}`} data-testid="async-error">
        <div className="flex items-start gap-2">
          <AlertCircle size={16} className="mt-0.5" />
          <div className="flex-1">
            <div className="font-medium">{errorMessage}</div>
            <div className="text-xs mt-1 opacity-75">
              {error === "permission_denied" ? "You don't have access to this data." : ""}
            </div>
          </div>
          {onRetry && (
            <Button size="sm" variant="outline" onClick={onRetry} data-testid="async-retry" className="rounded-full border-[#d4a8a8] text-[#7a2a2a]">
              <RefreshCw size={12} className="mr-1" /> Retry
            </Button>
          )}
        </div>
      </div>
    );
  }
  if (empty || data === null || data === undefined
      || (Array.isArray(data) && data.length === 0)) {
    return (
      <div className={`rounded-2xl border border-dashed border-[#e2ebe4] bg-white p-8 text-center text-slate-400 text-sm ${className}`} data-testid="async-empty">
        {emptyMessage}
      </div>
    );
  }
  return <>{children}</>;
}
