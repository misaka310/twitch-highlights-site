import type { PlaybackRequest } from "./playback-types.js";

export const DEFAULT_TWITCH_PARENTS = ["localhost", "127.0.0.1"];

export function formatTwitchTime(totalSeconds: number): string {
  const total = Math.max(0, Math.floor(Number(totalSeconds) || 0));
  return `${Math.floor(total / 3600)}h${Math.floor((total % 3600) / 60)}m${total % 60}s`;
}

export function getTwitchParents(
  hostname: string,
  defaults: string[] = DEFAULT_TWITCH_PARENTS,
): string[] {
  const currentHostname = String(hostname || "").trim();
  return Array.from(new Set([currentHostname, ...defaults].filter(Boolean)));
}

export function buildEmbedUrl(request: PlaybackRequest, hostname: string): string {
  const url = new URL("https://player.twitch.tv/");
  url.searchParams.set("video", request.vodId.replace(/^v/i, ""));
  url.searchParams.set("autoplay", request.autoplay ? "true" : "false");
  url.searchParams.set("muted", request.muted ? "true" : "false");
  url.searchParams.set("playsinline", "true");
  url.searchParams.set("seq", String(request.requestId));
  url.searchParams.set("time", formatTwitchTime(request.startSec));
  getTwitchParents(hostname).forEach((parent) => url.searchParams.append("parent", parent));
  return url.toString();
}
