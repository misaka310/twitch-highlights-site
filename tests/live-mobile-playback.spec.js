const { test, expect } = require("@playwright/test");

const EXPECTED_BUILD_LABEL = "build at 05.25";
const AUTOPLAY_WARNING = /Autoplay disabled|minimum requirements for autoplay|style visibility|playback[_ ]blocked/i;

for (const projectName of ["mobile-383", "mobile-430"]) {
  test(`${projectName} uses repo 19 interactive playback and advances real video`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== projectName, `Runs only in ${projectName}`);

    const consoleMessages = [];
    page.on("console", (message) => {
      consoleMessages.push(message.text());
    });

    await waitForRestoredBuild(page);

    const frame = page.locator("#player-frame");
    const player = page.locator("#twitch-player");
    const sdkIframe = page.locator(".player-embed-slot__sdk-iframe");
    const segment = page.locator(".vod-card:not([hidden]) .segment-button").first();

    await expect(page.locator('script[src*="player-recovery.js"]')).toHaveCount(0);
    await expect(page.locator("#player-unmute")).toHaveCount(0);
    await expect
      .poll(async () => player.evaluate((element) => element.parentElement?.id || ""))
      .toBe("player-frame");
    await expect(frame).toHaveAttribute("data-player-mode", "interactive", { timeout: 60_000 });
    await expect(sdkIframe).toBeVisible({ timeout: 60_000 });
    await expect(segment).toBeVisible();
    await expect(segment).toBeEnabled();

    const viewport = page.viewportSize();
    const frameBox = await frame.boundingBox();
    const iframeBox = await sdkIframe.boundingBox();
    console.log(
      `[repo19-layout] project=${testInfo.project.name} viewport=${JSON.stringify(viewport)} frame=${JSON.stringify(frameBox)} iframe=${JSON.stringify(iframeBox)}`
    );

    consoleMessages.length = 0;
    await segment.scrollIntoViewIfNeeded();
    const segmentBox = await segment.boundingBox();
    expect(segmentBox).not.toBeNull();
    await page.touchscreen.tap(
      segmentBox.x + segmentBox.width / 2,
      segmentBox.y + segmentBox.height / 2
    );

    await expect(frame).toHaveAttribute("data-player-mode", "interactive");
    await expect
      .poll(
        async () => readActiveVideo(page),
        {
          message: `${testInfo.project.name}: real Twitch video should be playing after one segment tap`,
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
          message: `${testInfo.project.name}: real Twitch video currentTime should advance`,
          timeout: 20_000,
          intervals: [500, 1000, 1000, 2000],
        }
      )
      .toBeGreaterThan(baseline + 1);

    await page.waitForTimeout(1500);
    const warnings = consoleMessages.filter((message) => AUTOPLAY_WARNING.test(message));
    console.log(`[repo19-autoplay-warnings] project=${testInfo.project.name} ${JSON.stringify(warnings)}`);
    expect(warnings).toEqual([]);
  });
}

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
        if (!best || (!state.paused && best.paused) || state.currentTime > best.currentTime) {
          best = state;
        }
      }
    } catch (error) {
      // Twitch replaces nested frames while the player initializes.
    }
  }
  return best;
}

async function waitForRestoredBuild(page) {
  const deadline = Date.now() + 10 * 60_000;
  let lastLabel = "";
  let attempt = 0;

  while (Date.now() < deadline) {
    attempt += 1;
    const response = await page.goto(`/?repo19_deploy_check=${Date.now()}`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });

    const label = page.locator("#build-label-mobile");
    let restored = false;
    try {
      await expect(label).toHaveText(EXPECTED_BUILD_LABEL, { timeout: 15_000 });
      await expect(page.locator('script[src*="player-recovery.js"]')).toHaveCount(0);
      await expect(page.locator("#player-unmute")).toHaveCount(0);
      restored = true;
    } catch (error) {
      restored = false;
    }

    try {
      lastLabel = String((await label.textContent()) || "").trim();
    } catch (error) {
      lastLabel = "";
    }

    console.log(
      `[repo19-deploy-wait] attempt=${attempt} status=${response?.status() ?? "none"} label=${JSON.stringify(lastLabel)} restored=${restored}`
    );

    if (restored) {
      return;
    }
    await page.waitForTimeout(10_000);
  }

  throw new Error(
    `Render did not deploy the restored repo 19 build. Expected ${EXPECTED_BUILD_LABEL}, received ${lastLabel || "<empty>"}`
  );
}
