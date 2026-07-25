import React from "react";
import { useParams, Link } from "react-router-dom";
import api from "../lib/api";
import PortalLayout, { PortalHeader } from "./PortalLayout";
import { LegalFooter } from "./LegalHub";
import { useAuth } from "../lib/auth";
import { Button } from "../components/ui/button";
import { ArrowLeft, Printer, Download } from "lucide-react";

function formatDate(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" }); }
  catch { return "—"; }
}

/**
 * Individual policy page. Renders the current version's sanitized HTML and
 * builds a sticky table of contents from the h2/h3 headings inside it.
 * Publicly accessible; extra chrome shown when unauthenticated.
 */
export default function LegalPolicyPage() {
  const { slug } = useParams();
  const { user } = useAuth();
  const [policy, setPolicy] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [notFound, setNotFound] = React.useState(false);
  const bodyRef = React.useRef(null);
  const [toc, setToc] = React.useState([]);

  React.useEffect(() => {
    setLoading(true); setNotFound(false); setPolicy(null); setToc([]);
    api.get(`/legal/policies/${slug}`)
      .then((r) => setPolicy(r.data))
      .catch(() => setNotFound(true))
      .finally(() => setLoading(false));
  }, [slug]);

  React.useEffect(() => {
    if (!policy || !bodyRef.current) return;
    const headings = bodyRef.current.querySelectorAll("h2, h3");
    const rows = [];
    headings.forEach((h, i) => {
      const id = h.id || `h-${i}-${h.textContent.replace(/\s+/g, "-").toLowerCase().slice(0, 40)}`;
      h.id = id;
      rows.push({ id, text: h.textContent, level: h.tagName === "H2" ? 2 : 3 });
    });
    setToc(rows);
  }, [policy]);

  const printDoc = () => window.print();

  const content = (
    <div data-testid={`legal-policy-${slug}`}>
      {loading && <div className="text-[#6a6a6a]">Loading…</div>}
      {notFound && (
        <div className="rounded-2xl border border-[#c19a4b] bg-[#fbf3df] p-6 max-w-2xl">
          <div className="font-display text-xl mb-1">Policy not found</div>
          <p className="text-sm text-[#3a3a3a] mb-3">
            The requested document is not available.
          </p>
          <Link to="/legal" className="text-[#2f6a4a] underline">Back to Legal &amp; Policies</Link>
        </div>
      )}
      {policy && (
        <>
          <div className="mb-4">
            <Link to="/legal" className="inline-flex items-center gap-1 text-[#2f6a4a] text-sm hover:underline"
                  data-testid="legal-back-btn">
              <ArrowLeft size={14} /> Back to Legal &amp; Policies
            </Link>
          </div>
          <PortalHeader
            title={policy.title}
            subtitle={
              <span>
                Effective {formatDate(policy.effective_date)} · Last updated {formatDate(policy.last_updated)}
                {policy.current_version && <> · v{policy.current_version}</>}
              </span>
            }
            actions={
              <div className="flex gap-2 print:hidden">
                <Button onClick={printDoc} variant="outline"
                        className="rounded-full border-[#8a6a3c] text-[#8a6a3c]"
                        data-testid="legal-print-btn">
                  <Printer size={14} className="mr-1" /> Print
                </Button>
                <Button variant="outline" disabled
                        title="PDF download coming soon"
                        className="rounded-full border-slate-300 text-slate-400"
                        data-testid="legal-pdf-btn">
                  <Download size={14} className="mr-1" /> PDF
                </Button>
              </div>
            }
          />
          <div className="grid lg:grid-cols-[220px_minmax(0,1fr)] gap-8">
            {toc.length > 0 && (
              <nav className="hidden lg:block lg:sticky lg:top-6 self-start text-sm space-y-1 print:hidden"
                   data-testid="legal-toc">
                <div className="eyebrow text-[#8a6a3c] mb-2">Contents</div>
                {toc.map((row) => (
                  <a key={row.id} href={`#${row.id}`}
                     className={`block hover:text-[#2f6a4a] ${row.level === 3 ? "ml-3 text-slate-500" : "text-[#1f2a22]"}`}>
                    {row.text}
                  </a>
                ))}
              </nav>
            )}
            <article
              ref={bodyRef}
              className="prose prose-slate max-w-none text-[#1f2a22] bg-white rounded-2xl border border-[#e7dfc9] p-8 shadow-sm"
              dangerouslySetInnerHTML={{ __html: policy.content_html || "" }}
              data-testid="legal-body"
            />
          </div>
        </>
      )}
    </div>
  );

  if (user) return <PortalLayout>{content}</PortalLayout>;
  return (
    <div className="min-h-screen bg-[#f6f1e6] text-[#1f2a22] font-body">
      <header className="border-b border-[#e7dfc9] bg-[#fbf7ee] print:hidden">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link to="/" className="font-display text-lg text-[#2f4a3a]">Natural Medical Solutions</Link>
        </div>
      </header>
      <main className="max-w-5xl mx-auto px-6 py-10">{content}</main>
      <LegalFooter />
    </div>
  );
}
