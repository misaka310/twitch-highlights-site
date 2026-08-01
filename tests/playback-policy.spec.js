const { test, expect } = require("@playwright/test");

test("playback policy is based on user interaction", async ({ page }) => {
  await page.goto("/");

  const firstSegmentButton = await getSegmentButton(page, 0, 0);
  const olderVodButton = await getSegmentButton(page, 1, 0);

  await expect
    .poll(async () => getPlaybackIntent(page))
    .toMatchObject({
      autoplay: "false",
      muted: "true",
    });

  await firstSegmentButton.click();
  await expect
    .poll(async () => getPlaybackIntent(page))
    .toMatchObject({
      autoplay: "true",
      muted: "false",
    });

  await olderVodButton.click();
  await expect
    .poll(async () => getPlaybackIntent(page))
    .toMatchObject({
      autoplay: "true",
      muted: "false",
    });

  await page.evaluate(() => {
    const playerFrame = document.querySelector("#player-frame");
    requestPlayback(playerFrame?.dataset.currentVodId, Number(playerFrame?.dataset.currentStartSec || 0) + 5, {
      triggeredByUser: false,
      statusLabel: "auto test",
    });
  });

  await expect
    .poll(async () => getPlaybackIntent(page))
    .toMatchObject({
      autoplay: "true",
      muted: "true",
    });
});

async function getPlaybackIntent(page) {
  const playerFrame = page.locator("#player-frame");
  return {
    autoplay: (await playerFrame.getAttribute("data-expected-autoplay")) || "",
    muted: (await playerFrame.getAttribute("data-expected-muted")) || "",
  };
}

async function getSegmentButton(page, vodIndex, segmentIndex) {
  await activateVodTab(page, vodIndex);
  return page.locator(".vod-card:not([hidden]) .segment-button").nth(segmentIndex);
}

async function activateVodTab(page, vodIndex) {
  const tabs = page.locator(".vod-tab, .mobile-vod-tab");
  const tabCount = await tabs.count();
  if (tabCount <= vodIndex) {
    return;
  }

  const tab = tabs.nth(vodIndex);
  await expect(tab).toBeVisible();
  await tab.click();
}
