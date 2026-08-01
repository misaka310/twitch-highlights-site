import test from "node:test";
import assert from "node:assert/strict";

globalThis.location = new URL("http://localhost/");

const module = await import("../site/js/vod-list-view.js");
const { normalizeTranscriptSyncConfidence, isTranscriptDisplayReadyForVod } = module;

test("timestamp availability helper is no longer exported", () => {
  assert.equal("isTimestampVodAvailableForVod" in module, false);
});

test("normalizeTranscriptSyncConfidence keeps trusted values only", () => {
  assert.equal(normalizeTranscriptSyncConfidence("HIGH"), "high");
  assert.equal(normalizeTranscriptSyncConfidence("medium"), "medium");
  assert.equal(normalizeTranscriptSyncConfidence("failed"), "failed");
  assert.equal(normalizeTranscriptSyncConfidence("unknown"), "");
});

test("transcript panel still requires transcript sync confidence", () => {
  const vod = {
    transcript_status: "ok",
    transcript_path: "/data/transcripts/vod-1.json",
    transcript_offset_sec: 0,
    transcript_sync_confidence: "",
    sync_confidence: "",
  };

  assert.equal(isTranscriptDisplayReadyForVod(vod), false);
});

test("transcript panel still renders when transcript sync confidence is trusted", () => {
  const vod = {
    transcript_status: "ok",
    transcript_path: "/data/transcripts/vod-2.json",
    transcript_offset_sec: 0,
    transcript_sync_confidence: "medium",
    sync_confidence: "medium",
  };

  assert.equal(isTranscriptDisplayReadyForVod(vod), true);
});
