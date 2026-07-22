const { test, expect } = require("@playwright/test");

test("public highlights load and remain clickable", async ({ page }) => {
  await page.goto("/");

  const firstSegment = page.locator(".vod-card:not([hidden]) .segment-button").first();
  await expect(firstSegment).toBeVisible();

  const vodId = await firstSegment.getAttribute("data-vod-id");
  const startSec = await firstSegment.getAttribute("data-start-sec");
  expect(vodId).toBeTruthy();
  expect(startSec).toBeTruthy();

  await firstSegment.click();
  await expect(page.locator("#player-frame")).toHaveAttribute("data-current-vod-id", String(vodId));
  await expect(page.locator("#player-frame")).toHaveAttribute("data-current-start-sec", String(startSec));
});
