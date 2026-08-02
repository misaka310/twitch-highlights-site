import type { TwitchPlayerConstructor } from "./twitch-player-adapter.js";

const TWITCH_PLAYER_SCRIPT_URL = "https://player.twitch.tv/js/embed/v1.js";

let playerScriptPromise: Promise<boolean> | null = null;

declare global {
  interface Window {
    Twitch?: {
      Player?: TwitchPlayerConstructor;
    };
  }
}

export function getTwitchPlayerConstructor(): TwitchPlayerConstructor | null {
  return typeof window.Twitch?.Player === "function" ? window.Twitch.Player : null;
}

export function ensurePlayerScript(): Promise<boolean> {
  if (getTwitchPlayerConstructor()) return Promise.resolve(true);
  if (playerScriptPromise) return playerScriptPromise;

  playerScriptPromise = new Promise<boolean>((resolve) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${TWITCH_PLAYER_SCRIPT_URL}"]`);
    const script = existing || document.createElement("script");
    let settled = false;

    const finish = (ready: boolean) => {
      if (settled) return;
      settled = true;
      resolve(ready);
    };

    script.addEventListener("load", () => finish(getTwitchPlayerConstructor() != null), { once: true });
    script.addEventListener("error", () => finish(false), { once: true });

    if (existing) {
      if (getTwitchPlayerConstructor()) finish(true);
      return;
    }

    script.src = TWITCH_PLAYER_SCRIPT_URL;
    script.async = true;
    document.head.append(script);
  }).finally(() => {
    playerScriptPromise = null;
  });

  return playerScriptPromise;
}
