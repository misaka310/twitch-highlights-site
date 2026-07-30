const { test, expect } = require("@playwright/test");

const EXPECTED_BUILD_LABEL = "cross-vod sync 20260730";
const AUTOPLAY_WARNING = /Autoplay disabled|minimum requirements for autoplay|style visibility|playback[_ ]blocked/i;

for (const projectName of ["responsive-626", "mobile-383"]) {
  test(`production ${projectName} switches to another VOD and really plays`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== projectName, `Only ${projectName}`);

    const consoleMessages = [];
    page.on("console", (message) => {
      consoleMessages.push(message.text());
    });

    await waitForDeployedBuild(page);

    const playerFrame = page.locator("#player-frame");
    await expect
      .poll(async () => playerFrame.getAttribute("data-player-status"), { timeout: 60_000 })
      .toMatch(/ready|playing/);
    await expect(playerFrame).toHaveAttribute("data-player-mode", "interactive", { timeout: 60_000 });
    await expect(page.locator("#twitch-player iframe").first()).toBeVisible({ timeout: 60_000 });

    const initialVodId = await playerFrame.getAttribute("data-current-vod-id");
    expect(initialVodId).toBeTruthy();

    const targetTab = await findVisibleTab(page, 1);
    await targetTab.scrollIntoViewIfNeeded();
    await trustedTap(page, targetTab);

    const target = page.locator(".vod-card:not([hidden]) .segment-button").first();
    await expect(target).toBeVisible();
    const targetVodId = await target.getAttribute("data-vod-id");
    const targetStartSec = Number(await target.getAttribute("data-start-sec"));
    expect(targetVodId).toBeTruthy();
    expect(targetVodId).not.toBe(initialVodId);
    expect(Number.isFinite(targetStartSec)).toBe(true);

    const iframeBefore = await page.locator("#twitch-player iframe").first().elementHandle();
    expect(iframeBefore).not.toBeNull();

    consoleMessages.length = 0;
    await target.scrollIntoViewIfNeeded();
    await trustedTap(page, target);

    await expect(playerFrame).toHaveAttribute("data-current-vod-id", targetVodId, { timeout: 30_000 });
    await expect(playerFrame).toHaveAttribute("data-player-mode", "interactive", { timeout: 30_000 });
    await expect(playerFrame).not.toHaveAttribute("data-player-status", /blocked|error/);
    await expect(page.locator("#twitch-player iframe")).toHaveCount(1);
    expect(await iframeBefore.evaluate((node) => node.isConnected)).toBe(true);

    await expect
      .poll(async () => readActiveVideo(page), {
        message: "The real Twitch video should be playing after switching VODs",
        timeout: 45_000,
        intervals: [500, 1000, 1000, 2000],
      })
      .toMatchObject({ paused: false });

    await expect
      .poll(async () => (await readActiveVideo(page))?.currentTime ?? -1, {
        message: `The real Twitch video should seek near ${targetStartSec}`,
        timeout: 45_000,
        intervals: [500, 1000, 1000, 2000],
      })
      .toBeGreaterThan(targetStartSec - 15);

    const baseline = (await readActiveVideo(page))?.currentTime;
    expect(Number.isFinite(baseline)).toBe(true);
    await expect
      .poll(async () => (await readActiveVideo(page))?.currentTime ?? -1, {
        message: "The real Twitch video currentTime should advance",
        timeout: 25_000,
        intervals: [500, 1000, 1000, 2000],
      })
      .toBeGreaterThan(baseline + 1);

    await page.waitForTimeout(2000);
    const warnings = consoleMessages.filter((message) => AUTOPLAY_WARNING.test(message));
    console.log(
      `[production-cross-vod] project=${projectName} viewport=${JSON.stringify(page.viewportSize())} targetVod=${targetVodId} targetStart=${targetStartSec} warnings=${JSON.stringify(warnings)}`
    );
    expect(warnings).toEqual([]);
  });
}

async function findVisibleTab(page, targetIndex) {
  const tabs = page.locator(".vod-tab, .mobile-vod-tab");
  const visibleTabs = [];
  for (let index = 0; index < (await tabs.count()); index += 1) {
    const tab = tabs.nth(index);
    if (await tab.isVisible()) {
      visibleTabs.push(tab);
    }
  }
  expect(visibleTabs.length).toBeGreaterThan(targetIndex);
  return visibleTabs[targetIndex];
}

async function trustedTap(page, locator) {
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  if (page.context().browser()?.browserType().name() === "chromium") {
    await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
    return;
  }
  await locator.click();
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
          muted: Boolean(video.muted),
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
      // Twitch replaces nested frames while changing VODs.
    }
  }
  return best;
}

async function waitForDeployedBuild(page) {
  const deadline = Date.now() + 10 * 60_000;
  let lastLabels = [];
  let attempt = 0;

  while (Date.now() < deadline) {
    attempt += 1;
    const response = await page.goto(`/?deploy_check=${Date.now()}`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });

    try {
      await expect
        .poll(async () => page.locator("#build-label, #build-label-mobile").allTextContents(), { timeout: 15_000 })
        .toContain(EXPECTED_BUILD_LABEL);
      console.log(`[deploy-wait] expected build live attempt=${attempt} status=${response?.status() ?? "none"}`);
      return;
    } catch (error) {
      lastLabels = await page.locator("#build-label, #build-label-mobile").allTextContents().catch(() => []);
      console.log(
        `[deploy-wait] attempt=${attempt} status=${response?.status() ?? "none"} labels=${JSON.stringify(lastLabels)}`
      );
    }

    await page.waitForTimeout(10_000);
  }

  throw new Error(`Render did not deploy ${EXPECTED_BUILD_LABEL}. Last labels: ${JSON.stringify(lastLabels)}`);
}
