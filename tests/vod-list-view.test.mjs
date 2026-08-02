import test from "node:test";
import assert from "node:assert/strict";

globalThis.location = new URL("http://localhost/");

const module = await import("../site/js/vod-list-view.js");

test("retired timestamp and transcript UI helpers are not exported", () => {
  assert.equal("isTimestampVodAvailableForVod" in module, false);
  assert.equal("normalizeTranscriptSyncConfidence" in module, false);
  assert.equal("isTranscriptDisplayReadyForVod" in module, false);
});
