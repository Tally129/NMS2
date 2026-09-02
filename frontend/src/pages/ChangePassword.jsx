import React from "react";
import { useNavigate } from "react-router-dom";
import api from "../lib/api";
import { useAuth, isWorkforceRole } from "../lib/auth";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { useToast } from "../hooks/use-toast";
import { KeyRound, ShieldCheck, LogOut } from "lucide-react";

function readBootstrapUser() {
  try {
    return JSON.parse(sessionStorage.getItem("nms_bootstrap_user") || "null");
  } catch {
    return null;
  }
}

function clearBootstrapState() {
  sessionStorage.removeItem("nms_bootstrap_token");
  sessionStorage.removeItem("nms_bootstrap_stage");
  sessionStorage.removeItem("nms_bootstrap_user");
}

export default function ChangePassword() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { toast } = useToast();

  const bootstrapToken = sessionStorage.getItem("nms_bootstrap_token");
  const bootstrapStage = sessionStorage.getItem("nms_bootstrap_stage");
  const bootstrapUser = React.useMemo(readBootstrapUser, []);

  const isBootstrap =
    Boolean(bootstrapToken) && bootstrapStage === "password_change";

  const effectiveUser = user || bootstrapUser;
  const forced = isBootstrap || Boolean(user?.must_change_password);

  const [currentPassword, setCurrentPassword] = React.useState("");
  const [newPassword, setNewPassword] = React.useState("");
  const [confirmPassword, setConfirmPassword] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (!user && !isBootstrap) {
      navigate("/staff-login", { replace: true });
    }
  }, [user, isBootstrap, navigate]);

  const submit = async (e) => {
    e.preventDefault();

    if (newPassword !== confirmPassword) {
      toast({
        title: "Passwords do not match",
        description: "Please retype the new password.",
      });
      return;
    }

    if (newPassword.length < 12) {
      toast({
        title: "Password too short",
        description: "Must be at least 12 characters.",
      });
      return;
    }

    setBusy(true);

    try {
      if (isBootstrap) {
        const { data } = await api.post(
          "/auth/bootstrap/password-change",
          {
            current_password: currentPassword,
            new_password: newPassword,
          },
          {
            headers: {
              Authorization: `Bearer ${bootstrapToken}`,
            },
          }
        );

        clearBootstrapState();

        toast({
          title: "Password updated",
          description:
            data?.next_step === "mfa_enrollment"
              ? "Sign in again with your new password to set up MFA."
              : "Sign in again with your new password.",
        });

        navigate(
          isWorkforceRole(effectiveUser?.role) ? "/staff-login" : "/login",
          { replace: true }
        );
        return;
      }

      await api.post("/auth/change-password", {
        current_password: currentPassword,
        new_password: newPassword,
      });

      toast({
        title: "Password updated",
        description: "Sign in again with your new password to continue.",
      });

      await logout?.();

      navigate(
        isWorkforceRole(effectiveUser?.role) ? "/staff-login" : "/login",
        { replace: true }
      );
    } catch (err) {
      const detail = err?.response?.data?.detail;
      const description =
        typeof detail === "string"
          ? detail
          : detail?.message || err?.message || "Try again.";

      toast({
        title: "Could not change password",
        description,
      });
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    clearBootstrapState();

    if (user) {
      await logout?.();
    }

    navigate(
      isWorkforceRole(effectiveUser?.role) ? "/staff-login" : "/login",
      { replace: true }
    );
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
              Replace your temporary password before continuing to the secure portal.
            </span>
          </div>
        )}

        {effectiveUser?.email && (
          <div className="text-xs text-slate-500 mb-4">
            Account: {effectiveUser.email}
          </div>
        )}

        <Label
          className="text-xs text-[#3d6b52]"
          htmlFor="current-password"
        >
          Temporary / current password
        </Label>
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

        <Label className="text-xs text-[#3d6b52]" htmlFor="new-password">
          New password (12+ characters)
        </Label>
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
          Must be at least 12 characters, not be a common password, and not
          contain your name or email.
        </p>

        <Label className="text-xs text-[#3d6b52]" htmlFor="confirm-password">
          Confirm new password
        </Label>
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
          disabled={
            busy ||
            !currentPassword ||
            newPassword.length < 12 ||
            newPassword !== confirmPassword
          }
          className="w-full h-11 rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]"
          data-testid="change-password-submit"
        >
          {busy ? "Updating…" : "Update password"}
        </Button>

        {forced && (
          <button
            type="button"
            onClick={cancel}
            className="mt-5 w-full flex items-center justify-center gap-2 text-xs text-[#8a6a3c] hover:text-[#6a4f28]"
            data-testid="change-password-logout"
          >
            <LogOut size={12} /> Cancel and return to sign in
          </button>
        )}
      </form>
    </div>
  );
}
