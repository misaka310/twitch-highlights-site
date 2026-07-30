const { test, expect } = require("@playwright/test");

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const parseTwitchTime = (value) => {
      const match = String(value || "").match(/^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$/);
      return match ? Number(match[1] || 0) * 3600 + Number(match[2] || 0) * 60 + Number(match[3] || 0) : 0;
    };

    class MockTwitchPlayer {
      constructor(element, options) {
        this.element = element;
        this.options = options || {};
        this.video = this.options.video || "";
        this.currentTime = parseTwitchTime(this.options.time);
        this.pendingTime = null;
        this.listeners = new Map();
        this.seekCalls = 0;
        this.setVideoCalls = 0;
        window.__mockTwitchPlayer = this;

        queueMicrotask(() => {
          this.emit("ready");
          this.emit("playing");
        });
      }

      addEventListener(name, callback) {
        const listeners = this.listeners.get(name) || [];
        listeners.push(callback);
        this.listeners.set(name, listeners);
      }

      emit(name) {
        (this.listeners.get(name) || []).forEach((callback) => callback());
      }

      getCurrentTime() {
        return this.currentTime;
      }

      seek(seconds) {
        this.seekCalls += 1;
        this.currentTime = Number(seconds);
        this.pendingTime = null;
        this.emit("seek");
      }

      play() {
        this.emit("playing");
      }

      setMuted() {}

      setVideo(video, seconds) {
        this.setVideoCalls += 1;
        this.video = video;
        this.currentTime = Number(seconds);
        this.pendingTime = null;
        this.emit("playing");
      }

      loadVideo(video, seconds) {
        this.setVideo(video, seconds);
      }

      destroy() {}
    }

    window.Twitch = { Player: MockTwitchPlayer };
  });
});

test("rewind button seeks back 10 seconds from current playback time", async ({ page }) => {
  await page.goto("/");

  const rewindButton = page.locator("#player-rewind-10");
  const playerFrame = page.locator("#player-frame");

  await expect(rewindButton).toBeVisible();
  await expect(playerFrame).toHaveAttribute("data-player-mode", "interactive");

  const advancedTime = await page.evaluate(() => {
    window.__mockTwitchPlayer.currentTime += 37;
    return window.__mockTwitchPlayer.currentTime;
  });

  await rewindButton.click();
  await expect
    .poll(async () => page.evaluate(() => window.__mockTwitchPlayer.currentTime))
    .toBe(advancedTime - 10);
  await expect(playerFrame).toHaveAttribute("data-current-start-sec", String(advancedTime - 10));

  await rewindButton.click();
  await expect
    .poll(async () => page.evaluate(() => window.__mockTwitchPlayer.currentTime))
    .toBe(advancedTime - 20);
  await expect(playerFrame).toHaveAttribute("data-current-start-sec", String(advancedTime - 20));
});

test("segment buttons prefer interactive playback", async ({ page }) => {
  await page.goto("/");

  const firstSegmentButton = page.locator(".segment-button").first();
  const playerFrame = page.locator("#player-frame");

  const startSec = Number(await firstSegmentButton.getAttribute("data-start-sec"));
  await firstSegmentButton.click();

  await expect(playerFrame).toHaveAttribute("data-player-mode", "interactive");
  await expect(playerFrame).toHaveAttribute("data-current-start-sec", String(startSec));
});

test("changing positions within the same VOD seeks the existing player", async ({ page }) => {
  await page.goto("/");

  const buttons = page.locator(".segment-button");
  const playerFrame = page.locator("#player-frame");
  const secondButton = buttons.nth(1);
  const targetStartSec = Number(await secondButton.getAttribute("data-start-sec"));
  const targetVodId = String(await secondButton.getAttribute("data-vod-id"));

  await secondButton.click();

  await expect(playerFrame).toHaveAttribute("data-current-vod-id", targetVodId);
  await expect(playerFrame).toHaveAttribute("data-current-start-sec", String(targetStartSec));
  await expect
    .poll(async () => page.evaluate(() => window.__mockTwitchPlayer.seekCalls))
    .toBeGreaterThan(0);
  await expect
    .poll(async () => page.evaluate(() => window.__mockTwitchPlayer.currentTime))
    .toBe(targetStartSec);
});


test("switching from the latest VOD to an older VOD keeps the older timestamp", async ({ page }) => {
  await page.goto("/");

  const playerFrame = page.locator("#player-frame");
  const latestVodButton = await getSegmentButton(page, 0, 0);
  const latestVodStartSec = Number(await latestVodButton.getAttribute("data-start-sec"));

  await latestVodButton.click();
  await expect(playerFrame).toHaveAttribute("data-current-start-sec", String(latestVodStartSec));
  await expect
    .poll(async () => page.evaluate(() => window.__mockTwitchPlayer.currentTime))
    .toBe(latestVodStartSec);

  const olderVodButton = await getSegmentButton(page, 1, 0);
  const olderVodStartSec = Number(await olderVodButton.getAttribute("data-start-sec"));
  const olderVodId = String(await olderVodButton.getAttribute("data-vod-id"));
  await olderVodButton.click();
  await expect(playerFrame).toHaveAttribute("data-current-vod-id", olderVodId);
  await expect(playerFrame).toHaveAttribute("data-current-start-sec", String(olderVodStartSec));
  await expect
    .poll(async () =>
      page.evaluate(() => String(window.__mockTwitchPlayer.video || "").replace(/^v/i, ""))
    )
    .toBe(String(olderVodId).replace(/^v/i, ""));
  await expect
    .poll(async () => page.evaluate(() => window.__mockTwitchPlayer.currentTime))
    .toBe(olderVodStartSec);
});
test("activity map clicks prefer interactive playback", async ({ page }) => {
  await page.addInitScript(() => {
    const nativeRequestAnimationFrame = window.requestAnimationFrame.bind(window);
    const heldCallbacks = [];
    let holdAnimationFrames = true;

    window.requestAnimationFrame = (callback) => {
      if (!holdAnimationFrames) {
        return nativeRequestAnimationFrame(callback);
      }
      heldCallbacks.push(callback);
      return heldCallbacks.length;
    };
    window.__releaseHeldAnimationFrames = () => {
      holdAnimationFrames = false;
      heldCallbacks.splice(0).forEach((callback) => nativeRequestAnimationFrame(callback));
    };
  });
  await page.goto("/");

  const activityMapButton = page.locator("#activity-map-button");
  const playerFrame = page.locator("#player-frame");

  await expect(activityMapButton).toBeVisible();
  await expect.poll(async () => page.evaluate(() => window.__mockTwitchPlayer == null)).toBe(true);
  const beforeStartSec = Number(await playerFrame.getAttribute("data-current-start-sec"));

  await activityMapButton.evaluate((button) => {
    const rect = button.getBoundingClientRect();
    const clickX = Math.max(0, Math.min(rect.width, rect.width * 0.4));
    const clickY = Math.max(0, Math.min(rect.height, rect.height * 0.45));
    const init = {
      bubbles: true,
      cancelable: true,
      clientX: rect.left + clickX,
      clientY: rect.top + clickY,
    };
    button.dispatchEvent(new PointerEvent("pointerdown", init));
    button.dispatchEvent(new MouseEvent("mousedown", init));
    button.dispatchEvent(new PointerEvent("pointerup", init));
    button.dispatchEvent(new MouseEvent("mouseup", init));
    button.dispatchEvent(new MouseEvent("click", init));
  });
  await page.evaluate(() => window.__releaseHeldAnimationFrames?.());

  await expect(playerFrame).toHaveAttribute("data-player-mode", "interactive");
  await expect
    .poll(async () => Number(await playerFrame.getAttribute("data-current-start-sec")))
    .not.toBe(beforeStartSec);
  const selectedStartSec = Number(await playerFrame.getAttribute("data-current-start-sec"));
  await expect
    .poll(async () => page.evaluate(() => window.__mockTwitchPlayer?.currentTime ?? -1))
    .toBe(selectedStartSec);
});

async function getSegmentButton(page, vodIndex, segmentIndex) {
  await activateVodTab(page, vodIndex);
  return page.locator(".vod-card:not([hidden]) .segment-button").nth(segmentIndex);
}

async function activateVodTab(page, vodIndex) {
  const tabs = page.locator(".vod-tab, .mobile-vod-tab");
  const tabCount = await tabs.count();
  if (tabCount <= vodIndex) {
    return;
  }

  const tab = tabs.nth(vodIndex);
  await expect(tab).toBeVisible();
  await tab.click();
}





