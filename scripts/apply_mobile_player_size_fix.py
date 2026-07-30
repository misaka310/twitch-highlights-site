from pathlib import Path

CSS_MARKER = "/* Twitch mobile minimum embed size */"
CSS_BLOCK = r'''

@media (max-width: 640px) {
  /* Twitch mobile minimum embed size */
  .player-surface {
    margin-inline: -10px;
    overflow: hidden;
  }

  .player-frame {
    left: 50%;
    width: 400px;
    max-width: none;
    height: 300px;
    aspect-ratio: auto;
    margin-inline: 0;
    transform: translateX(-50%);
  }

  .player-embed,
  .player-embed--mounted,
  .player-embed-slot,
  .player-frame[data-player-mode="interactive"] .player-embed-slot--interactive,
  .player-frame[data-player-mode="interactive"] .player-embed-slot__sdk-wrapper,
  .player-frame[data-player-mode="interactive"] .player-embed-slot__sdk-iframe,
  .player-embed-frame {
    width: 400px !important;
    min-width: 400px !important;
    height: 300px !important;
    min-height: 300px !important;
  }
}
'''

TEST_CONTENT = r'''const { test, expect } = require("@playwright/test");

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
'''


def main() -> None:
    css_path = Path("site/styles.css")
    css = css_path.read_text(encoding="utf-8")
    if CSS_MARKER not in css:
        css_path.write_text(css.rstrip() + CSS_BLOCK + "\n", encoding="utf-8")

    Path("tests/mobile-player-size.spec.js").write_text(TEST_CONTENT, encoding="utf-8")


if __name__ == "__main__":
    main()
