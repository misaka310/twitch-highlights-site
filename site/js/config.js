export const DATA_URL = "../../data/vods.json?v=20260327-3";
export const DATA_INDEX_URL = "../../data/vod_index.json?v=20260414-1";
export const DETAILS_PER_PAGE = 3;
export const CACHE_KEY = "twitch-highlights-site:vod-data:v7";
export const SITE_BUILD_LABEL = "mobile player fit inline 20260730";
export const SCHEDULE_TEXT = {
  dataUpdated: "更新",
  nextDataUpdate: "次回更新予定",
  unset: "未設定",
};
export const DEFAULT_PARENTS = ["localhost", "127.0.0.1"];
export const ACTIVITY_MAP_VIEWBOX_WIDTH = 1000;
export const ACTIVITY_MAP_VIEWBOX_HEIGHT = 88;
export const MOBILE_MEDIA_QUERY = "(max-width: 640px)";
export const ACTIVITY_MAP_MAX_DRAW_POINTS_DESKTOP = 320;
export const ACTIVITY_MAP_MAX_DRAW_POINTS_MOBILE = 120;
export const ACTIVITY_MAP_SMOOTHING_RADIUS_DESKTOP = 2;
export const ACTIVITY_MAP_SMOOTHING_RADIUS_MOBILE = 3;
export const QUERY_PARAMS = new URLSearchParams(location.search);
export const DEBUG_VOD_OFFSET = Math.max(0, Number.parseInt(QUERY_PARAMS.get("vodOffset") || "0", 10) || 0);
export const DEBUG_ACTIVITY_GAP_SEC = Math.max(0, Number.parseInt(QUERY_PARAMS.get("debugActivityGapSec") || "0", 10) || 0);
export const DEBUG_SMALL_PLAYER = QUERY_PARAMS.get("debugSmallPlayer") === "1";
export const DEBUG_NO_FLOATING_UNMUTE = QUERY_PARAMS.get("debugNoFloatingUnmute") === "1";
export const TWITCH_PLAYER_SCRIPT_URL = "https://player.twitch.tv/js/embed/v1.js";
export const INTERACTIVE_SEEK_STABILIZE_MS = 2500;
export const INTERACTIVE_CONTAINER_MIN_HEIGHT_PX = 400;
export const INTERACTIVE_CONTAINER_FALLBACK_MIN_HEIGHT_PX = 200;
export const INTERACTIVE_CONTAINER_STABLE_FRAMES = 2;
export const INTERACTIVE_CONTAINER_STABLE_EPSILON_PX = 1;
export const INTERACTIVE_CONTAINER_WAIT_TIMEOUT_MS = 3200;

export function createInitialState() {
  return {
  vods: [],
  pageOffset: 0,
  selectedVodId: null,
  selectedSegmentId: null,
  requestedVodId: null,
  requestedStartSec: null,
  desiredPlayback: null,
  playbackToken: 0,
  playerMode: "iframe",
  playerReady: false,
  playbackBlocked: false,
  playerInstance: null,
  interactiveVodId: null,
  interactiveMountInFlight: false,
  interactiveMountToken: 0,
  interactiveMountVodId: null,
  playerScriptReady: typeof window.Twitch?.Player === "function",
  playerPollId: null,
  currentPlaybackSec: null,
  lastInteractiveSeekTargetSec: null,
  lastInteractiveSeekAt: 0,
};
}

export function applyDebugFlags() {
  document.documentElement.classList.toggle("debug-small-player", DEBUG_SMALL_PLAYER);
  document.documentElement.classList.toggle("debug-no-floating-unmute", DEBUG_NO_FLOATING_UNMUTE);
}
