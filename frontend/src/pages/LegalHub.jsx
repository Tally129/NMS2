import React from "react";
import { Link } from "react-router-dom";
import api from "../lib/api";
import PortalLayout, { PortalHeader } from "./PortalLayout";
import { useAuth } from "../lib/auth";
import { Shield, Scale, FileText, BadgeCheck, Mail, Video, Receipt, Accessibility, ArrowRight } from "lucide-react";

const ICONS = {
  shield: Shield, scale: Scale, "file-text": FileText, "badge-check": BadgeCheck,
  mail: Mail, video: Video, receipt: Receipt, accessibility: Accessibility,
};

function formatDate(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" }); }
  catch { return "—"; }
}

/**
 * Legal & Policies hub — publicly accessible. Loads through the standard
 * PortalLayout when the visitor is authenticated, and through a lightweight
 * public wrapper otherwise so unauthenticated users can still read policies.
 */
export default function LegalHub() {
  const { user } = useAuth();
  const [policies, setPolicies] = React.useState([]);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    api.get("/legal/policies")
      .then((r) => setPolicies(r.data || []))
      .catch(() => setPolicies([]))
      .finally(() => setLoading(false));
  }, []);

  const content = (
    <div data-testid="legal-hub">
      <PortalHeader
        title="Legal & Policies"
        subtitle="We believe every patient should understand how our services work and how we protect your information. The documents below explain your rights, responsibilities, and our commitment to privacy and security."
      />
      {loading ? (
        <div className="text-[#6a6a6a]">Loading policies…</div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {policies.map((p) => {
            const Icon = ICONS[p.icon] || FileText;
            return (
              <Link
                key={p.slug}
                to={`/legal/${p.slug}`}
                className="group rounded-2xl border border-[#e7dfc9] bg-white p-5 hover:border-[#c19a4b] transition shadow-sm hover:shadow-md flex flex-col"
                data-testid={`legal-card-${p.slug}`}
              >
                <div className="flex items-center gap-3 mb-3">
                  <div className="rounded-xl bg-[#eaf2ec] text-[#2f4a3a] p-2">
                    <Icon size={20} />
                  </div>
                  <div className="text-[10px] uppercase tracking-widest text-[#8a6a3c]">
                    v{p.current_version || "1.0"}
                  </div>
                </div>
                <div className="font-display text-xl text-[#1f2a22] mb-2">{p.title}</div>
                <p className="text-sm text-[#3a3a3a] mb-4 flex-1">{p.description}</p>
                <div className="text-[11px] text-slate-500 mb-3">Last updated {formatDate(p.last_updated)}</div>
                <div className="flex items-center gap-1 text-[#2f6a4a] text-sm font-medium group-hover:gap-2 transition-all">
                  View policy <ArrowRight size={14} />
                </div>
              </Link>
            );
          })}
        </div>
      )}
      <div className="mt-8 rounded-2xl bg-[#fbf7ee] border border-[#e7dfc9] p-5 text-sm text-[#3a3a3a]">
        Questions or concerns about how your information is handled?
        Contact our Privacy Officer at{" "}
        <a href="mailto:privacy@natmedsol.com" className="text-[#2f6a4a] underline">privacy@natmedsol.com</a>{" "}
        or (770) 674-6311.
      </div>
    </div>
  );

  if (user) return <PortalLayout>{content}</PortalLayout>;
  return <PublicShell>{content}</PublicShell>;
}

/** Minimal marketing-site shell so unauthenticated readers still see chrome. */
function PublicShell({ children }) {
  return (
    <div className="min-h-screen bg-[#f6f1e6] text-[#1f2a22] font-body">
      <header className="border-b border-[#e7dfc9] bg-[#fbf7ee]">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link to="/" className="font-display text-lg text-[#2f4a3a]">Natural Medical Solutions</Link>
          <nav className="text-sm space-x-4">
            <Link to="/patient-login" className="text-[#8a6a3c] hover:underline">Patient login</Link>
            <Link to="/staff-login" className="text-[#8a6a3c] hover:underline">Staff login</Link>
          </nav>
        </div>
      </header>
      <main className="max-w-5xl mx-auto px-6 py-10">{children}</main>
      <LegalFooter />
    </div>
  );
}

export function LegalFooter() {
  return (
    <footer className="mt-16 border-t border-[#e7dfc9] bg-[#fbf7ee]">
      <div className="max-w-5xl mx-auto px-6 py-6 text-xs text-[#8a6a3c] flex flex-wrap gap-x-5 gap-y-2 justify-center">
        <Link to="/legal/terms" className="hover:underline">Terms of Use</Link>
        <Link to="/legal/privacy" className="hover:underline">Privacy Policy</Link>
        <Link to="/legal/hipaa" className="hover:underline">Notice of Privacy Practices</Link>
        <Link to="/legal/accessibility" className="hover:underline">Accessibility</Link>
        <Link to="/legal/cookies" className="hover:underline">Cookie Policy</Link>
        <a href="mailto:privacy@natmedsol.com" className="hover:underline">Contact Privacy Officer</a>
      </div>
    </footer>
  );
}
