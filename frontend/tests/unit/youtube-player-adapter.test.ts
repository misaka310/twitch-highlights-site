import assert from "node:assert/strict";
import test from "node:test";
import { createYoutubePlayerAdapter, type YoutubeApiPlayer } from "../../src/player/youtube-player-adapter.js";
import { safePlay, safeSeek, safeSetMuted } from "../../src/player/twitch-player-adapter.js";


test("maps YouTube IFrame API operations to the shared player adapter", () => {
  const calls: string[] = [];
  const raw: YoutubeApiPlayer = {
    addEventListener: () => undefined,
    destroy: () => { calls.push("destroy"); },
    getCurrentTime: () => 12.5,
    pauseVideo: () => { calls.push("pause"); },
    playVideo: () => { calls.push("play"); },
    seekTo: (seconds) => { calls.push(`seek:${seconds}`); },
    mute: () => { calls.push("mute"); },
    unMute: () => { calls.push("unmute"); },
  };
  const adapter = createYoutubePlayerAdapter(raw);

  safePlay(adapter);
  safeSeek(adapter, 42);
  safeSetMuted(adapter, false);
  assert.equal(adapter.getCurrentTime?.(), 12.5);
  adapter.pause?.();
  adapter.destroy?.();

  assert.deepEqual(calls, ["play", "seek:42", "unmute", "pause", "destroy"]);
});
