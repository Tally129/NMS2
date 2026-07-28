import { pickAiErrorCode, showAiErrorToast } from "./aiErrors";

/**
 * Unit tests for the AI error → toast translator.
 * The translator is shared by every AI feature (Lab Review, Marketing, and
 * any future feature) so a wrong mapping surfaces here instead of in the
 * feature-specific pages.
 */

describe("pickAiErrorCode", () => {
  test("extracts safe code from detail object", () => {
    const e = { response: { data: { detail: { code: "bedrock_misconfigured" } } } };
    expect(pickAiErrorCode(e)).toBe("bedrock_misconfigured");
  });

  test("accepts string detail directly", () => {
    const e = { response: { data: { detail: "request_timeout" } } };
    expect(pickAiErrorCode(e)).toBe("request_timeout");
  });

  test("returns null when nothing matches", () => {
    expect(pickAiErrorCode({})).toBeNull();
    expect(pickAiErrorCode(null)).toBeNull();
    expect(pickAiErrorCode({ response: { data: { detail: { message: "hi" } } } })).toBeNull();
  });
});

describe("showAiErrorToast", () => {
  test("maps every known Bedrock error code to a user-safe copy", () => {
    const cases = [
      "ai_disabled",
      "bedrock_misconfigured",
      "bedrock_unavailable",
      "model_access_denied",
      "request_timeout",
      "invalid_model_response",
      "output_validation_failed",
      "unauthorized",
    ];
    for (const code of cases) {
      const toast = jest.fn();
      const err = { response: { data: { detail: { code } } } };
      const returned = showAiErrorToast(err, toast);
      expect(returned).toBe(code);
      expect(toast).toHaveBeenCalledTimes(1);
      const call = toast.mock.calls[0][0];
      expect(typeof call.title).toBe("string");
      expect(call.title.length).toBeGreaterThan(0);
      expect(typeof call.description).toBe("string");
      // Guardrail: our toast copy must not leak raw AWS / Bedrock names.
      expect(call.description.toLowerCase()).not.toMatch(/accessdenied|throttlingexception|boto3/);
    }
  });

  test("falls back to a generic toast for unknown codes", () => {
    const toast = jest.fn();
    const err = { response: { data: { detail: { code: "wat" } } } };
    showAiErrorToast(err, toast);
    expect(toast).toHaveBeenCalledTimes(1);
    expect(toast.mock.calls[0][0].title).toBe("AI request failed");
  });

  test("no detail still produces a safe toast", () => {
    const toast = jest.fn();
    showAiErrorToast({}, toast);
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({
      title: "AI request failed",
    }));
  });
});
