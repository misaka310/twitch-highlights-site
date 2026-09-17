import type {
  MountContinuation,
  PlaybackDecision,
  PlaybackRequest,
  PlaybackRuntimeState,
} from "./playback-types.js";

export function decidePlayback(request: PlaybackRequest, state: PlaybackRuntimeState): PlaybackDecision {
  const requestProvider = request.provider || "twitch";
  const playerProvider = state.playerProvider || "twitch";
  const mountProvider = state.mountProvider || "twitch";
  const samePlayer = state.playerVodId === request.vodId && playerProvider === requestProvider;
  const mountingSameVod = state.mountInFlight
    && state.mountVodId === request.vodId
    && mountProvider === requestProvider;
  return {
    seekInteractive: state.playerReady && samePlayer,
    mountFallback: !mountingSameVod,
    waitForMount: state.mountInFlight,
    destroyInteractive: !state.mountInFlight && state.hasInteractivePlayer,
    mountInteractive: !state.mountInFlight,
  };
}

export function decideMountContinuation(
  startedRequest: PlaybackRequest,
  desiredRequest: PlaybackRequest | null,
): MountContinuation {
  if (!desiredRequest) return "stop";
  return desiredRequest.requestId === startedRequest.requestId ? "continue" : "restart";
}
