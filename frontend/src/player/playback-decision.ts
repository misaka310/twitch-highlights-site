import type {
  MountContinuation,
  PlaybackDecision,
  PlaybackRequest,
  PlaybackRuntimeState,
} from "./playback-types.js";

export function decidePlayback(request: PlaybackRequest, state: PlaybackRuntimeState): PlaybackDecision {
  const mountingSameVod = state.mountInFlight && state.mountVodId === request.vodId;
  return {
    seekInteractive: state.playerReady && state.playerVodId === request.vodId,
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
