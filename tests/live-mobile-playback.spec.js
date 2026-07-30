const { test, expect } = require("@playwright/test");

const EXPECTED_BUILD_LABEL = "mobile player fitted 20260730";

test("production mobile player fits viewport and tap starts real Twitch playback", async ({ page }) => {
  await waitForDeployedBuild(page);

  const frame = page.locator("#player-frame");
  const segment = page.locator(".vod-card:not([hidden]) .segment-button").first();
  const sdkIframe = page.locator(".player-embed-slot__sdk-iframe");

  await expect(segment).toBeVisible();
  await expect(segment).toBeEnabled({ timeout: 60_000 });
  await expect(frame).toHaveAttribute("data-player-mode", "interactive", { timeout: 60_000 });
  await expect(sdkIframe).toBeVisible({ timeout: 60_000 });

  const frameBox = await frame.boundingBox();
  const playerBox = await sdkIframe.boundingBox();
  expect(frameBox).not.toBeNull();
  expect(playerBox).not.toBeNull();

  const viewport = page.viewportSize();
  expect(viewport).not.toBeNull();
  expect(frameBox.x).toBeGreaterThanOrEqual(-0.5);
  expect(frameBox.x + frameBox.width).toBeLessThanOrEqual(viewport.width + 0.5);
  expect(playerBox.x).toBeGreaterThanOrEqual(frameBox.x - 1);
  expect(playerBox.x + playerBox.width).toBeLessThanOrEqual(frameBox.x + frameBox.width + 1);
  expect(Math.abs(playerBox.width - frameBox.width)).toBeLessThanOrEqual(2.1);
  expect(Math.abs(playerBox.height - frameBox.height)).toBeLessThanOrEqual(2.1);

  const pageHasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1
  );
  expect(pageHasHorizontalOverflow).toBe(false);

  await segment.scrollIntoViewIfNeeded();
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
  let attempt = 0;

  while (Date.now() < deadline) {
    attempt += 1;
    const response = await page.goto(`/?deploy_check=${Date.now()}`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });

    const label = page.locator("#build-label-mobile");
    let expectedBuildReached = false;
    try {
      await expect(label).toHaveText(EXPECTED_BUILD_LABEL, { timeout: 15_000 });
      expectedBuildReached = true;
    } catch (error) {
      expectedBuildReached = false;
    }

    try {
      lastLabel = String(await label.textContent() || "").trim();
    } catch (error) {
      lastLabel = "";
    }

    console.log(
      `[deploy-wait] attempt=${attempt} status=${response?.status() ?? "none"} label=${JSON.stringify(lastLabel)} url=${page.url()}`
    );

    if (expectedBuildReached) {
      console.log(`[deploy-wait] expected build is live after ${attempt} attempt(s)`);
      return;
    }
    await page.waitForTimeout(10_000);
  }

  throw new Error(
    `Render did not deploy the expected build label. Expected ${EXPECTED_BUILD_LABEL}, received ${lastLabel || "<empty>"}`
  );
}
