import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { installFakeYoutube } from "./fake-youtube";

const artifactsDirectory = resolve(process.cwd(), "artifacts");
const videoId = "anosa000001";

test.beforeAll(() => {
  mkdirSync(artifactsDirectory, { recursive: true });
});

test("anosa tab shows only complete statements beginning with あのさ", async ({ page }) => {
  await installFakeYoutube(page);

  await page.route("**/site-config.json", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        site: { name: "dotitao moments", feedback_url: "" },
        twitch: {},
      }),
    });
  });
  await page.route("**/data/vod_index.json", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        updated_at: "2026-09-20T00:00:00Z",
        next_update_at: "2026-09-21T00:00:00Z",
        videos: [
          {
            provider: "youtube",
            vod_id: videoId,
            detail_path: `/data/vods/${videoId}.json`,
            published_at: "2026-09-20T00:00:00Z",
          },
        ],
      }),
    });
  });
  await page.route(`**/data/vods/${videoId}.json`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        provider: "youtube",
        vod_id: videoId,
        title: "あのさ確認用配信",
        published_at: "2026-09-20T00:00:00Z",
        duration_sec: 120,
        activity_map: {
          duration_sec: 120,
          last_comment_sec: 110,
          buckets: [1, 3, 2, 4, 2, 1],
        },
        items: [
          {
            id: "seg-1",
            rank: 1,
            start_sec: 10,
            end_sec: 20,
            headline: "確認用見どころ",
            reason: "確認用",
          },
        ],
      }),
    });
  });
  await page.route("**/data/captions/*.json", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        video_id: videoId,
        source: "youtube_automatic_captions",
        language: "ja",
        language_source: "ja-orig",
        cues: [
          { start_sec: 10, end_sec: 12, text: "前置き。あのさ、エルデンリング飯って" },
          { start_sec: 12, end_sec: 14, text: "こういう感じで作るのが" },
          { start_sec: 14, end_sec: 16, text: "一番いいと思うんだよね。" },
          { start_sec: 30, end_sec: 32, text: "あのさ、これは途中で" },
          { start_sec: 32, end_sec: 34, text: "意味が切れて" },
          { start_sec: 50, end_sec: 52, text: "別の話。あのさ、これ は 絶対" },
          { start_sec: 52, end_sec: 54, text: "絶対やった方がいい。" },
          { start_sec: 60, end_sec: 61, text: "あのさ、三つ目の完結発話です。" },
          { start_sec: 65, end_sec: 66, text: "あのさ、四つ目の完結発話です。" },
          { start_sec: 70, end_sec: 71, text: "あのさ、五つ目の完結発話です。" },
          { start_sec: 75, end_sec: 76, text: "あのさ、六つ目の完結発話です。" },
          { start_sec: 80, end_sec: 81, text: "あのさ、七つ目の完結発話です。" },
          { start_sec: 85, end_sec: 86, text: "あのさ、八つ目の完結発話です。" },
        ],
      }),
    });
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "dotitao moments" })).toBeVisible();
  const anosaTab = page.getByRole("tab", { name: "あのさ" });
  await expect(anosaTab).toBeVisible();
  await anosaTab.click();

  const rows = page.locator(".anosa-row");
  await expect(rows).toHaveCount(8);
  const texts = await rows.locator(".anosa-text").allTextContents();
  expect(texts.slice(0, 2)).toEqual([
    "あのさ、エルデンリング飯ってこういう感じで作るのが一番いいと思うんだよね。",
    "あのさ、これは絶対やった方がいい。",
  ]);
  for (const text of texts) {
    expect(text.startsWith("あのさ")).toBe(true);
  }
  await expect(page.getByText("あのさ、これは途中で", { exact: false })).toHaveCount(0);

  const layout = await page.evaluate(() => ({
    innerHeight: window.innerHeight,
    scrollHeight: document.documentElement.scrollHeight,
  }));
  expect(layout.scrollHeight).toBeLessThanOrEqual(layout.innerHeight);

  const panelBox = await page.locator(".caption-panel--anosa").boundingBox();
  const listBox = await page.locator(".anosa-list").boundingBox();
  expect(panelBox).not.toBeNull();
  expect(listBox).not.toBeNull();
  expect((listBox?.y || 0) + (listBox?.height || 0)).toBeLessThanOrEqual(
    (panelBox?.y || 0) + (panelBox?.height || 0) + 1,
  );

  await page.screenshot({
    path: resolve(artifactsDirectory, "anosa-preview-desktop.png"),
    fullPage: true,
  });
});
