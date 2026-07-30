const { test, expect } = require("@playwright/test");

const AUTOPLAY_WARNING = /Autoplay disabled|minimum requirements for autoplay|style visibility|playback[_ ]blocked/i;

test("626px responsive view portals the real Twitch player and plays another VOD", async ({ page }, testInfo) => {
  test.slow();
  test.skip(testInfo.project.name !== "desktop", "626px real Twitch check uses desktop Chromium");

  await page.setViewportSize({ width: 626, height: 935 });
  const consoleMessages = [];
  page.on("console", (message) => consoleMessages.push(message.text()));

  await page.goto("/");
  const frame = page.locator("#player-frame");
  const player = page.locator("#twitch-player");

  await expect
    .poll(async () => player.evaluate((element) => element.parentElement === document.body), { timeout: 30_000 })
    .toBe(true);
  await expect(frame).toHaveAttribute("data-player-portal", "body");
  await expect(frame).toHaveAttribute("data-player-mode", "interactive", { timeout: 30_000 });
  await expect
    .poll(async () => frame.getAttribute("data-player-status"), { timeout: 30_000 })
    .toMatch(/ready|playing/);

  const tabs = page.locator(".vod-tab, .mobile-vod-tab");
  const visibleTabs = [];
  for (let index = 0; index < (await tabs.count()); index += 1) {
    if (await tabs.nth(index).isVisible()) {
      visibleTabs.push(tabs.nth(index));
    }
  }
  expect(visibleTabs.length).toBeGreaterThan(1);
  await visibleTabs[1].click();

  const target = page.locator(".vod-card:not([hidden]) .segment-button").first();
  await expect(target).toBeVisible();
  const targetVodId = await target.getAttribute("data-vod-id");
  const targetStartSec = Number(await target.getAttribute("data-start-sec"));

  consoleMessages.length = 0;
  await target.click();

  await expect(frame).toHaveAttribute("data-current-vod-id", targetVodId, { timeout: 30_000 });
  await expect(frame).toHaveAttribute("data-player-mode", "interactive");
  await expect(player).toHaveClass(/player-embed--portal/);

  await expect
    .poll(async () => readActiveVideo(page), {
      message: "Real Twitch video should play after a cross-VOD click at 626px",
      timeout: 45_000,
      intervals: [500, 1000, 1000, 2000],
    })
    .toMatchObject({ paused: false });

  await expect
    .poll(async () => (await readActiveVideo(page))?.currentTime ?? -1, {
      timeout: 45_000,
      intervals: [500, 1000, 1000, 2000],
    })
    .toBeGreaterThan(targetStartSec - 15);

  const baseline = (await readActiveVideo(page))?.currentTime;
  expect(Number.isFinite(baseline)).toBe(true);
  await expect
    .poll(async () => (await readActiveVideo(page))?.currentTime ?? -1, {
      timeout: 20_000,
      intervals: [500, 1000, 1000, 2000],
    })
    .toBeGreaterThan(baseline + 1);

  await page.waitForTimeout(1500);
  expect(consoleMessages.filter((message) => AUTOPLAY_WARNING.test(message))).toEqual([]);
});

async function readActiveVideo(page) {
  let best = null;
  for (const childFrame of page.frames()) {
    try {
      const videos = childFrame.locator("video");
      for (let index = 0; index < (await videos.count()); index += 1) {
        const state = await videos.nth(index).evaluate((video) => ({
          paused: Boolean(video.paused),
          currentTime: Number(video.currentTime),
          muted: Boolean(video.muted),
        }));
        if (!Number.isFinite(state.currentTime)) {
          continue;
        }
        if (!best || (!state.paused && best.paused) || state.currentTime > best.currentTime) {
          best = state;
        }
      }
    } catch (error) {
      // Twitch may replace nested frames while changing videos.
    }
  }
  return best;
}
