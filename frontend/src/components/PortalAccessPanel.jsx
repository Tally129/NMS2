import React from "react";
import api from "../lib/api";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Checkbox } from "./ui/checkbox";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "./ui/dialog";
import { useToast } from "../hooks/use-toast";
import {
  Mail, KeyRound, Copy, ShieldOff, ShieldCheck, Send, ExternalLink, RefreshCw,
  UserPlus, Eye, EyeOff, AlertTriangle,
} from "lucide-react";

const STATUS_BADGES = {
  active: { label: "Active", cls: "bg-[#eaf2ec] text-[#3d6b52]" },
  invitation_pending: { label: "Invitation pending", cls: "bg-[#fdf3d0] text-[#8a6a3c]" },
  provisioned: { label: "Provisioned · awaiting first login", cls: "bg-[#fdf3d0] text-[#8a6a3c]" },
  disabled: { label: "Disabled", cls: "bg-[#fdecec] text-[#7a2a2a]" },
  not_invited: { label: "Not invited", cls: "bg-slate-100 text-slate-500" },
};

function humanDate(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString(); } catch { return "—"; }
}

/**
 * Patient portal access + credential-management panel.
 * Rendered on the admin/provider patient chart. Never displays a password
 * after creation. All actions produce audit entries on the backend.
 */
export default function PortalAccessPanel({ clientId, clientEmail }) {
  const { toast } = useToast();
  const [status, setStatus] = React.useState(null);
  const [lastInviteUrl, setLastInviteUrl] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [createOpen, setCreateOpen] = React.useState(false);
  const [oneTimePassword, setOneTimePassword] = React.useState(null);

  const load = React.useCallback(async () => {
    try {
      const r = await api.get(`/clients/${clientId}/portal-status`);
      setStatus(r.data);
    } catch { setStatus(null); }
  }, [clientId]);

  React.useEffect(() => { load(); }, [load]);

  const invite = async () => {
    setBusy(true);
    try {
      const r = await api.post(`/clients/${clientId}/portal-invite`);
      setLastInviteUrl(r.data?.invite_url || null);
      setOneTimePassword(null);
      toast({
        title: r.data?.already_has_user ? "Invite re-sent" : "Portal account provisioned",
        description: r.data?.invite_url
          ? "Setup link ready — copy or share below."
          : (r.data?.message || "Invitation sent."),
      });
      load();
    } catch (e) {
      toast({ title: "Invite failed",
              description: e?.response?.data?.detail?.message || e.message });
    } finally { setBusy(false); }
  };

  const reset = async () => {
    setBusy(true);
    try {
      const r = await api.post(`/clients/${clientId}/portal-reset-password`);
      setLastInviteUrl(r.data?.invite_url || null);
      setOneTimePassword(null);
      toast({ title: "Password reset link sent", description: r.data?.message });
      load();
    } catch (e) {
      toast({ title: "Reset failed",
              description: e?.response?.data?.detail?.message || e.message });
    } finally { setBusy(false); }
  };

  const disable = async () => {
    const reason = window.prompt("Reason for disabling this portal account? (optional)") || undefined;
    if (reason === null) return;
    setBusy(true);
    try {
      await api.post(`/clients/${clientId}/portal-disable`, { reason });
      toast({ title: "Portal disabled" });
      load();
    } catch (e) {
      toast({ title: "Disable failed",
              description: e?.response?.data?.detail?.message || e.message });
    } finally { setBusy(false); }
  };

  const enable = async () => {
    setBusy(true);
    try {
      await api.post(`/clients/${clientId}/portal-enable`);
      toast({ title: "Portal re-enabled" });
      load();
    } catch (e) {
      toast({ title: "Enable failed",
              description: e?.response?.data?.detail?.message || e.message });
    } finally { setBusy(false); }
  };

  const loginUrl = `${window.location.origin}/patient-login`;
  const copyLogin = () => {
    navigator.clipboard.writeText(loginUrl);
    toast({ title: "Portal login URL copied", description: loginUrl });
  };
  const copyInvite = () => {
    if (!lastInviteUrl) return;
    navigator.clipboard.writeText(lastInviteUrl);
    toast({ title: "Setup link copied", description: "Send this to the patient over a secure channel." });
  };
  const copyOneTimePassword = () => {
    if (!oneTimePassword) return;
    navigator.clipboard.writeText(oneTimePassword);
    toast({ title: "Temporary password copied",
             description: "This password will not be shown again." });
  };

  if (!status) return null;
  const badge = STATUS_BADGES[status.status] || STATUS_BADGES.not_invited;
  const hasPortal = status.has_portal;
  const active = status.portal_active;

  return (
    <div className="rounded-2xl border border-[#c19a4b] bg-[#fbf3df] p-5" data-testid="portal-access-panel">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <div>
          <div className="eyebrow text-[#8a6a3c]">Patient portal access</div>
          <div className="mt-1 flex items-center gap-2 flex-wrap">
            <Badge className={`${badge.cls} hover:${badge.cls}`} data-testid="portal-status-badge">
              {status.status === "active" ? <ShieldCheck size={12} className="mr-1" /> :
               status.status === "disabled" ? <ShieldOff size={12} className="mr-1" /> :
               <AlertTriangle size={12} className="mr-1" />}
              {badge.label}
            </Badge>
            {status.is_test_patient && (
              <Badge className="bg-[#fdf3d0] text-[#8a6a3c] hover:bg-[#fdf3d0]">
                TEST PATIENT — NON-PRODUCTION
              </Badge>
            )}
          </div>
        </div>
        <Button
          onClick={load}
          variant="ghost" size="sm"
          className="h-8 rounded-full text-[#8a6a3c] hover:bg-[#f1ead8]"
          data-testid="portal-refresh-btn"
        >
          <RefreshCw size={13} className="mr-1" /> Refresh
        </Button>
      </div>

      {/* Status details grid */}
      <div className="grid sm:grid-cols-2 gap-2 text-xs mb-4 bg-white/50 rounded-lg p-3 border border-[#e2d5b3]">
        <Field label="Login email" value={status.email || "—"} testid="portal-status-email" />
        <Field label="Account created" value={humanDate(status.created_at)} testid="portal-status-created" />
        <Field label="Invitation sent" value={humanDate(status.invitation_sent_at)} testid="portal-status-invited" />
        <Field label="Last login" value={humanDate(status.last_login_at)} testid="portal-status-lastlogin" />
        <Field label="Password last changed" value={humanDate(status.password_changed_at)} testid="portal-status-password" />
        <Field label="Must change on next login"
               value={status.must_change_password ? "Yes" : "No"}
               testid="portal-status-must-change"
               emphasize={status.must_change_password} />
      </div>

      <div className="flex flex-wrap gap-2">
        {!hasPortal && (
          <Button
            onClick={() => setCreateOpen(true)} disabled={busy}
            className="rounded-full bg-[#2f6a4a] hover:bg-[#265739] text-white"
            data-testid="portal-create-btn"
          >
            <UserPlus size={13} className="mr-1" /> Create portal account
          </Button>
        )}
        {!hasPortal || !active ? (
          <Button
            onClick={invite} disabled={busy || (!clientEmail && !status.email)}
            className="rounded-full bg-[#2f6a4a] hover:bg-[#265739] text-white"
            data-testid="portal-invite-btn"
          >
            <Send size={13} className="mr-1" /> {hasPortal ? "Resend invitation" : "Send portal invitation"}
          </Button>
        ) : (
          <Button
            onClick={invite} disabled={busy}
            variant="outline"
            className="rounded-full border-[#2f6a4a] text-[#2f6a4a]"
            data-testid="portal-resend-invite-btn"
          >
            <Mail size={13} className="mr-1" /> Resend invitation
          </Button>
        )}
        {hasPortal && (
          <>
            <Button
              onClick={() => setCreateOpen(true)} disabled={busy || !active}
              variant="outline"
              className="rounded-full border-[#c19a4b] text-[#8a6a3c]"
              data-testid="portal-set-temp-btn"
            >
              <KeyRound size={13} className="mr-1" /> Set temporary password
            </Button>
            <Button
              onClick={reset} disabled={busy || !active}
              variant="outline"
              className="rounded-full border-[#c19a4b] text-[#8a6a3c]"
              data-testid="portal-reset-btn"
            >
              <Mail size={13} className="mr-1" /> Email reset link
            </Button>
          </>
        )}
        <Button
          onClick={copyLogin}
          variant="outline"
          className="rounded-full border-[#8a6a3c] text-[#8a6a3c]"
          data-testid="portal-copy-url-btn"
        >
          <Copy size={13} className="mr-1" /> Copy portal login URL
        </Button>
        {hasPortal && (
          active ? (
            <Button
              onClick={disable} disabled={busy}
              variant="outline"
              className="rounded-full border-[#7a2a2a] text-[#7a2a2a]"
              data-testid="portal-disable-btn"
            >
              <ShieldOff size={13} className="mr-1" /> Disable portal access
            </Button>
          ) : (
            <Button
              onClick={enable} disabled={busy}
              variant="outline"
              className="rounded-full border-[#2f6a4a] text-[#2f6a4a]"
              data-testid="portal-enable-btn"
            >
              <ShieldCheck size={13} className="mr-1" /> Re-enable portal
            </Button>
          )
        )}
      </div>

      {lastInviteUrl && (
        <div className="mt-3 rounded-lg bg-white border border-dashed border-[#c19a4b] p-3 text-xs text-slate-700 flex items-center gap-2">
          <ExternalLink size={12} className="text-[#8a6a3c] flex-shrink-0" />
          <span className="flex-1 font-mono truncate" data-testid="portal-invite-link">{lastInviteUrl}</span>
          <Button size="sm" variant="ghost"
            onClick={copyInvite}
            className="h-7 rounded-full text-[#2f6a4a]"
            data-testid="portal-copy-invite-btn"
          >
            <Copy size={12} className="mr-1" /> Copy
          </Button>
        </div>
      )}

      {oneTimePassword && (
        <OneTimePasswordCard
          password={oneTimePassword}
          loginUrl={loginUrl}
          onCopy={copyOneTimePassword}
          onDismiss={() => setOneTimePassword(null)}
        />
      )}

      <CreatePortalAccountDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        clientId={clientId}
        defaultEmail={status.email || clientEmail || ""}
        isExisting={hasPortal}
        onSuccess={(password) => {
          setOneTimePassword(password);
          setLastInviteUrl(null);
          setCreateOpen(false);
          load();
        }}
      />
    </div>
  );
}

function Field({ label, value, testid, emphasize }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-widest text-[#8a6a3c]">{label}</span>
      <span className={`${emphasize ? "text-[#7a2a2a] font-semibold" : "text-[#1f2a22]"}`} data-testid={testid}>
        {value}
      </span>
    </div>
  );
}

function OneTimePasswordCard({ password, loginUrl, onCopy, onDismiss }) {
  const [show, setShow] = React.useState(true);
  return (
    <div className="mt-4 rounded-lg border-2 border-[#c19a4b] bg-white p-4" data-testid="one-time-password-card">
      <div className="flex items-start gap-2 mb-2">
        <AlertTriangle className="text-[#8a6a3c] mt-0.5 flex-shrink-0" size={16} />
        <div className="text-xs text-[#8a6a3c]">
          <strong>Share this password with the patient now.</strong> It will not
          be shown again. The patient will be required to change it at first
          login.
        </div>
      </div>
      <div className="flex items-center gap-2 mb-3">
        <div className="flex-1 font-mono text-lg tracking-wide bg-[#fbf7ee] border border-[#e0d6bc] rounded px-3 py-2 select-all"
             data-testid="one-time-password-value">
          {show ? password : "•".repeat(password.length)}
        </div>
        <Button
          onClick={() => setShow((v) => !v)}
          variant="outline" size="sm"
          className="h-9 rounded-full border-[#8a6a3c] text-[#8a6a3c]"
          data-testid="one-time-password-toggle"
        >
          {show ? <EyeOff size={13} /> : <Eye size={13} />}
        </Button>
        <Button
          onClick={onCopy}
          size="sm"
          className="h-9 rounded-full bg-[#2f6a4a] hover:bg-[#265739] text-white"
          data-testid="one-time-password-copy"
        >
          <Copy size={13} className="mr-1" /> Copy
        </Button>
      </div>
      <div className="text-[11px] text-slate-500 mb-2">
        Patient portal login URL: <span className="font-mono">{loginUrl}</span>
      </div>
      <Button
        onClick={onDismiss} variant="ghost" size="sm"
        className="h-8 rounded-full text-[#8a6a3c]"
        data-testid="one-time-password-dismiss"
      >
        I've shared it securely — hide
      </Button>
    </div>
  );
}

function CreatePortalAccountDialog({ open, onClose, clientId, defaultEmail, isExisting, onSuccess }) {
  const { toast } = useToast();
  const [email, setEmail] = React.useState(defaultEmail);
  const [password, setPassword] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [requireChange, setRequireChange] = React.useState(true);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (open) {
      setEmail(defaultEmail || "");
      setPassword("");
      setConfirm("");
      setRequireChange(true);
    }
  }, [open, defaultEmail]);

  const generate = () => {
    // Word-based passphrases are easy to read aloud yet meet the 12-char policy.
    const words = ["Cedar", "Willow", "Maple", "Aspen", "River", "Meadow",
                    "Harbor", "Summit", "Ember", "Otter", "Vinca", "Sage"];
    const w1 = words[Math.floor(Math.random() * words.length)];
    const w2 = words[Math.floor(Math.random() * words.length)];
    const n = Math.floor(1000 + Math.random() * 9000);
    const s = "!@#$%&*"[Math.floor(Math.random() * 7)];
    const pwd = `${w1}-${w2}-${n}${s}`;
    setPassword(pwd);
    setConfirm(pwd);
  };

  const submit = async (e) => {
    e?.preventDefault?.();
    if (password !== confirm) {
      toast({ title: "Passwords do not match" });
      return;
    }
    if (password.length < 12) {
      toast({ title: "Password too short", description: "Minimum 12 characters." });
      return;
    }
    setBusy(true);
    try {
      await api.post(`/clients/${clientId}/portal-create-account`, {
        email,
        password,
        password_confirm: confirm,
        require_password_change: requireChange,
      });
      // Surface the password to the admin ONCE, never persist it after this call.
      onSuccess?.(password);
      toast({
        title: isExisting ? "Temporary password set" : "Portal account created",
        description: "Share the password securely with the patient.",
      });
    } catch (err) {
      const msg = err?.response?.data?.detail;
      toast({
        title: "Could not create account",
        description: typeof msg === "string" ? msg : msg?.message || "Try again.",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent className="bg-white max-w-md" data-testid="create-portal-dialog">
        <DialogHeader>
          <DialogTitle>
            {isExisting ? "Set temporary password" : "Create portal account"}
          </DialogTitle>
          <DialogDescription>
            The patient will sign in at <span className="font-mono">/patient-login</span>
            {" "}with this email and password. The password is shown only once
            after you create the account.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-3">
          <div>
            <Label htmlFor="create-email">Login email</Label>
            <Input
              id="create-email" type="email" value={email}
              onChange={(e) => setEmail(e.target.value)}
              required disabled={isExisting}
              className="mt-1" data-testid="create-portal-email"
            />
            {isExisting && (
              <p className="text-[11px] text-slate-500 mt-1">
                Email cannot be changed here — use the client profile to change it.
              </p>
            )}
          </div>
          <div>
            <div className="flex items-center justify-between">
              <Label htmlFor="create-password">Temporary password (12+ chars)</Label>
              <button
                type="button" onClick={generate}
                className="text-[11px] text-[#2f6a4a] hover:underline"
                data-testid="create-portal-generate"
              >
                Generate one for me
              </button>
            </div>
            <Input
              id="create-password" type="text" value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={12} required
              className="mt-1 font-mono" data-testid="create-portal-password"
            />
          </div>
          <div>
            <Label htmlFor="create-confirm">Confirm password</Label>
            <Input
              id="create-confirm" type="text" value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              minLength={12} required
              className="mt-1 font-mono" data-testid="create-portal-confirm"
            />
          </div>
          <label className="flex items-start gap-2 text-xs text-slate-700">
            <Checkbox
              checked={requireChange}
              onCheckedChange={(v) => setRequireChange(!!v)}
              className="mt-0.5"
              data-testid="create-portal-force-change"
            />
            <span>
              Require the patient to change this password at first login
              (recommended).
            </span>
          </label>
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button
            onClick={submit}
            disabled={busy || password.length < 12 || password !== confirm}
            className="bg-[#2f6a4a] hover:bg-[#265739] text-white rounded-full"
            data-testid="create-portal-submit"
          >
            {busy ? "Creating…" : (isExisting ? "Set temporary password" : "Create account")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
