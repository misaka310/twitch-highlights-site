import { expect, test } from "@playwright/test";
import { getFakeTwitchLog, installFakeTwitch } from "./fake-twitch";

test.beforeEach(async ({ page }) => {
  await installFakeTwitch(page);
});

test("keeps the legacy Twitch player path available alongside YouTube", async ({ page }) => {
  await page.route("**/data/vod_index.json", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        updated_at: "2026-09-17T00:00:00Z",
        videos: [
          {
            provider: "twitch",
            vod_id: "2873115795",
            vod_url: "https://www.twitch.tv/videos/2873115795",
            detail_path: "/data/vods/twitch-regression.json",
            published_at: "2026-09-17T00:00:00Z",
          },
        ],
      }),
    });
  });
  await page.route("**/data/vods/twitch-regression.json", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        provider: "twitch",
        vod_id: "2873115795",
        vod_url: "https://www.twitch.tv/videos/2873115795",
        title: "Twitch回帰テスト",
        published_at: "2026-09-17T00:00:00Z",
        duration_sec: 120,
        items: [
          { id: "2873115795_10_20", rank: 1, start_sec: 10, end_sec: 20, reason: "Chat activity spike around 00:00:10 (z-score=4.2)." },
        ],
        activity_map: { duration_sec: 120, buckets: [1, 2] },
      }),
    });
  });

  await page.goto("/");
  const frame = page.locator(".player-frame");
  await expect(frame).toHaveAttribute("data-player-provider", "twitch");
  await expect(page.locator("body > .player-embed--portal [data-fake-twitch-player='true']")).toHaveCount(1);
  await expect(page.locator(".highlight-copy > strong")).toHaveText("コメントが集中した場面");

  await page.locator(".highlight-item").click();
  await expect(frame).toHaveAttribute("data-expected-autoplay", "true");
  await expect(frame).toHaveAttribute("data-expected-muted", "false");
  await expect(frame).toHaveAttribute("data-player-status", "playing");
  const log = await getFakeTwitchLog(page);
  expect(log.mounts).toHaveLength(1);
  expect(log.plays).toBeGreaterThan(0);
  expect(log.seeks).toContain(10);
});
