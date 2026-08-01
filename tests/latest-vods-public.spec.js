const { test, expect } = require("@playwright/test");

function parseJsonAllowBom(text) {
  return JSON.parse(String(text || "").replace(/^\uFEFF/, ""));
}

function toPublicDataPath(path) {
  const raw = String(path || "").trim();
  if (!raw) {
    return "";
  }
  return raw.startsWith("/") ? raw : `/${raw}`;
}

test.describe("public latest 3 vod checks", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      try {
        localStorage.clear();
      } catch (_error) {
        // ignore
      }
    });
    await page.goto("/");
  });

  test("latest 3 public VODs keep transcript metadata consistent while timestamp tab stays absent", async ({ page }) => {
    await expect(page.locator("#vod-mode-timestamps")).toHaveCount(0);
    await expect(page.locator("#timestamp-list")).toHaveCount(0);

    const latest = await page.evaluate(async () => {
      const parseJsonAllowBomInBrowser = (text) => JSON.parse(String(text || "").replace(/^\uFEFF/, ""));

      const indexRes = await fetch("/data/vod_index.json");
      const indexPayload = parseJsonAllowBomInBrowser(await indexRes.text());
      const rows = Array.isArray(indexPayload?.videos) ? indexPayload.videos : [];
      const sorted = rows
        .slice()
        .sort(
          (a, b) => new Date(String(b?.published_at || "")).getTime() - new Date(String(a?.published_at || "")).getTime()
        )
        .slice(0, 3);

      const details = [];
      for (const row of sorted) {
        const detailPath = String(row?.detail_path || "").trim();
        const detailRes = await fetch(detailPath);
        const detail = detailRes.ok ? parseJsonAllowBomInBrowser(await detailRes.text()) : {};
        details.push({
          vod_id: String(row?.vod_id || ""),
          transcript_path: String(detail?.transcript_path || "").trim(),
          transcript_status: String(detail?.transcript_status || "").trim().toLowerCase(),
          sync_confidence: String(detail?.transcript_sync_confidence || detail?.sync_confidence || "").trim().toLowerCase(),
        });
      }
      return details;
    });

    expect(latest.length).toBe(3);

    for (const row of latest) {
      await page.locator(`#vod-tab-${row.vod_id}`).click();
      await expect(page.locator("#player-frame")).toBeVisible();

      if (row.transcript_status === "ok" && row.transcript_path) {
        const transcript = await page.request.get(toPublicDataPath(row.transcript_path));
        expect(transcript.ok()).toBeTruthy();
        const payload = parseJsonAllowBom(await transcript.text());
        const cues = Array.isArray(payload?.cues) ? payload.cues : [];
        expect(cues.length).toBeGreaterThan(0);
        expect(["high", "medium", "low", "failed", ""]).toContain(row.sync_confidence);
      }
    }
  });

  test("header subtitle copy is fixed", async ({ page }) => {
    await expect(page.locator(".brand-header-support__subtitle")).toHaveText(
      "直近2ヶ月の配信の見どころをすぐ再生［非公式ファンサイト］"
    );
  });

  test("highlights remain playable from the latest VODs without timestamp mode", async ({ page }) => {
    await expect(page.locator("#vod-mode-timestamps")).toHaveCount(0);

    const firstVisibleSegment = page.locator(".vod-card:not([hidden]) .segment-button").first();
    await expect(firstVisibleSegment).toBeVisible();

    const expectedVodId = String(await firstVisibleSegment.getAttribute("data-vod-id"));
    const expectedStartSec = String(await firstVisibleSegment.getAttribute("data-start-sec"));

    await firstVisibleSegment.click();
    await expect(page.locator("#player-frame")).toHaveAttribute("data-current-vod-id", expectedVodId);
    await expect(page.locator("#player-frame")).toHaveAttribute("data-current-start-sec", expectedStartSec);
  });
});
