const { test, expect } = require("@playwright/test");

const EXPECTED_BUILD_LABEL = "mobile playback verified 20260730";

test("production mobile tap starts real Twitch playback and advances time", async ({ page }) => {
  await waitForDeployedBuild(page);

  const frame = page.locator("#player-frame");
  const segment = page.locator(".vod-card:not([hidden]) .segment-button").first();
  const sdkIframe = page.locator(".player-embed-slot__sdk-iframe");

  await expect(segment).toBeVisible();
  await expect(segment).toBeEnabled({ timeout: 60_000 });
  await expect(frame).toHaveAttribute("data-player-mode", "interactive", { timeout: 60_000 });
  await expect(sdkIframe).toBeVisible({ timeout: 60_000 });

  const playerBox = await sdkIframe.boundingBox();
  expect(playerBox).not.toBeNull();
  expect(playerBox.width).toBeGreaterThanOrEqual(400);
  expect(playerBox.height).toBeGreaterThanOrEqual(300);

  const pageHasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1
  );
  expect(pageHasHorizontalOverflow).toBe(false);

  const segmentBox = await segment.boundingBox();
  expect(segmentBox).not.toBeNull();
  await page.touchscreen.tap(
    segmentBox.x + segmentBox.width / 2,
    segmentBox.y + segmentBox.height / 2
  );

  await expect(frame).toHaveAttribute("data-player-status", "playing", { timeout: 30_000 });
  await expect(frame).not.toHaveAttribute("data-player-status", /blocked|error/);

  const playingAt = Number(await frame.getAttribute("data-current-start-sec"));
  expect(Number.isFinite(playingAt)).toBe(true);

  await expect
    .poll(
      async () => Number(await frame.getAttribute("data-current-start-sec")),
      {
        message: "Twitch playback time should advance after the real PLAYING event",
        timeout: 20_000,
        intervals: [500, 1000, 1000, 2000],
      }
    )
    .toBeGreaterThan(playingAt + 1);
});

async function waitForDeployedBuild(page) {
  const deadline = Date.now() + 10 * 60_000;
  let lastLabel = "";

  while (Date.now() < deadline) {
    await page.goto(`/?deploy_check=${Date.now()}`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });

    const label = page.locator("#build-label-mobile");
    try {
      lastLabel = String(await label.textContent({ timeout: 15_000 }) || "").trim();
    } catch (error) {
      lastLabel = "";
    }

    if (lastLabel === EXPECTED_BUILD_LABEL) {
      return;
    }
    await page.waitForTimeout(10_000);
  }

  throw new Error(
    `Render did not deploy the expected build label. Expected ${EXPECTED_BUILD_LABEL}, received ${lastLabel || "<empty>"}`
  );
}
