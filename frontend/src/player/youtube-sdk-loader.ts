import type { YoutubeApiPlayer } from "./youtube-player-adapter.js";


const YOUTUBE_PLAYER_SCRIPT_URL = "https://www.youtube.com/iframe_api";

export type YoutubePlayerConstructor = new (
  element: HTMLElement,
  options: {
    videoId: string;
    playerVars: Record<string, number | string>;
    events: {
      onReady: () => void;
      onStateChange: (event: { data?: number }) => void;
      onError: () => void;
    };
  },
) => YoutubeApiPlayer;

declare global {
  interface Window {
    YT?: {
      Player?: YoutubePlayerConstructor;
    };
    onYouTubeIframeAPIReady?: () => void;
  }
}

let playerScriptPromise: Promise<boolean> | null = null;
const YOUTUBE_PLAYER_READY_TIMEOUT_MS = 15_000;

export function getYoutubePlayerConstructor(): YoutubePlayerConstructor | null {
  return typeof window.YT?.Player === "function" ? window.YT.Player : null;
}

export function ensureYoutubePlayerScript(): Promise<boolean> {
  if (getYoutubePlayerConstructor()) return Promise.resolve(true);
  if (playerScriptPromise) return playerScriptPromise;

  playerScriptPromise = new Promise<boolean>((resolve) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${YOUTUBE_PLAYER_SCRIPT_URL}"]`);
    const script = existing || document.createElement("script");
    let settled = false;
    const previousReady = window.onYouTubeIframeAPIReady;

    const finish = (ready: boolean) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeoutId);
      resolve(ready);
    };

    const timeoutId = window.setTimeout(() => finish(false), YOUTUBE_PLAYER_READY_TIMEOUT_MS);

    window.onYouTubeIframeAPIReady = () => {
      previousReady?.();
      finish(getYoutubePlayerConstructor() != null);
    };
    script.addEventListener("load", () => {
      if (getYoutubePlayerConstructor()) finish(true);
    }, { once: true });
    script.addEventListener("error", () => finish(false), { once: true });

    if (existing) {
      if (getYoutubePlayerConstructor()) finish(true);
      return;
    }

    script.src = YOUTUBE_PLAYER_SCRIPT_URL;
    script.async = true;
    document.head.append(script);
  }).finally(() => {
    playerScriptPromise = null;
  });

  return playerScriptPromise;
}
