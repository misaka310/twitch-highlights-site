const path = require("path");
const { test, expect } = require("@playwright/test");

const instanceConfig = require(path.join(__dirname, "..", "config", "site.json"));

test("configured site identity is applied at runtime", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(instanceConfig.site.name);
  await expect(page.locator("#site-name")).toHaveText(instanceConfig.site.name);
  await expect(page.locator("#site-description")).toHaveText(instanceConfig.site.description);
});

test("highlight data loads and remains interactive", async ({ page }) => {
  await page.goto("/");
  const firstSegment = page.locator(".vod-card:not([hidden]) .segment-button").first();
  await expect(firstSegment).toBeVisible({ timeout: 15_000 });

  const vodId = await firstSegment.getAttribute("data-vod-id");
  const startSec = await firstSegment.getAttribute("data-start-sec");
  expect(vodId).toBeTruthy();
  expect(startSec).toBeTruthy();

  await firstSegment.click();
  await expect(page.locator("#player-frame")).toHaveAttribute("data-current-vod-id", String(vodId));
  await expect(page.locator("#player-frame")).toHaveAttribute("data-current-start-sec", String(startSec));
});

test("runtime config endpoint exposes the selected instance", async ({ request }) => {
  const response = await request.get("/site-config.json");
  expect(response.ok()).toBeTruthy();
  const config = await response.json();
  expect(config.site.name).toBe(instanceConfig.site.name);
  expect(config.twitch.channel_login).toBe(instanceConfig.twitch.channel_login);
});
