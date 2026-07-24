import assert from "node:assert/strict";
import test from "node:test";

globalThis.location = new URL("http://localhost/");
globalThis.window = {};

const { applyInitialSelectionToState, getInitialSelection, normalizeData } = await import("../site/js/vod-normalizer.js");

function makeVideo(overrides = {}) {
  return {
    vod_id: "vod-1",
    published_at: "2026-07-01T00:00:00Z",
    items: [
      {
        id: "segment-1",
        start_sec: 15,
        end_sec: 25,
        reason: "z-score",
        tags: ["ww"],
      },
    ],
    activity_map: { bucket_sec: 10, duration_sec: 100, buckets: [0, 2, 0] },
    ...overrides,
  };
}

test("VOD without highlight segments is excluded", () => {
  assert.deepEqual(normalizeData({ videos: [makeVideo({ items: [] })] }), []);
});

test("generated headline is shown instead of the generic highlight reason", () => {
  const [vod] = normalizeData({
    videos: [
      makeVideo({
        items: [
          {
            id: "segment-1",
            start_sec: 15,
            end_sec: 25,
            reason: "z-score",
            headline: "見どころの見出し",
          },
        ],
      }),
    ],
  });
  assert.equal(vod.segments[0].summary, "見どころの見出し");
});

test("initial selection uses the first highlight segment", () => {
  const vods = normalizeData({ videos: [makeVideo()] });
  const selection = getInitialSelection(vods);
  assert.equal(selection.segment.id, "segment-1");
  assert.equal(selection.start_sec, 15);
});

test("initial selection seeds playback state", () => {
  const state = {};
  applyInitialSelectionToState(state, {
    vod: { id: "vod-5" },
    segment: { id: "segment-5" },
    start_sec: 90,
  });
  assert.deepEqual(state, {
    selectedVodId: "vod-5",
    selectedSegmentId: "segment-5",
    requestedVodId: "vod-5",
    requestedStartSec: 90,
  });
});
