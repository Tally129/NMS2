import React from "react";
import api from "../lib/api";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { useToast } from "../hooks/use-toast";
import {
  Mail, KeyRound, Copy, ShieldOff, ShieldCheck, Send, ExternalLink, RefreshCw,
} from "lucide-react";

/**
 * Portal Access panel: rendered on the patient chart. Lets admins/practitioners
 * invite a client to the portal, resend a fresh password link, disable/enable
 * portal access, and copy the public portal URL. Never surfaces passwords.
 */
export default function PortalAccessPanel({ clientId, clientEmail }) {
  const { toast } = useToast();
  const [status, setStatus] = React.useState(null);
  const [lastInviteUrl, setLastInviteUrl] = React.useState(null);
  const [busy, setBusy] = React.useState(false);

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
      toast({
        title: r.data?.already_has_user ? "Invite re-sent" : "Portal account created",
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
      toast({ title: "Password reset link sent",
              description: r.data?.message });
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

  const loginUrl = `${window.location.origin}/login`;
  const copyLogin = () => {
    navigator.clipboard.writeText(loginUrl);
    toast({ title: "Portal login URL copied", description: loginUrl });
  };
  const copyInvite = () => {
    if (!lastInviteUrl) return;
    navigator.clipboard.writeText(lastInviteUrl);
    toast({ title: "Setup link copied", description: "Send this to the patient over a secure channel." });
  };

  if (!status) return null;
  const hasPortal = status.has_portal;
  const active = status.portal_active;

  return (
    <div className="rounded-2xl border border-[#c19a4b] bg-[#fbf3df] p-5" data-testid="portal-access-panel">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <div>
          <div className="eyebrow text-[#8a6a3c]">Patient portal access</div>
          <div className="mt-1 flex items-center gap-2 flex-wrap">
            {hasPortal ? (
              active ? (
                <Badge className="bg-[#eaf2ec] text-[#3d6b52] hover:bg-[#eaf2ec]">
                  <ShieldCheck size={12} className="mr-1" /> Active
                </Badge>
              ) : (
                <Badge className="bg-[#fdecec] text-[#7a2a2a] hover:bg-[#fdecec]">
                  <ShieldOff size={12} className="mr-1" /> Disabled
                </Badge>
              )
            ) : (
              <Badge className="bg-slate-100 text-slate-500 hover:bg-slate-100">Not yet invited</Badge>
            )}
            {status.is_test_patient && (
              <Badge className="bg-[#fdf3d0] text-[#8a6a3c] hover:bg-[#fdf3d0]">
                TEST PATIENT — NON-PRODUCTION
              </Badge>
            )}
            {status.email && (
              <span className="text-xs text-slate-600">{status.email}</span>
            )}
            {status.last_login_at && (
              <span className="text-xs text-slate-500">
                Last login {new Date(status.last_login_at).toLocaleString()}
              </span>
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

      <div className="flex flex-wrap gap-2">
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
          <Button
            onClick={reset} disabled={busy || !active}
            variant="outline"
            className="rounded-full border-[#c19a4b] text-[#8a6a3c]"
            data-testid="portal-reset-btn"
          >
            <KeyRound size={13} className="mr-1" /> Reset patient password
          </Button>
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
      {status.must_change_password && (
        <div className="mt-2 text-xs text-[#8a6a3c]">
          Patient hasn't set a password yet — the invite link is required for first login.
        </div>
      )}
    </div>
  );
}
