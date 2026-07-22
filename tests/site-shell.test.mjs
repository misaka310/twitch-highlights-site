import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const html = await readFile(new URL("../site/index.html", import.meta.url), "utf8");

test("site shell uses generic placeholders populated by runtime config", () => {
  assert.match(html, /id="site-name"/);
  assert.match(html, /id="site-description"/);
  assert.match(html, /<title>Twitch Highlights<\/title>/);
  assert.doesNotMatch(html, /data-goatcounter/);
});

test("site shell keeps the approved player and VOD rail structure", () => {
  assert.match(html, /class="workspace"/);
  assert.match(html, /id="player-frame"/);
  assert.match(html, /id="vod-list"/);
  assert.match(html, /id="activity-map"/);
});
