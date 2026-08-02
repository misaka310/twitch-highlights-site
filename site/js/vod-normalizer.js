import { DEBUG_ACTIVITY_GAP_SEC, DEBUG_VOD_OFFSET } from "./config.js";
import { buildTwitchVodUrl, formatClock, localizeReason } from "./formatters.js";

export function normalizeData(data) {
  const videos = Array.isArray(data.videos)
    ? data.videos
    : Array.isArray(data.vods)
      ? data.vods
      : [];

  const orderedVideos = videos
    .filter((video) => video && (video.vod_id || video.id))
    .sort((a, b) => new Date(b.published_at).getTime() - new Date(a.published_at).getTime());

  return orderedVideos
    .slice(DEBUG_VOD_OFFSET, DEBUG_VOD_OFFSET + 3)
    .map((video) => {
      const vodId = video.vod_id || video.id;
      const vodUrl = video.vod_url || video.url || `https://www.twitch.tv/videos/${vodId}`;
      const items = Array.isArray(video.items)
        ? video.items
        : Array.isArray(video.segments)
          ? video.segments
          : [];
      const anosaTimestampsStatus = normalizeAnosaTimestampsStatus(video.anosa_timestamps_status);
      const anosaTimestampsPath = normalizeAnosaTimestampsPath(video.anosa_timestamps_path);
      const anosaTimestamps = normalizeAnosaTimestamps(
        video.anosa_timestamps,
        vodId,
        vodUrl,
        anosaTimestampsStatus
      );
      const legacyTimestampsStatus = normalizeLegacyTimestampsStatus(video.timestamps_status);


      return {
        id: vodId,
        url: vodUrl,
        title: video.title,
        published_at: video.published_at,
        timestamps_status: legacyTimestampsStatus,
        timestamps_path: normalizeLegacyTimestampsPath(video.timestamps_path),
        anosa_timestamps_status: anosaTimestampsStatus,
        anosa_timestamps_path: anosaTimestampsPath,
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
        thumbnail_url: video.thumbnail_url || "",
        activity_map: normalizeActivityMap(video.activity_map),
        timestamps: anosaTimestamps,
        anosa_timestamps: anosaTimestamps,
        segments: items
          .filter((item) => item && (item.id || item.rank || item.start_sec != null))
          .sort((a, b) => (a.rank ?? a.start_sec) - (b.rank ?? b.start_sec))
          .slice(0, 3)
          .map((item) => ({
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
          })),
      };
    })
    .filter((vod) => vod.segments.length > 0 || vod.timestamps.length > 0 || vod.anosa_timestamps.length > 0);
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

  return { bucket_sec: bucketSec, duration_sec: durationSec, last_comment_sec: lastCommentSec, peak_count: peakCount, buckets };
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
  const firstTimestamp = latestVod?.anosa_timestamps?.[0] || latestVod?.timestamps?.[0] || null;
  const startSec = firstSegment
    ? normalizeSelectionStartSec(firstSegment.start_sec)
    : normalizeSelectionStartSec(firstTimestamp?.start_sec);
  return { vod: latestVod, segment: firstSegment, start_sec: startSec };
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
  if (!Number.isFinite(parsed) || parsed < 0) {
    return null;
  }
  return Math.floor(parsed);
}

function normalizeCommentsPerHour(value) {
  if (isMissingNumericValue(value)) {
    return null;
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return null;
  }
  return parsed;
}

function isMissingNumericValue(value) {
  if (value == null) {
    return true;
  }
  if (typeof value === "string" && value.trim() === "") {
    return true;
  }
  return false;
}

function normalizeAnosaTimestamps(timestamps, vodId, vodUrl, statusValue = "ok") {
  const status = normalizeAnosaTimestampsStatus(statusValue);
  if (status !== "ok") {
    return [];
  }
  if (!Array.isArray(timestamps)) {
    return [];
  }

  return timestamps
    .filter((row) => row && row.start_sec != null)
    .map((row, index) => {
      const startSec = Number(row.start_sec);
      if (!Number.isFinite(startSec) || startSec < 0) {
        return null;
      }
      const safeStartSec = Math.floor(startSec);
      const label = String(row.label || "").trim();
      if (!label) {
        return null;
      }
      return {
        id: String(row.id || `ts_${index + 1}`),
        start_sec: safeStartSec,
        start_time: String(row.start_time || formatClock(safeStartSec)),
        label,
        watch_url: String(row.watch_url || buildTwitchVodUrl(vodUrl, safeStartSec)),
      };
    })
    .filter(Boolean)
    .sort((a, b) => a.start_sec - b.start_sec)
    .slice(0, 10);
}

function normalizeAnosaTimestampsStatus(value) {
  const status = String(value || "").trim().toLowerCase();
  if (status === "ok" || status === "pending" || status === "error" || status === "alignment_failed") {
    return status;
  }
  return "";
}

function normalizeLegacyTimestampsStatus(value) {
  const status = String(value || "").trim().toLowerCase();
  if (status === "ok" || status === "pending" || status === "error" || status === "alignment_failed") {
    return status;
  }
  return "";
}

function normalizeAnosaTimestampsPath(value) {
  let path = String(value || "").trim();
  if (!path) {
    return "";
  }
  if (path.startsWith("data/anosa-timestamps/")) {
    path = `/${path}`;
  }
  if (!path.startsWith("/data/anosa-timestamps/")) {
    return "";
  }
  if (!path.endsWith(".json")) {
    return "";
  }
  return path;
}

function normalizeLegacyTimestampsPath(value) {
  let path = String(value || "").trim();
  if (!path) {
    return "";
  }
  if (path.startsWith("data/timestamps/")) {
    path = `/${path}`;
  }
  if (!path.startsWith("/data/timestamps/")) {
    return "";
  }
  if (!path.endsWith(".json")) {
    return "";
  }
  return path;
}

function normalizeSelectionStartSec(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return 0;
  }
  return Math.floor(parsed);
}

