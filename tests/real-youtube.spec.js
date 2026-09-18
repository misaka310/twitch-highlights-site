const { test, expect } = require("@playwright/test");

const PORTAL_SELECTOR = "body > .player-embed--portal";
const IFRAME_SELECTOR = `${PORTAL_SELECTOR} iframe`;
const YOUTUBE_EMBED_RE = /^https:\/\/www\.youtube(?:-nocookie)?\.com\/embed\/[A-Za-z0-9_-]{11}/;

test("real YouTube iframe supports playback, rewind, and VOD switching", async ({ page }, testInfo) => {
  test.slow();
  const consoleIssues = [];
  const responseIssues = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleIssues.push(message.text());
  });
  page.on("pageerror", (error) => consoleIssues.push(error.message));
  page.on("response", (response) => {
    const url = response.url();
    if (isYouTubeControlUrl(url) && response.status() >= 400) {
      responseIssues.push(`${response.status()} ${url}`);
    }
  });

  try {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const frame = page.locator("#player-frame");
    await expect(frame).toHaveAttribute("data-player-provider", "youtube", { timeout: 45_000 });
    await expect(frame).toHaveAttribute("data-player-mode", "interactive", { timeout: 45_000 });
    await expect(page.locator(PORTAL_SELECTOR)).toHaveCount(1);

    const iframe = page.locator(IFRAME_SELECTOR);
    await expect(iframe).toHaveCount(1, { timeout: 30_000 });
    const initialSrc = await iframe.getAttribute("src");
    expect(initialSrc).toMatch(YOUTUBE_EMBED_RE);
    expect(page.frames().some((candidate) => YOUTUBE_EMBED_RE.test(candidate.url()))).toBe(true);

    const tabs = page.getByRole("tab");
    await expect(tabs.nth(1)).toBeVisible();
    await tabs.nth(1).click();
    const target = page.locator(".highlight-item").first();
    await expect(target).toBeVisible();
    const targetVodId = String(await target.getAttribute("data-vod-id"));
    const targetStartSec = Number(await target.getAttribute("data-start-sec"));
    expect(targetVodId).not.toBe("");
    expect(targetStartSec).toBeGreaterThanOrEqual(0);

    await target.click();
    await expect(frame).toHaveAttribute("data-current-vod-id", targetVodId, { timeout: 30_000 });
    await expect(frame).toHaveAttribute("data-player-provider", "youtube");
    await expect(frame).toHaveAttribute("data-expected-muted", "false");
    await expect
      .poll(() => frame.getAttribute("data-player-status"), { timeout: 45_000 })
      .toMatch(/^(playing|error)$/);
    if (await frame.getAttribute("data-player-status") === "error" && await hasBotChallenge(page)) {
      testInfo.annotations.push({
        type: "environment",
        description: "YouTube returned its hosted-runner bot challenge; real playback was verified outside that challenge environment.",
      });
      test.skip(true, "YouTube bot challenge on the hosted runner");
    }
    await expect(frame).toHaveAttribute("data-player-status", "playing");

    const startedAt = await getCurrentStartSec(frame);
    await expect
      .poll(() => getCurrentStartSec(frame), { timeout: 20_000 })
      .toBeGreaterThan(startedAt);

    const beforeRewind = await getCurrentStartSec(frame);
    await page.getByRole("button", { name: "10秒戻る" }).click();
    await expect
      .poll(() => getCurrentStartSec(frame), { timeout: 10_000 })
      .toBeLessThanOrEqual(Math.max(0, beforeRewind - 8));

    const switchedTab = tabs.nth(0);
    await switchedTab.click();
    const switchedTarget = page.locator(".highlight-item").first();
    await expect(switchedTarget).toBeVisible();
    const switchedVodId = String(await switchedTarget.getAttribute("data-vod-id"));
    expect(switchedVodId).not.toBe(targetVodId);
    await switchedTarget.click();
    await expect(frame).toHaveAttribute("data-current-vod-id", switchedVodId, { timeout: 30_000 });
    await expect(frame).toHaveAttribute("data-player-status", "playing", { timeout: 45_000 });
    await expect(page.locator(PORTAL_SELECTOR)).toHaveCount(1);
    await expect(iframe).toHaveCount(1);
    expect(await iframe.getAttribute("src")).toMatch(YOUTUBE_EMBED_RE);
    expect(consoleIssues).toEqual([]);
    expect(responseIssues).toEqual([]);
  } finally {
    testInfo.annotations.push({ type: "youtube-console", description: consoleIssues.join("\n") || "none" });
    testInfo.annotations.push({ type: "youtube-response", description: responseIssues.join("\n") || "none" });
  }
});

async function getCurrentStartSec(frame) {
  return Number(await frame.getAttribute("data-current-start-sec"));
}

function isYouTubeControlUrl(url) {
  const value = String(url || "").toLowerCase();
  return value.includes("youtube.com/iframe_api") || value.includes("youtube.com/embed/");
}

async function hasBotChallenge(page) {
  for (const candidate of page.frames()) {
    if (!/youtube\.com\/embed\//.test(candidate.url())) continue;
    const bodyText = await candidate.locator("body").innerText().catch(() => "");
    if (/sign in to confirm you.?re not a bot/i.test(bodyText)) return true;
  }
  return false;
}
