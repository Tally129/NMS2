import axios from "axios";
import { normalizeApiList } from "./collections";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API_BASE = `${BACKEND_URL}/api`;

// Sprint 2: NO refresh token in browser storage. Access token stays in memory only.
// LS.user + LS.lastActivity are UX conveniences that do NOT grant PHI access.
export const LS = {
  user: "nms_user",
  lastActivity: "nms_last_activity",
};

export const IDLE_TIMEOUT_MS = 15 * 60 * 1000; // 15 min
export function touchActivity() { try { localStorage.setItem(LS.lastActivity, String(Date.now())); } catch {} }
export function isIdle() {
  try {
    const v = parseInt(localStorage.getItem(LS.lastActivity) || "0", 10);
    return v > 0 && (Date.now() - v) > IDLE_TIMEOUT_MS;
  } catch { return false; }
}

// In-memory access token — never written to any storage.
let _access_token = null;
export function setAccessToken(t) { _access_token = t || null; }
export function getAccessToken() { return _access_token; }
export function clearAccessToken() { _access_token = null; }

// Cross-tab logout + refresh coordination.
// The `nms_auth` BroadcastChannel carries EVENT NAMES ONLY — never token
// values. The `nms_refresh` Web Lock (when available) serializes refresh
// calls across tabs so only one tab talks to /auth/refresh at a time; the
// others wait for it to finish and then perform their own refresh (which
// hits the concurrency-grace path with a fresh cookie).
let bc = null;
try { bc = new BroadcastChannel("nms_auth"); } catch { bc = null; }
const bcListeners = new Set();
if (bc) {
  bc.addEventListener("message", (ev) => {
    bcListeners.forEach((cb) => { try { cb(ev.data); } catch {} });
  });
}
export function onAuthBroadcast(cb) { bcListeners.add(cb); return () => bcListeners.delete(cb); }
export function broadcastAuth(event) { try { bc && bc.postMessage({ event, ts: Date.now() }); } catch {} }

const api = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
  // CRITICAL: treat 403 as a NON-error status so axios' internal `settle()`
  // resolves the promise instead of constructing an AxiosError. This is the
  // only way to prevent CRA's react-error-overlay from ever seeing the
  // "Request failed with status code 403" error — the AxiosError is never
  // created in the first place. The response interceptor below converts the
  // 403 response into the { data: null, __isAuthDenied: true } sentinel.
  validateStatus: (status) => (status >= 200 && status < 300) || status === 403,
});

api.interceptors.request.use((config) => {
  const token = _access_token;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Single-flight refresh queue + cross-tab exclusive lock.
let refreshing = null;

async function _refreshOnce() {
  // Perform the actual network call. Handles the backend's 409
  // `concurrency_retry` by immediately retrying with the fresh cookie
  // that the winning tab installed. Two retries max, then bail.
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const r = await axios.post(`${API_BASE}/auth/refresh`, {}, { withCredentials: true });
      _access_token = r.data.access_token;
      if (r.data.user) localStorage.setItem(LS.user, JSON.stringify(r.data.user));
      // Notify any idle tabs — event only, never the token.
      broadcastAuth("refresh-done");
      return _access_token;
    } catch (e) {
      if (e?.response?.status === 409 && attempt === 0) {
        // 409 = server observed a same-family used token within the grace
        // window. Another tab rotated ahead of us. Wait a beat so the
        // browser applies the winning tab's Set-Cookie, then retry.
        await new Promise((res) => setTimeout(res, 120));
        continue;
      }
      throw e;
    }
  }
  throw new Error("refresh_retry_exhausted");
}

async function doRefresh() {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    // Web Locks API serialises refresh across ALL tabs in this origin —
    // solves the multi-tab race that otherwise triggers concurrency 409s
    // for tabs 2..N. When Locks are unavailable, fall back to the
    // per-tab single-flight (`refreshing`).
    if (typeof navigator !== "undefined" && navigator.locks && typeof navigator.locks.request === "function") {
      return await navigator.locks.request(
        "nms_refresh_lock",
        { mode: "exclusive" },
        async () => _refreshOnce(),
      );
    }
    return await _refreshOnce();
  })().finally(() => { refreshing = null; });
  return refreshing;
}
export { doRefresh };

// Retry cap protects against infinite 401 loops.
api.interceptors.response.use(
  (r) => {
    // Because validateStatus allows 403, we may arrive here with a 403.
    // 403 has TWO meanings we must distinguish BEFORE converting to the
    // empty-data sentinel:
    //   1. `must_enroll_mfa`     → session is fine, workforce hasn't
    //      finished TOTP setup. Preserve the token and redirect to the
    //      role-appropriate Security page.
    //   2. `mfa_reauth_required` → session lost its mfa_satisfied_at.
    //      Preserve the token and redirect to /mfa-challenge.
    //   3. Everything else       → real RBAC denial; return the sentinel
    //      shape so callers can render an empty state without crashing.
    if (r && r.status === 403) {
      const detail = r?.data?.detail;
      const code = (detail && typeof detail === "object") ? detail.code : null;

      if (code === "must_enroll_mfa") {
        try {
          const user = JSON.parse(localStorage.getItem(LS.user) || "null");
          const role = user?.role || "staff";
          const dest =
            role === "admin"             ? "/portal/admin/security"    :
            role === "practitioner"      ? "/portal/provider/security" :
            role === "medical_assistant" ? "/portal/provider/security" :
            role === "auditor"           ? "/portal/admin/security"    :
                                            "/portal/staff/security";
          const path = window.location.pathname;
          const alreadyThere = path === dest
            || path.startsWith("/login")
            || path.startsWith("/staff-login")
            || path.endsWith("/security");
          if (!alreadyThere) window.location.href = dest + "?enroll=required";
        } catch { /* fall through */ }
        broadcastAuth(code);
      } else if (code === "mfa_reauth_required") {
        try {
          const path = window.location.pathname;
          const alreadyOnAuth = path.startsWith("/login")
            || path.startsWith("/staff-login")
            || path.startsWith("/mfa-challenge");
          if (!alreadyOnAuth) {
            window.location.href = "/mfa-challenge?reason=reauth";
          }
        } catch { /* fall through */ }
        broadcastAuth(code);
      } else {
        // eslint-disable-next-line no-console
        console.debug("[nms] 403 auth denial resolved as empty:", r?.config?.url);
      }

      const msg = typeof detail === "string" ? detail : detail?.message || "You don't have access.";
      return {
        ...r,
        data: null,
        __isAuthDenied: true,
        __authCode: code || null,
        __errorMessage: msg,
      };
    }
    return r;
  },
  async (error) => {
    const original = error.config;
    const status = error?.response?.status;
    if (status === 401 && original && !original._retry && !(original.url || "").includes("/auth/")) {
      original._retry = true;
      try {
        const newToken = await doRefresh();
        if (newToken) original.headers.Authorization = `Bearer ${newToken}`;
        return api(original);
      } catch (e) {
        const refreshStatus = e?.response?.status;

        // Only end the session when refresh is definitively rejected.
        // Network failures and backend 5xx responses must not erase a
        // potentially valid session.
        if (refreshStatus === 401 || refreshStatus === 403) {
          clearAccessToken();
          localStorage.removeItem(LS.user);
          broadcastAuth("session-expired");

          const path = window.location.pathname;
          const alreadyPublic =
            path.startsWith("/login") ||
            path.startsWith("/staff-login") ||
            path.startsWith("/forgot-password") ||
            path.startsWith("/reset-password");

          if (!alreadyPublic) {
            window.location.replace("/login");
          }
        }

        return Promise.reject(e);
      }
    }
    return Promise.reject(error);
  }
);

// Global safety net for background fetches that forget to `.catch`.
// Purpose: prevent expected 403 (and stale-request 401 already redirected)
// from surfacing as red "Uncaught (in promise) AxiosError" console noise or
// the CRA react-error-overlay. We DO NOT swallow other errors — real
// bugs still propagate.
//
// Registration details that matter for CRA dev-mode:
//   * useCapture=true  — our listener runs before the react-error-overlay
//     listener (which is added later in bubbling phase).
//   * stopImmediatePropagation() — prevents subsequent listeners (including
//     CRA's overlay) from ever seeing this event.
//   * preventDefault() — silences the browser's default console warning.
if (typeof window !== "undefined" && !window.__nms_rejection_installed) {
  window.__nms_rejection_installed = true;
  const handler = (ev) => {
    const err = ev.reason;
    const status = err?.response?.status;
    if (status === 403 || err?.isAuthDenied || err?.handled) {
      ev.preventDefault();
      if (typeof ev.stopImmediatePropagation === "function") {
        ev.stopImmediatePropagation();
      }
      // Kill CRA react-error-overlay for this specific event by
      // dispatching a follow-up "handled" flag it inspects.
      try { ev.reason && (ev.reason.__nms_swallowed = true); } catch { /* frozen */ }
      // eslint-disable-next-line no-console
      console.debug("[nms] suppressed 403 auth denial:", err?.config?.url || err);
    }
  };
  window.addEventListener("unhandledrejection", handler, true);   // capture phase
  window.addEventListener("unhandledrejection", handler, false);  // bubble phase (belt & braces)
}

export { api };

/**
 * Fetch an endpoint whose primary result is a collection.
 *
 * response.data is guaranteed to be an array.
 * response.rawData preserves pagination and other metadata.
 */
api.getList = async function getList(
  url,
  config = {},
  preferredKeys = []
) {
  const response = await api.get(url, config);
  const rawData = response.data;

  return {
    ...response,
    rawData,
    data: normalizeApiList(rawData, {
      endpoint: url,
      preferredKeys,
    }),
  };
};

export default api;

/**
 * Download a protected file via the authenticated axios instance and either
 * hand back the blob URL for the caller to consume (print / preview) or
 * trigger a browser download. Uses `responseType: "blob"` so the current
 * bearer is attached automatically via the request interceptor — the caller
 * never needs (and MUST NOT) read localStorage for a token.
 *
 *  - filename supplied → downloads directly and revokes the object URL
 *  - filename omitted  → returns { blob, url } for the caller to manage
 */
export async function downloadBlob(url, { filename, params, method = "get", data } = {}) {
  const cfg = { responseType: "blob", params };
  const res = method === "get"
    ? await api.get(url, cfg)
    : await api.request({ url, method, data, ...cfg });
  if (res && (res.__isAuthDenied || res.status === 403)) {
    const msg = res.__errorMessage || "You don't have access to that file.";
    const err = new Error(msg);
    err.isAuthDenied = true;
    err.status = 403;
    throw err;
  }
  const blob = res.data;
  const objectUrl = URL.createObjectURL(blob);
  if (filename) {
    const a = document.createElement("a");
    a.href = objectUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    // give the browser a beat to start the download before revoking
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);
    return { blob };
  }
  return { blob, url: objectUrl, revoke: () => URL.revokeObjectURL(objectUrl) };
}
