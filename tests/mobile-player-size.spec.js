const { test, expect } = require("@playwright/test");

const MOBILE_VIEWPORTS = [
  { width: 320, height: 700 },
  { width: 360, height: 800 },
  { width: 390, height: 844 },
  { width: 412, height: 915 },
];

for (const viewport of MOBILE_VIEWPORTS) {
  test(`mobile Twitch player stays fully visible at ${viewport.width}px`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile", "Mobile Twitch sizing only");

    await page.addInitScript(() => {
      class FakePlayer {
        static READY = "ready";
        static PLAY = "play";
        static PLAYING = "playing";
        static PAUSE = "pause";
        static ENDED = "ended";
        static PLAYBACK_BLOCKED = "playback_blocked";

        constructor(target, options) {
          this.listeners = new Map();
          this.currentTime = Number.parseInt(String(options?.time || "0"), 10) || 0;
          const host = typeof target === "string" ? document.getElementById(target) : target;
          const wrapper = document.createElement("div");
          const iframe = document.createElement("iframe");
          iframe.title = "Fake Twitch player";
          wrapper.append(iframe);
          host?.append(wrapper);
          queueMicrotask(() => this.emit(FakePlayer.READY));
        }

        addEventListener(name, callback) {
          const callbacks = this.listeners.get(name) || [];
          callbacks.push(callback);
          this.listeners.set(name, callbacks);
        }

        emit(name) {
          (this.listeners.get(name) || []).forEach((callback) => callback());
        }

        setMuted() {}
        seek(seconds) { this.currentTime = Number(seconds) || 0; }
        getCurrentTime() { return this.currentTime; }
        play() { this.emit(FakePlayer.PLAYING); }
        pause() {}
        destroy() {}
      }

      window.Twitch = { Player: FakePlayer };
    });

    await page.setViewportSize(viewport);
    await page.goto("/");

    const segment = page.locator(".vod-card:not([hidden]) .segment-button").first();
    const frame = page.locator("#player-frame");
    const iframe = page.locator(".player-embed-slot__sdk-iframe");

    await expect(segment).toBeEnabled();
    await expect(iframe).toBeVisible();
    await expect(page.locator("#mobile-player-fit-styles")).toHaveCount(1);

    const frameBox = await frame.boundingBox();
    const iframeBox = await iframe.boundingBox();
    expect(frameBox).not.toBeNull();
    expect(iframeBox).not.toBeNull();

    expect(frameBox.x).toBeGreaterThanOrEqual(-0.5);
    expect(frameBox.x + frameBox.width).toBeLessThanOrEqual(viewport.width + 0.5);
    expect(iframeBox.x).toBeGreaterThanOrEqual(frameBox.x - 1);
    expect(iframeBox.x + iframeBox.width).toBeLessThanOrEqual(frameBox.x + frameBox.width + 1);
    expect(Math.abs(iframeBox.width - frameBox.width)).toBeLessThanOrEqual(2.1);
    expect(Math.abs(iframeBox.height - frameBox.height)).toBeLessThanOrEqual(2.1);
    expect(frameBox.width / frameBox.height).toBeGreaterThan(1.31);
    expect(frameBox.width / frameBox.height).toBeLessThan(1.35);

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
    await expect(frame).toHaveAttribute("data-player-status", "playing");
  });
}
