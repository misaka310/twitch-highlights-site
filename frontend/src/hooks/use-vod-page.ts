import { useEffect, useState } from "react";
import {
  VOD_PAGE_SIZE,
  type RuntimeSiteConfig,
  type VodData,
  type VodIndexData,
  type VodPageData,
} from "../domain/vod.js";
import { normalizeDataPath, orderSegments } from "../lib/vod-data.js";

export async function loadVodPage(page: number, fetcher: typeof fetch = fetch): Promise<VodPageData> {
  const [indexResponse, configResponse] = await Promise.all([
    fetcher("/data/vod_index.json", { cache: "no-store" }),
    fetcher("/site-config.json", { cache: "no-store" }),
  ]);
  if (!indexResponse.ok) throw new Error("配信一覧を読み込めませんでした。");
  const index = (await indexResponse.json()) as VodIndexData;
  const siteConfig = configResponse.ok ? ((await configResponse.json()) as RuntimeSiteConfig) : {};
  const entries = Array.isArray(index.videos) ? [...index.videos] : [];
  entries.sort((a, b) => new Date(b.published_at || 0).getTime() - new Date(a.published_at || 0).getTime());
  const pageCount = Math.max(1, Math.ceil(entries.length / VOD_PAGE_SIZE));
  const requestedPage = Math.max(1, Math.floor(Number(page) || 1));
  const resolvedPage = Math.min(requestedPage, pageCount);
  const start = (resolvedPage - 1) * VOD_PAGE_SIZE;
  const pageEntries = entries.slice(start, start + VOD_PAGE_SIZE);
  const detailResults = await Promise.allSettled(
    pageEntries.map(async (entry) => {
      const response = await fetcher(normalizeDataPath(entry.detail_path), { cache: "no-store" });
      if (!response.ok) throw new Error(`VOD ${entry.vod_id} を読み込めませんでした。`);
      const vod = (await response.json()) as VodData;
      return { ...vod, items: orderSegments(vod.items) };
    }),
  );
  const vods = detailResults.flatMap((result) => (result.status === "fulfilled" ? [result.value] : []));
  return {
    requestedPage,
    page: resolvedPage,
    updatedAt: index.updated_at || "",
    nextUpdateAt: index.next_update_at || "",
    vods,
    totalCount: entries.length,
    siteConfig,
  };
}

export function useVodPage(page: number): { data: VodPageData | null; error: string } {
  const [data, setData] = useState<VodPageData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setError("");
    setData(null);
    void loadVodPage(page)
      .then((loaded) => {
        if (!cancelled) setData(loaded);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "データを読み込めませんでした。");
      });
    return () => {
      cancelled = true;
    };
  }, [page]);

  return { data, error };
}
