const { test, expect } = require("@playwright/test");

const EXPECTED_BUILD_LABEL = "mobile original iframe restored 20260730";
const AUTOPLAY_WARNING = /Autoplay disabled|minimum requirements for autoplay|style visibility|playback[_ ]blocked/i;

test("production mobile segment tap starts the original Twitch iframe playback", async ({ page }) => {
  const consoleMessages = [];
  page.on("console", (message) => {
    consoleMessages.push(message.text());
  });

  await waitForDeployedBuild(page);

  const frame = page.locator("#player-frame");
  const segment = page.locator(".vod-card:not([hidden]) .segment-button").first();
  const iframe = page.locator(".player-embed-frame");

  await expect(segment).toBeVisible();
  await expect(segment).toBeEnabled({ timeout: 60_000 });
  await expect(iframe).toBeVisible({ timeout: 60_000 });
  await expect(page.locator("#mobile-player-fit-styles")).toHaveCount(1);
  await expect(page.locator('script[src="https://player.twitch.tv/js/embed/v1.js"]')).toHaveCount(0);
  await expect(page.locator(".player-embed-slot__sdk-iframe")).toHaveCount(0);
  await expect(frame).toHaveAttribute("data-player-layout-width", "400");
  await expect(frame).toHaveAttribute("data-player-layout-height", "300");

  const frameBox = await frame.boundingBox();
  const playerBox = await iframe.boundingBox();
  const playerLayoutSize = await iframe.evaluate((node) => ({
    width: node.offsetWidth,
    height: node.offsetHeight,
  }));

  expect(frameBox).not.toBeNull();
  expect(playerBox).not.toBeNull();
  expect(playerLayoutSize.width).toBeGreaterThanOrEqual(400);
  expect(playerLayoutSize.height).toBeGreaterThanOrEqual(300);

  const viewport = page.viewportSize();
  expect(viewport).not.toBeNull();
  console.log(
    `[player-fit] viewport=${viewport.width}x${viewport.height} frame=${JSON.stringify(frameBox)} iframe=${JSON.stringify(playerBox)} layout=${JSON.stringify(playerLayoutSize)}`
  );
  expect(frameBox.x).toBeGreaterThanOrEqual(-0.5);
  expect(frameBox.x + frameBox.width).toBeLessThanOrEqual(viewport.width + 0.5);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)).toBe(false);

  consoleMessages.length = 0;
  await segment.scrollIntoViewIfNeeded();
  const segmentBox = await segment.boundingBox();
  expect(segmentBox).not.toBeNull();
  await page.touchscreen.tap(
    segmentBox.x + segmentBox.width / 2,
    segmentBox.y + segmentBox.height / 2
  );

  await expect(frame).toHaveAttribute("data-player-mode", "iframe");
  await expect(iframe).toHaveAttribute("src", /autoplay=true/);
  await expect(iframe).toHaveAttribute("src", /muted=false/);
  await expect(frame).not.toHaveAttribute("data-player-status", /blocked|error/);

  const initialPlayback = await expect
    .poll(
      async () => readActiveVideo(page),
      {
        message: "A real Twitch video element should be playing after the segment tap",
        timeout: 30_000,
        intervals: [500, 1000, 1000, 2000],
      }
    )
    .toMatchObject({ paused: false });

  const baseline = (await readActiveVideo(page))?.currentTime;
  expect(Number.isFinite(baseline)).toBe(true);
  await expect
    .poll(
      async () => (await readActiveVideo(page))?.currentTime ?? -1,
      {
        message: "The real Twitch video currentTime should advance",
        timeout: 20_000,
        intervals: [500, 1000, 1000, 2000],
      }
    )
    .toBeGreaterThan(baseline + 1);

  await page.waitForTimeout(1500);
  const autoplayWarnings = consoleMessages.filter((message) => AUTOPLAY_WARNING.test(message));
  console.log(`[autoplay-warnings] ${JSON.stringify(autoplayWarnings)}`);
  expect(autoplayWarnings).toEqual([]);
});

async function readActiveVideo(page) {
  let best = null;
  for (const childFrame of page.frames()) {
    try {
      const videos = childFrame.locator("video");
      const count = await videos.count();
      for (let index = 0; index < count; index += 1) {
        const state = await videos.nth(index).evaluate((video) => ({
          currentTime: Number(video.currentTime),
          paused: Boolean(video.paused),
          readyState: Number(video.readyState),
        }));
        if (!Number.isFinite(state.currentTime)) {
          continue;
        }
        if (!best || state.currentTime > best.currentTime || (!state.paused && best.paused)) {
          best = state;
        }
      }
    } catch (error) {
      // Twitch replaces nested frames while the player initializes.
    }
  }
  return best;
}

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
      lastLabel = String((await label.textContent()) || "").trim();
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
