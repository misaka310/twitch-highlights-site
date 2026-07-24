import { DEBUG_ACTIVITY_GAP_SEC, DEBUG_VOD_OFFSET } from "./config.js";
import { buildTwitchVodUrl, formatClock, localizeReason } from "./formatters.js";

export function normalizeData(data) {
  const videos = Array.isArray(data?.videos)
    ? data.videos
    : Array.isArray(data?.vods)
      ? data.vods
      : [];

  return videos
    .filter((video) => video && (video.vod_id || video.id))
    .sort((a, b) => new Date(b.published_at).getTime() - new Date(a.published_at).getTime())
    .slice(DEBUG_VOD_OFFSET, DEBUG_VOD_OFFSET + 3)
    .map(normalizeVod)
    .filter((vod) => vod.segments.length > 0);
}

function normalizeVod(video) {
  const vodId = String(video.vod_id || video.id);
  const vodUrl = video.vod_url || video.url || `https://www.twitch.tv/videos/${vodId}`;
  const items = Array.isArray(video.items)
    ? video.items
    : Array.isArray(video.segments)
      ? video.segments
      : [];

  return {
    id: vodId,
    url: vodUrl,
    title: String(video.title || ""),
    published_at: String(video.published_at || ""),
    count:
      Number.isFinite(Number(video.count)) && Number(video.count) >= 0
        ? Number(video.count)
        : items.length,
    duration_sec:
      Number.isFinite(Number(video.duration_sec)) && Number(video.duration_sec) > 0
        ? Number(video.duration_sec)
        : null,
    chat_total: normalizeChatTotal(video.chat_total),
    comments_per_hour: normalizeCommentsPerHour(video.comments_per_hour),
    thumbnail_url: String(video.thumbnail_url || ""),
    activity_map: normalizeActivityMap(video.activity_map),
    segments: items
      .filter((item) => item && (item.id || item.rank || item.start_sec != null))
      .sort((a, b) => (a.rank ?? a.start_sec) - (b.rank ?? b.start_sec))
      .slice(0, 3)
      .map((item) => normalizeSegment(item, vodId, vodUrl)),
  };
}

function normalizeSegment(item, vodId, vodUrl) {
  return {
    id: item.id || `${vodId}_${item.start_sec}_${item.end_sec}`,
    rank: item.rank ?? null,
    rank_label: item.rank != null ? `#${item.rank}` : "",
    start_sec: item.start_sec,
    end_sec: item.end_sec,
    start_time: item.start_time || formatClock(item.start_sec),
    end_time: item.end_time || formatClock(item.end_sec),
    label:
      item.label ||
      `${item.start_time || formatClock(item.start_sec)} - ${item.end_time || formatClock(item.end_sec)}`,
    summary: String(item.headline || "").trim() || localizeReason(item.reason || item.summary || ""),
    tags: normalizeTags(item.tags),
    watch_url: item.watch_url || buildTwitchVodUrl(vodUrl, item.start_sec),
    screenshot_url: String(item.screenshot_url || "").trim(),
  };
}

export function normalizeActivityMap(activityMap) {
  const bucketSec =
    Number.isFinite(Number(activityMap?.bucket_sec)) && Number(activityMap.bucket_sec) > 0
      ? Number(activityMap.bucket_sec)
      : 10;
  const buckets = Array.isArray(activityMap?.buckets)
    ? activityMap.buckets
      .map((value) => Number(value))
      .filter((value) => Number.isFinite(value) && value >= 0)
    : [];
  const durationSec =
    Number.isFinite(Number(activityMap?.duration_sec)) && Number(activityMap.duration_sec) >= 0
      ? Number(activityMap.duration_sec)
      : buckets.length * bucketSec;
  const inferredLastCommentBucket = (() => {
    for (let index = buckets.length - 1; index >= 0; index -= 1) {
      if (buckets[index] > 0) {
        return index;
      }
    }
    return -1;
  })();
  let lastCommentSec =
    Number.isFinite(Number(activityMap?.last_comment_sec)) && Number(activityMap.last_comment_sec) >= 0
      ? Number(activityMap.last_comment_sec)
      : inferredLastCommentBucket >= 0
        ? (inferredLastCommentBucket + 1) * bucketSec
        : 0;
  const peakCount =
    Number.isFinite(Number(activityMap?.peak_count)) && Number(activityMap.peak_count) >= 0
      ? Number(activityMap.peak_count)
      : Math.max(0, ...buckets);

  if (DEBUG_ACTIVITY_GAP_SEC > 0 && durationSec > 0) {
    lastCommentSec = Math.max(0, Math.min(lastCommentSec, durationSec - DEBUG_ACTIVITY_GAP_SEC));
  }

  return {
    bucket_sec: bucketSec,
    duration_sec: durationSec,
    last_comment_sec: lastCommentSec,
    peak_count: peakCount,
    buckets,
  };
}

export function normalizeTags(tags) {
  if (!Array.isArray(tags)) {
    return [];
  }
  return tags
    .map((tag) => String(tag || "").trim())
    .filter(Boolean)
    .filter((tag, index, all) => all.indexOf(tag) === index)
    .slice(0, 3);
}

export function getInitialSelection(vods) {
  const latestVod = vods[0];
  const firstSegment = latestVod?.segments?.[0] || null;
  return {
    vod: latestVod,
    segment: firstSegment,
    start_sec: normalizeSelectionStartSec(firstSegment?.start_sec),
  };
}

export function applyInitialSelectionToState(state, selection) {
  if (!state || !selection?.vod) {
    return;
  }
  state.selectedVodId = selection.vod.id;
  state.selectedSegmentId = selection.segment?.id ? String(selection.segment.id) : "";
  state.requestedVodId = selection.vod.id;
  state.requestedStartSec = normalizeSelectionStartSec(selection.start_sec);
}

function normalizeChatTotal(value) {
  if (isMissingNumericValue(value)) {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? Math.floor(parsed) : null;
}

function normalizeCommentsPerHour(value) {
  if (isMissingNumericValue(value)) {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function isMissingNumericValue(value) {
  return value == null || (typeof value === "string" && value.trim() === "");
}

function normalizeSelectionStartSec(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? Math.floor(parsed) : 0;
}
