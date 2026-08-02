import assert from "node:assert/strict";
import test from "node:test";

test("frontend unit-test harness runs compiled TypeScript", () => {
  assert.equal(2 + 2, 4);
});
