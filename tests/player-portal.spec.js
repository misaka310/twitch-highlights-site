const { test, expect } = require("@playwright/test");

test("Twitch player stays at its visual slot while portaled to body", async ({ page }, testInfo) => {
  await page.goto("/");

  const player = page.locator("#twitch-player");
  const frame = page.locator("#player-frame");

  await expect
    .poll(async () => player.evaluate((element) => element.parentElement === document.body))
    .toBe(true);
  await expect(player).toHaveClass(/player-embed--portal/);
  await expect(frame).toHaveAttribute("data-player-portal", "body");

  await expect
    .poll(async () => measureDifference(frame, player))
    .toMatchObject({ left: 0, top: 0, width: 0, height: 0 });

  const resizedViewport =
    testInfo.project.name === "mobile"
      ? { width: 390, height: 844 }
      : { width: 1280, height: 900 };
  await page.setViewportSize(resizedViewport);

  await expect
    .poll(async () => measureDifference(frame, player))
    .toMatchObject({ left: 0, top: 0, width: 0, height: 0 });
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
