const { test, expect } = require("@playwright/test");

test("wide and responsive layouts keep the Twitch player at the visual slot while portaling it to body", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "Portal geometry check uses desktop Chromium");

  for (const viewport of [
    { width: 1440, height: 1200 },
    { width: 626, height: 935 },
    { width: 400, height: 900 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto("/");

    const player = page.locator("#twitch-player");
    const frame = page.locator("#player-frame");

    await expect
      .poll(async () => player.evaluate((element) => element.parentElement === document.body))
      .toBe(true);

    await expect(frame).toHaveAttribute("data-player-portal", "body");
    await expect
      .poll(async () => measureDifference(frame, player))
      .toMatchObject({ left: 0, top: 0, width: 0, height: 0 });
  }
});

test("sub-400px mobile keeps the Twitch player inside the normal frame", async ({ page }) => {
  await page.setViewportSize({ width: 383, height: 926 });
  await page.goto("/");

  const player = page.locator("#twitch-player");
  await expect
    .poll(async () => player.evaluate((element) => element.parentElement?.id || ""))
    .toBe("player-frame");

  await expect(player).not.toHaveClass(/player-embed--portal/);
  await expect(page.locator("#player-frame")).toHaveAttribute("data-player-portal", "frame");
});

async function measureDifference(frame, player) {
  const [frameBox, playerBox] = await Promise.all([frame.boundingBox(), player.boundingBox()]);
  if (!frameBox || !playerBox) {
    return { left: 999, top: 999, width: 999, height: 999 };
  }
  return {
    left: Math.round(Math.abs(frameBox.x + 1 - playerBox.x)),
    top: Math.round(Math.abs(frameBox.y + 1 - playerBox.y)),
    width: Math.round(Math.abs(frameBox.width - 2 - playerBox.width)),
    height: Math.round(Math.abs(frameBox.height - 2 - playerBox.height)),
  };
}
