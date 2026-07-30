const { test, expect } = require("@playwright/test");

test("mobile Twitch player keeps the required 400x300 layout without page overflow", async ({ page }, testInfo) => {
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

  await page.setViewportSize({ width: 383, height: 841 });
  await page.goto("/");

  const segment = page.locator(".vod-card:not([hidden]) .segment-button").first();
  await expect(segment).toBeEnabled();

  const iframe = page.locator(".player-embed-slot__sdk-iframe");
  await expect(iframe).toBeVisible();
  const box = await iframe.boundingBox();
  expect(box).not.toBeNull();
  expect(box.width).toBeGreaterThanOrEqual(400);
  expect(box.height).toBeGreaterThanOrEqual(300);

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
  await expect(page.locator("#player-frame")).toHaveAttribute("data-player-status", "playing");
});
