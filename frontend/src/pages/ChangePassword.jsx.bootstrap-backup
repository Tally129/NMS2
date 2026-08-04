import React from "react";
import { useNavigate } from "react-router-dom";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { useToast } from "../hooks/use-toast";
import { KeyRound, ShieldCheck, LogOut } from "lucide-react";

/**
 * Forced first-login password change screen.
 *
 * Reached automatically by `MustChangePasswordGate` whenever
 * `user.must_change_password === true`. Also mounted at `/change-password`
 * for voluntary use. Uses the existing `POST /api/auth/change-password`
 * endpoint — which revokes all sessions on success — so we log the user
 * out and route them to the correct login screen.
 */
export default function ChangePassword() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [currentPassword, setCurrentPassword] = React.useState("");
  const [newPassword, setNewPassword] = React.useState("");
  const [confirmPassword, setConfirmPassword] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const forced = !!user?.must_change_password;

  const submit = async (e) => {
    e?.preventDefault?.();
    if (newPassword !== confirmPassword) {
      toast({ title: "Passwords do not match", description: "Please retype the new password." });
      return;
    }
    if (newPassword.length < 12) {
      toast({ title: "Password too short", description: "Must be at least 12 characters." });
      return;
    }
    setBusy(true);
    try {
      await api.post("/auth/change-password", {
        current_password: currentPassword,
        new_password: newPassword,
      });
      toast({
        title: "Password updated",
        description: "Sign in again with your new password to continue.",
      });
      // Backend revokes all sessions on change → force a re-login.
      await logout?.();
      // Patients (role=client) hit /patient-login; workforce hits /staff-login.
      const target = user?.role && user.role !== "client" ? "/staff-login" : "/patient-login";
      navigate(target, { replace: true });
    } catch (err) {
      const msg = err?.response?.data?.detail;
      toast({
        title: "Could not change password",
        description: (typeof msg === "string" ? msg : msg?.message) || "Try again.",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#f6f1e6] flex items-center justify-center px-4 py-10">
      <form
        onSubmit={submit}
        className="w-full max-w-md bg-white rounded-2xl border border-[#e7dfc9] p-8 shadow-sm"
        data-testid="change-password-form"
      >
        <div className="flex items-center gap-3 mb-1">
          <KeyRound className="text-[#2f4a3a]" size={22} />
          <h1 className="font-display text-2xl text-[#1f2a22]">
            {forced ? "Choose a new password" : "Change your password"}
          </h1>
        </div>
        {forced && (
          <div className="mt-3 mb-4 rounded-lg border border-[#c19a4b] bg-[#fbf3df] px-3 py-2 text-xs text-[#8a6a3c] flex items-start gap-2">
            <ShieldCheck size={13} className="mt-0.5 flex-shrink-0" />
            <span>
              For your security, please replace the temporary password you were given before continuing.
            </span>
          </div>
        )}
        {user?.email && (
          <div className="text-xs text-slate-500 mb-4">Signed in as {user.email}</div>
        )}

        <Label className="text-xs text-[#3d6b52]" htmlFor="current-password">Temporary / current password</Label>
        <Input
          id="current-password"
          type="password"
          autoComplete="current-password"
          value={currentPassword}
          onChange={(e) => setCurrentPassword(e.target.value)}
          className="mt-1 mb-4 bg-[#fbf7ee] border-[#e0d6bc]"
          required
          data-testid="change-current-password"
        />

        <Label className="text-xs text-[#3d6b52]" htmlFor="new-password">New password (12+ characters)</Label>
        <Input
          id="new-password"
          type="password"
          autoComplete="new-password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          className="mt-1 mb-1 bg-[#fbf7ee] border-[#e0d6bc]"
          required
          minLength={12}
          data-testid="change-new-password"
        />
        <p className="text-[11px] text-slate-500 mb-4">
          Must be at least 12 characters, not a common password, and not contain your name or email.
        </p>

        <Label className="text-xs text-[#3d6b52]" htmlFor="confirm-password">Confirm new password</Label>
        <Input
          id="confirm-password"
          type="password"
          autoComplete="new-password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          className="mt-1 mb-6 bg-[#fbf7ee] border-[#e0d6bc]"
          required
          minLength={12}
          data-testid="change-confirm-password"
        />

        <Button
          type="submit"
          disabled={busy || !currentPassword || newPassword.length < 12 || newPassword !== confirmPassword}
          className="w-full h-11 rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
          data-testid="change-password-submit"
        >
          {busy ? "Updating…" : "Update password"}
        </Button>

        {forced && (
          <button
            type="button"
            onClick={async () => {
              await logout?.();
              navigate("/patient-login", { replace: true });
            }}
            className="mt-5 w-full flex items-center justify-center gap-2 text-xs text-[#8a6a3c] hover:text-[#6a4f28]"
            data-testid="change-password-logout"
          >
            <LogOut size={12} /> Sign out instead
          </button>
        )}
      </form>
    </div>
  );
}
