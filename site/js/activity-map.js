import {
  ACTIVITY_MAP_MAX_DRAW_POINTS_DESKTOP,
  ACTIVITY_MAP_MAX_DRAW_POINTS_MOBILE,
  ACTIVITY_MAP_SMOOTHING_RADIUS_DESKTOP,
  ACTIVITY_MAP_SMOOTHING_RADIUS_MOBILE,
  ACTIVITY_MAP_VIEWBOX_HEIGHT,
  ACTIVITY_MAP_VIEWBOX_WIDTH,
  MOBILE_MEDIA_QUERY,
} from "./config.js";
import { formatClock } from "./formatters.js";

export function createActivityMapController({ elements, state, getSelectedSegment }) {
function renderActivityMap(vod) {
  if (!elements.activityMap) {
    return;
  }

  if (!vod?.activity_map?.buckets?.length) {
    elements.activityMap.hidden = true;
    hideActivityMapSegmentRange();
    return;
  }

  const renderOptions = resolveActivityMapRenderOptions();
  const smoothed = smoothBuckets(vod.activity_map.buckets, renderOptions.smoothingRadius);
  const sampled = downsampleBuckets(smoothed, renderOptions.maxDrawPoints);
  const peak = Math.max(1, ...sampled);
  const lastIndex = Math.max(1, sampled.length - 1);
  const points = sampled.map((value, index) => {
    const x = (index / lastIndex) * ACTIVITY_MAP_VIEWBOX_WIDTH;
    const ratio = value / peak;
    const y = ACTIVITY_MAP_VIEWBOX_HEIGHT - ratio * (ACTIVITY_MAP_VIEWBOX_HEIGHT - 8);
    return `${x.toFixed(2)} ${y.toFixed(2)}`;
  });

  elements.activityMap.hidden = false;
  elements.activityMapPath.setAttribute(
    "d",
    `M 0 ${ACTIVITY_MAP_VIEWBOX_HEIGHT} L ${points.join(" L ")} L ${ACTIVITY_MAP_VIEWBOX_WIDTH} ${ACTIVITY_MAP_VIEWBOX_HEIGHT} Z`
  );
  elements.activityMapButton.setAttribute("aria-label", `${vod.title} の盛り上がりマップ`);
  elements.activityMapDuration.textContent = formatClock(vod.activity_map.duration_sec);
  updateActivityMapProgress();
}


function updateActivityMapProgress() {
  const selection = getSelectedSegment();
  const vod = selection?.vod;

  if (!vod?.activity_map?.duration_sec || !elements.activityMapMarker || !elements.activityMapProgress) {
    hideActivityMapSegmentRange();
    if (elements.activityMapUnavailable) {
      elements.activityMapUnavailable.setAttribute("x", String(ACTIVITY_MAP_VIEWBOX_WIDTH));
      elements.activityMapUnavailable.setAttribute("width", "0");
      elements.activityMapUnavailable.setAttribute("hidden", "");
    }
    if (elements.activityMapCurrent) {
      elements.activityMapCurrent.textContent = "00:00:00";
    }
    return;
  }

  const duration = Math.max(1, vod.activity_map.duration_sec);
  updateActivityMapSegmentRange(selection?.segment, duration);
  const currentSec = Math.max(0, Math.min(state.currentPlaybackSec ?? state.requestedStartSec ?? 0, duration));
  const markerX = (currentSec / duration) * ACTIVITY_MAP_VIEWBOX_WIDTH;
  elements.activityMapCurrent.textContent = formatClock(currentSec);
  elements.activityMapMarker.setAttribute("x1", String(markerX));
  elements.activityMapMarker.setAttribute("x2", String(markerX));
  elements.activityMapProgress.setAttribute(
    "d",
    `M 0 ${ACTIVITY_MAP_VIEWBOX_HEIGHT} L 0 0 L ${markerX.toFixed(2)} 0 L ${markerX.toFixed(2)} ${ACTIVITY_MAP_VIEWBOX_HEIGHT} Z`
  );
}

function updateActivityMapSegmentRange(segment, durationSec) {
  const rangeRect = elements.activityMapSegmentRange;
  if (!rangeRect || !Number.isFinite(Number(durationSec)) || Number(durationSec) <= 0) {
    hideActivityMapSegmentRange();
    return;
  }

  const rawStartSec = Number(segment?.start_sec);
  const rawEndSec = Number(segment?.end_sec);
  if (!Number.isFinite(rawStartSec) || !Number.isFinite(rawEndSec)) {
    hideActivityMapSegmentRange();
    return;
  }

  const clampedStartSec = Math.max(0, Math.min(rawStartSec, durationSec));
  const clampedEndSec = Math.max(0, Math.min(rawEndSec, durationSec));
  if (clampedEndSec <= clampedStartSec) {
    hideActivityMapSegmentRange();
    return;
  }

  const rangeX = (clampedStartSec / durationSec) * ACTIVITY_MAP_VIEWBOX_WIDTH;
  const rangeWidth = ((clampedEndSec - clampedStartSec) / durationSec) * ACTIVITY_MAP_VIEWBOX_WIDTH;
  if (!(rangeWidth > 0)) {
    hideActivityMapSegmentRange();
    return;
  }

  rangeRect.setAttribute("x", rangeX.toFixed(2));
  rangeRect.setAttribute("width", rangeWidth.toFixed(2));
  rangeRect.removeAttribute("hidden");
}

function hideActivityMapSegmentRange() {
  if (!elements.activityMapSegmentRange) {
    return;
  }
  elements.activityMapSegmentRange.setAttribute("x", "0");
  elements.activityMapSegmentRange.setAttribute("width", "0");
  elements.activityMapSegmentRange.setAttribute("hidden", "");
}


  return {
    renderActivityMap,
    updateActivityMapProgress,
  };
}

export function resolveUnavailableRatio(activityMap) {
  const duration = Math.max(0, Number(activityMap?.duration_sec) || 0);
  const lastCommentSec = Math.max(0, Number(activityMap?.last_comment_sec) || 0);
  if (duration <= 0 || lastCommentSec <= 0 || lastCommentSec >= duration) {
    return 0;
  }
  return Math.min(1, Math.max(0, (duration - lastCommentSec) / duration));
}


export function smoothBuckets(buckets, radius = ACTIVITY_MAP_SMOOTHING_RADIUS_DESKTOP) {
  const safeRadius = Math.max(0, Math.floor(Number(radius) || 0));
  return buckets.map((_, index) => {
    let total = 0;
    let count = 0;
    for (let offset = -safeRadius; offset <= safeRadius; offset += 1) {
      const value = buckets[index + offset];
      if (value == null) {
        continue;
      }
      total += value;
      count += 1;
    }
    return count > 0 ? total / count : 0;
  });
}

function resolveActivityMapRenderOptions() {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return {
      maxDrawPoints: ACTIVITY_MAP_MAX_DRAW_POINTS_DESKTOP,
      smoothingRadius: ACTIVITY_MAP_SMOOTHING_RADIUS_DESKTOP,
    };
  }
  if (window.matchMedia(MOBILE_MEDIA_QUERY).matches) {
    return {
      maxDrawPoints: ACTIVITY_MAP_MAX_DRAW_POINTS_MOBILE,
      smoothingRadius: ACTIVITY_MAP_SMOOTHING_RADIUS_MOBILE,
    };
  }
  return {
    maxDrawPoints: ACTIVITY_MAP_MAX_DRAW_POINTS_DESKTOP,
    smoothingRadius: ACTIVITY_MAP_SMOOTHING_RADIUS_DESKTOP,
  };
}

export function downsampleBuckets(buckets, maxPoints) {
  if (!Array.isArray(buckets) || buckets.length <= maxPoints) {
    return Array.isArray(buckets) ? buckets : [];
  }

  const chunkSize = Math.ceil(buckets.length / maxPoints);
  const sampled = [];

  for (let index = 0; index < buckets.length; index += chunkSize) {
    const chunk = buckets.slice(index, index + chunkSize);
    if (!chunk.length) {
      continue;
    }
    sampled.push(Math.max(...chunk));
  }

  return sampled;
}

