const { test, expect } = require("@playwright/test");
const { PNG } = require("playwright-core/lib/utilsBundle");

const PLAYER_SIZE_MIN_RATIO = 0.7;
const PLAYER_SIZE_MIN_HEIGHT_PX = 220;
const MAX_BOTTOM_BLACK_BAND_RATIO = 0.28;
const EXPECTED_SEGMENT_COUNT = 3;
const PORTAL_SELECTOR = "body > .player-embed--portal";
const IFRAME_SELECTOR = `${PORTAL_SELECTOR} iframe`;

test("Twitch embed playback and unmute works", async ({ page }, testInfo) => {
  test.slow();
  test.skip(testInfo.project.name !== "desktop", "Twitch embed check is desktop only");

  const consoleIssues = [];
  const responseIssues = [];
  page.on("console", (message) => {
    if (!["error", "warning"].includes(message.type())) return;
    if (isRelevantEmbedMessage(message.text())) {
      consoleIssues.push(`[${message.type()}] ${message.text()}`);
    }
  });
  page.on("response", (response) => {
    if (isRelevantTwitchUrl(response.url()) && response.status() >= 400) {
      responseIssues.push(`${response.status()} ${response.url()}`);
    }
  });

  try {
    await page.goto("/");
    const frame = page.locator("#player-frame");
    await frame.scrollIntoViewIfNeeded();
    await expect(page.locator(".highlight-item")).toHaveCount(EXPECTED_SEGMENT_COUNT);

    const secondButton = await getHighlightButton(page, 0, 1);
    const startSec = Number(await secondButton.getAttribute("data-start-sec"));
    const vodId = String(await secondButton.getAttribute("data-vod-id"));
    await secondButton.click();

    await expect(frame).toHaveAttribute("data-current-vod-id", vodId, { timeout: 25000 });
    await expect(frame).toHaveAttribute("data-current-start-sec", String(startSec), { timeout: 25000 });
    await expect(frame).toHaveAttribute("data-expected-autoplay", "true");
    await expect(frame).toHaveAttribute("data-expected-muted", "false");
    await expect(frame).toHaveAttribute("data-triggered-by-user", "true");
    await waitForPlayablePlayer(page);
    await expect(page.locator(PORTAL_SELECTOR)).toHaveCount(1);
    await expect(page.locator(IFRAME_SELECTOR)).toHaveCount(1);

    await expect
      .poll(async () => getInnerVideoState(page), { timeout: 25000 })
      .toMatchObject({ paused: false, muted: false });
    const startedAt = await getInnerCurrentTime(page);
    await expect
      .poll(async () => getInnerCurrentTime(page), { timeout: 15000 })
      .toBeGreaterThan(startedAt + 1);

    const switchedButton = await getHighlightButton(page, 1, 0);
    const switchedStartSec = Number(await switchedButton.getAttribute("data-start-sec"));
    const switchedVodId = String(await switchedButton.getAttribute("data-vod-id"));
    await switchedButton.click();
    await expect(frame).toHaveAttribute("data-current-vod-id", switchedVodId, { timeout: 25000 });
    await expect(frame).toHaveAttribute("data-current-start-sec", String(switchedStartSec), { timeout: 25000 });
    await expect(page.locator(PORTAL_SELECTOR)).toHaveCount(1);
    await expect(page.locator(IFRAME_SELECTOR)).toHaveCount(1);
  } finally {
    testInfo.annotations.push({ type: "embed-console", description: consoleIssues.join("\n") || "none" });
    testInfo.annotations.push({ type: "embed-response", description: responseIssues.join("\n") || "none" });
  }
});

test("same VOD second click after VOD switch keeps Twitch rendering area healthy", async ({ page }, testInfo) => {
  test.slow();
  test.skip(testInfo.project.name !== "desktop", "Twitch embed check is desktop only");

  await page.goto("/");
  await page.locator("#player-frame").scrollIntoViewIfNeeded();
  const sameVodButton = await getHighlightButton(page, 1, 1);
  const beforeClick = await capturePlayerBoxSnapshot(page);
  await savePlayerScreenshot(page, testInfo, "real-same-vod-before");

  await sameVodButton.click();
  await waitForPlayablePlayer(page);
  await sameVodButton.click();
  await waitForPlayablePlayer(page);

  const startedAt = await getInnerCurrentTime(page);
  await expect
    .poll(async () => getInnerCurrentTime(page), { timeout: 15000 })
    .toBeGreaterThan(startedAt + 1);
  await expectNoMajorBottomBlackBand(page);

  const afterSecondClick = await capturePlayerBoxSnapshot(page);
  await savePlayerScreenshot(page, testInfo, "real-same-vod-after-second");
  expectNoPlayerShrink(afterSecondClick, beforeClick);
});

test("different VOD double-click keeps player size stable from initial load", async ({ page }, testInfo) => {
  test.slow();
  test.skip(testInfo.project.name !== "desktop", "Twitch embed check is desktop only");

  await page.goto("/");
  await page.locator("#player-frame").scrollIntoViewIfNeeded();
  const differentVodButton = await getHighlightButton(page, 1, 0);
  const beforeClick = await capturePlayerBoxSnapshot(page);
  await savePlayerScreenshot(page, testInfo, "real-different-vod-before");

  await differentVodButton.click();
  await waitForPlayablePlayer(page);
  const afterFirstClick = await capturePlayerBoxSnapshot(page);
  await savePlayerScreenshot(page, testInfo, "real-different-vod-after-first");

  await differentVodButton.click();
  await waitForPlayablePlayer(page);
  const afterSecondClick = await capturePlayerBoxSnapshot(page);
  await savePlayerScreenshot(page, testInfo, "real-different-vod-after-second");

  expectNoPlayerShrink(afterFirstClick, beforeClick);
  expectNoPlayerShrink(afterSecondClick, beforeClick);
});

async function getHighlightButton(page, vodIndex, segmentIndex) {
  const tabs = page.getByRole("tab");
  await expect(tabs).toHaveCount(3);
  await tabs.nth(vodIndex).click();
  const buttons = page.locator(".highlight-item");
  await expect(buttons).toHaveCount(EXPECTED_SEGMENT_COUNT);
  return buttons.nth(segmentIndex);
}

async function waitForPlayablePlayer(page) {
  await expect
    .poll(async () => {
      const mode = await page.locator("#player-frame").getAttribute("data-player-mode");
      const vodId = await page.locator("#player-frame").getAttribute("data-current-vod-id");
      return ["interactive", "iframe"].includes(mode || "") && Boolean(vodId);
    }, { timeout: 25000 })
    .toBeTruthy();
  await expect(page.locator(PORTAL_SELECTOR)).toHaveCount(1);
  await expect(page.locator(IFRAME_SELECTOR)).toHaveCount(1, { timeout: 25000 });
}

async function getInnerVideoState(page) {
  try {
    const frame = await getTwitchFrame(page);
    if (!frame) return null;
    return await frame.evaluate(() => {
      const video = document.querySelector("video");
      return video ? {
        paused: video.paused,
        muted: video.muted,
        currentTime: video.currentTime,
        readyState: video.readyState,
      } : null;
    });
  } catch {
    return null;
  }
}

async function getInnerCurrentTime(page) {
  const state = await getInnerVideoState(page);
  return Number(state?.currentTime || 0);
}

async function getTwitchFrame(page) {
  const iframe = page.locator(IFRAME_SELECTOR).first();
  await expect(iframe).toBeVisible({ timeout: 25000 });
  const handle = await iframe.elementHandle();
  return handle ? handle.contentFrame() : null;
}

async function getPlayerBottomBlackBandRatio(page) {
  const portal = page.locator(PORTAL_SELECTOR);
  await expect(portal).toBeVisible({ timeout: 25000 });
  return computeBottomBlackBandRatio(await portal.screenshot({ animations: "disabled" }));
}

function computeBottomBlackBandRatio(pngBuffer) {
  const png = PNG.sync.read(pngBuffer);
  const width = Number(png.width) || 0;
  const height = Number(png.height) || 0;
  if (width <= 0 || height <= 0) return 1;
  const xStart = Math.floor(width * 0.08);
  const xEnd = Math.max(xStart + 1, Math.ceil(width * 0.92));
  const yStart = Math.floor(height * 0.35);
  let maxConsecutiveBlackRows = 0;
  let consecutiveBlackRows = 0;
  for (let y = yStart; y < height; y += 1) {
    let darkPixels = 0;
    let totalPixels = 0;
    for (let x = xStart; x < xEnd; x += 1) {
      const index = (y * width + x) * 4;
      const [r, g, b, a] = png.data.slice(index, index + 4);
      if (a < 16) continue;
      totalPixels += 1;
      const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;
      const channelSpan = Math.max(r, g, b) - Math.min(r, g, b);
      if (luminance < 24 && channelSpan < 16) darkPixels += 1;
    }
    const darkRatio = totalPixels > 0 ? darkPixels / totalPixels : 0;
    if (darkRatio >= 0.9) {
      consecutiveBlackRows += 1;
      maxConsecutiveBlackRows = Math.max(maxConsecutiveBlackRows, consecutiveBlackRows);
    } else {
      consecutiveBlackRows = 0;
    }
  }
  return maxConsecutiveBlackRows / height;
}

async function expectNoMajorBottomBlackBand(page) {
  await expect
    .poll(async () => getPlayerBottomBlackBandRatio(page), { timeout: 25000 })
    .toBeLessThanOrEqual(MAX_BOTTOM_BLACK_BAND_RATIO);
}

async function savePlayerScreenshot(page, testInfo, name) {
  await page.screenshot({ path: testInfo.outputPath(`${name}.png`), fullPage: false });
}

async function capturePlayerBoxSnapshot(page) {
  await expect(page.locator(PORTAL_SELECTOR)).toBeVisible({ timeout: 25000 });
  return page.evaluate((portalSelector) => {
    const measure = (selector) => {
      const node = document.querySelector(selector);
      if (!node) return null;
      const rect = node.getBoundingClientRect();
      return {
        width: Math.round(rect.width * 100) / 100,
        height: Math.round(rect.height * 100) / 100,
      };
    };
    return {
      frame: measure("#player-frame"),
      player: measure(portalSelector),
      iframe: measure(`${portalSelector} iframe`),
    };
  }, PORTAL_SELECTOR);
}

function expectNoPlayerShrink(afterSnapshot, beforeSnapshot) {
  expectBoxStable(afterSnapshot.frame, beforeSnapshot.frame, "player-frame");
  expectBoxStable(afterSnapshot.player, beforeSnapshot.player, "player");
  expectBoxStable(afterSnapshot.iframe, beforeSnapshot.iframe, "iframe");
}

function expectBoxStable(afterBox, beforeBox, label) {
  expect(afterBox, `${label} after box`).not.toBeNull();
  expect(beforeBox, `${label} before box`).not.toBeNull();
  expect(afterBox.width, `${label} width`).toBeGreaterThanOrEqual(beforeBox.width * PLAYER_SIZE_MIN_RATIO);
  expect(afterBox.height, `${label} height`).toBeGreaterThanOrEqual(
    Math.max(beforeBox.height * PLAYER_SIZE_MIN_RATIO, PLAYER_SIZE_MIN_HEIGHT_PX),
  );
}

function isRelevantEmbedMessage(text) {
  const value = String(text || "").toLowerCase();
  return ["twitch", "player.twitch.tv", "embed", "autoplay", "refused", "failed to load", "blocked"]
    .some((marker) => value.includes(marker));
}

function isRelevantTwitchUrl(url) {
  const value = String(url || "").toLowerCase();
  return value.includes("player.twitch.tv") || value.includes("twitch.tv");
}
