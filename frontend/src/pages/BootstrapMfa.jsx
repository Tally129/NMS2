import React from "react";
import { useNavigate } from "react-router-dom";
import api from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { useToast } from "../hooks/use-toast";
import { ShieldCheck, Copy, KeyRound } from "lucide-react";

function clearBootstrapState() {
  sessionStorage.removeItem("nms_bootstrap_token");
  sessionStorage.removeItem("nms_bootstrap_stage");
  sessionStorage.removeItem("nms_bootstrap_user");
}

export default function BootstrapMfa() {
  const navigate = useNavigate();
  const { toast } = useToast();

  const bootstrapToken = sessionStorage.getItem("nms_bootstrap_token");
  const bootstrapStage = sessionStorage.getItem("nms_bootstrap_stage");

  const [secret, setSecret] = React.useState("");
  const [provisioningUri, setProvisioningUri] = React.useState("");
  const [code, setCode] = React.useState("");
  const [recoveryCodes, setRecoveryCodes] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    let mounted = true;

    if (!bootstrapToken || bootstrapStage !== "mfa_enrollment") {
      navigate("/staff-login", { replace: true });
      return undefined;
    }

    api
      .post(
        "/auth/bootstrap/mfa/setup",
        {},
        {
          headers: {
            Authorization: `Bearer ${bootstrapToken}`,
          },
        }
      )
      .then(({ data }) => {
        if (!mounted) return;
        setSecret(data.secret || "");
        setProvisioningUri(data.provisioning_uri || "");
      })
      .catch((err) => {
        const detail = err?.response?.data?.detail;
        toast({
          title: "Could not start MFA setup",
          description:
            typeof detail === "string"
              ? detail
              : detail?.message || "Sign in again to restart enrollment.",
        });
        clearBootstrapState();
        navigate("/staff-login", { replace: true });
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, [bootstrapToken, bootstrapStage, navigate, toast]);

  const copyText = async (value, label) => {
    try {
      await navigator.clipboard.writeText(value);
      toast({ title: `${label} copied` });
    } catch {
      toast({ title: "Copy failed", description: "Select and copy it manually." });
    }
  };

  const verify = async (e) => {
    e.preventDefault();

    if (!/^\d{6}$/.test(code)) {
      toast({
        title: "Enter a valid code",
        description: "Use the current 6-digit code from your authenticator app.",
      });
      return;
    }

    setBusy(true);

    try {
      const { data } = await api.post(
        "/auth/bootstrap/mfa/verify",
        { token: code },
        {
          headers: {
            Authorization: `Bearer ${bootstrapToken}`,
          },
        }
      );

      setRecoveryCodes(data.recovery_codes || []);
      clearBootstrapState();

      toast({
        title: "MFA enabled",
        description: "Save your recovery codes before signing in.",
      });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      toast({
        title: "Verification failed",
        description:
          typeof detail === "string"
            ? detail
            : detail?.message || "Check the code and try again.",
      });
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#f6f1e6] text-[#2f4a3a]">
        Preparing MFA setup…
      </div>
    );
  }

  if (recoveryCodes.length > 0) {
    return (
      <div className="min-h-screen bg-[#f6f1e6] flex items-center justify-center px-4 py-10">
        <div className="w-full max-w-lg rounded-2xl bg-white border border-[#e7dfc9] p-8 shadow-sm">
          <div className="flex items-center gap-3">
            <ShieldCheck className="text-[#2f4a3a]" />
            <h1 className="font-display text-2xl text-[#1f2a22]">
              Save your recovery codes
            </h1>
          </div>

          <p className="mt-3 text-sm text-slate-600">
            Each code can be used once if you lose access to your authenticator.
            Store them somewhere secure. They will not be shown again.
          </p>

          <div className="mt-5 grid grid-cols-2 gap-2 rounded-xl bg-[#fbf7ee] border border-[#e0d6bc] p-4 font-mono text-sm">
            {recoveryCodes.map((item) => (
              <div key={item}>{item}</div>
            ))}
          </div>

          <Button
            type="button"
            onClick={() => copyText(recoveryCodes.join("\n"), "Recovery codes")}
            className="mt-4 w-full"
          >
            <Copy size={15} className="mr-2" />
            Copy recovery codes
          </Button>

          <Button
            type="button"
            onClick={() => navigate("/staff-login", { replace: true })}
            className="mt-3 w-full bg-[#2f4a3a] text-white"
          >
            Continue to sign in
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#f6f1e6] flex items-center justify-center px-4 py-10">
      <form
        onSubmit={verify}
        className="w-full max-w-lg rounded-2xl bg-white border border-[#e7dfc9] p-8 shadow-sm"
      >
        <div className="flex items-center gap-3">
          <KeyRound className="text-[#2f4a3a]" />
          <h1 className="font-display text-2xl text-[#1f2a22]">
            Set up multi-factor authentication
          </h1>
        </div>

        <p className="mt-3 text-sm text-slate-600">
          Add this account to Google Authenticator, Microsoft Authenticator,
          Authy, or another TOTP-compatible app.
        </p>

        <div className="mt-5 rounded-xl bg-[#fbf7ee] border border-[#e0d6bc] p-4">
          <Label className="text-xs text-[#3d6b52]">
            Manual setup key
          </Label>
          <div className="mt-2 flex gap-2">
            <Input value={secret} readOnly className="font-mono" />
            <Button type="button" onClick={() => copyText(secret, "Setup key")}>
              <Copy size={15} />
            </Button>
          </div>
        </div>

        {provisioningUri && (
          <details className="mt-4 text-xs text-slate-500">
            <summary className="cursor-pointer">Advanced setup URI</summary>
            <div className="mt-2 break-all font-mono rounded-lg bg-slate-50 p-3">
              {provisioningUri}
            </div>
          </details>
        )}

        <Label className="mt-6 block text-xs text-[#3d6b52]" htmlFor="mfa-code">
          Current 6-digit authenticator code
        </Label>
        <Input
          id="mfa-code"
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
          inputMode="numeric"
          autoComplete="one-time-code"
          placeholder="000000"
          className="mt-2 tracking-[0.35em] font-mono text-center"
          required
        />

        <Button
          type="submit"
          disabled={busy || code.length !== 6}
          className="mt-6 w-full bg-[#2f4a3a] text-white"
        >
          {busy ? "Verifying…" : "Verify and enable MFA"}
        </Button>
      </form>
    </div>
  );
}
