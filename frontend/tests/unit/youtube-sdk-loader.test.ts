import assert from "node:assert/strict";
import test from "node:test";
import { ensureYoutubePlayerScript } from "../../src/player/youtube-sdk-loader.js";


test("waits for the YouTube API callback after the loader script fires load", async () => {
  const originalWindow = globalThis.window;
  const originalDocument = globalThis.document;
  const listeners: Record<string, () => void> = {};
  const script = {
    addEventListener: (type: string, listener: () => void) => { listeners[type] = listener; },
    src: "",
    async: false,
  } as unknown as HTMLScriptElement;
  const fakeDocument = {
    querySelector: () => null,
    createElement: () => script,
    head: {
      append: () => {
        queueMicrotask(() => {
          listeners.load?.();
          queueMicrotask(() => {
            window.YT = { Player: (() => undefined) as never };
            window.onYouTubeIframeAPIReady?.();
          });
        });
      },
    },
  } as unknown as Document;

  Object.assign(globalThis, {
    window: { setTimeout, clearTimeout },
    document: fakeDocument,
  });
  try {
    assert.equal(await ensureYoutubePlayerScript(), true);
  } finally {
    Object.assign(globalThis, { window: originalWindow, document: originalDocument });
  }
});
