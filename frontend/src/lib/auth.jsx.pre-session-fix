import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import api, {
  LS, touchActivity, isIdle, IDLE_TIMEOUT_MS,
  setAccessToken, getAccessToken, clearAccessToken, doRefresh,
  onAuthBroadcast, broadcastAuth,
} from "./api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const logout = useCallback(async () => {
    try { await api.post("/auth/logout"); } catch {}
    clearAccessToken();
    localStorage.removeItem(LS.user);
    localStorage.removeItem(LS.lastActivity);
    setUser(null);
    broadcastAuth("logout");
  }, []);

  const logoutAll = useCallback(async () => {
    try { await api.post("/auth/logout-all"); } catch {}
    clearAccessToken();
    localStorage.removeItem(LS.user);
    setUser(null);
    broadcastAuth("logout-all");
  }, []);

  const refreshMe = useCallback(async () => {
    if (!getAccessToken()) { setLoading(false); return; }
    try {
      const { data } = await api.get("/auth/me");
      setUser(data);
      localStorage.setItem(LS.user, JSON.stringify(data));
    } catch {
      setUser(null);
      clearAccessToken();
      localStorage.removeItem(LS.user);
    } finally {
      setLoading(false);
    }
  }, []);

  // Sprint 2 bootstrap: on app-start, try the refresh cookie for a new access token.
  // Public auth routes (`/login`, `/staff-login`, `/forgot-password`,
  // `/reset-password`, `/patient-login`, `/register`) MUST NOT depend on a
  // refresh cookie. When the user lands on one of them directly (e.g. from
  // an emailed reset link), we do not call `/auth/refresh` at all — a 401
  // there is expected but can still confuse users if a downstream layer
  // ever surfaces the response body.
  const _isPublicAuthPath = () => {
    try {
      const p = (typeof window !== "undefined" && window.location.pathname) || "";
      return /^\/(reset-password|forgot-password|login|staff-login|patient-login|register)(\/|$)/.test(p);
    } catch { return false; }
  };
  useEffect(() => {
    let mounted = true;
    if (_isPublicAuthPath()) {
      // Anonymous session — do not touch /auth/refresh.
      setLoading(false);
      return () => { mounted = false; };
    }
    (async () => {
      try {
        await doRefresh();
        const cached = localStorage.getItem(LS.user);
        if (mounted && cached) setUser(JSON.parse(cached));
        await refreshMe();
      } catch {
        if (mounted) { clearAccessToken(); setUser(null); setLoading(false); }
      }
    })();
    const off = onAuthBroadcast((msg) => {
      if (msg?.event === "logout" || msg?.event === "logout-all" || msg?.event === "session-expired") {
        clearAccessToken();
        localStorage.removeItem(LS.user);
        setUser(null);
      }
      // A sibling tab just refreshed — if we don't yet have a token in
      // memory, kick off our own refresh (which will hit the concurrency
      // grace path and get a fresh access token quickly).
      if (msg?.event === "refresh-done" && !getAccessToken()) {
        doRefresh().then(() => refreshMe()).catch(() => {});
      }
    });
    return () => { mounted = false; off(); };
  }, [refreshMe]);

  async function loginWithPassword(email, password, mfa_token) {
    const { data } = await api.post("/auth/login", { email, password, mfa_token: mfa_token || null });
    if (data.mfa_required) return { mfa_required: true };
    setAccessToken(data.access_token);
    localStorage.setItem(LS.user, JSON.stringify(data.user));
    touchActivity();
    setUser(data.user);
    return { user: data.user, notice: data.notice };
  }

  async function loginContinue(continuation_ticket, revoke_session_id) {
    const { data } = await api.post("/auth/login/continue", { continuation_ticket, revoke_session_id });
    setAccessToken(data.access_token);
    localStorage.setItem(LS.user, JSON.stringify(data.user));
    touchActivity();
    setUser(data.user);
    return { user: data.user };
  }

  async function registerNew({ email, password, full_name, phone }) {
    const { data } = await api.post("/auth/register", { email, password, full_name, phone });
    setAccessToken(data.access_token);
    localStorage.setItem(LS.user, JSON.stringify(data.user));
    touchActivity();
    setUser(data.user);
    return { user: data.user };
  }

  return (
    <AuthContext.Provider
      value={{
        user, loading, logout, logoutAll, loginWithPassword, loginContinue, registerNew, refreshMe, setUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() { return useContext(AuthContext); }

export function roleHome(role) {
  switch (role) {
    case "admin":            return "/portal/admin";
    case "practitioner":     return "/portal/provider";
    case "medical_assistant": return "/portal/staff";
    case "staff":
    case "front_desk":
    case "frontdesk":        return "/portal/staff";
    case "auditor":          return "/portal/admin/audit";
    case "client":           return "/portal/patient";
    default:                 return "/portal/patient";
  }
}

// Roles that must sign in through the staff/provider login page (dark
// theme, /staff-login). Everything else — clients + fallback — belongs on the
// patient login. Kept here (co-located with `roleHome`) so route guards and
// the two login screens agree on which portal a user "belongs" to.
export const WORKFORCE_ROLES = new Set([
  "admin",
  "practitioner",
  "medical_assistant",
  "staff",
  "front_desk",
  "frontdesk",
  "auditor",
]);

export function isWorkforceRole(role) {
  return WORKFORCE_ROLES.has(role);
}

export function loginPathForRole(role) {
  return isWorkforceRole(role) ? "/staff-login" : "/login";
}
