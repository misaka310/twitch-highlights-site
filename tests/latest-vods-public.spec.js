const { test, expect } = require("@playwright/test");

test.describe("public latest VOD checks", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      try {
        localStorage.clear();
      } catch (_error) {
        // ignore
      }
    });
    await page.goto("/");
  });

  test("latest public VODs use the core data contract", async ({ page }) => {
    const results = await page.evaluate(async () => {
      const parse = (text) => JSON.parse(String(text || "").replace(/^\uFEFF/, ""));
      const indexResponse = await fetch("/data/vod_index.json");
      const indexPayload = parse(await indexResponse.text());
      const rows = Array.isArray(indexPayload?.videos) ? indexPayload.videos.slice(0, 3) : [];
      const details = [];
      for (const row of rows) {
        const response = await fetch(String(row.detail_path || ""));
        details.push(response.ok ? parse(await response.text()) : null);
      }
      return { rows, details };
    });

    expect(results.rows.length).toBeGreaterThan(0);
    const forbidden = [
      ["trans", "cript"].join(""),
      ["you", "tube"].join(""),
      ["time", "stamp"].join(""),
      ["head", "line"].join(""),
    ];

    results.rows.forEach((row) => {
      const keys = Object.keys(row).map((key) => key.toLowerCase());
      forbidden.forEach((marker) => expect(keys.some((key) => key.includes(marker))).toBeFalsy());
    });
    results.details.filter(Boolean).forEach((detail) => {
      const serialized = JSON.stringify(detail).toLowerCase();
      forbidden.forEach((marker) => expect(serialized.includes(`\"${marker}`)).toBeFalsy());
      expect(Array.isArray(detail.items)).toBeTruthy();
      expect(detail.activity_map).toBeTruthy();
    });
  });

  test("highlights remain playable", async ({ page }) => {
    const firstVisibleSegment = page.locator(".vod-card:not([hidden]) .segment-button").first();
    await expect(firstVisibleSegment).toBeVisible();

    const expectedVodId = String(await firstVisibleSegment.getAttribute("data-vod-id"));
    const expectedStartSec = String(await firstVisibleSegment.getAttribute("data-start-sec"));

    await firstVisibleSegment.click();
    await expect(page.locator("#player-frame")).toHaveAttribute("data-current-vod-id", expectedVodId);
    await expect(page.locator("#player-frame")).toHaveAttribute("data-current-start-sec", expectedStartSec);
  });
});
