import assert from "node:assert/strict";
import test from "node:test";
import {
  ACTIVITY_CHART_WIDTH,
  createActivityGeometry,
  createActivityOverlay,
  downsampleBuckets,
  smoothBuckets,
} from "../../src/lib/activity-geometry.js";
import { formatChatVolume, formatClock, localizeReason } from "../../src/lib/formatters.js";
import { loadVodPage } from "../../src/hooks/use-vod-page.js";
import {
  normalizeDataPath,
  orderSegments,
  pageUrl,
  parsePageSearch,
  resolveDurationSec,
} from "../../src/lib/vod-data.js";

test("normalizes public data paths without changing canonical paths", () => {
  assert.equal(normalizeDataPath("/data/vods/1.json"), "/data/vods/1.json");
  assert.equal(normalizeDataPath("data/vods/1.json"), "/data/vods/1.json");
  assert.equal(normalizeDataPath("vods/1.json"), "/data/vods/1.json");
});

test("orders segments by rank and derives duration with existing precedence", () => {
  const ordered = orderSegments([
    { id: "third", rank: 3, start_sec: 30, end_sec: 40 },
    { id: "first", rank: 1, start_sec: 10, end_sec: 20 },
    { id: "second", rank: 2, start_sec: 20, end_sec: 30 },
  ]);
  assert.deepEqual(ordered.map((item) => item.id), ["first", "second", "third"]);
  assert.equal(resolveDurationSec({ vod_id: "1", title: "", published_at: "", duration_sec: 100 }), 100);
  assert.equal(resolveDurationSec({ vod_id: "1", title: "", published_at: "", activity_map: { duration_sec: 90 } }), 90);
  assert.equal(resolveDurationSec({ vod_id: "1", title: "", published_at: "", items: ordered }), 40);
});

test("preserves page navigation query behavior", () => {
  assert.equal(parsePageSearch("?page=2"), 2);
  assert.equal(parsePageSearch("?page=0"), 1);
  assert.equal(parsePageSearch("?page=invalid"), 1);
  assert.equal(pageUrl("https://example.test/?mode=preview&page=1", 3), "https://example.test/?mode=preview&page=3");
});

test("clamps out-of-range VOD pages to the last available page", async () => {
  const requestedPaths: string[] = [];
  const fetcher = async (input: string | URL | Request): Promise<Response> => {
    const path = String(input);
    requestedPaths.push(path);
    if (path === "/data/vod_index.json") {
      return Response.json({
        videos: [
          { vod_id: "4", detail_path: "data/vods/4.json", published_at: "2026-08-04T00:00:00Z" },
          { vod_id: "3", detail_path: "data/vods/3.json", published_at: "2026-08-03T00:00:00Z" },
          { vod_id: "2", detail_path: "data/vods/2.json", published_at: "2026-08-02T00:00:00Z" },
          { vod_id: "1", detail_path: "data/vods/1.json", published_at: "2026-08-01T00:00:00Z" },
        ],
      });
    }
    if (path === "/site-config.json") return Response.json({ site: { name: "Example" } });
    if (path === "/data/vods/1.json") {
      return Response.json({ vod_id: "1", title: "last page", published_at: "2026-08-01T00:00:00Z" });
    }
    return new Response("not found", { status: 404 });
  };

  const result = await loadVodPage(99, fetcher as typeof fetch);

  assert.equal(result.requestedPage, 99);
  assert.equal(result.page, 2);
  assert.deepEqual(result.vods.map((vod) => vod.vod_id), ["1"]);
  assert.equal(requestedPaths.includes("/data/vods/4.json"), false);
});

test("keeps display formatting and reason localization", () => {
  assert.equal(formatClock(3661.9), "01:01:01");
  assert.equal(localizeReason("Chat activity spike around 00:00:40 (z-score=4.2)."), "コメントが集中した場面");
  assert.equal(formatChatVolume({ vod_id: "1", title: "", published_at: "" }), "―");
  assert.equal(
    formatChatVolume({ vod_id: "1", title: "", published_at: "", chat_total: 1234, comments_per_hour: 56.7 }),
    "1,234件 / 時間あたり約57件",
  );
});

test("creates responsive activity geometry without reading browser globals", () => {
  const buckets = Array.from({ length: 1000 }, (_, index) => index % 17);
  assert.equal(smoothBuckets([1, 3, 5], 1)[1], 3);
  assert.equal(downsampleBuckets(buckets, 120).length <= 120, true);

  const desktop = createActivityGeometry(buckets, false);
  const compact = createActivityGeometry(buckets, true);
  assert.ok(desktop);
  assert.ok(compact);
  const desktopPoints = (desktop.areaPath.match(/ L /g) || []).length - 1;
  const compactPoints = (compact.areaPath.match(/ L /g) || []).length - 1;
  assert.equal(desktopPoints <= 320, true);
  assert.equal(compactPoints <= 120, true);
});

test("calculates selected and unavailable activity ranges", () => {
  const overlay = createActivityOverlay({
    durationSec: 100,
    positionSec: 25,
    segmentStartSec: 20,
    segmentEndSec: 30,
    lastCommentSec: 80,
  });
  assert.equal(overlay.positionRatio, 0.25);
  assert.equal(overlay.segmentRangeX, ACTIVITY_CHART_WIDTH * 0.2);
  assert.equal(overlay.segmentRangeWidth, ACTIVITY_CHART_WIDTH * 0.1);
  assert.equal(overlay.unavailableX, ACTIVITY_CHART_WIDTH * 0.8);
  assert.equal(overlay.unavailableWidth, ACTIVITY_CHART_WIDTH * 0.2);
});
