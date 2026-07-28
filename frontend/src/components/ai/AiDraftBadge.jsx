import React from "react";
import { Sparkles } from "lucide-react";
import {
  Tooltip, TooltipContent, TooltipProvider, TooltipTrigger,
} from "../ui/tooltip";

/**
 * Uniform badge for anything that started life as an AI draft.
 * Same visual treatment across Lab Review, Marketing, and every future AI
 * feature so users learn to recognise "this needs my review" at a glance.
 */
export function AiDraftBadge({ compact = false, className = "" }) {
  const size = compact ? 10 : 12;
  const padding = compact ? "px-1.5 py-0.5" : "px-2 py-0.5";
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            data-testid="ai-draft-badge"
            className={`inline-flex items-center gap-1 rounded-full ${padding} bg-[#f2ecf9] text-[#5a3a8a] text-[10px] uppercase tracking-wider font-medium border border-[#e0d3f0] ${className}`}
          >
            <Sparkles size={size} />
            AI Draft
          </span>
        </TooltipTrigger>
        <TooltipContent side="top">
          <p className="text-xs max-w-[220px]">
            Generated using Amazon Bedrock. Requires human review before use.
          </p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export default AiDraftBadge;
