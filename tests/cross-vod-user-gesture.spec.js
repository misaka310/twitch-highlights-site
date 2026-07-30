const { test, expect } = require("@playwright/test");

test("cross-VOD click replaces the SDK once and keeps the trusted direct iframe", async ({ page }) => {
  await page.route("https://player.twitch.tv/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/html",
      body: "<!doctype html><title>Fake direct Twitch iframe</title>",
    });
  });

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
          destroyCalls: 0,
        });
        state.instances += 1;

        const host = typeof target === "string" ? document.getElementById(target) : target;
        const iframe = document.createElement("iframe");
        iframe.title = "Fake Twitch SDK player";
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
        window.__fakeTwitchState.setVideoCalls.push({ videoId, timestamp });
      }

      play() {
        window.__fakeTwitchState.playCalls += 1;
      }

      seek(timestamp) {
        this.currentTime = Number(timestamp) || 0;
      }

      getCurrentTime() {
        return this.currentTime;
      }

      pause() {}

      destroy() {
        window.__fakeTwitchState.destroyCalls += 1;
      }
    }

    window.Twitch = { Player: FakePlayer };
  });

  await page.goto("/");

  const frame = page.locator("#player-frame");
  await expect(frame).toHaveAttribute("data-player-status", "ready");
  await expect(frame).toHaveAttribute("data-player-mode", "interactive");

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

  const iframe = page.locator(".player-embed-frame");
  await expect(iframe).toBeVisible();
  await expect(frame).toHaveAttribute("data-player-mode", "iframe");
  await expect(frame).toHaveAttribute("data-current-vod-id", targetVodId);
  await expect(frame).toHaveAttribute("data-current-start-sec", String(targetStartSec));
  await expect(frame).toHaveAttribute("data-triggered-by-user", "true");
  await expect(iframe).toHaveAttribute("src", new RegExp(`video=${targetVodId}`));
  await expect(iframe).toHaveAttribute("src", /autoplay=true/);
  await expect(iframe).toHaveAttribute("src", /muted=false/);
  await expect(iframe).toHaveAttribute("src", new RegExp(`time=${encodeURIComponent(formatTwitchTime(targetStartSec))}`));
  await expect(page.locator("#twitch-player-inner")).toHaveCount(0);

  await expect
    .poll(() => page.evaluate(() => window.__fakeTwitchState))
    .toMatchObject({
      instances: 1,
      setVideoCalls: [],
      playCalls: 0,
      destroyCalls: 1,
    });
});

function formatTwitchTime(totalSeconds) {
  const seconds = Math.max(0, Math.floor(Number(totalSeconds) || 0));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = seconds % 60;
  return `${hours}h${minutes}m${remainingSeconds}s`;
}
