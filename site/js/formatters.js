const JST_TIME_ZONE = "Asia/Tokyo";
const JST_OFFSET_MS = 9 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;

export function formatDate(value) {
  return new Intl.DateTimeFormat("ja-JP", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: JST_TIME_ZONE,
  }).format(new Date(value));
}


export function formatDateOnly(value) {
  return new Intl.DateTimeFormat("ja-JP", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: JST_TIME_ZONE,
  }).format(new Date(value));
}


export function formatDateOnlyMobile(value) {
  return new Intl.DateTimeFormat("ja-JP", {
    month: "2-digit",
    day: "2-digit",
    timeZone: JST_TIME_ZONE,
  }).format(new Date(value));
}


export function formatScheduleDate(value) {
  return new Intl.DateTimeFormat("ja-JP", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: JST_TIME_ZONE,
  }).format(new Date(value));
}

function toValidDate(value) {
  const parsed = value instanceof Date ? new Date(value.getTime()) : new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function resolveJstNineUtcMsForDate(baseDate) {
  const jstDate = new Date(baseDate.getTime() + JST_OFFSET_MS);
  return Date.UTC(jstDate.getUTCFullYear(), jstDate.getUTCMonth(), jstDate.getUTCDate(), 0, 0, 0, 0);
}

export function resolveNextJstNineUpdateAt(baseAt, nowAt = new Date()) {
  const now = toValidDate(nowAt) || new Date();
  const base = toValidDate(baseAt) || now;
  const candidateFromBaseUtcMs = resolveJstNineUtcMsForDate(base);
  if (candidateFromBaseUtcMs > now.getTime()) {
    return new Date(candidateFromBaseUtcMs).toISOString();
  }
  let nextFromNowUtcMs = resolveJstNineUtcMsForDate(now);
  if (nextFromNowUtcMs <= now.getTime()) {
    nextFromNowUtcMs += DAY_MS;
  }
  return new Date(nextFromNowUtcMs).toISOString();
}


export function resolveNextUpdateAt(nextUpdateAt, updatedAt, nowAt = new Date()) {
  const now = toValidDate(nowAt) || new Date();
  const parsedNext = toValidDate(nextUpdateAt);

  if (parsedNext && parsedNext > now) {
    return parsedNext.toISOString();
  }

  return resolveNextJstNineUpdateAt(updatedAt, now);
}


export function getVodOrderLabel(index) {
  if (index === 0) {
    return "最新";
  }
  if (index === 1) {
    return "1つ前";
  }
  if (index === 2) {
    return "2つ前";
  }
  return `過去 ${index}`;
}


export function buildTwitchVodUrl(baseUrl, startSec) {
  const url = new URL(baseUrl);
  url.searchParams.set("t", formatTwitchTime(startSec));
  return url.toString();
}


export function formatTwitchTime(totalSeconds) {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return `${hours}h${minutes}m${seconds}s`;
}


export function formatClock(totalSeconds) {
  const hours = String(Math.floor(totalSeconds / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${hours}:${minutes}:${seconds}`;
}


export function formatShortClock(totalSeconds) {
  const hours = String(Math.floor(totalSeconds / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, "0");
  return `${hours}:${minutes}`;
}


export function formatSegmentLabelCompact(startSec) {
  return formatShortClock(startSec);
}


export function formatSegmentRange(label) {
  if (!label) {
    return "";
  }

  const [start, end] = label.split(" - ");
  if (!start || !end) {
    return label;
  }

  return `開始 ${start} / 終了 ${end}`;
}


export function localizeReason(reason) {
  const text = String(reason || "").trim();
  const match = text.match(/^Chat activity spike around (.+?) \(z-score=[^)]+\)\.?$/i);
  if (match) {
    return "コメントが集中した場面";
  }

  return text
    .replace(/^\d+h\d+m\d+s\s*/i, "")
    .replace(/\s*\(z-score=[^)]+\)\.?/gi, "")
    .trim();
}

