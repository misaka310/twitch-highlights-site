const { test, expect } = require("@playwright/test");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const DEPLOY_WAIT_MS = 10 * 60_000;
const LIVE_BASE_URL = process.env.LIVE_BASE_URL || "";

test("deployed mobile first cross-VOD click starts audible playback without overflow", async ({ page, request }) => {
  test.skip(!LIVE_BASE_URL, "LIVE_BASE_URL is required for production verification");

  await waitForExpectedDeployment(request);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.locator("#player-frame").scrollIntoViewIfNeeded();

  const initialVodId = String(
    (await page.locator("#player-frame").getAttribute("data-current-vod-id")) || ""
  );

  const tabs = page.locator(".vod-tab, .mobile-vod-tab");
  await expect(tabs.nth(1)).toBeVisible();
  await tabs.nth(1).click();

  const button = page.locator(".vod-card:not([hidden]) .segment-button").first();
  await expect(button).toBeVisible();
  const targetVodId = String((await button.getAttribute("data-vod-id")) || "");
  const targetStartSec = Number((await button.getAttribute("data-start-sec")) || 0);
  expect(targetVodId).not.toBe("");
  if (initialVodId) {
    expect(targetVodId).not.toBe(initialVodId);
  }

  await button.click();

  await expect
    .poll(async () => getPlaybackState(page), { timeout: 45_000 })
    .toMatchObject({
      currentVodId: targetVodId,
      currentStartSec: String(targetStartSec),
      paused: false,
      muted: false,
    });

  const startedAt = (await getPlaybackState(page)).currentTime;
  await expect
    .poll(async () => (await getPlaybackState(page)).currentTime, { timeout: 20_000 })
    .toBeGreaterThan(startedAt + 1);

  const layout = await page.evaluate(() => {
    const iframe = document.querySelector("#twitch-player iframe");
    const frame = document.querySelector("#player-frame");
    const iframeRect = iframe?.getBoundingClientRect();
    const frameRect = frame?.getBoundingClientRect();
    return {
      innerWidth: window.innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      iframe: iframeRect
        ? { left: iframeRect.left, right: iframeRect.right, width: iframeRect.width }
        : null,
      frame: frameRect
        ? { left: frameRect.left, right: frameRect.right, width: frameRect.width }
        : null,
      portal: frame?.dataset.playerPortal || "",
    };
  });

  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.innerWidth + 1);
  expect(layout.iframe).not.toBeNull();
  expect(layout.iframe.left).toBeGreaterThanOrEqual(-1);
  expect(layout.iframe.right).toBeLessThanOrEqual(layout.innerWidth + 1);
  expect(layout.iframe.width).toBeGreaterThan(0);
  expect(layout.portal).toBe("body");
});

async function waitForExpectedDeployment(request) {
  const expectedPath = path.join(__dirname, "..", "public", "js", "player-portal.js");
  const expectedHash = sha256(fs.readFileSync(expectedPath));
  const deadline = Date.now() + DEPLOY_WAIT_MS;
  let lastHash = "unavailable";

  while (Date.now() < deadline) {
    try {
      const response = await request.get(
        `${LIVE_BASE_URL.replace(/\/$/, "")}/js/player-portal.js?deployment-check=${Date.now()}`,
        { headers: { "cache-control": "no-cache" } }
      );
      if (response.ok()) {
        lastHash = sha256(await response.body());
        if (lastHash === expectedHash) {
          return;
        }
      } else {
        lastHash = `HTTP ${response.status()}`;
      }
    } catch (error) {
      lastHash = String(error?.message || error);
    }
    await new Promise((resolve) => setTimeout(resolve, 10_000));
  }

  throw new Error(`production deployment did not match expected player-portal.js; last=${lastHash}`);
}

async function getPlaybackState(page) {
  const frameNode = page.locator("#player-frame");
  const currentVodId = String((await frameNode.getAttribute("data-current-vod-id")) || "");
  const currentStartSec = String((await frameNode.getAttribute("data-current-start-sec")) || "");
  const twitchFrame = page.frames().find((candidate) => /player\.twitch\.tv/.test(candidate.url()));
  if (!twitchFrame) {
    return {
      currentVodId,
      currentStartSec,
      paused: null,
      muted: null,
      currentTime: -1,
    };
  }

  try {
    const videoState = await twitchFrame.evaluate(() => {
      const video = document.querySelector("video");
      return video
        ? {
            paused: video.paused,
            muted: video.muted,
            currentTime: Number(video.currentTime || 0),
          }
        : { paused: null, muted: null, currentTime: -1 };
    });
    return { currentVodId, currentStartSec, ...videoState };
  } catch {
    return {
      currentVodId,
      currentStartSec,
      paused: null,
      muted: null,
      currentTime: -1,
    };
  }
}

function sha256(buffer) {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}
