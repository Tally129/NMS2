import React from "react";
import { Loader2, Sparkles } from "lucide-react";

/**
 * Full-panel loading state for AI operations.
 *
 * Feature-agnostic. Use inside any modal, side panel, or card body that
 * needs to communicate "AI is generating". Renders inline (not fixed) so
 * the parent's dimensions are preserved.
 */
export function AiLoadingOverlay({
  message = "Generating AI draft…",
  hint = "This usually takes 5–20 seconds.",
  testid = "ai-loading-overlay",
}) {
  return (
    <div
      data-testid={testid}
      className="flex flex-col items-center justify-center gap-3 py-10 text-center text-slate-600"
    >
      <div className="relative">
        <Sparkles size={26} className="text-[#5a3a8a]" />
        <Loader2 size={16} className="absolute -bottom-1 -right-1 animate-spin text-[#5a3a8a]" />
      </div>
      <div>
        <div className="font-medium text-[#5a3a8a]">{message}</div>
        {hint ? (
          <div className="text-xs text-slate-500 mt-1">{hint}</div>
        ) : null}
      </div>
    </div>
  );
}

export default AiLoadingOverlay;
