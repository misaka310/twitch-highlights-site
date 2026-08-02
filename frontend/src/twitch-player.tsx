import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { decideMountContinuation, decidePlayback } from "./player/playback-decision.js";
import { createPlaybackRequest } from "./player/playback-request.js";
import type { PlaybackOptions, PlaybackRequest, PlaybackStatus } from "./player/playback-types.js";
import { buildEmbedUrl, formatTwitchTime, getTwitchParents } from "./player/twitch-url.js";

const TWITCH_PLAYER_SCRIPT_URL = "https://player.twitch.tv/js/embed/v1.js";
const INTERACTIVE_SEEK_STABILIZE_MS = 2500;

type TwitchPlayerInstance = {
  addEventListener?: (eventName: string, callback: () => void) => void;
  destroy?: () => void;
  getCurrentTime?: () => number;
  pause?: () => void;
  play?: () => void | Promise<void>;
  seek?: (seconds: number) => void;
  setMuted?: (muted: boolean) => void;
};

type TwitchPlayerConstructor = {
  new (element: HTMLElement, options: Record<string, unknown>): TwitchPlayerInstance;
  READY?: string;
  PLAY?: string;
  PLAYING?: string;
  PAUSE?: string;
  ENDED?: string;
  PLAYBACK_BLOCKED?: string;
};

declare global {
  interface Window {
    Twitch?: {
      Player?: TwitchPlayerConstructor;
    };
  }
}

export type TwitchPlayerHandle = {
  requestPlayback: (vodId: string, startSec: number, options?: PlaybackOptions) => void;
  getCurrentTime: () => number | null;
};

type TwitchPlayerProps = {
  onPositionChange: (seconds: number) => void;
  onStatusChange: (label: string, status: PlaybackStatus) => void;
};

let playerScriptPromise: Promise<boolean> | null = null;

function ensurePlayerScript(): Promise<boolean> {
  if (typeof window.Twitch?.Player === "function") return Promise.resolve(true);
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

    script.addEventListener("load", () => finish(typeof window.Twitch?.Player === "function"), { once: true });
    script.addEventListener("error", () => finish(false), { once: true });

    if (existing) {
      if (typeof window.Twitch?.Player === "function") finish(true);
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

function safePlay(player: TwitchPlayerInstance | null): void {
  if (!player?.play) return;
  try {
    const result = player.play();
    if (result && typeof result.catch === "function") result.catch(() => undefined);
  } catch {
    // Browser autoplay policy can reject playback even after initialization.
  }
}

function safeSetMuted(player: TwitchPlayerInstance | null, muted: boolean): void {
  if (!player?.setMuted) return;
  try {
    player.setMuted(muted);
  } catch {
    // Ignore transient SDK errors during player initialization.
  }
}

function safeSeek(player: TwitchPlayerInstance | null, seconds: number): void {
  if (!player?.seek) return;
  try {
    player.seek(Math.max(0, seconds));
  } catch {
    // Ignore transient SDK errors during player initialization.
  }
}

function addPlayerListener(player: TwitchPlayerInstance, eventName: string | undefined, callback: () => void): void {
  if (!eventName || typeof player.addEventListener !== "function") return;
  player.addEventListener(eventName, callback);
}

export const TwitchPlayer = forwardRef<TwitchPlayerHandle, TwitchPlayerProps>(function TwitchPlayer(
  { onPositionChange, onStatusChange },
  ref,
) {
  const frameRef = useRef<HTMLDivElement>(null);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const playerRef = useRef<TwitchPlayerInstance | null>(null);
  const desiredRef = useRef<PlaybackRequest | null>(null);
  const requestSequenceRef = useRef(0);
  const mountInFlightRef = useRef(false);
  const mountVodIdRef = useRef("");
  const playerVodIdRef = useRef("");
  const playerReadyRef = useRef(false);
  const pollIdRef = useRef<number | null>(null);
  const lastKnownPositionRef = useRef(0);
  const lastSeekTargetRef = useRef<number | null>(null);
  const lastSeekAtRef = useRef(0);

  const setUiState = (
    status: PlaybackStatus,
    request: PlaybackRequest | null,
    label: string,
    mode: "iframe" | "interactive" | "",
  ) => {
    const frame = frameRef.current;
    if (frame) {
      frame.dataset.playerStatus = status;
      frame.dataset.currentVodId = request?.vodId || "";
      frame.dataset.currentStartSec = request ? String(request.startSec) : "";
      frame.dataset.playerMode = mode;
      frame.dataset.expectedAutoplay = String(request?.autoplay === true);
      frame.dataset.expectedMuted = String(request?.muted === true);
      frame.dataset.triggeredByUser = String(request?.triggeredByUser === true);
    }
    onStatusChange(label, status);
  };

  const getCurrentTime = (): number | null => {
    const player = playerRef.current;
    if (player?.getCurrentTime) {
      try {
        const current = Number(player.getCurrentTime());
        if (Number.isFinite(current) && current >= 0) return current;
      } catch {
        // Fall back to the last known position.
      }
    }
    return Number.isFinite(lastKnownPositionRef.current) ? lastKnownPositionRef.current : null;
  };

  const stopPolling = () => {
    if (pollIdRef.current != null) {
      window.clearInterval(pollIdRef.current);
      pollIdRef.current = null;
    }
  };

  const syncCurrentTime = () => {
    const current = getCurrentTime();
    if (current == null) return;
    const seekTarget = lastSeekTargetRef.current;
    const seekAge = Date.now() - lastSeekAtRef.current;
    if (seekTarget != null && seekAge >= 0 && seekAge <= INTERACTIVE_SEEK_STABILIZE_MS && Math.abs(current - seekTarget) > 5) {
      return;
    }
    if (seekTarget != null && (seekAge > INTERACTIVE_SEEK_STABILIZE_MS || Math.abs(current - seekTarget) <= 6)) {
      lastSeekTargetRef.current = null;
      lastSeekAtRef.current = 0;
    }
    const floored = Math.max(0, Math.floor(current));
    lastKnownPositionRef.current = floored;
    const frame = frameRef.current;
    if (frame) frame.dataset.currentStartSec = String(floored);
    onPositionChange(floored);
  };

  const startPolling = () => {
    stopPolling();
    pollIdRef.current = window.setInterval(syncCurrentTime, 500);
  };

  const destroyInteractivePlayer = () => {
    stopPolling();
    playerReadyRef.current = false;
    playerVodIdRef.current = "";
    const player = playerRef.current;
    playerRef.current = null;
    if (!player) return;
    try {
      player.pause?.();
    } catch {
      // Ignore cleanup errors.
    }
    try {
      player.destroy?.();
    } catch {
      // Ignore cleanup errors.
    }
  };

  const mountFallbackIframe = (request: PlaybackRequest) => {
    const host = hostRef.current;
    if (!host) return;
    const iframe = document.createElement("iframe");
    iframe.className = "player-embed-frame";
    iframe.title = "Twitch";
    iframe.allow = "autoplay; fullscreen";
    iframe.setAttribute("allowfullscreen", "");
    iframe.setAttribute("scrolling", "no");
    iframe.setAttribute("frameborder", "0");
    iframe.src = buildEmbedUrl(request, location.hostname);
    iframe.addEventListener("load", () => {
      if (desiredRef.current?.requestId !== request.requestId || playerReadyRef.current) return;
      setUiState(request.autoplay ? "playing" : "ready", request, request.autoplay ? "再生中" : "待機中", "iframe");
    }, { once: true });
    host.replaceChildren(iframe);
  };

  const seekInteractivePlayer = (request: PlaybackRequest) => {
    const player = playerRef.current;
    if (!player || !playerReadyRef.current || playerVodIdRef.current !== request.vodId) return false;
    safeSetMuted(player, request.muted);
    lastSeekTargetRef.current = request.startSec;
    lastSeekAtRef.current = Date.now();
    lastKnownPositionRef.current = request.startSec;
    safeSeek(player, request.startSec);
    if (request.autoplay) safePlay(player);
    onPositionChange(request.startSec);
    setUiState(request.autoplay ? "playing" : "ready", request, request.autoplay ? "再生中" : "待機中", "interactive");
    window.setTimeout(syncCurrentTime, 180);
    window.setTimeout(syncCurrentTime, 520);
    window.setTimeout(syncCurrentTime, 1100);
    return true;
  };

  const mountInteractivePlayer = async (request: PlaybackRequest) => {
    if (mountInFlightRef.current) return;
    mountInFlightRef.current = true;
    mountVodIdRef.current = request.vodId;

    const scriptLoaded = await ensurePlayerScript();
    const latestAfterLoad = desiredRef.current;
    if (!scriptLoaded || typeof window.Twitch?.Player !== "function") {
      mountInFlightRef.current = false;
      mountVodIdRef.current = "";
      if (latestAfterLoad) setUiState("ready", latestAfterLoad, "プレイヤー準備完了", "iframe");
      return;
    }
    const continuation = decideMountContinuation(request, latestAfterLoad);
    if (continuation === "stop") {
      mountInFlightRef.current = false;
      mountVodIdRef.current = "";
      return;
    }
    if (continuation === "restart" && latestAfterLoad) {
      mountInFlightRef.current = false;
      mountVodIdRef.current = "";
      void mountInteractivePlayer(latestAfterLoad);
      return;
    }

    destroyInteractivePlayer();
    const host = hostRef.current;
    if (!host) {
      mountInFlightRef.current = false;
      mountVodIdRef.current = "";
      return;
    }

    const inner = document.createElement("div");
    inner.className = "player-embed-slot";
    host.replaceChildren(inner);

    const PlayerClass = window.Twitch.Player;
    const player = new PlayerClass(inner, {
      width: "100%",
      height: "100%",
      video: request.vodId,
      parent: getTwitchParents(location.hostname),
      autoplay: request.autoplay,
      muted: request.muted,
      time: formatTwitchTime(request.startSec),
      playsinline: true,
    });

    playerRef.current = player;
    playerVodIdRef.current = request.vodId;
    playerReadyRef.current = false;

    const readyEvent = PlayerClass.READY || "ready";
    const playEvent = PlayerClass.PLAY || "play";
    const playingEvent = PlayerClass.PLAYING || "playing";
    const pauseEvent = PlayerClass.PAUSE || "pause";
    const endedEvent = PlayerClass.ENDED || "ended";
    const blockedEvent = PlayerClass.PLAYBACK_BLOCKED || "playback_blocked";

    addPlayerListener(player, readyEvent, () => {
      if (playerRef.current !== player) return;
      playerReadyRef.current = true;
      mountInFlightRef.current = false;
      mountVodIdRef.current = "";
      startPolling();

      const latest = desiredRef.current;
      if (!latest) return;
      if (latest.vodId !== request.vodId) {
        mountFallbackIframe(latest);
        void mountInteractivePlayer(latest);
        return;
      }

      safeSetMuted(player, latest.muted);
      lastKnownPositionRef.current = latest.startSec;
      if (latest.startSec !== request.startSec) {
        seekInteractivePlayer(latest);
        return;
      }
      if (latest.autoplay) safePlay(player);
      onPositionChange(latest.startSec);
      setUiState(latest.autoplay ? "playing" : "ready", latest, latest.autoplay ? "再生中" : "待機中", "interactive");
    });

    addPlayerListener(player, playEvent, () => {
      if (playerRef.current !== player) return;
      setUiState("playing", desiredRef.current, "再生中", "interactive");
    });
    if (playingEvent !== playEvent) {
      addPlayerListener(player, playingEvent, () => {
        if (playerRef.current !== player) return;
        setUiState("playing", desiredRef.current, "再生中", "interactive");
      });
    }
    addPlayerListener(player, pauseEvent, () => {
      if (playerRef.current !== player) return;
      setUiState("ready", desiredRef.current, "待機中", "interactive");
    });
    addPlayerListener(player, endedEvent, () => {
      if (playerRef.current !== player) return;
      setUiState("ready", desiredRef.current, "待機中", "interactive");
    });
    addPlayerListener(player, blockedEvent, () => {
      if (playerRef.current !== player) return;
      setUiState("blocked", desiredRef.current, "再生がブロックされました", "interactive");
    });
  };

  const requestPlayback = (vodId: string, startSec: number, options: PlaybackOptions = {}) => {
    const request = createPlaybackRequest(requestSequenceRef.current + 1, vodId, startSec, options);
    if (!request) return;
    requestSequenceRef.current = request.requestId;

    desiredRef.current = request;
    lastKnownPositionRef.current = request.startSec;
    onPositionChange(request.startSec);
    setUiState("loading", request, request.triggeredByUser ? "再生を開始中" : "プレイヤー読込中", playerReadyRef.current ? "interactive" : "iframe");

    const decision = decidePlayback(request, {
      playerReady: playerReadyRef.current,
      playerVodId: playerVodIdRef.current,
      mountInFlight: mountInFlightRef.current,
      mountVodId: mountVodIdRef.current,
      hasInteractivePlayer: playerRef.current != null,
    });
    if (decision.seekInteractive && seekInteractivePlayer(request)) return;
    if (decision.mountFallback) mountFallbackIframe(request);
    if (decision.waitForMount) return;
    if (decision.destroyInteractive) destroyInteractivePlayer();
    if (decision.mountInteractive) void mountInteractivePlayer(request);
  };

  useImperativeHandle(ref, () => ({ requestPlayback, getCurrentTime }));

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return undefined;

    const host = document.createElement("div");
    host.className = "player-embed player-embed--portal";
    host.setAttribute("aria-label", "Twitch player");
    document.body.append(host);
    hostRef.current = host;
    frame.dataset.playerPortal = "body";

    let animationFrameId: number | null = null;
    const sync = () => {
      animationFrameId = null;
      const rect = frame.getBoundingClientRect();
      Object.assign(host.style, {
        position: "fixed",
        inset: "auto",
        left: `${rect.left + frame.clientLeft}px`,
        top: `${rect.top + frame.clientTop}px`,
        width: `${frame.clientWidth}px`,
        height: `${frame.clientHeight}px`,
        minHeight: "0",
        margin: "0",
        zIndex: "2",
        visibility: rect.width > 0 && rect.height > 0 ? "visible" : "hidden",
      });
    };
    const scheduleSync = () => {
      if (animationFrameId != null) window.cancelAnimationFrame(animationFrameId);
      animationFrameId = window.requestAnimationFrame(sync);
    };

    const resizeObserver = typeof ResizeObserver === "function" ? new ResizeObserver(scheduleSync) : null;
    resizeObserver?.observe(frame);
    window.addEventListener("resize", scheduleSync);
    window.addEventListener("scroll", scheduleSync, { passive: true });
    window.visualViewport?.addEventListener("resize", scheduleSync);
    window.visualViewport?.addEventListener("scroll", scheduleSync);
    scheduleSync();

    return () => {
      if (animationFrameId != null) window.cancelAnimationFrame(animationFrameId);
      resizeObserver?.disconnect();
      window.removeEventListener("resize", scheduleSync);
      window.removeEventListener("scroll", scheduleSync);
      window.visualViewport?.removeEventListener("resize", scheduleSync);
      window.visualViewport?.removeEventListener("scroll", scheduleSync);
      destroyInteractivePlayer();
      host.remove();
      hostRef.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- portal lifecycle is mount/unmount only

  return (
    <div
      id="player-frame"
      ref={frameRef}
      className="player-frame"
      data-player-status="idle"
      data-current-vod-id=""
      data-current-start-sec=""
      data-player-mode=""
      data-expected-autoplay="false"
      data-expected-muted="true"
      data-triggered-by-user="false"
    >
      <span className="sr-only" aria-live="polite">Twitchプレイヤー</span>
    </div>
  );
});
