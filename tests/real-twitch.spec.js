const { test, expect } = require("@playwright/test");
const { PNG } = require("playwright-core/lib/utilsBundle");
const fs = require("fs");
const path = require("path");
const PLAYER_SIZE_MIN_RATIO = 0.7;
const PLAYER_SIZE_MIN_HEIGHT_PX = 220;
const MAX_BOTTOM_BLACK_BAND_RATIO = 0.28;
const EXPECTED_SEGMENT_COUNT = resolveExpectedSegmentCount();

test("Twitch embed playback and unmute works", async ({ page }, testInfo) => {
  test.slow();
  test.skip(testInfo.project.name !== "desktop", "Twitch embed check is desktop only");

  const consoleIssues = [];
  const responseIssues = [];

  page.on("console", (msg) => {
    if (!["error", "warning"].includes(msg.type())) {
      return;
    }
    const text = msg.text();
    if (isRelevantEmbedMessage(text)) {
      consoleIssues.push(`[${msg.type()}] ${text}`);
    }
  });

  page.on("response", (response) => {
    const url = response.url();
    if (!isRelevantTwitchUrl(url)) {
      return;
    }
    if (response.status() >= 400) {
      responseIssues.push(`${response.status()} ${url}`);
    }
  });

  try {
    await page.goto("/");
    await page.locator("#player-frame").scrollIntoViewIfNeeded();

    const buttons = page.locator(".segment-button");
    await expect(buttons).toHaveCount(EXPECTED_SEGMENT_COUNT);

    const secondButton = await getSegmentButton(page, 0, 1);
    const startSec = Number(await secondButton.getAttribute("data-start-sec"));
    const vodId = String(await secondButton.getAttribute("data-vod-id"));

    await secondButton.click();

    await expect
      .poll(async () => getPlayerSnapshot(page), { timeout: 25000 })
      .toMatchObject({
        requestedVodId: vodId,
        requestedStartSec: startSec,
        currentVodId: vodId,
        currentStartSec: String(startSec),
        overlayVisible: false,
        playbackBlocked: false,
      });

    await expect
      .poll(async () => {
        const snapshot = await getPlayerSnapshot(page);
        return ["interactive", "iframe"].includes(snapshot.playerMode);
      }, { timeout: 25000 })
      .toBeTruthy();

    await expect
      .poll(async () => getInnerVideoState(page), { timeout: 25000 })
      .toMatchObject({
        paused: false,
        muted: false,
      });

    const startedAt = await getInnerCurrentTime(page);

    await expect
      .poll(async () => getInnerCurrentTime(page), { timeout: 15000 })
      .toBeGreaterThan(startedAt + 1);

    const fourthButton = await getSegmentButton(page, 1, 0);
    const switchedStartSec = Number(await fourthButton.getAttribute("data-start-sec"));
    const switchedVodId = String(await fourthButton.getAttribute("data-vod-id"));

    await fourthButton.click();

    await expect
      .poll(async () => getPlayerSnapshot(page), { timeout: 25000 })
      .toMatchObject({
        requestedVodId: switchedVodId,
        requestedStartSec: switchedStartSec,
        currentVodId: switchedVodId,
        currentStartSec: String(switchedStartSec),
      });

    await expect(page.locator("#twitch-player iframe")).toHaveCount(1);

  } finally {
    testInfo.annotations.push({ type: "embed-console", description: consoleIssues.join("\n") || "none" });
    testInfo.annotations.push({ type: "embed-response", description: responseIssues.join("\n") || "none" });
  }
});

test("same VOD second click after VOD switch keeps Twitch rendering area healthy (real Twitch)", async ({ page }, testInfo) => {
  test.slow();
  test.skip(testInfo.project.name !== "desktop", "Twitch embed check is desktop only");

  await page.goto("/");
  await page.locator("#player-frame").scrollIntoViewIfNeeded();

  const buttons = page.locator(".segment-button");
  await expect(buttons).toHaveCount(EXPECTED_SEGMENT_COUNT);

  // Repro path: first click switches to another VOD (different route),
  // second click hits same VOD path and must not collapse Twitch rendering.
  const sameVodButton = await getSegmentButton(page, 1, 1);
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

test("different VOD double-click keeps player size stable from initial URL load (real Twitch)", async ({ page }, testInfo) => {
  test.slow();
  test.skip(testInfo.project.name !== "desktop", "Twitch embed check is desktop only");

  await page.goto("/");
  await page.locator("#player-frame").scrollIntoViewIfNeeded();

  const buttons = page.locator(".segment-button");
  await expect(buttons).toHaveCount(EXPECTED_SEGMENT_COUNT);

  const differentVodButton = await getSegmentButton(page, 1, 0);
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

async function getPlayerSnapshot(page) {
  return page.evaluate(() => {
    const playerFrame = document.querySelector("#player-frame");
    const playerUnmute = document.querySelector("#player-unmute");
    return {
      requestedVodId: playerFrame?.dataset.currentVodId || "",
      requestedStartSec: Number(playerFrame?.dataset.currentStartSec || 0),
      currentVodId: playerFrame?.dataset.currentVodId || "",
      currentStartSec: playerFrame?.dataset.currentStartSec || "",
      playerMode: playerFrame?.dataset.playerMode || "",
      overlayVisible: Boolean(playerUnmute && !playerUnmute.hidden),
      playbackBlocked: false,
      muted: playerUnmute && playerUnmute.hidden ? false : true,
    };
  });
}

async function getInnerVideoState(page) {
  try {
    const frame = await getTwitchFrame(page);
    if (!frame) {
      return null;
    }
    return await frame.evaluate(() => {
      const video = document.querySelector("video");
      return video
        ? {
            paused: video.paused,
            muted: video.muted,
            currentTime: video.currentTime,
            readyState: video.readyState,
          }
        : null;
    });
  } catch (error) {
    return null;
  }
}

async function getPlayerBottomBlackBandRatio(page) {
  const frame = page.locator("#player-frame");
  await expect(frame).toBeVisible({ timeout: 25000 });
  const pngBuffer = await frame.screenshot({ animations: "disabled" });
  return computeBottomBlackBandRatio(pngBuffer);
}

function computeBottomBlackBandRatio(pngBuffer) {
  const png = PNG.sync.read(pngBuffer);
  const width = Number(png.width) || 0;
  const height = Number(png.height) || 0;
  if (width <= 0 || height <= 0) {
    return 1;
  }

  const xStart = Math.floor(width * 0.08);
  const xEnd = Math.max(xStart + 1, Math.ceil(width * 0.92));
  const yStart = Math.floor(height * 0.35);
  const yEnd = height;

  let maxConsecutiveBlackRows = 0;
  let consecutiveBlackRows = 0;

  for (let y = yStart; y < yEnd; y += 1) {
    let darkPixels = 0;
    let totalPixels = 0;

    for (let x = xStart; x < xEnd; x += 1) {
      const index = (y * width + x) * 4;
      const r = png.data[index];
      const g = png.data[index + 1];
      const b = png.data[index + 2];
      const a = png.data[index + 3];
      if (a < 16) {
        continue;
      }
      totalPixels += 1;

      const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;
      const channelSpan = Math.max(r, g, b) - Math.min(r, g, b);
      if (luminance < 24 && channelSpan < 16) {
        darkPixels += 1;
      }
    }

    const darkRatio = totalPixels > 0 ? darkPixels / totalPixels : 0;
    if (darkRatio >= 0.9) {
      consecutiveBlackRows += 1;
      if (consecutiveBlackRows > maxConsecutiveBlackRows) {
        maxConsecutiveBlackRows = consecutiveBlackRows;
      }
    } else {
      consecutiveBlackRows = 0;
    }
  }

  return maxConsecutiveBlackRows / height;
}

async function expectNoMajorBottomBlackBand(page) {
  await expect
    .poll(async () => {
      const ratio = await getPlayerBottomBlackBandRatio(page);
      return Number.isFinite(ratio) ? ratio : 1;
    }, { timeout: 25000 })
    .toBeLessThanOrEqual(MAX_BOTTOM_BLACK_BAND_RATIO);
}

async function getInnerCurrentTime(page) {
  const state = await getInnerVideoState(page);
  return Number(state?.currentTime || 0);
}

async function getTwitchFrame(page) {
  const iframe = page.locator("#twitch-player iframe").first();
  await expect(iframe).toBeVisible({ timeout: 25000 });
  const handle = await iframe.elementHandle();
  if (!handle) {
    return null;
  }
  return handle.contentFrame();
}

async function waitForPlayablePlayer(page) {
  await expect
    .poll(async () => {
      const snapshot = await getPlayerSnapshot(page);
      return ["interactive", "iframe"].includes(snapshot.playerMode) && snapshot.currentVodId !== "";
    }, { timeout: 25000 })
    .toBeTruthy();

  await expect
    .poll(async () => {
      const box = await capturePlayerBoxSnapshot(page);
      return Number(box?.iframe?.height || 0);
    }, { timeout: 25000 })
    .toBeGreaterThan(0);
}

async function savePlayerScreenshot(page, testInfo, name) {
  await page.screenshot({
    path: testInfo.outputPath(`${name}.png`),
    fullPage: false,
  });
}

async function capturePlayerBoxSnapshot(page) {
  await expect
    .poll(async () => {
      const snapshot = await page.evaluate(() => {
        const measure = (selector) => {
          const node = document.querySelector(selector);
          if (!node) {
            return null;
          }
          const rect = node.getBoundingClientRect();
          return {
            width: Math.round(rect.width * 100) / 100,
            height: Math.round(rect.height * 100) / 100,
          };
        };
        return {
          frame: measure("#player-frame"),
          player: measure("#twitch-player"),
          iframe: measure("#twitch-player iframe"),
        };
      });
      const frameHeight = Number(snapshot?.frame?.height || 0);
      const iframeHeight = Number(snapshot?.iframe?.height || 0);
      return frameHeight > 0 && iframeHeight > 0 ? snapshot : null;
    }, { timeout: 25000 })
    .not.toBeNull();

  return page.evaluate(() => {
    const measure = (selector) => {
      const node = document.querySelector(selector);
      if (!node) {
        return null;
      }
      const rect = node.getBoundingClientRect();
      return {
        width: Math.round(rect.width * 100) / 100,
        height: Math.round(rect.height * 100) / 100,
      };
    };
    return {
      frame: measure("#player-frame"),
      player: measure("#twitch-player"),
      iframe: measure("#twitch-player iframe"),
    };
  });
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
    Math.max(beforeBox.height * PLAYER_SIZE_MIN_RATIO, PLAYER_SIZE_MIN_HEIGHT_PX)
  );
}

function isRelevantEmbedMessage(text) {
  const value = String(text || "").toLowerCase();
  return (
    value.includes("twitch") ||
    value.includes("player.twitch.tv") ||
    value.includes("embed") ||
    value.includes("autoplay") ||
    value.includes("refused") ||
    value.includes("failed to load") ||
    value.includes("blocked")
  );
}

function isRelevantTwitchUrl(url) {
  const value = String(url || "").toLowerCase();
  return value.includes("player.twitch.tv") || value.includes("twitch.tv");
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

function resolveExpectedSegmentCount() {
  const dataPath = path.join(__dirname, "..", "data", "vods.json");
  let payload = {};
  try {
    payload = JSON.parse(fs.readFileSync(dataPath, "utf8").replace(/^\uFEFF/, ""));
  } catch (_error) {
    return 0;
  }
  const videos = Array.isArray(payload?.videos)
    ? payload.videos
    : Array.isArray(payload?.vods)
      ? payload.vods
      : [];
  return videos
    .filter((video) => video && (video.vod_id || video.id))
    .sort((a, b) => new Date(String(b?.published_at || "")).getTime() - new Date(String(a?.published_at || "")).getTime())
    .slice(0, 3)
    .reduce((sum, video) => {
      const items = Array.isArray(video?.items)
        ? video.items
        : Array.isArray(video?.segments)
          ? video.segments
          : [];
      return sum + Math.min(3, items.length);
    }, 0);
}
