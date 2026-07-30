import React from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import Logo from "./Logo";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { ArrowLeft, Shield } from "lucide-react";
import { useToast } from "../hooks/use-toast";
import { useAuth, roleHome, isWorkforceRole } from "../lib/auth";
import { getErrorMessage } from "../lib/errors";

/**
 * Shared authentication shell used by both the Patient Portal (`/login`) and
 * the Staff & Provider Portal (`/staff-login`).
 *
 * Both pages render an identical layout, typography, spacing, branding and
 * animations — the only differences are the title, subtitle and the
 * cross-portal link at the bottom.
 *
 * All authentication logic — email/password login, MFA challenge, workforce
 * vs. client routing — is centralized here so the two portals cannot drift
 * apart.
 */
export default function AuthCard({
  variant,          // "patient" | "staff"
  title,
  subtitle,
  crossPortalTo,    // where to send a user who chose the "wrong" portal link
  crossPortalLabel,
  crossPortalLinkText,
}) {
  const { toast } = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const { loginWithPassword } = useAuth();

  const [form, setForm] = React.useState(() => {
    let last = "";
    try { last = localStorage.getItem("nms_last_login_email") || ""; } catch {}
    return { email: last, password: "", mfa: "" };
  });
  const [mfaRequired, setMfaRequired] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const set = (k, v) => setForm((p) => ({ ...p, [k]: v }));
  const from = location.state?.from;

  const finishLogin = React.useCallback((res) => {
    const role = res.user.role;
    const belongsHere =
      (variant === "staff" && isWorkforceRole(role)) ||
      (variant === "patient" && !isWorkforceRole(role));
    try { localStorage.setItem("nms_last_login_email", form.email); } catch {}
    if (!belongsHere) {
      const other = isWorkforceRole(role) ? "staff workspace" : "patient portal";
      toast({ title: "Welcome back", description: `Redirecting you to your ${other}…` });
      navigate(roleHome(role), { replace: true });
      return;
    }
    toast({ title: "Welcome back" });
    navigate(from || roleHome(role), { replace: true });
  }, [variant, form.email, from, navigate, toast]);

  const submit = async (e) => {
    e.preventDefault();
    if (!form.email || !form.password) {
      toast({ title: "Enter your email and password" });
      return;
    }
    setBusy(true);
    try {
      const res = await loginWithPassword(form.email, form.password, form.mfa || undefined);
      if (res.mfa_required) {
        setMfaRequired(true);
        toast({ title: "Two-factor required", description: "Enter the 6-digit code from your authenticator app." });
        return;
      }
      finishLogin(res);
    } catch (err) {
      toast({ title: "Sign in failed", description: getErrorMessage(err) || "Please try again." });
    } finally { setBusy(false); }
  };

  return (
    <div className="page-fade min-h-screen bg-gradient-to-b from-white via-[#f4f7f2] to-[#eef3ec] font-body" data-testid={`${variant}-login-page`}>
      <div className="h-1 w-full bg-gradient-to-r from-[#7fa48b] via-[#c19a4b] to-[#7fa48b]" />

      <div className="max-w-md mx-auto px-6 pt-8">
        <Link to="/" className="inline-flex items-center gap-2 text-sm text-slate-500 hover:text-[#2f6a4a] transition-colors">
          <ArrowLeft size={16} /> Back to home
        </Link>
      </div>

      <section className="max-w-md mx-auto px-6 mt-6 text-center animate-[fadeIn_.35s_ease-out]">
        <div className="flex justify-center">
          <div className="rounded-full bg-white shadow-sm border border-[#e2ebe4] p-2">
            <Logo size={72} />
          </div>
        </div>
        <div className="inline-flex items-center gap-1.5 mt-6 px-3 py-1 rounded-full bg-[#eaf2ec] border border-[#cfe0d3] text-[11px] tracking-widest uppercase text-[#3d6b52]">
          <Shield size={11} /> {variant === "staff" ? "Secure staff access" : "Secure patient access"}
        </div>
        <h1
          className="font-display text-[36px] sm:text-[40px] text-[#1f2a22] mt-4 leading-tight"
          data-testid={`${variant}-login-title`}
        >
          {title}
        </h1>
        <p className="text-slate-500 mt-2 text-sm">{subtitle}</p>
      </section>

      <section className="max-w-md mx-auto px-6 mt-8 pb-10">
        <div className="rounded-3xl border border-[#e2ebe4] bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04),0_10px_30px_-15px_rgba(47,106,74,0.15)] p-7 sm:p-8 animate-[fadeIn_.45s_ease-out]">
          <form onSubmit={submit} className="space-y-4">
            <div>
              <Label htmlFor={`${variant}-email`} className="text-slate-700">Email</Label>
              <Input
                id={`${variant}-email`} type="email" autoComplete="email" required
                value={form.email} onChange={(e) => set("email", e.target.value)}
                className="mt-2 h-11 bg-white border-[#d9e2db] focus-visible:border-[#7fa48b] focus-visible:ring-[#7fa48b]/30 rounded-lg"
                data-testid={`${variant}-login-email`}
              />
            </div>
            <div>
              <Label htmlFor={`${variant}-password`} className="text-slate-700">Password</Label>
              <Input
                id={`${variant}-password`} type="password" autoComplete="current-password" required
                value={form.password} onChange={(e) => set("password", e.target.value)}
                className="mt-2 h-11 bg-white border-[#d9e2db] focus-visible:border-[#7fa48b] focus-visible:ring-[#7fa48b]/30 rounded-lg"
                data-testid={`${variant}-login-password`}
              />
            </div>
            {mfaRequired && (
              <div className="animate-[fadeIn_.25s_ease-out]">
                <Label htmlFor={`${variant}-mfa`} className="text-slate-700">Two-factor code</Label>
                <Input
                  id={`${variant}-mfa`} value={form.mfa} onChange={(e) => set("mfa", e.target.value)}
                  className="mt-2 h-11 bg-white border-[#d9e2db] focus-visible:border-[#7fa48b] focus-visible:ring-[#7fa48b]/30 rounded-lg tracking-[0.3em] font-mono"
                  placeholder="6-digit code" maxLength={6}
                  data-testid={`${variant}-login-mfa`}
                />
              </div>
            )}
            <p className="text-[12px] text-slate-500 leading-relaxed" data-testid="login-legal-consent">
              By signing in, you agree to the{" "}
              <Link to="/legal/terms" target="_blank" rel="noopener noreferrer"
                    className="underline hover:text-[#2f6a4a]" data-testid="login-terms-link">
                Terms of Use
              </Link>, acknowledge our{" "}
              <Link to="/legal/hipaa" target="_blank" rel="noopener noreferrer"
                    className="underline hover:text-[#2f6a4a]" data-testid="login-hipaa-link">
                Notice of Privacy Practices
              </Link>, and understand our{" "}
              <Link to="/legal/privacy" target="_blank" rel="noopener noreferrer"
                    className="underline hover:text-[#2f6a4a]" data-testid="login-privacy-link">
                Privacy Policy
              </Link>.
            </p>
            <Button
              type="submit" disabled={busy}
              className="btn-lift h-12 w-full rounded-full bg-[#2f6a4a] hover:bg-[#265739] text-white shadow-sm transition-all"
              data-testid={`${variant}-login-submit`}
            >
              {busy ? "Signing in…" : mfaRequired ? "Verify & sign in" : "Sign in"}
            </Button>
          </form>

          {variant === "patient" && (
            <p className="text-center text-sm text-slate-500 mt-5">
              New here?{" "}
              <Link to="/signup" className="text-[#2f6a4a] hover:text-[#1f4a34] underline underline-offset-2 font-medium" data-testid="signup-link">
                Create an account
              </Link>
            </p>
          )}

          <p className="text-center text-[12px] text-slate-500 mt-4">
            {crossPortalLabel}{" "}
            <Link
              to={crossPortalTo}
              className="text-[#2f6a4a] hover:text-[#1f4a34] underline underline-offset-2 font-medium"
              data-testid={variant === "patient" ? "staff-login-link" : "patient-login-link"}
            >
              {crossPortalLinkText}
            </Link>
          </p>
        </div>
      </section>
    </div>
  );
}
