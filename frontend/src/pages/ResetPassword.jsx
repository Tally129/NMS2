import React from "react";
import { Link, useSearchParams } from "react-router-dom";
import axios from "axios";
import { clearAccessToken, LS, broadcastAuth } from "../lib/api";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * `/reset-password?token=<one-time-token>`
 *
 * Reads the token from the query string, POSTs it plus a new password to
 * `POST /api/auth/reset-password`, and never persists the token or new
 * password in browser storage. On success the URL is stripped of the
 * token before redirecting to /login.
 */
export default function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [pw, setPw] = React.useState("");
  const [pw2, setPw2] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState("");
  const [done, setDone] = React.useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    if (!token) {
      setErr("This password-reset link is incomplete or invalid.");
      return;
    }
    if (pw.length < 12) {
      setErr("Password must be at least 12 characters.");
      return;
    }
    if (pw !== pw2) {
      setErr("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await axios.post(`${API}/auth/reset-password`, {
        token,
        new_password: pw,
      });
      // The backend revoked every session for this user. Purge every
      // fragment of client-side auth state so the AuthProvider does not
      // briefly re-hydrate from a stale cache and bounce us into a
      // Protected route before landing on /login.
      try {
        clearAccessToken();
        localStorage.removeItem(LS.user);
        localStorage.removeItem(LS.lastActivity);
        // Best-effort clear of the refresh cookie for this device.
        await axios.post(`${API}/auth/logout`, {}, { withCredentials: true }).catch(() => {});
        broadcastAuth("logout");
      } catch (_) { /* non-fatal */ }
      setDone(true);
      // Strip the token from the URL before the redirect so it does not
      // sit in browser history in a usable form.
      try {
        window.history.replaceState({}, "", "/reset-password");
      } catch (_) { /* history API unavailable — safe to ignore */ }
      // Hard navigation ensures the AuthProvider re-initializes with a
      // clean refresh call rather than replaying the cached user.
      setTimeout(() => {
        window.location.assign("/login");
      }, 1400);
    } catch (e) {
      // Never surface the raw backend error message — map every failure
      // to a safe generic string so an invalid/expired token cannot be
      // distinguished from an unknown backend fault.
      setErr("This reset link is invalid or has expired. Please request a new one.");
    } finally {
      setBusy(false);
    }
  };

  if (!token) {
    return (
      <div className="min-h-screen bg-[#f6f1e6] flex items-center justify-center p-6"
            data-testid="reset-password-missing-token">
        <div className="bg-white rounded-2xl shadow p-8 max-w-md w-full text-center">
          <h1 className="text-xl font-semibold text-[#3b2f19] mb-3">Reset link invalid</h1>
          <p className="text-sm text-[#5a4a1f]">
            This password-reset link is incomplete or invalid. Please request a new one.
          </p>
          <Link to="/forgot-password"
                 className="mt-6 inline-block text-[#8b7226] underline"
                 data-testid="reset-password-request-new">
            Request a new reset link
          </Link>
        </div>
      </div>
    );
  }

  if (done) {
    return (
      <div className="min-h-screen bg-[#f6f1e6] flex items-center justify-center p-6"
            data-testid="reset-password-success">
        <div className="bg-white rounded-2xl shadow p-8 max-w-md w-full text-center">
          <h1 className="text-xl font-semibold text-[#3b2f19] mb-3">Password updated</h1>
          <p className="text-sm text-[#5a4a1f]">
            Your password has been changed. Redirecting to sign in…
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#f6f1e6] flex items-center justify-center p-6">
      <form onSubmit={submit}
             className="bg-white rounded-2xl shadow p-8 max-w-md w-full space-y-4"
             data-testid="reset-password-form">
        <h1 className="text-xl font-semibold text-[#3b2f19]">Choose a new password</h1>
        <p className="text-sm text-[#5a4a1f]">
          Enter a new password for your Natural Medical Solutions account.
        </p>
        <label className="block">
          <span className="text-sm text-[#3b2f19]">New password</span>
          <input type="password" value={pw} onChange={(e) => setPw(e.target.value)}
                 autoComplete="new-password" required minLength={12}
                 className="mt-1 block w-full rounded border border-[#e0d6bc] px-3 py-2"
                 data-testid="reset-password-new" />
        </label>
        <label className="block">
          <span className="text-sm text-[#3b2f19]">Confirm password</span>
          <input type="password" value={pw2} onChange={(e) => setPw2(e.target.value)}
                 autoComplete="new-password" required minLength={12}
                 className="mt-1 block w-full rounded border border-[#e0d6bc] px-3 py-2"
                 data-testid="reset-password-confirm" />
        </label>
        {err ? (
          <div className="text-sm text-[#a3251a]" data-testid="reset-password-error">
            {err}
          </div>
        ) : null}
        <button type="submit" disabled={busy}
                 className="w-full rounded bg-[#8b7226] text-white px-4 py-2 disabled:opacity-60"
                 data-testid="reset-password-submit">
          {busy ? "Saving…" : "Change password"}
        </button>
        <div className="text-center">
          <Link to="/login" className="text-sm text-[#8b7226] underline">
            Back to sign in
          </Link>
        </div>
      </form>
    </div>
  );
}
