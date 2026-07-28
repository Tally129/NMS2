import React from "react";
import { AlertTriangle } from "lucide-react";

/**
 * Inline banner shown at the top of every AI-generated panel to remind the
 * user that the content is a draft. Also acts as the "AI Draft" disclosure
 * inside modals — companion to the compact `AiDraftBadge` used on rows.
 *
 * Text is fixed on purpose. Do not localise per-feature; consistency is a
 * safety feature.
 */
export function AiDisclaimerBanner({
  role = "provider",              // "provider" | "human"
  className = "",
  testid = "ai-disclaimer-banner",
}) {
  const message =
    role === "provider"
      ? "AI-generated draft. Provider review and clinical judgment are required."
      : "AI-generated draft. Human review is required before use.";
  return (
    <div
      data-testid={testid}
      className={`flex items-start gap-2 rounded-lg border border-[#f0dfa6] bg-[#fdf6db] px-3 py-2 text-xs text-[#8a6a3c] ${className}`}
    >
      <AlertTriangle size={14} className="mt-[1px] flex-shrink-0" />
      <span>{message}</span>
    </div>
  );
}

export default AiDisclaimerBanner;
