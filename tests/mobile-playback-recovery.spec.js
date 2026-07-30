const { test, expect } = require("@playwright/test");

test("interactive playback exposes a recovery control when autoplay is blocked", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "Interactive SDK recovery is desktop-only");

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
        this.currentTime = 0;
        this.muted = Boolean(options?.muted);
        window.__fakeTwitchState = {
          playCalls: 0,
          muted: this.muted,
        };

        const host = typeof target === "string" ? document.getElementById(target) : target;
        const iframe = document.createElement("iframe");
        iframe.title = "Fake Twitch player";
        host?.append(iframe);

        window.setTimeout(() => this.emit(FakePlayer.READY), 500);
      }

      addEventListener(name, callback) {
        const callbacks = this.listeners.get(name) || [];
        callbacks.push(callback);
        this.listeners.set(name, callbacks);
      }

      emit(name) {
        (this.listeners.get(name) || []).forEach((callback) => callback());
      }

      setMuted(muted) {
        this.muted = Boolean(muted);
        window.__fakeTwitchState.muted = this.muted;
      }

      seek(seconds) {
        this.currentTime = Number(seconds) || 0;
      }

      getCurrentTime() {
        return this.currentTime;
      }

      play() {
        window.__fakeTwitchState.playCalls += 1;
        if (window.__fakeTwitchState.playCalls === 1) {
          window.setTimeout(() => this.emit(FakePlayer.PLAYBACK_BLOCKED), 0);
          return;
        }
        this.emit(FakePlayer.PLAYING);
      }

      pause() {}
      destroy() {}
    }

    window.Twitch = { Player: FakePlayer };
  });

  await page.goto("/");
  const segment = page.locator(".vod-card:not([hidden]) .segment-button").first();
  await expect(segment).toBeVisible();
  await segment.click();

  const recoveryButton = page.locator("#player-unmute");
  await expect(recoveryButton).toBeVisible();
  await expect(page.locator("#player-frame")).toHaveAttribute("data-player-status", "blocked");

  await recoveryButton.click();

  await expect(recoveryButton).toBeHidden();
  await expect(page.locator("#player-frame")).toHaveAttribute("data-player-status", "playing");
  await expect
    .poll(() => page.evaluate(() => window.__fakeTwitchState))
    .toMatchObject({ playCalls: 2, muted: false });
});
