const { test, expect } = require("@playwright/test");

if (process.env.PLAYWRIGHT_CHANNEL) {
  test.use({ channel: process.env.PLAYWRIGHT_CHANNEL });
}

test("mobile starts Twitch playback with sound from one highlight click", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "mobile playback regression only");
  test.slow();

  await page.goto("/");
  await page.locator("#player-frame").scrollIntoViewIfNeeded();

  const button = page.locator(".vod-card:not([hidden]) .segment-button").nth(1);
  await expect(button).toBeVisible();
  await button.click();

  await expect
    .poll(async () => getPlaybackState(page), { timeout: 30_000 })
    .toMatchObject({ paused: false, muted: false });

  const startedAt = (await getPlaybackState(page)).currentTime;
  await expect
    .poll(async () => (await getPlaybackState(page)).currentTime, { timeout: 15_000 })
    .toBeGreaterThan(startedAt + 1);
});

async function getPlaybackState(page) {
  const frame = page.frames().find((candidate) => /player\.twitch\.tv/.test(candidate.url()));
  if (!frame) {
    return { paused: null, muted: null, currentTime: -1 };
  }

  try {
    return await frame.evaluate(() => {
      const video = document.querySelector("video");
      return video
        ? {
            paused: video.paused,
            muted: video.muted,
            currentTime: Number(video.currentTime || 0),
          }
        : { paused: null, muted: null, currentTime: -1 };
    });
  } catch {
    return { paused: null, muted: null, currentTime: -1 };
  }
}
