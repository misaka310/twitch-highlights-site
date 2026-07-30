\
const { test, expect } = require("@playwright/test");

test("mobile tap keeps playback on the synchronous iframe path", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "Mobile playback path only");

  await page.route("https://player.twitch.tv/js/embed/v1.js", (route) => route.abort());
  await page.goto("/");

  const frame = page.locator("#player-frame");
  const iframe = page.locator("#twitch-player iframe");
  const segment = page.locator(".vod-card:not([hidden]) .segment-button").first();

  await expect(segment).toBeVisible();
  await expect(iframe).toHaveCount(1);
  await expect(iframe).toHaveAttribute("src", /autoplay=false/);
  await expect(frame).toHaveAttribute("data-player-mode", "iframe");

  const vodId = await segment.getAttribute("data-vod-id");
  const startSec = await segment.getAttribute("data-start-sec");
  const box = await segment.boundingBox();
  expect(box).not.toBeNull();
  await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);

  await expect(frame).toHaveAttribute("data-current-vod-id", String(vodId));
  await expect(frame).toHaveAttribute("data-current-start-sec", String(startSec));
  await expect(frame).toHaveAttribute("data-player-mode", "iframe");
  await expect(iframe).toHaveAttribute("src", /autoplay=true/);
  await expect(iframe).toHaveAttribute("src", /muted=false/);
  await expect(iframe).toHaveAttribute("src", new RegExp(`video=${vodId}`));
  expect(await page.locator('script[src="https://player.twitch.tv/js/embed/v1.js"]').count()).toBe(0);
});
