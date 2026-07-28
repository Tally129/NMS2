import React from "react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "../ui/dialog";
import { Button } from "../ui/button";
import { Copy, RefreshCw, X, Pencil, ChevronsRight } from "lucide-react";
import { AiLoadingOverlay } from "./AiLoadingOverlay";
import { AiDisclaimerBanner } from "./AiDisclaimerBanner";
import { AiDraftBadge } from "./AiDraftBadge";

/**
 * Generic AI-draft modal.
 *
 * Wraps every AI feature (Lab Review, Marketing, and future ones — SOAP,
 * treatment plans, referral letters, insurance appeals, etc.) with an
 * identical shell so users see the same layout everywhere.
 *
 * The caller is responsible for:
 *   - the async generate call (owns `loading`, `error`, `data`)
 *   - the actual section rendering (`renderSections`)
 *   - deciding which action buttons to show (`primaryAction`)
 *
 * The modal never mutates the parent's data. Nothing persists here.
 */
export function AiDraftModal({
  open,
  onOpenChange,
  title,
  subtitle,
  loading,
  data,
  error,
  disclaimerRole = "provider",      // "provider" | "human"
  onRegenerate,
  onCopy,
  onEdit,                            // optional Edit-in-place callback
  primaryAction,                     // { label, onClick, disabled, testid }
  renderSections,                    // (data) => ReactNode
  testid = "ai-draft-modal",
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="bg-white max-w-2xl max-h-[85vh] overflow-y-auto"
        data-testid={testid}
      >
        <DialogHeader>
          <DialogTitle className="font-display text-2xl flex items-center gap-2">
            {title}
            <AiDraftBadge compact />
          </DialogTitle>
          {subtitle ? (
            <DialogDescription>{subtitle}</DialogDescription>
          ) : null}
        </DialogHeader>

        <AiDisclaimerBanner role={disclaimerRole} className="mb-3" />

        {loading ? (
          <AiLoadingOverlay />
        ) : error ? (
          <div className="rounded-lg border border-[#f0c8c8] bg-[#fdecec] p-4 text-sm text-[#7a2a2a]"
               data-testid="ai-draft-error">
            {error}
          </div>
        ) : data ? (
          <div className="space-y-3">{renderSections?.(data)}</div>
        ) : (
          <div className="text-sm text-slate-500 py-6 text-center">
            No draft yet.
          </div>
        )}

        <div className="mt-4 flex flex-wrap gap-2 justify-end border-t border-[#e2ebe4] pt-3">
          {onCopy ? (
            <Button
              variant="outline" size="sm"
              onClick={onCopy}
              disabled={loading || !data}
              className="rounded-full border-[#d9e2db]"
              data-testid="ai-draft-copy"
            >
              <Copy size={13} className="mr-1" /> Copy
            </Button>
          ) : null}
          {onEdit ? (
            <Button
              variant="outline" size="sm"
              onClick={onEdit}
              disabled={loading || !data}
              className="rounded-full border-[#d9e2db]"
              data-testid="ai-draft-edit"
            >
              <Pencil size={13} className="mr-1" /> Edit
            </Button>
          ) : null}
          {onRegenerate ? (
            <Button
              variant="outline" size="sm"
              onClick={onRegenerate}
              disabled={loading}
              className="rounded-full border-[#d9e2db]"
              data-testid="ai-draft-regenerate"
            >
              <RefreshCw size={13} className="mr-1" /> Regenerate
            </Button>
          ) : null}
          <Button
            variant="outline" size="sm"
            onClick={() => onOpenChange(false)}
            className="rounded-full border-[#d9e2db]"
            data-testid="ai-draft-close"
          >
            <X size={13} className="mr-1" /> Close
          </Button>
          {primaryAction ? (
            <Button
              size="sm"
              onClick={primaryAction.onClick}
              disabled={primaryAction.disabled || loading || !data}
              className="rounded-full bg-[#5a3a8a] hover:bg-[#4a2a7a] text-white"
              data-testid={primaryAction.testid || "ai-draft-insert"}
            >
              <ChevronsRight size={13} className="mr-1" />
              {primaryAction.label}
            </Button>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Small helper renderer for a section card — used by consumers to keep the
 * shell consistent (title, muted body). Kept co-located because it is only
 * useful inside `AiDraftModal`.
 */
export function AiSectionCard({ title, children, testid, empty = "—" }) {
  const hasContent =
    children !== null && children !== undefined && children !== false;
  return (
    <section
      className="rounded-lg border border-[#e2ebe4] bg-[#f7fbf8] p-3"
      data-testid={testid}
    >
      <div className="eyebrow text-[#3d6b52] mb-1 text-[11px] uppercase tracking-wider font-medium">
        {title}
      </div>
      <div className="text-sm text-slate-700 whitespace-pre-wrap">
        {hasContent ? children : <span className="text-slate-400">{empty}</span>}
      </div>
    </section>
  );
}

export default AiDraftModal;
