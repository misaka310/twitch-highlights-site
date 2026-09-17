import { expect, test } from "@playwright/test";

test("does not expose legacy Twitch entries in the public site", async ({ page }) => {
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
  await page.goto("/");
  await expect(page.getByText("公開中のVODデータがまだありません")).toBeVisible();
  await expect(page.locator(".player-frame")).toHaveCount(0);
  await expect(page.getByRole("tab")).toHaveCount(0);
});
