import { DEFAULT_PARENTS } from "./config.js";
import { formatTwitchTime } from "./formatters.js";

const DIRECT_MOUNT_LOCK_MS = 5000;

export function createPlaybackRequestRouter({
  state,
  elements,
  playerController,
  updateActivityMapProgress,
}) {
  const controllerRequestPlayback = playerController.requestPlayback;

  return function requestPlayback(vodId, startSec, options = {}) {
    const targetVodId = String(vodId || "");
    const targetStartSec = Math.max(0, Number(startSec) || 0);
    const triggeredByUser = options.triggeredByUser === true;
    const activeVodId = resolveActiveVodId(state, elements);
    const isCrossVodRequest = Boolean(activeVodId) && activeVodId !== targetVodId;
    const shouldKeepDirectIframe = triggeredByUser && state.playerMode === "iframe";

    if (!triggeredByUser || (!isCrossVodRequest && !shouldKeepDirectIframe)) {
      return controllerRequestPlayback(vodId, startSec, options);
    }

    return mountDirectIframePlayback({
      state,
      elements,
      playerController,
      updateActivityMapProgress,
      playback: {
        token: ++state.playbackToken,
        vodId: targetVodId,
        startSec: targetStartSec,
        autoplay: options.autoplay !== false,
        muted: options.muted !== false,
        triggeredByUser: true,
        statusLabel: options.statusLabel || "再生を開始中",
      },
    });
  };
}

function mountDirectIframePlayback({
  state,
  elements,
  playerController,
  updateActivityMapProgress,
  playback,
}) {
  if (!playback.vodId || !elements.player || !elements.playerFrame) {
    return;
  }

  playerController.stopPlayerPolling();
  destroyInteractiveInstance(state);

  state.desiredPlayback = playback;
  state.requestedVodId = playback.vodId;
  state.requestedStartSec = playback.startSec;
  state.currentPlaybackSec = playback.startSec;
  state.playerMode = "iframe";
  state.playerReady = false;
  state.playbackBlocked = false;
  state.playerInstance = null;
  state.interactiveVodId = null;
  state.lastInteractiveSeekTargetSec = null;
  state.lastInteractiveSeekAt = 0;

  // Prevent an older asynchronous SDK mount from replacing the iframe after the
  // trusted click has already navigated it to the requested VOD.
  state.interactiveMountInFlight = true;
  state.interactiveMountToken = playback.token;
  state.interactiveMountVodId = playback.vodId;

  elements.playerFrame.dataset.expectedAutoplay = String(playback.autoplay);
  elements.playerFrame.dataset.expectedMuted = String(playback.muted);
  elements.playerFrame.dataset.triggeredByUser = "true";
  playerController.setPlayerUiState(
    "loading",
    playback.vodId,
    playback.startSec,
    playback.statusLabel,
    "iframe"
  );

  if (!playback.muted) {
    playerController.hideUnmuteOverlay();
  }

  elements.player.classList.add("player-embed--mounted");
  const iframe = document.createElement("iframe");
  iframe.className = "player-embed-frame";
  iframe.title = "Twitch";
  iframe.allow = "autoplay; fullscreen; picture-in-picture";
  iframe.setAttribute("allowfullscreen", "");
  iframe.setAttribute("scrolling", "no");
  iframe.setAttribute("frameborder", "0");
  iframe.width = "100%";
  iframe.height = "100%";

  iframe.addEventListener(
    "load",
    () => {
      if (playback.token !== state.playbackToken || state.playerMode !== "iframe") {
        return;
      }
      state.playerReady = true;
      state.playbackBlocked = false;
      playerController.setPlayerUiState(
        "ready",
        playback.vodId,
        playback.startSec,
        "プレイヤー準備完了",
        "iframe"
      );
    },
    { once: true }
  );

  elements.player.replaceChildren(iframe);
  iframe.src = buildEmbedUrl(playback);
  updateActivityMapProgress();

  window.setTimeout(() => {
    if (
      state.playerMode === "iframe" &&
      Number(state.interactiveMountToken) === Number(playback.token)
    ) {
      state.interactiveMountInFlight = false;
      state.interactiveMountToken = 0;
      state.interactiveMountVodId = null;
    }
  }, DIRECT_MOUNT_LOCK_MS);
}

function destroyInteractiveInstance(state) {
  const player = state.playerInstance;
  if (!player) {
    return;
  }
  try {
    player.pause?.();
  } catch (error) {
    // Twitch cleanup failures must not delay the trusted iframe navigation.
  }
  try {
    player.destroy?.();
  } catch (error) {
    // The iframe replacement below is the final cleanup fallback.
  }
}

function resolveActiveVodId(state, elements) {
  if (state.playerMode === "interactive" && state.interactiveVodId) {
    return String(state.interactiveVodId);
  }
  const frameVodId = String(elements.playerFrame?.dataset.currentVodId || "");
  return frameVodId || String(state.requestedVodId || "");
}

function buildEmbedUrl(playback) {
  const url = new URL("https://player.twitch.tv/");
  url.searchParams.set("video", playback.vodId.replace(/^v/i, ""));
  url.searchParams.set("autoplay", playback.autoplay ? "true" : "false");
  url.searchParams.set("muted", playback.muted ? "true" : "false");
  url.searchParams.set("playsinline", "true");
  url.searchParams.set("time", formatTwitchTime(playback.startSec));
  url.searchParams.set("seq", String(playback.token));

  const hostname = String(location.hostname || "").trim();
  Array.from(new Set([hostname, ...DEFAULT_PARENTS].filter(Boolean))).forEach((parent) => {
    url.searchParams.append("parent", parent);
  });
  return url.toString();
}
