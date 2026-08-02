import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, Button, Empty, LayerCard, Pagination, Tabs } from "@cloudflare/kumo";
import { ArrowCounterClockwiseIcon, PlayIcon } from "@phosphor-icons/react";
import { TwitchPlayer, type TwitchPlayerHandle } from "./twitch-player";

type Segment = {
  id: string;
  rank?: number;
  start_sec: number;
  end_sec?: number;
  start_time?: string;
  headline?: string;
  reason?: string;
  tags?: string[];
  screenshot_url?: string;
};

type ActivityMap = {
  bucket_sec?: number;
  duration_sec?: number;
  last_comment_sec?: number;
  buckets?: number[];
};

type Vod = {
  vod_id: string;
  vod_url?: string;
  title: string;
  published_at: string;
  duration_sec?: number;
  chat_total?: number;
  comments_per_hour?: number;
  items?: Segment[];
  activity_map?: ActivityMap;
};

type IndexEntry = {
  vod_id: string;
  detail_path: string;
  title?: string;
  published_at?: string;
};

type IndexPayload = {
  updated_at?: string;
  next_update_at?: string;
  videos?: IndexEntry[];
};

type RuntimeSiteConfig = {
  site?: {
    name?: string;
    description?: string;
    base_url?: string;
    analytics?: {
      goatcounter_code?: string;
    };
  };
  twitch?: {
    channel_login?: string;
  };
};

type LoadState = {
  updatedAt: string;
  nextUpdateAt: string;
  vods: Vod[];
  totalCount: number;
  siteConfig: RuntimeSiteConfig;
};

const PAGE_SIZE = 3;

function normalizeDataPath(path: string): string {
  const value = String(path || "").trim();
  if (value.startsWith("/data/")) return value;
  if (value.startsWith("data/")) return `/${value}`;
  return `/data/${value.replace(/^\/+/, "")}`;
}

function normalizeAssetPath(path = ""): string {
  return normalizeDataPath(path);
}

function formatClock(totalSeconds: number): string {
  const total = Math.max(0, Math.floor(totalSeconds || 0));
  const hours = String(Math.floor(total / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
  const seconds = String(total % 60).padStart(2, "0");
  return `${hours}:${minutes}:${seconds}`;
}

function formatDate(value: string, options: Intl.DateTimeFormatOptions): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "―";
  return new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", ...options }).format(date);
}

function formatUpdate(value: string): string {
  return formatDate(value, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function localizeReason(reason = ""): string {
  const text = String(reason).trim();
  const match = text.match(/^Chat activity spike around (.+?) \(z-score=[^)]+\)\.?$/i);
  if (match) return "コメントが集中した場面";
  return text
    .replace(/^\d+h\d+m\d+s\s*/i, "")
    .replace(/\s*\(z-score=[^)]+\)\.?/gi, "")
    .trim();
}

function orderSegments(items?: Segment[]): Segment[] {
  return [...(Array.isArray(items) ? items : [])]
    .sort((a, b) => Number(a.rank ?? a.start_sec) - Number(b.rank ?? b.start_sec));
}

function resolveDurationSec(vod: Vod | null): number {
  const direct = Number(vod?.duration_sec);
  if (Number.isFinite(direct) && direct > 0) return direct;
  const activity = Number(vod?.activity_map?.duration_sec);
  if (Number.isFinite(activity) && activity > 0) return activity;
  return Math.max(0, ...orderSegments(vod?.items).map((segment) => Number(segment.end_sec) || 0));
}

function formatChatVolume(vod: Vod): string {
  if (vod.chat_total == null || vod.comments_per_hour == null) return "―";
  const chatTotal = Number(vod.chat_total);
  const commentsPerHour = Number(vod.comments_per_hour);
  if (!Number.isFinite(chatTotal) || chatTotal < 0 || !Number.isFinite(commentsPerHour) || commentsPerHour < 0) return "―";
  return `${Math.floor(chatTotal).toLocaleString("ja-JP")}件 / 時間あたり約${Math.round(commentsPerHour).toLocaleString("ja-JP")}件`;
}

type ActivityGeometry = {
  areaPath: string;
};

const ACTIVITY_CHART_WIDTH = 1000;
const ACTIVITY_CHART_HEIGHT = 88;

function smoothBuckets(buckets: number[], radius: number): number[] {
  const safeRadius = Math.max(0, Math.floor(Number(radius) || 0));
  return buckets.map((_, index) => {
    let total = 0;
    let count = 0;
    for (let offset = -safeRadius; offset <= safeRadius; offset += 1) {
      const value = buckets[index + offset];
      if (value == null) continue;
      total += value;
      count += 1;
    }
    return count > 0 ? total / count : 0;
  });
}

function downsampleBuckets(buckets: number[], maxPoints: number): number[] {
  if (buckets.length <= maxPoints) return buckets;
  const chunkSize = Math.ceil(buckets.length / maxPoints);
  const sampled: number[] = [];
  for (let index = 0; index < buckets.length; index += chunkSize) {
    const chunk = buckets.slice(index, index + chunkSize);
    if (chunk.length > 0) sampled.push(Math.max(...chunk));
  }
  return sampled;
}

function createActivityGeometry(buckets: number[]): ActivityGeometry | null {
  if (buckets.length === 0) return null;
  const mobile = typeof window !== "undefined" && window.matchMedia("(max-width: 600px)").matches;
  const smoothed = smoothBuckets(buckets, mobile ? 3 : 2);
  const sampled = downsampleBuckets(smoothed, mobile ? 120 : 320);
  const peak = Math.max(1, ...sampled);
  const lastIndex = Math.max(1, sampled.length - 1);
  const points = sampled.map((value, index) => {
    const x = (index / lastIndex) * ACTIVITY_CHART_WIDTH;
    const y = ACTIVITY_CHART_HEIGHT - (Math.max(0, value) / peak) * (ACTIVITY_CHART_HEIGHT - 8);
    return `${x.toFixed(2)} ${y.toFixed(2)}`;
  });
  return {
    areaPath: `M 0 ${ACTIVITY_CHART_HEIGHT} L ${points.join(" L ")} L ${ACTIVITY_CHART_WIDTH} ${ACTIVITY_CHART_HEIGHT} Z`,
  };
}

async function loadPage(page: number): Promise<LoadState> {
  const [indexResponse, configResponse] = await Promise.all([
    fetch("/data/vod_index.json", { cache: "no-store" }),
    fetch("/site-config.json", { cache: "no-store" }),
  ]);
  if (!indexResponse.ok) throw new Error("配信一覧を読み込めませんでした。");
  const index = (await indexResponse.json()) as IndexPayload;
  const siteConfig = configResponse.ok ? ((await configResponse.json()) as RuntimeSiteConfig) : {};
  const entries = Array.isArray(index.videos) ? [...index.videos] : [];
  entries.sort((a, b) => new Date(b.published_at || 0).getTime() - new Date(a.published_at || 0).getTime());
  const start = (page - 1) * PAGE_SIZE;
  const pageEntries = entries.slice(start, start + PAGE_SIZE);
  const vods = await Promise.all(
    pageEntries.map(async (entry) => {
      const response = await fetch(normalizeDataPath(entry.detail_path), { cache: "no-store" });
      if (!response.ok) throw new Error(`VOD ${entry.vod_id} を読み込めませんでした。`);
      const vod = (await response.json()) as Vod;
      return { ...vod, items: orderSegments(vod.items) };
    }),
  );
  return {
    updatedAt: index.updated_at || "",
    nextUpdateAt: index.next_update_at || "",
    vods,
    totalCount: entries.length,
    siteConfig,
  };
}

export default function App() {
  const initialPage = Math.max(1, Number.parseInt(new URLSearchParams(location.search).get("page") || "1", 10) || 1);
  const [page, setPageState] = useState(initialPage);
  const [data, setData] = useState<LoadState | null>(null);
  const [error, setError] = useState("");
  const playerRef = useRef<TwitchPlayerHandle>(null);
  const [activeVodId, setActiveVodId] = useState("");
  const [activeSegmentId, setActiveSegmentId] = useState("");
  const [positionSec, setPositionSec] = useState(0);
  const [playerState, setPlayerState] = useState("待機中");

  useEffect(() => {
    let cancelled = false;
    setError("");
    setData(null);
    void loadPage(page)
      .then((loaded) => {
        if (cancelled) return;
        setData(loaded);
        const firstVod = loaded.vods[0];
        const firstSegment = firstVod?.items?.[0];
        setActiveVodId(firstVod?.vod_id || "");
        setActiveSegmentId(firstSegment?.id || "");
        setPositionSec(Number(firstSegment?.start_sec || 0));
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "データを読み込めませんでした。");
      });
    return () => {
      cancelled = true;
    };
  }, [page]);

  useEffect(() => {
    const firstVod = data?.vods[0];
    const firstSegment = firstVod?.items?.[0];
    if (!firstVod || !playerRef.current) return;
    playerRef.current.requestPlayback(firstVod.vod_id, Number(firstSegment?.start_sec || 0), {
      autoplay: false,
      muted: true,
      triggeredByUser: false,
    });
  }, [data]);

  useEffect(() => {
    const site = data?.siteConfig.site;
    const siteName = String(site?.name || "dotitao moments").trim();
    const description = String(site?.description || "Twitch配信の見どころをすぐ再生できる非公式ファンサイトです。").trim();
    document.title = siteName;
    document.querySelector<HTMLMetaElement>('meta[name="description"]')?.setAttribute("content", description);
    document.querySelector<HTMLMetaElement>('meta[property="og:title"]')?.setAttribute("content", siteName);
    document.querySelector<HTMLMetaElement>('meta[property="og:description"]')?.setAttribute("content", description);

    const analyticsCode = String(site?.analytics?.goatcounter_code || "").trim();
    const isLocal = ["localhost", "127.0.0.1"].includes(location.hostname);
    if (!analyticsCode || isLocal || document.querySelector("script[data-goatcounter]")) return;
    const script = document.createElement("script");
    script.async = true;
    script.dataset.goatcounter = `https://${analyticsCode}.goatcounter.com/count`;
    script.src = "https://gc.zgo.at/count.js";
    document.head.append(script);
  }, [data?.siteConfig]);

  const activeVod = data?.vods.find((vod) => vod.vod_id === activeVodId) || data?.vods[0] || null;
  const segments = useMemo(() => activeVod?.items?.slice(0, 3) || [], [activeVod]);
  const activeSegment = segments.find((segment) => segment.id === activeSegmentId) || segments[0] || null;
  const activityGeometry = useMemo(
    () => createActivityGeometry(activeVod?.activity_map?.buckets || []),
    [activeVod?.activity_map?.buckets],
  );
  const durationSec = resolveDurationSec(activeVod);
  const positionRatio = durationSec ? Math.min(1, Math.max(0, positionSec / durationSec)) : 0;
  const segmentStartSec = Math.max(0, Math.min(Number(activeSegment?.start_sec) || 0, durationSec));
  const segmentEndSec = Math.max(0, Math.min(Number(activeSegment?.end_sec) || 0, durationSec));
  const segmentRangeX = durationSec ? (segmentStartSec / durationSec) * ACTIVITY_CHART_WIDTH : 0;
  const segmentRangeWidth =
    durationSec && segmentEndSec > segmentStartSec
      ? ((segmentEndSec - segmentStartSec) / durationSec) * ACTIVITY_CHART_WIDTH
      : 0;
  const lastCommentValue = Number(activeVod?.activity_map?.last_comment_sec);
  const lastCommentSec = Number.isFinite(lastCommentValue) && lastCommentValue >= 0
    ? Math.max(0, Math.min(lastCommentValue, durationSec))
    : durationSec;
  const unavailableX = durationSec ? (lastCommentSec / durationSec) * ACTIVITY_CHART_WIDTH : ACTIVITY_CHART_WIDTH;
  const unavailableWidth = Math.max(0, ACTIVITY_CHART_WIDTH - unavailableX);

  function setPage(nextPage: number) {
    const safePage = Math.max(1, nextPage);
    const url = new URL(location.href);
    url.searchParams.set("page", String(safePage));
    history.replaceState({}, "", url);
    setPageState(safePage);
  }

  function requestUserPlayback(vodId: string, startSec: number) {
    const safeStartSec = Math.max(0, Math.floor(Number(startSec) || 0));
    setPositionSec(safeStartSec);
    playerRef.current?.requestPlayback(vodId, safeStartSec, {
      autoplay: true,
      muted: false,
      triggeredByUser: true,
    });
  }

  function selectVod(vodId: string) {
    const vod = data?.vods.find((entry) => entry.vod_id === vodId);
    const first = vod?.items?.[0];
    const startSec = Number(first?.start_sec || 0);
    setActiveVodId(vodId);
    setActiveSegmentId(first?.id || "");
    requestUserPlayback(vodId, startSec);
  }

  function selectSegment(segment: Segment) {
    setActiveSegmentId(segment.id);
    requestUserPlayback(activeVod?.vod_id || "", segment.start_sec);
  }

  function seekByMap(event: React.MouseEvent<HTMLButtonElement>) {
    if (!durationSec || !activeVod) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    requestUserPlayback(activeVod.vod_id, Math.floor(durationSec * ratio));
  }

  function rewindTenSeconds() {
    if (!activeVod) return;
    const current = playerRef.current?.getCurrentTime();
    const base = current == null ? positionSec : current;
    requestUserPlayback(activeVod.vod_id, Math.max(0, Math.floor(base) - 10));
  }

  if (error) {
    return (
      <main className="preview-shell preview-shell--empty">
        <Empty title="表示データがありません" description={error} />
      </main>
    );
  }

  if (!data || !activeVod) {
    return <main className="loading-state">読み込み中...</main>;
  }

  const tabItems = data.vods.map((vod) => ({
    value: vod.vod_id,
    label: formatDate(vod.published_at, { month: "numeric", day: "numeric", weekday: "short" }),
  }));
  const siteName = String(data.siteConfig.site?.name || "dotitao moments").trim();

  return (
    <div className="preview-shell">
      <header className="site-header">
        <div>
          <div className="brand-line">
            <PlayIcon weight="fill" aria-hidden="true" />
            <h1>{siteName}</h1>
          </div>
          <p>直近2ヶ月の配信の見どころをすぐ再生［非公式ファンサイト］</p>
        </div>
        <div className="update-stack" aria-label="更新情報">
          <span>データ更新: {formatUpdate(data.updatedAt)}</span>
          <span>次回更新予定: {formatUpdate(data.nextUpdateAt)}</span>
        </div>
      </header>

      <main className="content-grid">
        <section className="player-column" aria-label="再生エリア">
          <LayerCard>
            <LayerCard.Primary>
              <div className="playback-surface">
                <TwitchPlayer
                  ref={playerRef}
                  onPositionChange={setPositionSec}
                  onStatusChange={(label) => setPlayerState(label)}
                />

                <div className="activity-card">
                  <div className="activity-head">
                    <div className="activity-title-row">
                      <span className="eyebrow">盛り上がりマップ</span>
                      <span className="activity-help">クリックで移動</span>
                    </div>
                    <div className="activity-actions">
                      <div className="activity-times">
                        <strong>{formatClock(positionSec)}</strong>
                        <span>{formatClock(durationSec)}</span>
                      </div>
                      <Button
                        className="rewind-button"
                        variant="secondary"
                        size="sm"
                        icon={ArrowCounterClockwiseIcon}
                        onClick={rewindTenSeconds}
                      >
                        10秒戻る
                      </Button>
                    </div>
                  </div>
                  {activityGeometry ? (
                    <button className="activity-chart" type="button" onClick={seekByMap} aria-label="盛り上がりマップから再生位置を選ぶ">
                      <svg viewBox={`0 0 ${ACTIVITY_CHART_WIDTH} ${ACTIVITY_CHART_HEIGHT}`} preserveAspectRatio="none" aria-hidden="true">
                        <defs>
                          <linearGradient id="activity-fill" x1="0" x2="0" y1="0" y2="1">
                            <stop offset="0%" stopColor="rgba(103, 134, 176, 0.38)" />
                            <stop offset="100%" stopColor="rgba(35, 51, 73, 0.04)" />
                          </linearGradient>
                        </defs>
                        <path
                          className="activity-progress"
                          d={`M 0 ${ACTIVITY_CHART_HEIGHT} L 0 0 L ${(positionRatio * ACTIVITY_CHART_WIDTH).toFixed(2)} 0 L ${(positionRatio * ACTIVITY_CHART_WIDTH).toFixed(2)} ${ACTIVITY_CHART_HEIGHT} Z`}
                        />
                        <path className="activity-area" d={activityGeometry.areaPath} />
                        {segmentRangeWidth > 0 ? (
                          <rect className="activity-segment-range" x={segmentRangeX} y="0" width={segmentRangeWidth} height={ACTIVITY_CHART_HEIGHT} />
                        ) : null}
                        {unavailableWidth > 0 ? (
                          <rect className="activity-unavailable" x={unavailableX} y="0" width={unavailableWidth} height={ACTIVITY_CHART_HEIGHT} />
                        ) : null}
                        <line
                          className="activity-marker"
                          x1={positionRatio * ACTIVITY_CHART_WIDTH}
                          x2={positionRatio * ACTIVITY_CHART_WIDTH}
                          y1="0"
                          y2={ACTIVITY_CHART_HEIGHT}
                        />
                      </svg>
                    </button>
                  ) : (
                    <Empty title="盛り上がりデータなし" description="この配信にはマップ用データがありません。" />
                  )}
                </div>
              </div>
            </LayerCard.Primary>
          </LayerCard>
        </section>

        <aside className="highlight-column" aria-label="VODと見どころ一覧">
          <LayerCard>
            <LayerCard.Primary>
              <div className="rail-content">
                <Tabs tabs={tabItems} value={activeVod.vod_id} onValueChange={selectVod} />
                <div className="highlight-list">
                  {segments.length > 0 ? segments.map((segment) => {
                    const selected = segment.id === activeSegment?.id;
                    const title = String(segment.headline || localizeReason(segment.reason) || "見どころ").trim();
                    return (
                      <button
                        key={segment.id}
                        type="button"
                        className={`highlight-item${selected ? " is-selected" : ""}`}
                        data-vod-id={activeVod.vod_id}
                        data-start-sec={segment.start_sec}
                        aria-pressed={selected}
                        onClick={() => selectSegment(segment)}
                      >
                        <span className="thumb-wrap">
                          {segment.screenshot_url ? (
                            <img src={normalizeAssetPath(segment.screenshot_url)} alt="" loading="lazy" />
                          ) : (
                            <span className="thumb-fallback"><PlayIcon weight="fill" /></span>
                          )}
                          <span className="time-chip">{segment.start_time || formatClock(segment.start_sec)}</span>
                        </span>
                        <span className="highlight-copy">
                          <strong>{title}</strong>
                          <span className="tag-row">
                            {(segment.tags || []).slice(0, 2).map((tag) => (
                              <Badge key={tag} className="highlight-tag" variant="neutral">{tag}</Badge>
                            ))}
                          </span>
                        </span>
                      </button>
                    );
                  }) : <Empty title="見どころなし" description="この配信には表示できる見どころがありません。" />}
                </div>
              </div>
            </LayerCard.Primary>
          </LayerCard>

          <LayerCard>
            <LayerCard.Primary>
              <section className="stream-summary" aria-label="この配信について">
                <h3>この配信について</h3>
                <dl>
                  <div><dt>配信タイトル</dt><dd>{String(activeVod.title || "").trim() || "―"}</dd></div>
                  <div><dt>配信日時</dt><dd>{formatDate(activeVod.published_at, { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}</dd></div>
                  <div><dt>長さ</dt><dd>{durationSec > 0 ? formatClock(durationSec) : "―"}</dd></div>
                  <div><dt>チャット量</dt><dd>{formatChatVolume(activeVod)}</dd></div>
                  <div><dt>再生状態</dt><dd>{playerState}</dd></div>
                  <div><dt>再生位置</dt><dd>{formatClock(positionSec)}</dd></div>
                </dl>
              </section>
            </LayerCard.Primary>
          </LayerCard>

          <div className="pagination-wrap" aria-label="ページ移動">
            <Pagination page={page} perPage={PAGE_SIZE} totalCount={data.totalCount} setPage={setPage} controls="full" />
          </div>
        </aside>
      </main>
    </div>
  );
}
