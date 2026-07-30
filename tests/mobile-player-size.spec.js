const { test, expect } = require("@playwright/test");

const MOBILE_VIEWPORTS = [
  { width: 320, height: 700 },
  { width: 360, height: 800 },
  { width: 390, height: 844 },
  { width: 412, height: 915 },
  { width: 430, height: 932 },
];

for (const viewport of MOBILE_VIEWPORTS) {
  test(`mobile tap restores the original iframe path and stays visible at ${viewport.width}px`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile", "Mobile iframe playback only");

    await page.setViewportSize(viewport);
    await page.goto("/");

    const segment = page.locator(".vod-card:not([hidden]) .segment-button").first();
    const frame = page.locator("#player-frame");

    await expect(segment).toBeVisible();
    await expect(segment).toBeEnabled();
    await expect(page.locator("#mobile-player-fit-styles")).toHaveCount(1);

    await segment.scrollIntoViewIfNeeded();
    const segmentBox = await segment.boundingBox();
    expect(segmentBox).not.toBeNull();
    await page.touchscreen.tap(
      segmentBox.x + segmentBox.width / 2,
      segmentBox.y + segmentBox.height / 2
    );

    const iframe = page.locator(".player-embed-frame");
    await expect(iframe).toBeVisible();
    await expect(frame).toHaveAttribute("data-player-mode", "iframe");
    await expect(iframe).toHaveAttribute("src", /autoplay=true/);
    await expect(iframe).toHaveAttribute("src", /muted=false/);
    await expect(iframe).toHaveAttribute("src", new RegExp(`video=${await segment.getAttribute("data-vod-id")}`));
    await expect(page.locator(".player-embed-slot__sdk-iframe")).toHaveCount(0);

    const frameBox = await frame.boundingBox();
    const iframeBox = await iframe.boundingBox();
    const layoutSize = await iframe.evaluate((node) => ({
      width: node.offsetWidth,
      height: node.offsetHeight,
    }));

    expect(frameBox).not.toBeNull();
    expect(iframeBox).not.toBeNull();
    expect(layoutSize.width).toBeGreaterThanOrEqual(400);
    expect(layoutSize.height).toBeGreaterThanOrEqual(300);
    expect(frameBox.x).toBeGreaterThanOrEqual(-0.5);
    expect(frameBox.x + frameBox.width).toBeLessThanOrEqual(viewport.width + 0.5);

    const pageHasHorizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1
    );
    expect(pageHasHorizontalOverflow).toBe(false);
  });
}
