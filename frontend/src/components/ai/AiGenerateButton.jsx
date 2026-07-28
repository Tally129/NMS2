import React from "react";
import { Loader2, Sparkles } from "lucide-react";
import { Button } from "../ui/button";

/**
 * Consistent trigger for any AI action across the application.
 *
 * The parent component owns the async call and passes `loading`. When
 * `loading` is true the button shows a spinner + "Generating AI draft…"
 * label and is disabled. Otherwise it renders `label` (default "Draft with
 * AI") next to a Sparkles icon.
 *
 * The intent is to give every AI entry point (Lab Review, Marketing, and
 * every future feature) exactly the same feel — one tiny primitive to
 * reuse instead of a bespoke button in each page.
 */
export function AiGenerateButton({
  onClick,
  loading = false,
  disabled = false,
  label = "Draft with AI",
  loadingLabel = "Generating AI draft…",
  size = "sm",
  className = "",
  testid = "ai-generate-button",
  variant = "outline",
}) {
  return (
    <Button
      type="button"
      onClick={onClick}
      disabled={loading || disabled}
      size={size}
      variant={variant}
      data-testid={testid}
      className={`rounded-full border-[#d5c5f0] text-[#5a3a8a] bg-[#faf7ff] hover:bg-[#f2ecf9] ${className}`}
    >
      {loading ? (
        <>
          <Loader2 size={14} className="mr-1.5 animate-spin" />
          {loadingLabel}
        </>
      ) : (
        <>
          <Sparkles size={14} className="mr-1.5" />
          {label}
        </>
      )}
    </Button>
  );
}

export default AiGenerateButton;
