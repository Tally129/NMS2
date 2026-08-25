/*
 * First-party Marketing OS attribution capture.
 *
 * IMPORTANT:
 * - Marketing attribution must remain non-PHI.
 * - Never place patient/contact/form/clinical values here.
 * - This module captures campaign-navigation metadata only.
 * - MARKETING_INGEST_KEY must never be exposed to the browser.
 */

const STORAGE_KEY = "nms_marketing_attribution_v1";
const SESSION_KEY = "nms_marketing_session_v1";

const ALLOWED_QUERY_PARAMS = Object.freeze({
  utm_source: "source",
  utm_medium: "medium",
  utm_campaign: "campaign",
  utm_content: "content",
  utm_term: "term",
});

const CLICK_ID_PARAMS = Object.freeze([
  "gclid",
  "gbraid",
  "wbraid",
  "fbclid",
  "msclkid",
  "ttclid",
]);

const clean = (value, maxLength = 255) => {
  if (typeof value !== "string") return null;

  const trimmed = value.trim();

  if (!trimmed) return null;

  return trimmed.slice(0, maxLength);
};

const makeSessionId = () => {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }

  return [
    Date.now().toString(36),
    Math.random().toString(36).slice(2),
    Math.random().toString(36).slice(2),
  ].join("-");
};

export const getMarketingSessionId = () => {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    let sessionId = window.sessionStorage.getItem(
      SESSION_KEY
    );

    if (!sessionId) {
      sessionId = makeSessionId();

      window.sessionStorage.setItem(
        SESSION_KEY,
        sessionId
      );
    }

    return sessionId;
  } catch {
    return null;
  }
};

export const readStoredAttribution = () => {
  if (typeof window === "undefined") {
    return {};
  }

  try {
    const raw = window.sessionStorage.getItem(
      STORAGE_KEY
    );

    if (!raw) {
      return {};
    }

    const parsed = JSON.parse(raw);

    if (
      !parsed ||
      typeof parsed !== "object" ||
      Array.isArray(parsed)
    ) {
      return {};
    }

    return parsed;
  } catch {
    return {};
  }
};

export const captureMarketingAttribution = () => {
  if (typeof window === "undefined") {
    return {};
  }

  try {
    const params = new URLSearchParams(
      window.location.search || ""
    );

    const captured = {};

    Object.entries(ALLOWED_QUERY_PARAMS).forEach(
      ([queryName, fieldName]) => {
        const value = clean(
          params.get(queryName),
          fieldName === "source" ||
            fieldName === "medium"
            ? 128
            : 255
        );

        if (value) {
          captured[fieldName] = value;
        }
      }
    );

    for (const clickParam of CLICK_ID_PARAMS) {
      const value = clean(
        params.get(clickParam),
        255
      );

      if (value) {
        captured.external_click_id = value;
        captured.click_id_type = clickParam;
        break;
      }
    }

    /*
     * Only overwrite stored attribution when the current
     * navigation contains an actual marketing touch.
     */
    if (Object.keys(captured).length > 0) {
      window.sessionStorage.setItem(
        STORAGE_KEY,
        JSON.stringify(captured)
      );

      return captured;
    }

    return readStoredAttribution();
  } catch {
    return {};
  }
};

export const getMarketingAttribution = () => {
  return {
    session_id: getMarketingSessionId(),
    ...readStoredAttribution(),
  };
};
