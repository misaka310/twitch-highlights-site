const { test, expect } = require("@playwright/test");

test("cross-VOD click reuses the ready Twitch player synchronously", async ({ page }) => {
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
        this.video = String(options.video || "");
        this.currentTime = Number.parseInt(String(options.time || "0"), 10) || 0;
        this.muted = Boolean(options.muted);

        const state = (window.__fakeTwitchState ||= {
          instances: 0,
          setVideoCalls: [],
          playCalls: 0,
        });
        state.instances += 1;

        const host = typeof target === "string" ? document.getElementById(target) : target;
        const iframe = document.createElement("iframe");
        iframe.title = "Fake Twitch player";
        host?.append(iframe);

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

      setMuted(value) {
        this.muted = Boolean(value);
      }

      setVideo(videoId, timestamp) {
        this.video = String(videoId || "");
        this.currentTime = Number(timestamp) || 0;
        window.__fakeTwitchState.setVideoCalls.push({
          videoId: this.video,
          timestamp: this.currentTime,
          userActivationActive: Boolean(navigator.userActivation?.isActive),
        });
      }

      play() {
        window.__fakeTwitchState.playCalls += 1;
        this.emit(FakePlayer.PLAYING);
      }

      seek(timestamp) {
        this.currentTime = Number(timestamp) || 0;
      }

      getCurrentTime() {
        return this.currentTime;
      }

      pause() {}
      destroy() {}
    }

    window.Twitch = { Player: FakePlayer };
  });

  await page.goto("/");

  const frame = page.locator("#player-frame");
  await expect(frame).toHaveAttribute("data-player-status", "ready");

  const initialVodId = await frame.getAttribute("data-current-vod-id");
  const tabs = page.locator(".vod-tab, .mobile-vod-tab");
  await expect(tabs.nth(1)).toBeVisible();
  await tabs.nth(1).click();

  const target = page.locator(".vod-card:not([hidden]) .segment-button").first();
  await expect(target).toBeVisible();

  const targetVodId = await target.getAttribute("data-vod-id");
  const targetStartSec = Number(await target.getAttribute("data-start-sec"));
  expect(targetVodId).not.toBe(initialVodId);
  await target.click();

  await expect
    .poll(() => page.evaluate(() => window.__fakeTwitchState))
    .toMatchObject({
      instances: 1,
      setVideoCalls: [
        {
          videoId: targetVodId,
          timestamp: targetStartSec,
          userActivationActive: true,
        },
      ],
    });

  await expect
    .poll(() => page.evaluate(() => window.__fakeTwitchState.playCalls))
    .toBeGreaterThanOrEqual(1);

  await expect(frame).toHaveAttribute("data-current-vod-id", targetVodId);
  await expect(page.locator("#twitch-player iframe")).toHaveCount(1);
});
