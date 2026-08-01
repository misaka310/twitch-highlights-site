import test from "node:test";
import assert from "node:assert/strict";

import {
  formatDateOnly,
  formatScheduleDate,
  resolveNextJstNineUpdateAt,
  resolveNextUpdateAt,
} from "../site/js/formatters.js";

test("resolveNextUpdateAt returns the provided next_update_at when it is in the future", () => {
  const now = new Date("2026-05-28T22:00:00.000Z");
  const result = resolveNextUpdateAt("2026-05-29T00:00:00.000Z", "2026-05-28T21:00:00.000Z", now);
  assert.equal(result, "2026-05-29T00:00:00.000Z");
});

test("resolveNextJstNineUpdateAt keeps JST 09:00 even in UTC runtime (before JST 09:00)", () => {
  const now = new Date("2026-05-28T23:30:00.000Z");
  const result = resolveNextJstNineUpdateAt("2026-05-28T23:00:22Z", now);
  assert.equal(result, "2026-05-29T00:00:00.000Z");
});

test("resolveNextJstNineUpdateAt keeps JST 09:00 even in UTC runtime (after JST 09:00)", () => {
  const now = new Date("2026-05-29T01:05:00.000Z");
  const result = resolveNextJstNineUpdateAt("2026-05-29T01:00:00Z", now);
  assert.equal(result, "2026-05-30T00:00:00.000Z");
});

test("schedule/date formatters render using Asia/Tokyo timezone", () => {
  assert.match(formatScheduleDate("2026-05-29T00:00:00.000Z"), /05\/29.*09:00/);
  assert.equal(formatDateOnly("2026-05-28T18:00:00.000Z"), "2026/05/29");
});
