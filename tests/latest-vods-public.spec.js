const { test, expect } = require("@playwright/test");

test.describe("legacy UI reference checks", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("retired timestamp and transcript interfaces stay absent", async ({ page }) => {
    await expect(page.locator("#vod-mode-timestamps")).toHaveCount(0);
    await expect(page.locator("#timestamp-list")).toHaveCount(0);
    await expect(page.locator("#transcript-panel")).toHaveCount(0);
    await expect(page.locator("[id^='transcript-']")).toHaveCount(0);
  });

  test("header subtitle copy is fixed", async ({ page }) => {
    await expect(page.locator(".brand-header-support__subtitle")).toHaveText(
      "直近2ヶ月の配信の見どころをすぐ再生［非公式ファンサイト］"
    );
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
