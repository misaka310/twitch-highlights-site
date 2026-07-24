import {
  DEFAULT_PARENTS,
  INTERACTIVE_CONTAINER_FALLBACK_MIN_HEIGHT_PX,
  INTERACTIVE_CONTAINER_MIN_HEIGHT_PX,
  INTERACTIVE_CONTAINER_STABLE_EPSILON_PX,
  INTERACTIVE_CONTAINER_STABLE_FRAMES,
  INTERACTIVE_CONTAINER_WAIT_TIMEOUT_MS,
  INTERACTIVE_SEEK_STABILIZE_MS,
  TWITCH_PLAYER_SCRIPT_URL,
} from "./config.js";
import { formatTwitchTime } from "./formatters.js";

export function createPlayerController({ state, elements, updateActivityMapProgress }) {
  let playerScriptPromise = null;

function requestPlayback(vodId, startSec, options = {}) {
  const playback = {
    token: ++state.playbackToken,
    vodId: String(vodId || ""),
    startSec: Math.max(0, Number(startSec) || 0),
    autoplay: options.autoplay !== false,
    muted: options.muted !== false,
    triggeredByUser: options.triggeredByUser === true,
    statusLabel:
      options.statusLabel ||
      (options.triggeredByUser === true ? "再生を開始中" : "プレイヤー読込中"),
  };
  const previousVodId = String(state.requestedVodId || "");
  const previousStartSec = Number(state.requestedStartSec);
  const isSeekReadySameVod = isInteractiveSeekReadyForVod(playback.vodId);
  const isMountInFlightSameVod = isInteractiveMountInFlightForVod(playback.vodId);
  const isMountInFlightAnyVod = state.interactiveMountInFlight === true;

  state.desiredPlayback = playback;
  state.requestedVodId = playback.vodId;
  state.requestedStartSec = playback.startSec;
  state.playbackBlocked = false;
  state.currentPlaybackSec = playback.startSec;
  syncExpectedPlaybackIntent(playback);

  if (playback.muted && playback.triggeredByUser) {
    showUnmuteOverlay();
  } else if (!playback.muted) {
    hideUnmuteOverlay();
  }

  updateActivityMapProgress();
  const loadingStartSec =
    isSeekReadySameVod || isMountInFlightSameVod
      ? resolveInteractiveUiStartSec()
      : playback.startSec;
  const loadingMode = isSeekReadySameVod || isMountInFlightSameVod ? "interactive" : "iframe";
  setPlayerUiState("loading", playback.vodId, loadingStartSec, playback.statusLabel, loadingMode);

  if (isSeekReadySameVod) {
    seekDesiredPlayback(playback);
    return;
  }

  const hasSameIframeTarget =
    state.playerMode === "iframe" &&
    previousVodId === playback.vodId &&
    Number.isFinite(previousStartSec) &&
    previousStartSec === playback.startSec;
  const shouldRefreshIframe = !isMountInFlightSameVod && !hasSameIframeTarget;

  if (shouldRefreshIframe) {
    if (state.playerMode === "interactive") {
      destroyInteractivePlayer({ preserveMountState: true });
    }
    mountIframePlayer(playback);
  }

  if (isMountInFlightAnyVod) {
    return;
  }

  void mountInteractivePlayer(playback);
}


function mountIframePlayer(playback) {
  ensurePlayerContainerLayout();
  const src = buildEmbedUrl(
    playback.vodId,
    playback.startSec,
    playback.muted,
    playback.autoplay,
    playback.token
  );
  const iframe =
    elements.player.querySelector(".player-embed-frame") || document.createElement("iframe");

  iframe.className = "player-embed-frame";
  iframe.title = "Twitch";
  iframe.allow = "autoplay; fullscreen";
  iframe.setAttribute("allowfullscreen", "");
  iframe.setAttribute("scrolling", "no");
  iframe.setAttribute("frameborder", "0");
  iframe.width = "100%";
  iframe.height = "100%";

  state.playerReady = false;
  state.playerMode = "iframe";
  stopPlayerPolling();
  if (iframe.parentElement !== elements.player) {
    elements.player.replaceChildren(iframe);
  }
  iframe.src = src;

  iframe.addEventListener("load", () => {
    if (playback.token !== state.playbackToken) {
      return;
    }
    state.playerReady = true;
    state.playbackBlocked = false;
    setPlayerUiState("ready", playback.vodId, playback.startSec, "プレイヤー準備完了", "iframe");
  });
}


function seekDesiredPlayback(playback) {
  if (!isInteractiveSeekReadyForVod(playback.vodId)) {
    return;
  }

  ensureInteractiveEmbedLayout();
  const player = state.playerInstance;
  safeSetMuted(player, playback.muted);
  state.currentPlaybackSec = playback.startSec;
  seekInteractivePlayer(player, playback.startSec, { shouldPlay: playback.autoplay !== false });

  state.playerMode = "interactive";
  state.playerReady = true;
  state.playbackBlocked = false;
  startPlayerPolling();
  setInteractiveUiState(playback.autoplay !== false ? "playing" : "ready", playback.statusLabel);
}


async function mountInteractivePlayer(playback) {
  if (!elements.player) {
    return;
  }

  const mountStartSec = Math.max(0, Number(playback.startSec) || 0);
  state.interactiveMountInFlight = true;
  state.interactiveMountToken = playback.token;
  state.interactiveMountVodId = playback.vodId;
  ensurePlayerContainerLayout();
  const scriptLoaded = await ensurePlayerScript();
  if (!scriptLoaded || typeof window.Twitch?.Player !== "function") {
    clearInteractiveMountState(playback.token);
    setPlayerUiState("error", playback.vodId, playback.startSec, "Twitch player init failed", "interactive");
    return;
  }
  if (!isInteractiveMountStillRelevant(playback)) {
    restartDesiredInteractiveMount(playback.token);
    return;
  }

  destroyInteractivePlayer({ preserveMountState: true });

  const inner = document.createElement("div");
  inner.id = "twitch-player-inner";
  inner.className = "player-embed-slot";
  elements.player.replaceChildren(inner);
  ensureInteractiveEmbedLayout();
  await waitForInteractiveContainerRect(playback);
  if (!isInteractiveMountStillRelevant(playback)) {
    restartDesiredInteractiveMount(playback.token);
    return;
  }

  const PlayerClass = window.Twitch.Player;
  const player = new PlayerClass(inner, {
    width: "100%",
    height: "100%",
    video: playback.vodId,
    parent: getTwitchParents(),
    autoplay: playback.autoplay !== false,
    muted: playback.muted,
    time: formatTwitchTime(playback.startSec),
    playsinline: true,
  });

  state.playerInstance = player;
  state.interactiveVodId = playback.vodId;
  state.playerMode = "interactive";
  state.playerReady = false;
  state.playbackBlocked = false;

  const readyEventName = PlayerClass.READY || "ready";
  const playEventName = PlayerClass.PLAY || "play";
  const playingEventName = PlayerClass.PLAYING || "playing";
  const pauseEventName = PlayerClass.PAUSE || "pause";
  const endedEventName = PlayerClass.ENDED || "ended";
  const blockedEventName = PlayerClass.PLAYBACK_BLOCKED || "playback_blocked";

  addPlayerEventListener(player, readyEventName, () => {
    if (player !== state.playerInstance) {
      return;
    }
    ensureInteractiveEmbedLayout();
    startPlayerPolling();
    state.playerReady = true;
    clearInteractiveMountState(playback.token);
    state.playbackBlocked = false;
    setInteractiveUiState("ready", "Player ready");

    const targetPlayback = state.desiredPlayback || playback;
    if (targetPlayback.vodId !== playback.vodId) {
      requestPlayback(targetPlayback.vodId, targetPlayback.startSec, targetPlayback);
      return;
    }
    safeSetMuted(player, targetPlayback.muted);
    state.currentPlaybackSec = targetPlayback.startSec;
    const shouldAutoplay = targetPlayback.autoplay !== false;
    if (Number(targetPlayback.startSec) !== mountStartSec) {
      seekInteractivePlayer(player, targetPlayback.startSec, { shouldPlay: shouldAutoplay });
    } else if (shouldAutoplay) {
      safePlay(player);
    }
    setInteractiveUiState(shouldAutoplay ? "playing" : "ready", targetPlayback.statusLabel);
  });

  addPlayerEventListener(player, playEventName, () => {
    if (player !== state.playerInstance) {
      return;
    }
    state.playbackBlocked = false;
    setInteractiveUiState("playing", "Playing");
  });
  if (String(playingEventName) !== String(playEventName)) {
    addPlayerEventListener(player, playingEventName, () => {
      if (player !== state.playerInstance) {
        return;
      }
      state.playbackBlocked = false;
      setInteractiveUiState("playing", "Playing");
    });
  }
  addPlayerEventListener(player, pauseEventName, () => {
    if (player !== state.playerInstance) {
      return;
    }
    setInteractiveUiState("ready", "Player ready");
  });
  addPlayerEventListener(player, endedEventName, () => {
    if (player !== state.playerInstance) {
      return;
    }
    setInteractiveUiState("ready", "Player ready");
  });
  if (
    String(blockedEventName) !== String(readyEventName) &&
    String(blockedEventName) !== String(playEventName) &&
    String(blockedEventName) !== String(playingEventName) &&
    String(blockedEventName) !== String(pauseEventName) &&
    String(blockedEventName) !== String(endedEventName)
  ) {
    addPlayerEventListener(player, blockedEventName, () => {
      if (player !== state.playerInstance) {
        return;
      }
      state.playbackBlocked = true;
      setInteractiveUiState("blocked", "Playback blocked");
    });
  }

}


function destroyInteractivePlayer(options = {}) {
  const preserveMountState = options.preserveMountState === true;
  stopPlayerPolling();
  state.playerReady = false;
  state.interactiveVodId = null;
  if (!preserveMountState) {
    clearInteractiveMountState();
  }
  if (!state.playerInstance) {
    return;
  }

  try {
    state.playerInstance.pause?.();
  } catch (error) {
    // Ignore cleanup failures from the Twitch embed.
  }
  try {
    state.playerInstance.destroy?.();
  } catch (error) {
    // Ignore cleanup failures from the Twitch embed.
  }
  state.playerInstance = null;
}


function isInteractiveSeekReadyForVod(vodId) {
  const targetVodId = String(vodId || "");
  if (!targetVodId) {
    return false;
  }
  return (
    state.playerMode === "interactive" &&
    Boolean(state.playerInstance) &&
    state.playerReady === true &&
    String(state.interactiveVodId || "") === targetVodId
  );
}


function isInteractiveMountInFlightForVod(vodId) {
  const targetVodId = String(vodId || "");
  if (!targetVodId) {
    return false;
  }
  const hasMountMarker =
    state.interactiveMountInFlight === true && String(state.interactiveMountVodId || "") === targetVodId;
  if (hasMountMarker) {
    return true;
  }
  return (
    state.playerMode === "interactive" &&
    Boolean(state.playerInstance) &&
    state.playerReady === false &&
    String(state.interactiveVodId || "") === targetVodId
  );
}


function isInteractiveMountStillRelevant(playback) {
  if (!playback) {
    return false;
  }
  if (Number(playback.token) === Number(state.playbackToken)) {
    return true;
  }

  const desiredPlayback = state.desiredPlayback;
  return (
    state.interactiveMountInFlight === true &&
    Number(state.interactiveMountToken) === Number(playback.token) &&
    String(state.interactiveMountVodId || "") === String(playback.vodId || "") &&
    String(desiredPlayback?.vodId || "") === String(playback.vodId || "")
  );
}


function restartDesiredInteractiveMount(staleToken) {
  clearInteractiveMountState(staleToken);
  const desiredPlayback = state.desiredPlayback;
  if (!desiredPlayback || Number(desiredPlayback.token) !== Number(state.playbackToken)) {
    return;
  }
  if (isInteractiveSeekReadyForVod(desiredPlayback.vodId) || state.interactiveMountInFlight === true) {
    return;
  }
  void mountInteractivePlayer(desiredPlayback);
}


function clearInteractiveMountState(token = null) {
  if (token != null && Number(state.interactiveMountToken) !== Number(token)) {
    return;
  }
  state.interactiveMountInFlight = false;
  state.interactiveMountToken = 0;
  state.interactiveMountVodId = null;
}


function addPlayerEventListener(player, eventName, callback) {
  if (!player || !eventName || typeof player.addEventListener !== "function") {
    return;
  }
  player.addEventListener(eventName, callback);
}


function safeSeek(player, startSec) {
  if (!player || typeof player.seek !== "function") {
    return false;
  }
  try {
    player.seek(startSec);
    return true;
  } catch (error) {
    return false;
  }
}


function safePlay(player) {
  if (!player || typeof player.play !== "function") {
    return;
  }
  try {
    const playResult = player.play();
    if (playResult && typeof playResult.catch === "function") {
      playResult.catch(() => {});
    }
  } catch (error) {
    // Ignore play failures (autoplay may still be restricted by browser policy).
  }
}


function safeSetMuted(player, muted) {
  if (!player || typeof player.setMuted !== "function") {
    return;
  }
  try {
    player.setMuted(Boolean(muted));
  } catch (error) {
    // Ignore mute failures.
  }
}


async function ensurePlayerScript() {
  if (typeof window.Twitch?.Player === "function") {
    state.playerScriptReady = true;
    return true;
  }

  if (!playerScriptPromise) {
    playerScriptPromise = new Promise((resolve) => {
      const existing = document.querySelector(`script[src="${TWITCH_PLAYER_SCRIPT_URL}"]`);
      const script = existing || document.createElement("script");

      const handleLoad = () => {
        const ready = typeof window.Twitch?.Player === "function";
        state.playerScriptReady = ready;
        resolve(ready);
      };
      const handleError = () => {
        state.playerScriptReady = false;
        resolve(false);
      };

      script.addEventListener("load", handleLoad, { once: true });
      script.addEventListener("error", handleError, { once: true });

      if (existing) {
        if (
          script.dataset.loaded === "true" ||
          script.readyState === "loaded" ||
          script.readyState === "complete"
        ) {
          handleLoad();
        }
        return;
      }

      script.src = TWITCH_PLAYER_SCRIPT_URL;
      script.async = true;
      document.head.append(script);
    }).finally(() => {
      playerScriptPromise = null;
    });
  }

  return playerScriptPromise;
}


function startPlayerPolling() {
  stopPlayerPolling();
  state.playerPollId = window.setInterval(syncPlayerTimeFromApi, 500);
}


function stopPlayerPolling() {
  if (state.playerPollId != null) {
    window.clearInterval(state.playerPollId);
    state.playerPollId = null;
  }
}


function syncPlayerTimeFromApi() {
  if (!state.playerInstance) {
    return;
  }

  const currentTime = getInteractiveCurrentTime();
  if (!Number.isFinite(currentTime)) {
    return;
  }
  if (shouldSkipTransientInteractiveTime(currentTime)) {
    return;
  }
  const flooredSec = Math.max(0, Math.floor(currentTime));
  state.currentPlaybackSec = flooredSec;
  clearInteractiveSeekGuardIfSettled(currentTime);
  updateActivityMapProgress();
  syncInteractiveCurrentStartSec();
}


function getPlayerCurrentTimeValue(player) {
  if (!player || typeof player.getCurrentTime !== "function") {
    return null;
  }
  try {
    const currentTime = Number(player.getCurrentTime());
    return Number.isFinite(currentTime) ? Math.max(0, currentTime) : null;
  } catch (error) {
    return null;
  }
}


function getInteractiveCurrentTime() {
  try {
    const currentTime = Number(state.playerInstance.getCurrentTime());
    return Number.isFinite(currentTime) ? Math.max(0, currentTime) : null;
  } catch (error) {
    // Ignore transient player API failures while the embed initializes.
    return null;
  }
}


function shouldSkipTransientInteractiveTime(currentTime) {
  const seekTarget = Number(state.lastInteractiveSeekTargetSec);
  if (!Number.isFinite(seekTarget)) {
    return false;
  }
  const seekAgeMs = Date.now() - Number(state.lastInteractiveSeekAt || 0);
  if (seekAgeMs > INTERACTIVE_SEEK_STABILIZE_MS || seekAgeMs < 0) {
    return false;
  }
  return Math.abs(currentTime - seekTarget) > 5;
}


function markInteractiveSeek(startSec) {
  const seekTarget = Math.max(0, Number(startSec) || 0);
  state.lastInteractiveSeekTargetSec = seekTarget;
  state.lastInteractiveSeekAt = Date.now();
}


function clearInteractiveSeekGuardIfSettled(currentTime) {
  const seekTarget = Number(state.lastInteractiveSeekTargetSec);
  if (!Number.isFinite(seekTarget)) {
    return;
  }
  const seekAgeMs = Date.now() - Number(state.lastInteractiveSeekAt || 0);
  if (seekAgeMs > INTERACTIVE_SEEK_STABILIZE_MS || seekAgeMs < 0) {
    state.lastInteractiveSeekTargetSec = null;
    state.lastInteractiveSeekAt = 0;
    return;
  }
  if (Math.abs(currentTime - seekTarget) <= 6) {
    state.lastInteractiveSeekTargetSec = null;
    state.lastInteractiveSeekAt = 0;
  }
}


function seekInteractivePlayer(player, startSec, options = {}) {
  if (!player) {
    return;
  }
  const seekTarget = Math.max(0, Number(startSec) || 0);
  const shouldPlay = options.shouldPlay !== false;
  markInteractiveSeek(seekTarget);
  if (player !== state.playerInstance) {
    return;
  }
  safeSeek(player, seekTarget);
  if (shouldPlay) {
    safePlay(player);
  }
  scheduleInteractiveTimeSync();
}


function scheduleInteractiveTimeSync() {
  syncPlayerTimeFromApi();
  window.setTimeout(syncPlayerTimeFromApi, 180);
  window.setTimeout(syncPlayerTimeFromApi, 520);
  window.setTimeout(syncPlayerTimeFromApi, 1100);
}


function getRewindBaseSec(fallbackSec) {
  const liveCurrentSec = getInteractiveCurrentTime();
  if (Number.isFinite(liveCurrentSec)) {
    return liveCurrentSec;
  }
  if (Number.isFinite(Number(state.currentPlaybackSec))) {
    return Number(state.currentPlaybackSec);
  }
  if (Number.isFinite(Number(fallbackSec))) {
    return Number(fallbackSec);
  }
  return 0;
}


function getTwitchParents() {
  const hostname = String(location.hostname || "").trim();
  if (!hostname) {
    return DEFAULT_PARENTS;
  }
  return Array.from(new Set([hostname, ...DEFAULT_PARENTS]));
}


function buildEmbedUrl(vodId, startSec, muted, autoplay, token = state.playbackToken) {
  const url = new URL("https://player.twitch.tv/");
  url.searchParams.set("video", String(vodId).replace(/^v/i, ""));
  url.searchParams.set("autoplay", autoplay ? "true" : "false");
  url.searchParams.set("muted", muted ? "true" : "false");
  url.searchParams.set("playsinline", "true");
  url.searchParams.set("seq", String(token));
  url.searchParams.set("time", formatTwitchTime(startSec));
  getTwitchParents().forEach((parent) => {
    url.searchParams.append("parent", parent);
  });
  return url.toString();
}


function syncExpectedPlaybackIntent(playback) {
  if (!elements.playerFrame) {
    return;
  }
  elements.playerFrame.dataset.expectedAutoplay = String(playback?.autoplay !== false);
  elements.playerFrame.dataset.expectedMuted = String(playback?.muted === true);
  elements.playerFrame.dataset.triggeredByUser = String(playback?.triggeredByUser === true);
}


function setPlayerUiState(status, vodId, startSec, label, mode = state.playerMode) {
  if (elements.playerFrame) {
    elements.playerFrame.dataset.playerStatus = status == null ? "" : String(status);
    elements.playerFrame.dataset.currentVodId = vodId == null ? "" : String(vodId);
    elements.playerFrame.dataset.currentStartSec = startSec == null || startSec === "" ? "" : String(startSec);
    elements.playerFrame.dataset.playerMode = mode == null ? "" : String(mode);
  }

  if (elements.playerStatusText) {
    elements.playerStatusText.textContent = label || "";
  }
}


function ensurePlayerContainerLayout() {
  if (!elements.player) {
    return;
  }
  elements.player.classList.add("player-embed--mounted");
}


function ensureInteractiveEmbedLayout() {
  const inner = elements.player?.querySelector("#twitch-player-inner");
  if (!inner) {
    return;
  }
  inner.classList.add("player-embed-slot--interactive");

  const iframeNodes = inner.querySelectorAll("iframe");
  iframeNodes.forEach((iframe) => {
    iframe.classList.add("player-embed-slot__sdk-iframe");

    let wrapper = iframe.parentElement;
    while (wrapper && wrapper !== inner) {
      if (wrapper.tagName === "DIV") {
        wrapper.classList.add("player-embed-slot__sdk-wrapper");
      }
      wrapper = wrapper.parentElement;
    }
  });
}


function resolveInteractiveContainerMinHeightPx(outerHeight, frameHeight) {
  const baseHeight = Math.max(Number(outerHeight) || 0, Number(frameHeight) || 0);
  const dynamicHeight = Math.floor(baseHeight * 0.8);
  return Math.max(
    INTERACTIVE_CONTAINER_FALLBACK_MIN_HEIGHT_PX,
    Math.min(INTERACTIVE_CONTAINER_MIN_HEIGHT_PX, dynamicHeight || INTERACTIVE_CONTAINER_FALLBACK_MIN_HEIGHT_PX)
  );
}


function waitForAnimationFrame() {
  return new Promise((resolve) => {
    if (typeof window.requestAnimationFrame === "function") {
      window.requestAnimationFrame(() => resolve());
      return;
    }
    window.setTimeout(resolve, 16);
  });
}


async function waitForInteractiveContainerRect(playback) {
  const startedAt = Date.now();
  let stableFrames = 0;
  let previousOuterHeight = null;
  let previousInnerHeight = null;

  while (Date.now() - startedAt <= INTERACTIVE_CONTAINER_WAIT_TIMEOUT_MS) {
    if (!isInteractiveMountStillRelevant(playback)) {
      return false;
    }

    const outerRect = elements.player?.getBoundingClientRect();
    const inner = elements.player?.querySelector("#twitch-player-inner");
    const innerRect = inner?.getBoundingClientRect();
    const frameRect = elements.playerFrame?.getBoundingClientRect();
    const outerHeight = Number(outerRect?.height) || 0;
    const innerHeight = Number(innerRect?.height) || 0;
    const minHeight = resolveInteractiveContainerMinHeightPx(outerHeight, frameRect?.height);
    const hasEnoughHeight = outerHeight >= minHeight && innerHeight >= minHeight;

    if (hasEnoughHeight) {
      const heightsAreStable =
        previousOuterHeight != null &&
        previousInnerHeight != null &&
        Math.abs(previousOuterHeight - outerHeight) <= INTERACTIVE_CONTAINER_STABLE_EPSILON_PX &&
        Math.abs(previousInnerHeight - innerHeight) <= INTERACTIVE_CONTAINER_STABLE_EPSILON_PX;
      stableFrames = heightsAreStable ? stableFrames + 1 : 1;
      if (stableFrames >= INTERACTIVE_CONTAINER_STABLE_FRAMES) {
        return true;
      }
    } else {
      stableFrames = 0;
    }

    previousOuterHeight = outerHeight;
    previousInnerHeight = innerHeight;
    await waitForAnimationFrame();
  }

  return false;
}


function resolveInteractiveUiStartSec() {
  const currentSec = Number(state.currentPlaybackSec);
  if (Number.isFinite(currentSec)) {
    return Math.max(0, Math.floor(currentSec));
  }
  return "";
}


function setInteractiveUiState(status, label) {
  setPlayerUiState(status, state.requestedVodId, resolveInteractiveUiStartSec(), label, "interactive");
}


function syncInteractiveCurrentStartSec() {
  if (!elements.playerFrame || state.playerMode !== "interactive") {
    return;
  }
  const currentStartSec = resolveInteractiveUiStartSec();
  elements.playerFrame.dataset.currentVodId = state.requestedVodId == null ? "" : String(state.requestedVodId);
  elements.playerFrame.dataset.currentStartSec = currentStartSec === "" ? "" : String(currentStartSec);
}


function showUnmuteOverlay() {
  if (elements.playerUnmute) {
    elements.playerUnmute.hidden = false;
  }
}


function hideUnmuteOverlay() {
  if (elements.playerUnmute) {
    elements.playerUnmute.hidden = true;
  }
}


  return {
    requestPlayback,
    destroyInteractivePlayer,
    stopPlayerPolling,
    setPlayerUiState,
    getRewindBaseSec,
    showUnmuteOverlay,
    hideUnmuteOverlay,
  };
}
