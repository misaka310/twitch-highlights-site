import type { HighlightSegment, VodData } from "../domain/vod.js";

export function normalizeDataPath(path: string): string {
  const value = String(path || "").trim();
  if (value.startsWith("/data/")) return value;
  if (value.startsWith("data/")) return `/${value}`;
  return `/data/${value.replace(/^\/+/, "")}`;
}

export function normalizeAssetPath(path = ""): string {
  return normalizeDataPath(path);
}

export function orderSegments(items?: HighlightSegment[]): HighlightSegment[] {
  return [...(Array.isArray(items) ? items : [])]
    .sort((a, b) => Number(a.rank ?? a.start_sec) - Number(b.rank ?? b.start_sec));
}

export function resolveDurationSec(vod: VodData | null): number {
  const direct = Number(vod?.duration_sec);
  if (Number.isFinite(direct) && direct > 0) return direct;
  const activity = Number(vod?.activity_map?.duration_sec);
  if (Number.isFinite(activity) && activity > 0) return activity;
  return Math.max(0, ...orderSegments(vod?.items).map((segment) => Number(segment.end_sec) || 0));
}

export function parsePageSearch(search: string): number {
  const value = Number.parseInt(new URLSearchParams(search).get("page") || "1", 10);
  return Math.max(1, value || 1);
}

export function pageUrl(currentUrl: string, nextPage: number): string {
  const safePage = Math.max(1, Math.floor(Number(nextPage) || 1));
  const url = new URL(currentUrl);
  url.searchParams.set("page", String(safePage));
  return url.toString();
}
