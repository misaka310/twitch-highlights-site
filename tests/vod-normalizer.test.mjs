import test from "node:test";
import assert from "node:assert/strict";

globalThis.location = new URL("http://localhost/");
globalThis.window = {};

const { createInitialState } = await import("../site/js/config.js");
const { normalizeData, getInitialSelection, applyInitialSelectionToState } = await import("../site/js/vod-normalizer.js");

test("normalizeData keeps anosa status isolated from legacy timestamps status", () => {
  const [vod] = normalizeData({
    videos: [
      {
        vod_id: "vod-1",
        title: "VOD 1",
        published_at: "2026-06-05T00:00:00Z",
        anosa_timestamps_status: "",
        anosa_timestamps_path: "",
        anosa_timestamps: [],
        timestamps_status: "ok",
        timestamps_path: "data/timestamps/vod-1.json",
        timestamps: [{ id: "legacy-1", start_sec: 10, label: "legacy" }],
        items: [{ id: "seg-1", start_sec: 1, end_sec: 5 }],
      },
    ],
  });

  assert.equal(vod.anosa_timestamps_status, "");
  assert.equal(vod.anosa_timestamps_path, "");
  assert.equal(vod.timestamps_status, "ok");
  assert.equal(vod.timestamps.length, 0);
  assert.equal(vod.timestamps_path, "/data/timestamps/vod-1.json");
});

test("normalizeData keeps vod when segments are empty but anosa timestamps exist", () => {
  const vods = normalizeData({
    videos: [
      {
        vod_id: "vod-2",
        title: "VOD 2",
        published_at: "2026-06-05T00:00:00Z",
        anosa_timestamps_status: "ok",
        anosa_timestamps_path: "data/anosa-timestamps/vod-2.json",
        anosa_timestamps: [{ id: "anosa-1", start_sec: 20, label: "あのさぁ、テスト" }],
        items: [],
      },
    ],
  });

  assert.equal(vods.length, 1);
  assert.equal(vods[0].segments.length, 0);
  assert.equal(vods[0].timestamps.length, 1);
});

test("normalizeData still keeps highlight segments when both highlights and anosa exist", () => {
  const [vod] = normalizeData({
    videos: [
      {
        vod_id: "vod-3",
        title: "VOD 3",
        published_at: "2026-06-05T00:00:00Z",
        anosa_timestamps_status: "ok",
        anosa_timestamps_path: "data/anosa-timestamps/vod-3.json",
        anosa_timestamps: [{ id: "anosa-1", start_sec: 20, label: "あのさぁ、テスト" }],
        items: [{ id: "seg-1", start_sec: 1, end_sec: 5, headline: "highlight" }],
      },
    ],
  });

  assert.equal(vod.segments.length, 1);
  assert.equal(vod.timestamps.length, 1);
});

test("getInitialSelection falls back to the first anosa timestamp when segments are empty", () => {
  const [vod] = normalizeData({
    videos: [
      {
        vod_id: "vod-4",
        title: "VOD 4",
        published_at: "2026-06-05T00:00:00Z",
        anosa_timestamps_status: "ok",
        anosa_timestamps_path: "data/anosa-timestamps/vod-4.json",
        anosa_timestamps: [{ id: "anosa-1", start_sec: 42, label: "anosa only" }],
        items: [],
      },
    ],
  });

  const selection = getInitialSelection([vod]);

  assert.equal(selection.vod.id, "vod-4");
  assert.equal(selection.segment, null);
  assert.equal(selection.start_sec, 42);
});

test("applyInitialSelectionToState seeds playback state for anosa-only selections", () => {
  const [vod] = normalizeData({
    videos: [
      {
        vod_id: "vod-5",
        title: "VOD 5",
        published_at: "2026-06-05T00:00:00Z",
        anosa_timestamps_status: "ok",
        anosa_timestamps_path: "data/anosa-timestamps/vod-5.json",
        anosa_timestamps: [{ id: "anosa-1", start_sec: 75, label: "anosa only" }],
        items: [],
      },
    ],
  });
  const state = createInitialState();

  applyInitialSelectionToState(state, getInitialSelection([vod]));

  assert.equal(state.selectedVodId, "vod-5");
  assert.equal(state.selectedSegmentId, "");
  assert.equal(state.requestedVodId, "vod-5");
  assert.equal(state.requestedStartSec, 75);
});

test("getInitialSelection still prefers the first highlight segment when segments exist", () => {
  const [vod] = normalizeData({
    videos: [
      {
        vod_id: "vod-6",
        title: "VOD 6",
        published_at: "2026-06-05T00:00:00Z",
        anosa_timestamps_status: "ok",
        anosa_timestamps_path: "data/anosa-timestamps/vod-6.json",
        anosa_timestamps: [{ id: "anosa-1", start_sec: 90, label: "fallback" }],
        items: [
          { id: "seg-1", start_sec: 11, end_sec: 20, headline: "first" },
          { id: "seg-2", start_sec: 25, end_sec: 35, headline: "second" },
        ],
      },
    ],
  });

  const selection = getInitialSelection([vod]);

  assert.equal(selection.vod.id, "vod-6");
  assert.equal(selection.segment.id, "seg-1");
  assert.equal(selection.start_sec, 11);
});
