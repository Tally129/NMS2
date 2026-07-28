/**
 * AI error-code → toast helper.
 *
 * Bedrock endpoints raise safe category tokens (`bedrock_unavailable`,
 * `bedrock_misconfigured`, `request_timeout`, `invalid_model_response`,
 * `ai_disabled`, `model_access_denied`, etc.). This helper translates them
 * into human-readable toast copy without ever exposing raw AWS internals.
 *
 * Usage:
 *   import { showAiErrorToast } from "../ai/aiErrors";
 *   catch (e) { showAiErrorToast(e, toast); }
 */
const CODE_MAP = {
  ai_disabled: {
    title: "AI is turned off",
    description: "An administrator has disabled AI features. Try again later.",
  },
  bedrock_disabled: {
    title: "AI is turned off",
    description: "An administrator has disabled AI features. Try again later.",
  },
  bedrock_misconfigured: {
    title: "AI is not configured yet",
    description: "The Bedrock model is not configured on the server. Ask an administrator to complete AWS setup.",
  },
  bedrock_unavailable: {
    title: "AI is temporarily unavailable",
    description: "Amazon Bedrock is not reachable right now. Please try again in a moment.",
  },
  model_access_denied: {
    title: "AI model access is not approved",
    description: "The server's AWS role has not been granted access to this Bedrock model. Please contact an administrator.",
  },
  request_timeout: {
    title: "AI request timed out",
    description: "The model took too long to respond. Try again with a shorter draft or retry.",
  },
  invalid_model_response: {
    title: "AI returned an invalid draft",
    description: "The model's response could not be parsed. Please regenerate.",
  },
  output_validation_failed: {
    title: "AI response was rejected",
    description: "The generated draft did not match the expected format. Please regenerate.",
  },
  unauthorized: {
    title: "You do not have access to this AI feature",
    description: "Ask an administrator to grant permission.",
  },
  ai_unavailable: {
    title: "AI is temporarily unavailable",
    description: "Please try again in a moment.",
  },
};

const DEFAULT_MSG = {
  title: "AI request failed",
  description: "Please try again in a moment.",
};

export function pickAiErrorCode(error) {
  const d = error?.response?.data?.detail;
  if (d && typeof d === "object" && typeof d.code === "string") return d.code;
  if (typeof d === "string") return d;
  return null;
}

export function showAiErrorToast(error, toastFn) {
  const code = pickAiErrorCode(error);
  const msg = (code && CODE_MAP[code]) || DEFAULT_MSG;
  toastFn({ title: msg.title, description: msg.description });
  return code;
}
