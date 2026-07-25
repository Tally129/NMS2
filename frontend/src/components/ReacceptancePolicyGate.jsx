import React from "react";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "./ui/dialog";
import { Button } from "./ui/button";
import { Link } from "react-router-dom";

/**
 * Post-login gate that pops a modal when the current user has one or more
 * policies flagged as `requires_reacceptance` and their most recent acceptance
 * is for an older version. Users can view the changes, read the full policy,
 * or accept in place. The portal itself remains rendered underneath but the
 * modal blocks interaction until every pending policy is accepted.
 */
export default function ReacceptancePolicyGate() {
  const { user } = useAuth();
  const [pending, setPending] = React.useState([]);
  const [i, setI] = React.useState(0);
  const [busy, setBusy] = React.useState(false);
  const [showText, setShowText] = React.useState(false);

  const load = React.useCallback(async () => {
    if (!user) { setPending([]); return; }
    try {
      const r = await api.get("/legal/pending-reacceptance");
      const arr = Array.isArray(r.data) ? r.data : [];
      setPending(arr);
      setI(0);
    } catch {
      setPending([]);
    }
  }, [user]);

  React.useEffect(() => { load(); }, [load]);

  const current = pending[i];
  if (!current) return null;

  const accept = async () => {
    setBusy(true);
    try {
      await api.post("/legal/acceptances", {
        policy_slug: current.slug,
        policy_version: current.current_version,
        method: "reacceptance_modal",
      });
      const next = i + 1;
      if (next >= pending.length) {
        setPending([]);
        setI(0);
      } else {
        setI(next);
        setShowText(false);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={true}>
      <DialogContent className="bg-white max-w-2xl" data-testid="reacceptance-modal">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">We've updated our policies</DialogTitle>
          <DialogDescription>
            To continue using the Patient Portal, please review and accept the updated{" "}
            <b>{current.title}</b> (v{current.current_version}).
          </DialogDescription>
        </DialogHeader>
        {showText ? (
          <div
            className="prose prose-sm max-w-none border border-[#e7dfc9] rounded-lg p-4 max-h-72 overflow-y-auto"
            dangerouslySetInnerHTML={{ __html: current.content_html || "" }}
            data-testid="reacceptance-body"
          />
        ) : (
          <p className="text-sm text-[#3a3a3a]">
            You can view the full document below, open it in the Legal &amp; Policies section, or accept the current version to continue.
          </p>
        )}
        <div className="flex flex-wrap gap-2 justify-end mt-4">
          {!showText && (
            <Button variant="outline" onClick={() => setShowText(true)}
                    className="rounded-full border-[#8a6a3c] text-[#8a6a3c]"
                    data-testid="reacceptance-view">
              View changes
            </Button>
          )}
          <Link to={`/legal/${current.slug}`} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center px-4 h-10 rounded-full border border-[#c19a4b] text-[#8a6a3c] text-sm"
                data-testid="reacceptance-read">
            Read full policy
          </Link>
          <Button onClick={accept} disabled={busy}
                  className="rounded-full bg-[#2f6a4a] hover:bg-[#265739] text-white"
                  data-testid="reacceptance-accept">
            {busy ? "Saving…" : "Accept & continue"}
          </Button>
        </div>
        {pending.length > 1 && (
          <div className="mt-3 text-[11px] text-slate-500 text-center">
            {i + 1} of {pending.length} pending updates
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
