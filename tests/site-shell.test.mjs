import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const indexHtmlPath = path.join(repoRoot, "site", "index.html");

test("site shell does not render the anosa timestamp mode tab", () => {
  const html = fs.readFileSync(indexHtmlPath, "utf8");

  assert.equal(html.includes('id="vod-mode-timestamps"'), false);
  assert.equal(html.includes("あのさぁタイムスタンプ"), false);
});
