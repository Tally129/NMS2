import React from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth, isWorkforceRole } from "./auth";

/**
 * Route guard.
 *
 * Redirect rules for signed-out visitors:
 *   • routes that ONLY admit `client` (e.g. `/portal/patient/*`) → `/login`
 *   • every other portal route (staff / provider / admin / MA / auditor)
 *     → `/staff-login`
 *   The originally-requested path is stashed in `location.state.from` so
 *   both login pages can bounce the user back after auth.
 *
 * Force-change-password gate:
 *   Users with `must_change_password: true` are diverted to
 *   `/change-password` before any PHI-bearing route renders. The gate is
 *   frontend UX only; backend `require_roles` also refuses PHI with
 *   `403 detail.code=password_change_required` for defense-in-depth.
 */
export function Protected({ children, roles }) {
  const { user, loading } = useAuth();
  const loc = useLocation();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#f6f1e6] text-[#2f4a3a] font-body">
        Loading…
      </div>
    );
  }

  if (!user) {
    // Client-only routes bounce unauthenticated visitors to the patient login;
    // everything else uses the staff/provider login.
    const isClientOnlyRoute =
      Array.isArray(roles) && roles.length === 1 && roles[0] === "client";
    const loginPath = isClientOnlyRoute ? "/login" : "/staff-login";
    return <Navigate to={loginPath} replace state={{ from: loc.pathname }} />;
  }

  // Forced first-login password change: block every portal route until the
  // temp password has been replaced. `/change-password` itself is excluded
  // because it renders on the guarded ChangePassword route below.
  if (user.must_change_password && loc.pathname !== "/change-password") {
    return <Navigate to="/change-password" replace state={{ from: loc.pathname }} />;
  }

  if (roles && !roles.includes(user.role)) {
    // Auditor break-glass — READ-only routes only. To opt a route in,
    // the route must EXPLICITLY list "auditor" in `roles`. We used to
    // implicitly grant auditor access to anything non-client, which
    // leaked write surfaces like POS. That has been tightened.
    return <Navigate to="/portal" replace />;
  }
  return children;
}

// Named re-export so callers that want to inspect workforce membership can
// pull it straight from this module without touching auth.jsx directly.
export { isWorkforceRole };
