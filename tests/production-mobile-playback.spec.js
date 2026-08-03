const { test, expect } = require("@playwright/test");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const DEPLOY_WAIT_MS = 10 * 60_000;
const SITE_CONFIG = JSON.parse(
  fs.readFileSync(path.join(__dirname, "..", "config/site.json"), "utf8")
);
const LIVE_BASE_URL = process.env.LIVE_BASE_URL || String(SITE_CONFIG.site?.base_url || "").trim();
const PUBLIC_ROOT = path.join(__dirname, "..", "public");
const DEPLOYMENT_PATHS = [
  "index.html",
  "favicon.svg",
  "site-config.json",
  ...fs
    .readdirSync(path.join(PUBLIC_ROOT, "assets"), { withFileTypes: true })
    .filter((entry) => entry.isFile() && (entry.name.endsWith(".js") || entry.name.endsWith(".css")))
    .map((entry) => `assets/${entry.name}`)
    .sort(),
];

test("deployed mobile first cross-VOD click starts audible playback without overflow", async ({ page, request }) => {
  test.skip(!LIVE_BASE_URL, "LIVE_BASE_URL is required for production verification");

  await waitForExpectedDeployment(request);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.locator("#player-frame").scrollIntoViewIfNeeded();

  const initialVodId = String(
    (await page.locator("#player-frame").getAttribute("data-current-vod-id")) || ""
  );

  const tabs = page.getByRole("tab");
  await expect(tabs.nth(1)).toBeVisible();
  await tabs.nth(1).click();

  const button = page.locator(".highlight-item").first();
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
    const iframe = document.querySelector(".player-embed--portal iframe");
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
  const expectedHashes = new Map(
    DEPLOYMENT_PATHS.map((relativePath) => [
      relativePath,
      sha256RuntimeText(
        fs.readFileSync(path.join(PUBLIC_ROOT, ...relativePath.split("/"))),
        relativePath
      ),
    ])
  );
  const deadline = Date.now() + DEPLOY_WAIT_MS;
  let lastMismatch = "unavailable";

  while (Date.now() < deadline) {
    const mismatches = [];
    for (const relativePath of DEPLOYMENT_PATHS) {
      try {
        const response = await request.get(
          `${LIVE_BASE_URL.replace(/\/$/, "")}/${relativePath}?deployment-check=${Date.now()}`,
          { headers: { "cache-control": "no-cache" } }
        );
        if (!response.ok()) {
          mismatches.push(`${relativePath}=HTTP ${response.status()}`);
          continue;
        }
        const actualHash = sha256RuntimeText(await response.body(), relativePath);
        if (actualHash !== expectedHashes.get(relativePath)) {
          mismatches.push(`${relativePath}=${actualHash}`);
        }
      } catch (error) {
        mismatches.push(`${relativePath}=${String(error?.message || error)}`);
      }
    }
    if (mismatches.length === 0) {
      return;
    }
    lastMismatch = mismatches.join(", ");
    await new Promise((resolve) => setTimeout(resolve, 10_000));
  }

  throw new Error(`production deployment did not match expected runtime assets; last=${lastMismatch}`);
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

function sha256RuntimeText(buffer, relativePath) {
  let normalized = Buffer.from(buffer).toString("utf8").replace(/\r\n/g, "\n");
  if (relativePath.endsWith(".html")) {
    normalized = normalized
      .split("\n")
      .filter((line) => line.trim() !== "")
      .join("\n");
  }
  return crypto.createHash("sha256").update(normalized, "utf8").digest("hex");
}
