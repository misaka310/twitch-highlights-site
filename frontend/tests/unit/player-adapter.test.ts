import assert from "node:assert/strict";
import test from "node:test";
import {
  addPlayerListener,
  destroyPlayer,
  safePlay,
  safeSeek,
  safeSetMuted,
  type TwitchPlayerInstance,
} from "../../src/player/twitch-player-adapter.js";

test("adapter forwards supported player operations", async () => {
  const calls: string[] = [];
  const listeners = new Map<string, () => void>();
  const player: TwitchPlayerInstance = {
    addEventListener: (event, callback) => listeners.set(event, callback),
    play: () => { calls.push("play"); },
    pause: () => { calls.push("pause"); },
    seek: (seconds) => { calls.push(`seek:${seconds}`); },
    setMuted: (muted) => { calls.push(`muted:${muted}`); },
    destroy: () => { calls.push("destroy"); },
  };

  safePlay(player);
  safeSeek(player, -3);
  safeSetMuted(player, false);
  addPlayerListener(player, "ready", () => calls.push("ready"));
  listeners.get("ready")?.();
  destroyPlayer(player);

  assert.deepEqual(calls, ["play", "seek:0", "muted:false", "ready", "pause", "destroy"]);
});

test("adapter absorbs transient SDK errors and rejected playback", async () => {
  const player: TwitchPlayerInstance = {
    play: () => Promise.reject(new Error("blocked")),
    pause: () => { throw new Error("pause failed"); },
    seek: () => { throw new Error("seek failed"); },
    setMuted: () => { throw new Error("mute failed"); },
    destroy: () => { throw new Error("destroy failed"); },
  };

  safePlay(player);
  safeSeek(player, 1);
  safeSetMuted(player, true);
  destroyPlayer(player);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.ok(true);
});
