import React from "react";
import { useSearchParams } from "react-router-dom";
import api from "../lib/api";
import { CheckCircle2, XCircle } from "lucide-react";

/**
 * Public unsubscribe landing page.
 * Called from the compliance footer of every marketing email; posts to the
 * signed backend endpoint /api/campaign-unsubscribe with the same c/t query
 * params and shows a confirmation.
 */
export default function Unsubscribe() {
  const [params] = useSearchParams();
  const [status, setStatus] = React.useState("working");
  const [message, setMessage] = React.useState("Processing your request…");

  React.useEffect(() => {
    const c = params.get("c");
    const t = params.get("t");
    if (!c || !t) {
      setStatus("error");
      setMessage("This link is missing information. Please use the link from your most recent email.");
      return;
    }
    api.get("/campaign-unsubscribe", { params: { c, t } })
      .then((r) => {
        setStatus("ok");
        setMessage(r?.data?.message || "You have been unsubscribed from marketing emails.");
      })
      .catch((e) => {
        setStatus("error");
        setMessage(
          e?.response?.data?.detail ||
          "We could not process that link. Contact us and we'll unsubscribe you manually."
        );
      });
  }, [params]);

  return (
    <div className="min-h-screen bg-[#f6f1e6] flex items-center justify-center px-4">
      <div className="bg-white rounded-2xl border border-[#e7dfc9] p-8 max-w-md shadow-sm text-center"
           data-testid="unsubscribe-page">
        {status === "ok" && <CheckCircle2 className="mx-auto text-[#2f4a3a]" size={40} />}
        {status === "error" && <XCircle className="mx-auto text-[#7a2a2a]" size={40} />}
        <h1 className="font-display text-2xl mt-4 mb-2 text-[#1f2a22]">
          {status === "ok" ? "You're unsubscribed" : status === "working" ? "Working…" : "Something went wrong"}
        </h1>
        <p className="text-sm text-[#3a3a3a]">{message}</p>
        <p className="mt-4 text-xs text-[#8a6a3c]">
          Transactional emails (appointment reminders, receipts, portal invitations) will continue.
        </p>
      </div>
    </div>
  );
}
