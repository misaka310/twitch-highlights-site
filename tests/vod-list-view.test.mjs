import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

globalThis.location = new URL("http://localhost/");

const module = await import("../site/js/vod-list-view.js");

test("view module exports only the VOD list factory", () => {
  assert.deepEqual(Object.keys(module), ["createVodListView"]);
});

test("view source has no retired playback-assist data loader", async () => {
  const source = await readFile(new URL("../site/js/vod-list-view.js", import.meta.url), "utf8");
  const retiredMarkers = [
    ["trans", "cript"].join(""),
    ["time", "stamp"].join(""),
    ["you", "tube"].join(""),
  ];
  retiredMarkers.forEach((marker) => assert.equal(source.toLowerCase().includes(marker), false));
});
