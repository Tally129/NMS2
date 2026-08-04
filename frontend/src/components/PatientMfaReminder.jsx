import React from "react";
import { Link } from "react-router-dom";
import { ShieldCheck, CheckCircle2, Circle, X } from "lucide-react";
import { useAuth } from "../lib/auth";
import { Button } from "./ui/button";

const STORAGE_KEY = "nms_patient_mfa_reminder_dismissed";

export default function PatientMfaReminder() {
  const { user } = useAuth();
  const [dismissed, setDismissed] = React.useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === "true";
    } catch {
      return false;
    }
  });

  if (
    !user ||
    user.role !== "client" ||
    user.mfa_enabled ||
    dismissed
  ) {
    return null;
  }

  const dismiss = () => {
    try {
      localStorage.setItem(STORAGE_KEY, "true");
    } catch {
      // Local storage may be unavailable; hiding it for this session is enough.
    }
    setDismissed(true);
  };

  return (
    <section
      className="mb-6 overflow-hidden rounded-2xl border border-amber-200 bg-white shadow-sm"
      data-testid="patient-mfa-reminder"
    >
      <div className="flex items-start gap-4 p-5">
        <div className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-full bg-amber-50 text-amber-700">
          <ShieldCheck size={23} />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-amber-700">
                Recommended security step
              </p>

              <h2 className="mt-1 text-lg font-semibold text-[#1f2a22]">
                Finish protecting your account
              </h2>
            </div>

            <button
              type="button"
              onClick={dismiss}
              aria-label="Dismiss MFA reminder"
              className="rounded-full p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
            >
              <X size={17} />
            </button>
          </div>

          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
            Multi-factor authentication adds another layer of protection when
            accessing your health information, appointments, files, and secure
            messages.
          </p>

          <div className="mt-4 grid gap-2 text-sm sm:grid-cols-2">
            <div className="flex items-center gap-2 text-emerald-700">
              <CheckCircle2 size={16} />
              <span>Password created</span>
            </div>

            <div className="flex items-center gap-2 text-amber-700">
              <Circle size={16} />
              <span>Multi-factor authentication not enabled</span>
            </div>
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-3">
            <Button
              asChild
              className="rounded-full bg-[#2f6a4a] px-5 text-white hover:bg-[#265739]"
            >
              <Link to="/portal/patient/security">
                Set up MFA
              </Link>
            </Button>

            <button
              type="button"
              onClick={dismiss}
              className="text-sm font-medium text-slate-500 underline-offset-4 hover:text-slate-800 hover:underline"
            >
              I’ll do this later
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
