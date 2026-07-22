import { CACHE_KEY, DATA_INDEX_URL, DATA_URL, DETAILS_PER_PAGE } from "./config.js";

const DEFAULT_PAGE = 1;

export async function loadData() {
  const requestedPage = resolveRequestedPage();
  const cacheKey = buildPageCacheKey(requestedPage);
  const cachedData = readCachedData(cacheKey);

  try {
    const data = await loadPagedData(requestedPage);
    const withSource = { ...data, __source: "live" };
    localStorage.setItem(cacheKey, JSON.stringify(withSource));
    return withSource;
  } catch (error) {
    if (cachedData) {
      cachedData.__source = "cache";
      return cachedData;
    }
  }

  if (requestedPage !== DEFAULT_PAGE) {
    return null;
  }

  return loadLegacyData(cacheKey);
}

function resolveRequestedPage() {
  const raw = new URLSearchParams(location.search).get("page");
  const parsed = Number.parseInt(raw || `${DEFAULT_PAGE}`, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_PAGE;
}

function buildPageCacheKey(page) {
  return `${CACHE_KEY}:page:${page}`;
}

function readCachedData(cacheKey) {
  const cachedRaw = localStorage.getItem(cacheKey);
  if (!cachedRaw) {
    return null;
  }
  try {
    return JSON.parse(cachedRaw);
  } catch (error) {
    localStorage.removeItem(cacheKey);
    return null;
  }
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${url}`);
  }
  return response.json();
}

function extractVideos(payload) {
  if (Array.isArray(payload?.videos)) {
    return payload.videos;
  }
  if (Array.isArray(payload?.vods)) {
    return payload.vods;
  }
  return [];
}

function buildPageInfo({ requestedPage, totalItems }) {
  const totalPages = Math.max(1, Math.ceil(totalItems / DETAILS_PER_PAGE));
  const page = Math.max(DEFAULT_PAGE, Math.min(requestedPage, totalPages));
  return {
    requested_page: requestedPage,
    page,
    page_size: DETAILS_PER_PAGE,
    total_pages: totalPages,
    total_items: totalItems,
    has_prev: page > DEFAULT_PAGE,
    has_next: page < totalPages,
  };
}

async function loadPagedData(requestedPage) {
  const indexData = await fetchJson(DATA_INDEX_URL);
  const indexVideos = extractVideos(indexData);
  const pageInfo = buildPageInfo({ requestedPage, totalItems: indexVideos.length });
  const startIndex = (pageInfo.page - 1) * DETAILS_PER_PAGE;
  const targetEntries = indexVideos.slice(startIndex, startIndex + DETAILS_PER_PAGE);

  const detailVideos = await Promise.all(
    targetEntries.map(async (entry) => {
      const vodId = String(entry?.vod_id || "").trim();
      const detailPath = String(entry?.detail_path || "").trim();
      if (!vodId || !detailPath) {
        return null;
      }
      const detail = await fetchJson(detailPath);
      return {
        ...detail,
        vod_id: detail.vod_id || vodId,
        vod_url: detail.vod_url || entry.vod_url || `https://www.twitch.tv/videos/${vodId}`,
        title: detail.title || entry.title || "",
        published_at: detail.published_at || entry.published_at || "",
        thumbnail_url: detail.thumbnail_url || entry.thumbnail_url || "",
        count: Number.isFinite(Number(detail.count))
          ? Number(detail.count)
          : Number.isFinite(Number(entry.count))
            ? Number(entry.count)
            : Array.isArray(detail.items)
              ? detail.items.length
              : 0,
      };
    })
  );

  const videos = detailVideos.filter(Boolean);
  if (indexVideos.length > 0 && videos.length === 0) {
    throw new Error("No detail videos resolved for requested page");
  }

  return {
    updated_at: indexData.updated_at,
    next_update_at: indexData.next_update_at,
    videos,
    __paging: pageInfo,
  };
}

async function loadLegacyData(cacheKey) {
  const cachedData = readCachedData(cacheKey);
  try {
    const data = await fetchJson(DATA_URL);
    const withSource = {
      ...data,
      __source: "live",
      __paging: {
        requested_page: DEFAULT_PAGE,
        page: DEFAULT_PAGE,
        page_size: DETAILS_PER_PAGE,
        total_pages: DEFAULT_PAGE,
        total_items: extractVideos(data).length,
        has_prev: false,
        has_next: false,
      },
    };
    localStorage.setItem(cacheKey, JSON.stringify(withSource));
    return withSource;
  } catch (error) {
    if (cachedData) {
      cachedData.__source = "cache";
      return cachedData;
    }
    return null;
  }
}
