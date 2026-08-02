const { test, expect } = require("@playwright/test");

test.beforeEach(async ({ page }) => {
  await page.route("https://player.twitch.tv/**", (route) => route.abort());
  await page.route("https://*.twitch.tv/**", (route) => route.abort());
});

test("generated public bundle serves the current React site", async ({ page }, testInfo) => {
  const response = await page.goto("/");
  expect(response?.ok()).toBeTruthy();
  await expect(page).toHaveTitle("dotitao moments");
  await expect(page.locator("header.site-header")).toBeVisible();
  await expect(page.locator("#player-frame")).toBeVisible();
  await expect(page.locator(".highlight-item")).toHaveCount(3);
  await expect(page.locator(".stream-summary")).toBeVisible();

  const bodySize = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    scrollHeight: document.documentElement.scrollHeight,
    clientHeight: document.documentElement.clientHeight,
  }));
  expect(bodySize.scrollWidth).toBeLessThanOrEqual(bodySize.clientWidth);
  if (testInfo.project.name === "desktop") {
    expect(bodySize.scrollHeight).toBeLessThanOrEqual(bodySize.clientHeight);
  }
});

test("generated public bundle exposes valid runtime assets", async ({ request }) => {
  const favicon = await request.get("/favicon.svg");
  expect(favicon.ok()).toBeTruthy();
  expect(favicon.headers()["content-type"]).toContain("image/svg+xml");

  const siteConfig = await request.get("/site-config.json");
  expect(siteConfig.ok()).toBeTruthy();
  expect(Object.keys(await siteConfig.json()).sort()).toEqual(["site", "twitch"]);

  const index = await request.get("/data/vod_index.json");
  expect(index.ok()).toBeTruthy();
  const payload = await index.json();
  expect(Array.isArray(payload.videos)).toBeTruthy();
  expect(payload.videos.length).toBeGreaterThan(0);
});
