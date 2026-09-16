import type { VodProvider } from "../domain/vod.js";

export type PlaybackStatus = "idle" | "loading" | "ready" | "playing" | "blocked" | "error";

export type PlaybackRequest = {
  requestId: number;
  vodId: string;
  startSec: number;
  autoplay: boolean;
  muted: boolean;
  triggeredByUser: boolean;
  provider?: VodProvider;
};

export type PlaybackOptions = {
  autoplay?: boolean;
  muted?: boolean;
  triggeredByUser?: boolean;
  provider?: VodProvider;
};

export type PlaybackRuntimeState = {
  playerReady: boolean;
  playerVodId: string;
  mountInFlight: boolean;
  mountVodId: string;
  hasInteractivePlayer: boolean;
  playerProvider?: VodProvider;
  mountProvider?: VodProvider;
};

export type PlaybackDecision = {
  seekInteractive: boolean;
  mountFallback: boolean;
  waitForMount: boolean;
  destroyInteractive: boolean;
  mountInteractive: boolean;
};

export type MountContinuation = "stop" | "continue" | "restart";
