import React from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import api, { clearAccessToken, LS, broadcastAuth } from "../lib/api";
import { useAuth } from "../lib/auth";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { useToast } from "../hooks/use-toast";
import { ShieldCheck, LogOut } from "lucide-react";

/**
 * Session-preserving MFA reauthentication screen.
 *
 * Reached when the backend answers a PHI route with
 * `403 detail.code=mfa_reauth_required` — the access token is still valid,
 * but the current session has no `mfa_satisfied_at`. Posting a valid TOTP
 * against `/auth/mfa/verify` (which does NOT require the MFA gate) marks
 * the session and lets the user continue.
 */
export default function MfaChallenge() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { toast } = useToast();
  const { user, refreshMe, logout } = useAuth();
  const [code, setCode] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [failed, setFailed] = React.useState(0);
  const reason = params.get("reason") || "reauth";

  const verify = async () => {
    if (code.length < 6) return;
    setBusy(true);
    try {
      await api.post("/auth/mfa/verify", { token: code });
      toast({ title: "Verified" });
      await refreshMe?.();
      broadcastAuth("mfa-reauthed");
      // Send them home. Router redirects clients to /portal, workforce
      // to /portal/staff etc. based on role.
      navigate("/portal", { replace: true });
    } catch (e) {
      const nextFailed = failed + 1;
      setFailed(nextFailed);
      const status = e?.response?.status;
      // Only drop the session after repeated failure OR a hard 401.
      // A single-digit typo shouldn't destroy the session.
      if (status === 401 && nextFailed >= 3) {
        clearAccessToken();
        try { localStorage.removeItem(LS.user); } catch {}
        toast({
          title: "Too many failed attempts",
          description: "Signing you out for safety.",
        });
        navigate("/login?reason=mfa_reauth_failed", { replace: true });
        return;
      }
      toast({ title: "Invalid code", description: "Try again with the current 6-digit code from your authenticator." });
    } finally {
      setBusy(false);
      setCode("");
    }
  };

  return (
    <div className="min-h-screen bg-[#f6f1e6] flex items-center justify-center px-4">
      <div className="w-full max-w-md bg-white rounded-2xl border border-[#e7dfc9] p-8 shadow-sm" data-testid="mfa-challenge">
        <div className="flex items-center gap-3 mb-1">
          <ShieldCheck className="text-[#2f4a3a]" size={22} />
          <h1 className="font-display text-2xl text-[#1f2a22]">Verify your identity</h1>
        </div>
        <p className="text-sm text-[#6a6a6a] mb-6">
          {reason === "reauth"
            ? "This session needs a fresh six-digit code from your authenticator app before you can view patient information."
            : "Enter the six-digit code from your authenticator to continue."}
        </p>
        {user?.email && (
          <div className="text-xs text-[#8a6a3c] mb-4">Signed in as {user.email}</div>
        )}
        <Input
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
          onKeyDown={(e) => { if (e.key === "Enter") verify(); }}
          placeholder="123 456"
          maxLength={6}
          inputMode="numeric"
          autoFocus
          className="text-center text-2xl tracking-widest font-mono bg-[#fbf7ee] border-[#e0d6bc] h-14"
          data-testid="mfa-challenge-input"
        />
        <Button
          onClick={verify}
          disabled={busy || code.length < 6}
          className="mt-4 w-full h-11 rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
          data-testid="mfa-challenge-submit"
        >
          {busy ? "Verifying…" : "Verify"}
        </Button>
        <button
          type="button"
          onClick={async () => { await logout?.(); navigate("/login", { replace: true }); }}
          className="mt-5 w-full flex items-center justify-center gap-2 text-xs text-[#8a6a3c] hover:text-[#6a4f28]"
          data-testid="mfa-challenge-logout"
        >
          <LogOut size={12} /> Sign out instead
        </button>
      </div>
    </div>
  );
}
