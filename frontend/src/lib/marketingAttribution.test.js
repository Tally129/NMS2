import {
  captureMarketingAttribution,
  getMarketingAttribution,
  getMarketingSessionId,
  readStoredAttribution,
} from "./marketingAttribution";

describe("marketing attribution", () => {
  beforeEach(() => {
    window.sessionStorage.clear();

    window.history.replaceState(
      {},
      "",
      "/"
    );
  });

  test("captures allowed UTM values", () => {
    window.history.replaceState(
      {},
      "",
      "/request-appointment" +
        "?utm_source=google" +
        "&utm_medium=cpc" +
        "&utm_campaign=wellness"
    );

    const result =
      captureMarketingAttribution();

    expect(result).toMatchObject({
      source: "google",
      medium: "cpc",
      campaign: "wellness",
    });
  });

  test("captures supported click id", () => {
    window.history.replaceState(
      {},
      "",
      "/?gclid=test-click-id"
    );

    const result =
      captureMarketingAttribution();

    expect(result.external_click_id)
      .toBe("test-click-id");

    expect(result.click_id_type)
      .toBe("gclid");
  });

  test("does not capture arbitrary query parameters", () => {
    window.history.replaceState(
      {},
      "",
      "/?name=Jane" +
        "&email=jane@example.com" +
        "&diagnosis=test" +
        "&notes=private"
    );

    captureMarketingAttribution();

    const stored =
      readStoredAttribution();

    expect(stored).toEqual({});
  });

  test("preserves attribution across navigation", () => {
    window.history.replaceState(
      {},
      "",
      "/?utm_source=google&utm_medium=cpc"
    );

    captureMarketingAttribution();

    window.history.replaceState(
      {},
      "",
      "/request-appointment"
    );

    const result =
      captureMarketingAttribution();

    expect(result).toMatchObject({
      source: "google",
      medium: "cpc",
    });
  });

  test("creates stable session id", () => {
    const first =
      getMarketingSessionId();

    const second =
      getMarketingSessionId();

    expect(first).toBeTruthy();
    expect(second).toBe(first);
  });

  test("returns safe attribution envelope", () => {
    window.history.replaceState(
      {},
      "",
      "/?utm_source=instagram&utm_medium=social"
    );

    captureMarketingAttribution();

    const result =
      getMarketingAttribution();

    expect(result.source)
      .toBe("instagram");

    expect(result.medium)
      .toBe("social");

    expect(result.session_id)
      .toBeTruthy();

    expect(result.email)
      .toBeUndefined();

    expect(result.name)
      .toBeUndefined();

    expect(result.notes)
      .toBeUndefined();
  });
});
