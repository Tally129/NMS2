/**
 * Safely extract a list from supported API response envelopes.
 *
 * Supported:
 *   [...]
 *   { items: [...] }
 *   { results: [...] }
 *   { data: [...] }
 *   { clients: [...] }
 *   { appointments: [...] }
 *
 * Unknown values return an empty array instead of crashing the UI.
 */
export function normalizeArray(value, preferredKeys = []) {
  if (Array.isArray(value)) {
    return value;
  }

  if (!value || typeof value !== "object") {
    return [];
  }

  const keys = [
    ...preferredKeys,
    "items",
    "results",
    "data",
    "rows",
    "records",
  ];

  for (const key of keys) {
    if (Array.isArray(value[key])) {
      return value[key];
    }
  }

  return [];
}

/**
 * Development guard that warns when an API list response has an
 * unexpected shape while preventing a production page crash.
 */
export function normalizeApiList(
  value,
  {
    endpoint = "unknown",
    preferredKeys = [],
  } = {}
) {
  const rows = normalizeArray(value, preferredKeys);

  if (
    process.env.NODE_ENV !== "production" &&
    !Array.isArray(value) &&
    rows.length === 0 &&
    value != null
  ) {
    console.warn(
      `[API list warning] Unexpected response shape from ${endpoint}`,
      value
    );
  }

  return rows;
}
