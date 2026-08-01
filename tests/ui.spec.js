const fs = require("fs");
const path = require("path");
const { test, expect } = require("@playwright/test");

const dataPath = path.join(__dirname, "..", "data", "vods.json");
const vodIndexPath = path.join(__dirname, "..", "data", "vod_index.json");
const rawData = JSON.parse(fs.readFileSync(dataPath, "utf8").replace(/^\uFEFF/, ""));
const expectedVods = normalizeData(rawData);
const transcriptFixtures = loadTranscriptFixtures(vodIndexPath);
const EXPECTED_SEGMENT_COUNT = expectedVods.reduce(
  (sum, vod) => sum + (Array.isArray(vod?.segments) ? vod.segments.length : 0),
  0
);
const PLAYER_SIZE_MIN_RATIO = 0.7;
const PLAYER_SIZE_MIN_HEIGHT_PX = 220;

test("transcript lookup applies timestamp offset", async () => {
  const cues = [
    { start_sec: 620, end_sec: 627, text: "before" },
    { start_sec: 628, end_sec: 638, text: "target" },
  ];
  const cue = resolveCueForTime(cues, 600, -28);
  expect(cue).not.toBeNull();
  expect(cue.start_sec).toBe(628);
});

test("transcript offset fallback uses metadata chain", async () => {
  expect(resolveTranscriptOffsetSecFromVideo({})).toBe(0);
  expect(resolveTranscriptOffsetSecFromVideo({ timestamp_offset_sec: 7 })).toBe(7);
  expect(resolveTranscriptOffsetSecFromVideo({ timestamps_offset_sec: 9, timestamp_offset_sec: 7 })).toBe(9);
  expect(resolveTranscriptOffsetSecFromVideo({ transcript_offset_sec: 12, timestamps_offset_sec: 9 })).toBe(12);
});

test.describe("UI playback regression guards", () => {
  test.beforeEach(async ({ page }) => {
    await installMockTwitchPlayer(page, {
      readyDelayMs: 1800,
      ignoreSeekBeforeReady: true,
    });

    await page.goto("/");
    await expect(page.locator(".segment-button")).toHaveCount(EXPECTED_SEGMENT_COUNT, {
      timeout: 15000,
    });
  });

  test("right rail date tabs and summary layout stay accurate across pages", async ({ page }) => {
    await expect(page.locator(".vod-rail-headline")).toHaveCount(0);
    await expect(page.locator("#vod-rail-period")).toHaveCount(0);

    const initialTabDates = await getVodTabDateTexts(page);
    expect(initialTabDates.length).toBeGreaterThan(0);
    initialTabDates.forEach((text) => {
      expect(text).toMatch(/^\d{1,2}\u6708\d{1,2}\u65e5\([\u6708\u706b\u6c34\u6728\u91d1\u571f\u65e5]\)$/);
      expect(text).not.toMatch(/\n/);
    });

    await expect(page.locator("#stream-summary")).toBeVisible();
    const layout = await page.evaluate(() => {
      const visibleCard = document.querySelector(".vod-card:not([hidden])");
      const cardBottom =
        visibleCard?.querySelector(".segment-list")?.getBoundingClientRect().bottom || 0;
      const pager = document.querySelector("#pager");
      const summary = document.querySelector("#stream-summary");
      const pagerRect = pager?.getBoundingClientRect();
      const summaryRect = summary?.getBoundingClientRect();
      return {
        cardBottom,
        pagerTop: pagerRect?.top || 0,
        summaryBottom: summaryRect?.bottom || 0,
        summaryTop: summaryRect?.top || 0,
      };
    });
    expect(layout.summaryTop).toBeGreaterThan(layout.cardBottom - 1);
    expect(layout.pagerTop).toBeGreaterThan(layout.summaryBottom - 1);

    await expect(page.locator("#vod-mode-timestamps")).toHaveCount(0);
    await expect(page.locator("#timestamp-list")).toHaveCount(0);
    await expect(page.locator("#stream-summary")).toBeVisible();
    await expect(page.locator(".vod-rail #activity-map")).toHaveCount(0);

    const nextDisabled = await page.locator("#pager-next").getAttribute("aria-disabled");
    if (nextDisabled !== "true") {
      await page.locator("#pager-next").click();
      await expect
        .poll(async () => JSON.stringify(await getVodTabDateTexts(page)))
        .not.toBe(JSON.stringify(initialTabDates));
    }
  });

  test("highlights stay interactive without timestamp mode", async ({ page }) => {
    await expect(page.locator("#vod-mode-timestamps")).toHaveCount(0);
    await expect(page.locator("#timestamp-list")).toHaveCount(0);
    await expect(page.locator("#vod-list")).toBeVisible();
    await expect(page.locator("#stream-summary")).toBeVisible();
    await expect(page.locator("#transcript-panel .transcript-line")).toHaveCount(3);
    await expect(page.getByText("全文を表示", { exact: true })).toHaveCount(0);
    await expect(page.getByText("自動スクロール", { exact: true })).toHaveCount(0);
    await expect(page.getByText("自動追従", { exact: true })).toHaveCount(0);

    const segmentButton = page.locator(".vod-card:not([hidden]) .segment-button").first();
    const segmentStartSec = Number(await segmentButton.getAttribute("data-start-sec"));
    const segmentVodId = String(await segmentButton.getAttribute("data-vod-id"));
    await segmentButton.click();
    await expect(page.locator("#player-frame")).toHaveAttribute("data-current-vod-id", segmentVodId);
    await expect(page.locator("#player-frame")).toHaveAttribute("data-current-start-sec", String(segmentStartSec));
  });

  test("transcript lookup uses transcript_offset_sec and does not read anosa path", async ({ page }) => {
    if (!transcriptFixtures.target || !String(transcriptFixtures.target.anosaPath || "").trim()) {
      test.skip(true, "No transcript fixture with anosa_timestamps_path available");
    }

    const target = transcriptFixtures.target;
    const normalizedAnosaPath = String(target.anosaPath || "").startsWith("/")
      ? String(target.anosaPath || "")
      : `/${String(target.anosaPath || "").replace(/^\/+/, "")}`;
    let anosaFetchCount = 0;
    await page.route(`**${normalizedAnosaPath}`, async (route) => {
      anosaFetchCount += 1;
      await route.continue();
    });

    const pageNumber = Math.floor(target.globalIndex / 3) + 1;
    if (pageNumber !== 1) {
      await page.goto(`/?page=${pageNumber}`);
      await expect(page.locator(".segment-button").first()).toBeVisible({ timeout: 15000 });
    }

    const localTabIndex = target.globalIndex % 3;
    await activateVodTab(page, localTabIndex);
    await page.locator(".vod-card:not([hidden]) .segment-button").first().click();
    await expect(page.locator("#player-frame")).toHaveAttribute("data-current-vod-id", String(target.vodId));
    await expectTranscriptNowMatchesTime(page, target.cues, Number(target.transcriptOffsetSec || 0));
    expect(anosaFetchCount).toBe(0);
  });

  test("transcript lookup falls back to timestamps_offset_sec when transcript_offset_sec is missing", async ({ page }) => {
    const fixtureVodId = "fixture-transcript-offset";
    const indexPayload = {
      updated_at: "2026-05-31T00:00:00Z",
      next_update_at: "2026-06-01T00:00:00Z",
      videos: [
        {
          vod_id: fixtureVodId,
          vod_url: `https://www.twitch.tv/videos/${fixtureVodId}`,
          title: "Fixture Transcript Offset",
          published_at: "2026-05-31T00:00:00Z",
          thumbnail_url: "",
          count: 1,
          detail_path: `/data/vods/${fixtureVodId}.json`,
        },
      ],
    };
    const detailPayload = {
      vod_id: fixtureVodId,
      vod_url: `https://www.twitch.tv/videos/${fixtureVodId}`,
      title: "Fixture Transcript Offset",
      published_at: "2026-05-31T00:00:00Z",
      count: 1,
      items: [
        {
          id: `${fixtureVodId}_60_90`,
          rank: 1,
          start_sec: 60,
          end_sec: 90,
          start_time: "00:01:00",
          end_time: "00:01:30",
          reason: "fixture",
          headline: "Fixture highlight",
          tags: [],
          watch_url: `https://www.twitch.tv/videos/${fixtureVodId}?t=0h1m0s`,
        },
      ],
      activity_map: { bucket_sec: 10, duration_sec: 120, buckets: [0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
      anosa_timestamps_status: "ok",
      anosa_timestamps_path: `data/anosa-timestamps/${fixtureVodId}.json`,
      anosa_timestamps: [
        {
          id: "anosa_001",
          start_sec: 60,
          start_time: "00:01:00",
          label: "あのさぁ、テスト見出し",
          watch_url: `https://www.twitch.tv/videos/${fixtureVodId}?t=0h1m0s`,
        },
      ],
      timestamps_status: "ok",
      timestamps: [],
      transcript_status: "ok",
      transcript_path: `data/transcripts/${fixtureVodId}.json`,
      timestamps_offset_sec: 20,
      transcript_offset_sec: "",
      sync_confidence: "medium",
    };
    const transcriptPayload = {
      cues: [
        { start_sec: 0, end_sec: 20, text: "before cue" },
        { start_sec: 40, end_sec: 70, text: "offset target cue" },
      ],
    };

    await page.route("**/data/vod_index.json**", (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify(indexPayload) })
    );
    await page.route(`**/data/vods/${fixtureVodId}.json**`, (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify(detailPayload) })
    );
    await page.route(`**/data/transcripts/${fixtureVodId}.json**`, (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify(transcriptPayload) })
    );

    await page.goto("/");
    await page.locator(".segment-button").first().click();
    await expect(page.locator("#player-frame")).toHaveAttribute("data-current-vod-id", fixtureVodId);
    await expect(page.locator("#transcript-panel")).toBeVisible();
    await expect(page.locator("#transcript-current")).toHaveText("offset target cue");
  });

  test("transcript panel display is gated by transcript_sync_confidence", async ({ page }) => {
    const transcriptPayload = {
      cues: [
        { start_sec: 0, end_sec: 20, text: "before cue" },
        { start_sec: 40, end_sec: 70, text: "offset target cue" },
      ],
    };
    const scenarios = [
      {
        id: "fixture-transcript-medium-zero",
        confidence: "medium",
        includeConfidence: true,
        offsetSec: 0,
        shouldDisplay: true,
      },
      {
        id: "fixture-transcript-failed-zero",
        confidence: "failed",
        includeConfidence: true,
        offsetSec: 0,
        shouldDisplay: false,
      },
      {
        id: "fixture-transcript-empty",
        confidence: "",
        includeConfidence: true,
        offsetSec: 38,
        shouldDisplay: false,
      },
      {
        id: "fixture-transcript-missing",
        confidence: "",
        includeConfidence: false,
        offsetSec: 38,
        shouldDisplay: false,
      },
    ];

    for (const scenario of scenarios) {
      const fixtureVodId = scenario.id;
      const indexPayload = {
        updated_at: "2026-05-31T00:00:00Z",
        next_update_at: "2026-06-01T00:00:00Z",
        videos: [
          {
            vod_id: fixtureVodId,
            vod_url: `https://www.twitch.tv/videos/${fixtureVodId}`,
            title: `Fixture ${fixtureVodId}`,
            published_at: "2026-05-31T00:00:00Z",
            thumbnail_url: "",
            count: 1,
            detail_path: `/data/vods/${fixtureVodId}.json`,
          },
        ],
      };
      const detailPayload = {
        vod_id: fixtureVodId,
        vod_url: `https://www.twitch.tv/videos/${fixtureVodId}`,
        title: `Fixture ${fixtureVodId}`,
        published_at: "2026-05-31T00:00:00Z",
        count: 1,
        items: [
          {
            id: `${fixtureVodId}_60_90`,
            rank: 1,
            start_sec: 60,
            end_sec: 90,
            start_time: "00:01:00",
            end_time: "00:01:30",
            reason: "fixture",
            headline: "Fixture highlight",
            tags: [],
            watch_url: `https://www.twitch.tv/videos/${fixtureVodId}?t=0h1m0s`,
          },
        ],
        activity_map: { bucket_sec: 10, duration_sec: 120, buckets: [0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
        anosa_timestamps_status: "ok",
        anosa_timestamps_path: `data/anosa-timestamps/${fixtureVodId}.json`,
        anosa_timestamps: [
          {
            id: "anosa_001",
            start_sec: 60,
            start_time: "00:01:00",
            label: "あのさぁ、テスト見出し",
            watch_url: `https://www.twitch.tv/videos/${fixtureVodId}?t=0h1m0s`,
          },
        ],
        transcript_status: "ok",
        transcript_path: `data/transcripts/${fixtureVodId}.json`,
        transcript_offset_sec: scenario.offsetSec,
      };
      if (scenario.includeConfidence) {
        detailPayload.transcript_sync_confidence = scenario.confidence;
        detailPayload.sync_confidence = scenario.confidence;
      }

      await page.route("**/data/vod_index.json**", (route) =>
        route.fulfill({ contentType: "application/json", body: JSON.stringify(indexPayload) })
      );
      await page.route(`**/data/vods/${fixtureVodId}.json**`, (route) =>
        route.fulfill({ contentType: "application/json", body: JSON.stringify(detailPayload) })
      );
      await page.route(`**/data/transcripts/${fixtureVodId}.json**`, (route) =>
        route.fulfill({ contentType: "application/json", body: JSON.stringify(transcriptPayload) })
      );

      await page.goto("/");
      await page.locator(".segment-button").first().click();
      await expect(page.locator("#player-frame")).toHaveAttribute("data-current-vod-id", fixtureVodId);
      if (scenario.shouldDisplay) {
        await expect(page.locator("#transcript-panel")).toBeVisible();
        await expect(page.locator("#transcript-current")).toHaveText("offset target cue");
      } else {
        await expect(page.locator("#transcript-panel")).toBeHidden();
      }
      await page.unroute("**/data/vod_index.json**");
      await page.unroute(`**/data/vods/${fixtureVodId}.json**`);
      await page.unroute(`**/data/transcripts/${fixtureVodId}.json**`);
    }
  });

  test("failed transcript sync still keeps highlights usable while transcript panel stays hidden", async ({ page }) => {
    const fixtureVodId = "fixture-anosa-visible-failed-sync";
    const indexPayload = {
      updated_at: "2026-05-31T00:00:00Z",
      next_update_at: "2026-06-01T00:00:00Z",
      videos: [
        {
          vod_id: fixtureVodId,
          vod_url: `https://www.twitch.tv/videos/${fixtureVodId}`,
          title: "Fixture failed sync confidence",
          published_at: "2026-05-31T00:00:00Z",
          thumbnail_url: "",
          count: 1,
          detail_path: `/data/vods/${fixtureVodId}.json`,
        },
      ],
    };
    const detailPayload = {
      vod_id: fixtureVodId,
      vod_url: `https://www.twitch.tv/videos/${fixtureVodId}`,
      title: "Fixture failed sync confidence",
      published_at: "2026-05-31T00:00:00Z",
      count: 1,
      items: [
        {
          id: `${fixtureVodId}_120_150`,
          rank: 1,
          start_sec: 120,
          end_sec: 150,
          start_time: "00:02:00",
          end_time: "00:02:30",
          reason: "fixture",
          headline: "Fixture highlight",
          tags: [],
          watch_url: `https://www.twitch.tv/videos/${fixtureVodId}?t=0h2m0s`,
        },
      ],
      activity_map: { bucket_sec: 10, duration_sec: 200, buckets: [0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
      anosa_timestamps_status: "ok",
      anosa_timestamps_path: `data/anosa-timestamps/${fixtureVodId}.json`,
      anosa_timestamps: [
        {
          id: "anosa_001",
          start_sec: 120,
          transcript_start_sec: 120,
          start_time: "00:02:00",
          label: "あのさぁ、失敗同期でも表示",
          watch_url: `https://www.twitch.tv/videos/${fixtureVodId}?t=0h2m0s`,
        },
      ],
      transcript_status: "ok",
      transcript_path: `data/transcripts/${fixtureVodId}.json`,
      transcript_offset_sec: 0,
      transcript_sync_confidence: "failed",
      sync_confidence: "failed",
    };
    const transcriptPayload = {
      cues: [
        { start_sec: 100, end_sec: 140, text: "fixture cue current" },
        { start_sec: 141, end_sec: 170, text: "fixture cue next" },
      ],
    };

    await page.route("**/data/vod_index.json**", (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify(indexPayload) })
    );
    await page.route(`**/data/vods/${fixtureVodId}.json**`, (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify(detailPayload) })
    );
    await page.route(`**/data/transcripts/${fixtureVodId}.json**`, (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify(transcriptPayload) })
    );

    await page.goto("/");
    await expect(page.locator("#vod-mode-timestamps")).toHaveCount(0);
    const segmentButton = page.locator(".segment-button").first();
    await segmentButton.click();
    await expect(page.locator("#player-frame")).toHaveAttribute("data-current-vod-id", fixtureVodId);
    await expect(page.locator("#transcript-panel")).toBeHidden();
  });

  test("real transcript cues sync with twitch playback time", async ({ page }) => {
    if (!transcriptFixtures.target) {
      test.skip(true, "No real transcript fixture available in data/vod_index.json");
    }

    const target = transcriptFixtures.target;
    const pageNumber = Math.floor(target.globalIndex / 3) + 1;
    if (pageNumber !== 1) {
      await page.goto(`/?page=${pageNumber}`);
      await expect(page.locator(".segment-button").first()).toBeVisible({ timeout: 15000 });
    }

    const localTabIndex = target.globalIndex % 3;
    await activateVodTab(page, localTabIndex);
    const selectedVodSegment = page.locator(".vod-card:not([hidden]) .segment-button").first();
    await selectedVodSegment.click();
    await expect(page.locator("#player-frame")).toHaveAttribute("data-current-vod-id", String(target.vodId));
    await expect(page.locator("#transcript-panel")).toBeVisible();
    await expect
      .poll(async () => normalizeText(await page.locator("#transcript-current").textContent()))
      .not.toBe("―");
    const stageOrder = await page.evaluate(() => {
      const stage = document.querySelector(".stage-sticky");
      if (!stage) {
        return [];
      }
      return Array.from(stage.children).map((node) => String(node.id || node.className || ""));
    });
    const playerIndex = stageOrder.findIndex((name) => name.includes("player-surface"));
    const assistIndex = stageOrder.findIndex((name) => name.includes("playback-assist-panel"));
    expect(playerIndex).toBeGreaterThanOrEqual(0);
    expect(assistIndex).toBeGreaterThan(playerIndex);
    await expect(page.locator(".vod-rail #activity-map")).toHaveCount(0);
    await expect(page.locator(".playback-assist-panel #activity-map")).toHaveCount(1);
    const assistLayout = await page.evaluate(() => {
      const panel = document.querySelector("#playback-assist-panel");
      const transcript = document.querySelector("#transcript-panel");
      const heatmap = document.querySelector("#activity-map");
      if (!panel || !transcript || !heatmap) {
        return null;
      }
      const panelRect = panel.getBoundingClientRect();
      const transcriptRect = transcript.getBoundingClientRect();
      const heatmapRect = heatmap.getBoundingClientRect();
      const orderedIds = Array.from(panel.children).map((node) => String(node.id || ""));
      return {
        panelWidth: panelRect.width,
        transcriptWidth: transcriptRect.width,
        heatmapWidth: heatmapRect.width,
        transcriptHeight: transcriptRect.height,
        heatmapHeight: heatmapRect.height,
        transcriptLeft: transcriptRect.left,
        heatmapLeft: heatmapRect.left,
        orderedIds,
      };
    });
    expect(assistLayout).not.toBeNull();
    const viewport = page.viewportSize();
    if (viewport && viewport.width >= 641) {
      const transcriptRatio = assistLayout.transcriptWidth / assistLayout.panelWidth;
      const heatmapRatio = assistLayout.heatmapWidth / assistLayout.panelWidth;
      expect(assistLayout.orderedIds[0]).toBe("activity-map");
      expect(assistLayout.orderedIds[1]).toBe("transcript-panel");
      expect(assistLayout.heatmapLeft).toBeLessThan(assistLayout.transcriptLeft);
      expect(transcriptRatio).toBeGreaterThanOrEqual(0.3);
      expect(transcriptRatio).toBeLessThanOrEqual(0.42);
      expect(heatmapRatio).toBeGreaterThanOrEqual(0.58);
      expect(heatmapRatio).toBeLessThanOrEqual(0.7);
      expect(Math.abs(assistLayout.heatmapHeight - assistLayout.transcriptHeight)).toBeLessThanOrEqual(2);
    } else if (viewport) {
      expect(assistLayout.orderedIds[0]).toBe("activity-map");
      expect(assistLayout.orderedIds[1]).toBe("transcript-panel");
      await expect(page.locator("#activity-map-help")).toBeHidden();
      const mobileAssistMetrics = await page.evaluate(() => {
        const svg = document.querySelector("#activity-map .activity-map__svg");
        const rewindButton = document.querySelector("#player-rewind-10");
        const svgHeight = svg ? svg.getBoundingClientRect().height : 0;
        const rewindHeight = rewindButton ? rewindButton.getBoundingClientRect().height : 0;
        return { svgHeight, rewindHeight };
      });
      expect(mobileAssistMetrics.svgHeight).toBeGreaterThanOrEqual(56);
      expect(mobileAssistMetrics.svgHeight).toBeLessThanOrEqual(64);
      expect(mobileAssistMetrics.rewindHeight).toBeLessThanOrEqual(28);
    }

    await expect(page.locator("#transcript-panel h1, #transcript-panel h2, #transcript-panel h3")).toHaveCount(0);
    await expect(page.locator("#transcript-panel")).not.toContainText("全文を表示");
    await expect(page.locator("#transcript-panel")).not.toContainText("自動追従");
    await expect(page.locator("#transcript-panel")).not.toContainText("自動スクロール");
    await expect(page.locator("#transcript-panel .transcript-line")).toHaveCount(3);
    await expect(page.locator("#transcript-panel .transcript-line--current .transcript-current-icon")).toBeVisible();
    await expect(page.locator("#transcript-prev")).toHaveCount(1);
    await expect(page.locator("#transcript-current")).toHaveCount(1);
    await expect(page.locator("#transcript-next")).toHaveCount(1);
    await expect(page.locator("#segment-range, #segment-title, #segment-meta")).toHaveCount(0);

    const transcriptCues = target.cues;
    const timestampLabels = new Set(target.labels.map((label) => normalizeText(label)));
    await expect
      .poll(async () => {
        const currentText = normalizeText(await page.locator("#transcript-current").textContent());
        return transcriptCues.some((cue) => normalizeText(cue.text) === currentText);
      })
      .toBe(true);

    const visibleRows = await Promise.all([
      page.locator("#transcript-prev").textContent(),
      page.locator("#transcript-current").textContent(),
      page.locator("#transcript-next").textContent(),
    ]);
    visibleRows.forEach((text) => {
      const normalized = normalizeText(text);
      if (!normalized || normalized === "―") {
        return;
      }
      expect(timestampLabels.has(normalized)).toBe(false);
    });

    await page.locator(".vod-card:not([hidden]) .segment-button").first().click();
    await expectTranscriptPanelShowsKnownCue(page, transcriptCues);
    await expect(page.locator("#vod-mode-timestamps")).toHaveCount(0);

    await page.locator("#activity-map-button").evaluate((button) => {
      const rect = button.getBoundingClientRect();
      const clickX = Math.max(0, Math.min(rect.width, rect.width * 0.72));
      const clickY = Math.max(0, Math.min(rect.height, rect.height * 0.5));
      const init = {
        bubbles: true,
        cancelable: true,
        clientX: rect.left + clickX,
        clientY: rect.top + clickY,
      };
      button.dispatchEvent(new PointerEvent("pointerdown", init));
      button.dispatchEvent(new MouseEvent("mousedown", init));
      button.dispatchEvent(new PointerEvent("pointerup", init));
      button.dispatchEvent(new MouseEvent("mouseup", init));
      button.dispatchEvent(new MouseEvent("click", init));
    });
    await expectTranscriptPanelShowsKnownCue(page, transcriptCues);

    await page.click("#player-rewind-10");
    await expectTranscriptPanelShowsKnownCue(page, transcriptCues);
  });

  test("transcript panel hides for VOD without transcript cues", async ({ page }) => {
    if (!transcriptFixtures.withoutTranscript) {
      test.skip(true, "No VOD without transcript_path/cues found in data/vod_index.json");
    }

    const target = transcriptFixtures.withoutTranscript;
    const pageNumber = Math.floor(target.globalIndex / 3) + 1;
    if (pageNumber !== 1) {
      await page.goto(`/?page=${pageNumber}`);
      await expect(page.locator(".segment-button").first()).toBeVisible({ timeout: 15000 });
    }

    const localTabIndex = target.globalIndex % 3;
    await activateVodTab(page, localTabIndex);
    const selectedVodSegment = page.locator(".vod-card:not([hidden]) .segment-button").first();
    await selectedVodSegment.click();
    await expect(page.locator("#player-frame")).toHaveAttribute("data-current-vod-id", String(target.vodId));
    await expect(page.locator("#transcript-panel")).toBeHidden();
    await expect(page.locator("#playback-assist-panel")).toHaveClass(/is-transcript-hidden/);
    await expect(page.locator("#activity-map")).toBeVisible();
    const widthSnapshot = await page.evaluate(() => {
      const panel = document.querySelector("#playback-assist-panel");
      const heatmap = document.querySelector("#activity-map");
      if (!panel || !heatmap) {
        return null;
      }
      return {
        panelWidth: panel.getBoundingClientRect().width,
        heatmapWidth: heatmap.getBoundingClientRect().width,
      };
    });
    expect(widthSnapshot).not.toBeNull();
    expect(widthSnapshot.heatmapWidth).toBeGreaterThanOrEqual(widthSnapshot.panelWidth * 0.94);
  });

  test("same VOD fresh interactive mount applies latest pre-ready target once after READY", async ({ page }) => {
    const firstButton = await getSegmentButton(page, 0, 0, { enabledOrder: true });
    const segmentButtons = page.locator(".vod-card:not([hidden]) .segment-button");
    const segmentCount = await segmentButtons.count();
    const targetIndex = Math.min(2, Math.max(0, segmentCount - 1));
    const thirdButton = segmentButtons.nth(targetIndex);
    const targetVodId = String(await thirdButton.getAttribute("data-vod-id"));
    const targetStartSec = Number(await thirdButton.getAttribute("data-start-sec"));

    await firstButton.click();
    await thirdButton.click();

    await expectPlayerState(page, {
      vodId: targetVodId,
      startSec: targetStartSec,
      mode: "interactive",
    });

    await expect
      .poll(async () => {
        const active = await getActiveMockPlayerSnapshot(page);
        const acceptedSeeks = (active?.seekCalls || []).filter((seek) => seek.accepted);
        const targetMatches = acceptedSeeks.filter((seek) => seek.target === targetStartSec);
        return targetMatches.length;
      })
      .toBe(1);
  });

  test("same VOD double-click keeps player size stable from initial URL load", async ({ page }, testInfo) => {
    const sameVodButton = await getSegmentButton(page, 0, 0, { enabledOrder: true });
    const expectedVodId = String(await sameVodButton.getAttribute("data-vod-id"));
    const expectedStartSec = Number(await sameVodButton.getAttribute("data-start-sec"));

    const beforeClick = await capturePlayerBoxSnapshot(page);
    await savePlayerScreenshot(page, testInfo, "ui-same-vod-before");

    await sameVodButton.click();
    await sameVodButton.click();

    await expectPlayerState(page, {
      vodId: expectedVodId,
      startSec: expectedStartSec,
    });

    const afterSecondClick = await capturePlayerBoxSnapshot(page);
    await savePlayerScreenshot(page, testInfo, "ui-same-vod-after-second");
    expectNoPlayerShrink(afterSecondClick, beforeClick);
  });

  test("different VOD first switch uses the requested start_sec", async ({ page }) => {
    const switchButton = await getSegmentButton(page, 1, 0, { enabledOrder: true });
    const expectedVodId = String(await switchButton.getAttribute("data-vod-id"));
    const expectedStartSec = Number(await switchButton.getAttribute("data-start-sec"));

    await switchButton.click();

    await expectPlayerState(page, {
      vodId: expectedVodId,
      startSec: expectedStartSec,
    });
  });

  test("ready cross-VOD switch mounts only the final Twitch SDK iframe", async ({ page }) => {
    const initialButton = await getSegmentButton(page, 0, 0, { enabledOrder: true });
    await initialButton.click();

    await expect
      .poll(
        async () =>
          page.evaluate(() => {
            const instances = window.__mockTwitch?.instances || [];
            const active = instances[instances.length - 1];
            return Boolean(active?.__ready && document.querySelector("#twitch-player .mock-twitch-sdk-iframe"));
          }),
        { timeout: 10000 }
      )
      .toBeTruthy();

    const initialInstanceCount = await page.evaluate(() => window.__mockTwitch?.instances?.length || 0);
    await page.evaluate(() => {
      const player = document.querySelector("#twitch-player");
      const probe = { added: [], removed: [] };
      const collectIframeClasses = (node, target) => {
        if (!(node instanceof Element)) {
          return;
        }
        if (node.matches("iframe")) {
          target.push(node.className || "");
        }
        node.querySelectorAll("iframe").forEach((iframe) => {
          target.push(iframe.className || "");
        });
      };
      const observer = new MutationObserver((records) => {
        records.forEach((record) => {
          record.addedNodes.forEach((node) => collectIframeClasses(node, probe.added));
          record.removedNodes.forEach((node) => collectIframeClasses(node, probe.removed));
        });
      });
      observer.observe(player, { childList: true, subtree: true });
      window.__iframeMountProbe = probe;
      window.__iframeMountProbeObserver = observer;
    });

    const switchButton = await getSegmentButton(page, 1, 0, { enabledOrder: true });
    const expectedVodId = String(await switchButton.getAttribute("data-vod-id"));
    const expectedStartSec = Number(await switchButton.getAttribute("data-start-sec"));
    await switchButton.click();

    await expectPlayerState(page, {
      vodId: expectedVodId,
      startSec: expectedStartSec,
      mode: "interactive",
    });
    await expect
      .poll(
        async () =>
          page.evaluate((minimumCount) => {
            const instances = window.__mockTwitch?.instances || [];
            const active = instances[instances.length - 1];
            return instances.length > minimumCount && active?.__ready === true;
          }, initialInstanceCount),
        { timeout: 10000 }
      )
      .toBeTruthy();

    const probe = await page.evaluate(() => {
      window.__iframeMountProbeObserver?.disconnect();
      return window.__iframeMountProbe;
    });
    expect(probe.added).toEqual(["mock-twitch-sdk-iframe"]);
    expect(probe.removed).toHaveLength(1);
    expect(probe.removed[0]).toContain("mock-twitch-sdk-iframe");
    expect(probe.removed.join(" ")).not.toContain("player-embed-frame");
  });

  test("different VOD double-click keeps player size stable from initial URL load", async ({ page }, testInfo) => {
    const differentVodButton = await getSegmentButton(page, 1, 0, { enabledOrder: true });
    const expectedVodId = String(await differentVodButton.getAttribute("data-vod-id"));
    const expectedStartSec = Number(await differentVodButton.getAttribute("data-start-sec"));

    const beforeClick = await capturePlayerBoxSnapshot(page);
    await savePlayerScreenshot(page, testInfo, "ui-different-vod-before");

    await differentVodButton.click();
    await expectPlayerState(page, {
      vodId: expectedVodId,
      startSec: expectedStartSec,
    });
    const afterFirstClick = await capturePlayerBoxSnapshot(page);
    await savePlayerScreenshot(page, testInfo, "ui-different-vod-after-first");

    await differentVodButton.click();
    await expectPlayerState(page, {
      vodId: expectedVodId,
      startSec: expectedStartSec,
    });

    const afterSecondClick = await capturePlayerBoxSnapshot(page);
    await savePlayerScreenshot(page, testInfo, "ui-different-vod-after-second");
    expectNoPlayerShrink(afterFirstClick, beforeClick);
    expectNoPlayerShrink(afterSecondClick, beforeClick);
  });

  test("first same-VOD click must seek correctly without requiring a second click", async ({ page }) => {
    const firstButton = await getSegmentButton(page, 0, 0, { enabledOrder: true });
    const secondButton = await getSegmentButton(page, 0, 1, { enabledOrder: true });
    const expectedVodId = String(await secondButton.getAttribute("data-vod-id"));
    const expectedStartSec = Number(await secondButton.getAttribute("data-start-sec"));

    await firstButton.click();
    await secondButton.click();

    await expectPlayerState(page, {
      vodId: expectedVodId,
      startSec: expectedStartSec,
    });

    const currentSecAfterFirstClick = Number(await page.locator("#player-frame").getAttribute("data-current-start-sec"));
    expect(currentSecAfterFirstClick).toBe(expectedStartSec);

    await secondButton.click();

    await expectPlayerState(page, {
      vodId: expectedVodId,
      startSec: expectedStartSec,
    });
  });

  test("custom button playback route works and iframe is never duplicated", async ({ page }) => {
    const firstButton = await getSegmentButton(page, 0, 0, { enabledOrder: true });
    const expectedVodId = String(await firstButton.getAttribute("data-vod-id"));
    await firstButton.click();
    await expect(page.locator("#activity-map")).toBeVisible();

    const beforeRewind = Number(await page.locator("#player-frame").getAttribute("data-current-start-sec"));
    await page.click("#player-rewind-10");

    await expectPlayerState(page, {
      vodId: expectedVodId,
      startSec: Math.max(0, beforeRewind - 10),
    });

    const beforeMapClick = Number(await page.locator("#player-frame").getAttribute("data-current-start-sec"));
    await page.locator("#activity-map-button").evaluate((button) => {
      const rect = button.getBoundingClientRect();
      const clickX = Math.max(0, Math.min(rect.width, rect.width * 0.6));
      const clickY = Math.max(0, Math.min(rect.height, rect.height * 0.5));
      const init = {
        bubbles: true,
        cancelable: true,
        clientX: rect.left + clickX,
        clientY: rect.top + clickY,
      };
      button.dispatchEvent(new PointerEvent("pointerdown", init));
      button.dispatchEvent(new MouseEvent("mousedown", init));
      button.dispatchEvent(new PointerEvent("pointerup", init));
      button.dispatchEvent(new MouseEvent("mouseup", init));
      button.dispatchEvent(new MouseEvent("click", init));
    });

    await expect(page.locator("#player-frame")).toHaveAttribute("data-current-vod-id", expectedVodId);
    await expect
      .poll(async () => Number(await page.locator("#player-frame").getAttribute("data-current-start-sec")))
      .not.toBe(beforeMapClick);

    await expect
      .poll(async () => page.locator("#twitch-player iframe").count())
      .toBe(1);
  });
});

async function expectPlayerState(page, { vodId, startSec, mode }) {
  const expected = {
    vodId: String(vodId),
    startSec: String(startSec),
  };
  if (mode != null) {
    expected.mode = String(mode);
  }

  await expect
    .poll(async () => {
      const playerFrame = page.locator("#player-frame");
      return {
        vodId: await playerFrame.getAttribute("data-current-vod-id"),
        startSec: await playerFrame.getAttribute("data-current-start-sec"),
        mode: await playerFrame.getAttribute("data-player-mode"),
      };
    })
    .toMatchObject(expected);
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
    })
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

async function getSegmentButton(page, vodIndex, segmentIndex, options = {}) {
  const { enabledOrder = false } = options;
  if (enabledOrder) {
    const enabledTabs = await getEnabledVodTabs(page);
    if (enabledTabs.length <= vodIndex) {
      throw new Error(`enabled tab index out of range: ${vodIndex}`);
    }
    await activateVodTab(page, enabledTabs[vodIndex].index);
  } else {
    await activateVodTab(page, vodIndex);
  }
  return page.locator(".vod-card:not([hidden]) .segment-button").nth(segmentIndex);
}

async function getVodTabDateTexts(page) {
  const tabs = page.locator(".vod-tab .vod-tab__date, .mobile-vod-tab .vod-tab__date");
  const count = await tabs.count();
  const values = [];
  for (let index = 0; index < count; index += 1) {
    const text = String((await tabs.nth(index).textContent()) || "").trim();
    if (text) {
      values.push(text);
    }
  }
  return values;
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

async function getEnabledVodTabs(page) {
  const tabs = page.locator(".vod-tab, .mobile-vod-tab");
  const tabCount = await tabs.count();
  const enabled = [];
  for (let index = 0; index < tabCount; index += 1) {
    const tab = tabs.nth(index);
    const disabledAttr = await tab.getAttribute("disabled");
    const ariaDisabled = await tab.getAttribute("aria-disabled");
    if (disabledAttr !== null || String(ariaDisabled || "").toLowerCase() === "true") {
      continue;
    }
    const vodId = String((await tab.getAttribute("data-vod-id")) || "").trim();
    if (!vodId) {
      continue;
    }
    enabled.push({ index, vodId });
  }
  return enabled;
}

async function getActiveMockPlayerSnapshot(page) {
  return page.evaluate(() => {
    const players = window.__mockTwitch?.instances || [];
    const active = players[players.length - 1];
    if (!active) {
      return null;
    }
    return {
      seekCalls: Array.isArray(active.__seekCalls) ? active.__seekCalls.slice() : [],
    };
  });
}

async function installMockTwitchPlayer(page, config = {}) {
  await page.addInitScript((initConfig) => {
    const defaultConfig = {
      readyDelayMs: 0,
      ignoreSeekBeforeReady: false,
      autoPlayOnReady: true,
    };

    const mockState = {
      config: { ...defaultConfig, ...(initConfig || {}) },
      instances: [],
      nextId: 1,
    };

    const parseTime = (value) => {
      const text = String(value || "");
      const match = text.match(/^(\d+)h(\d+)m(\d+)s$/);
      if (!match) {
        return 0;
      }
      return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]);
    };

    class MockPlayer {
      static READY = "ready";
      static PLAY = "play";
      static PLAYING = "playing";
      static PAUSE = "pause";
      static ENDED = "ended";
      static PLAYBACK_BLOCKED = "playback_blocked";

      constructor(container, options = {}) {
        this.__id = mockState.nextId++;
        this.__options = options;
        this.__listeners = new Map();
        this.__ready = false;
        this.__destroyed = false;
        this.__paused = false;
        this.__muted = Boolean(options.muted);
        this.__currentTime = parseTime(options.time);
        this.__seekCalls = [];

        const iframe = document.createElement("iframe");
        iframe.className = "mock-twitch-sdk-iframe";
        iframe.src = "about:blank#mock-twitch-player";
        container.appendChild(iframe);
        this.__iframe = iframe;

        mockState.instances.push(this);

        const delay = Math.max(0, Number(mockState.config.readyDelayMs) || 0);
        window.setTimeout(() => {
          if (this.__destroyed) {
            return;
          }
          this.__ready = true;
          this.__emit(MockPlayer.READY);
          if (mockState.config.autoPlayOnReady !== false) {
            this.__paused = false;
            this.__emit(MockPlayer.PLAY);
            this.__emit(MockPlayer.PLAYING);
          }
        }, delay);
      }

      addEventListener(eventName, callback) {
        if (!eventName || typeof callback !== "function") {
          return;
        }
        const key = String(eventName);
        const list = this.__listeners.get(key) || [];
        list.push(callback);
        this.__listeners.set(key, list);
      }

      seek(startSec) {
        const target = Math.max(0, Math.floor(Number(startSec) || 0));
        const ignoreBeforeReady = Boolean(mockState.config.ignoreSeekBeforeReady) && !this.__ready;
        const accepted = !ignoreBeforeReady;
        this.__seekCalls.push({
          target,
          accepted,
          ready: this.__ready,
        });
        if (!accepted) {
          return;
        }
        this.__currentTime = target;
      }

      play() {
        this.__paused = false;
        this.__emit(MockPlayer.PLAY);
        this.__emit(MockPlayer.PLAYING);
        return Promise.resolve();
      }

      pause() {
        this.__paused = true;
        this.__emit(MockPlayer.PAUSE);
      }

      destroy() {
        this.__destroyed = true;
        this.__iframe?.remove();
      }

      setMuted(muted) {
        this.__muted = Boolean(muted);
      }

      getCurrentTime() {
        return this.__currentTime;
      }

      __emit(eventName) {
        const list = this.__listeners.get(String(eventName)) || [];
        list.forEach((callback) => {
          try {
            callback();
          } catch (error) {
            // Keep the mock resilient to callback failures.
          }
        });
      }
    }

    window.__mockTwitch = mockState;
    window.Twitch = { Player: MockPlayer };
  }, config);
}

function loadTranscriptFixtures(indexJsonPath) {
  let indexPayload = {};
  try {
    indexPayload = JSON.parse(fs.readFileSync(indexJsonPath, "utf8").replace(/^\uFEFF/, ""));
  } catch (_error) {
    return { target: null, withoutTranscript: null };
  }
  const videos = Array.isArray(indexPayload?.videos) ? indexPayload.videos : [];
  const parsedVideos = videos
    .map((video, globalIndex) => ({ video, globalIndex }))
    .map(({ video, globalIndex }) => {
      const vodId = String(video?.vod_id || "").trim();
      const detailPath = String(video?.detail_path || "").trim();
      if (!vodId || !detailPath) {
        return null;
      }
      const detailFsPath = path.join(__dirname, "..", detailPath.replace(/^\//, ""));
      if (!fs.existsSync(detailFsPath)) {
        return null;
      }
      let detail = {};
      try {
        detail = JSON.parse(fs.readFileSync(detailFsPath, "utf8").replace(/^\uFEFF/, ""));
      } catch (_error) {
        return null;
      }
      const transcriptPath = String(detail?.transcript_path || "").trim();
      const anosaPath = String(detail?.anosa_timestamps_path || "").trim();
      const timestampsStatus = String(detail?.anosa_timestamps_status || "").trim().toLowerCase();
      const transcriptOffsetSec = resolveTranscriptOffsetSecFromVideo(detail);
      let cues = [];
      if (transcriptPath) {
        const transcriptFsPath = path.join(__dirname, "..", transcriptPath.replace(/^\//, ""));
        if (fs.existsSync(transcriptFsPath)) {
          let transcriptPayload = {};
          try {
            transcriptPayload = JSON.parse(fs.readFileSync(transcriptFsPath, "utf8").replace(/^\uFEFF/, ""));
          } catch (_error) {
            transcriptPayload = {};
          }
          cues = Array.isArray(transcriptPayload?.cues)
            ? transcriptPayload.cues
                .map((cue) => ({
                  start_sec: Number(cue?.start_sec),
                  end_sec: Number(cue?.end_sec),
                  text: String(cue?.text || "").trim(),
                }))
                .filter(
                  (cue) =>
                    Number.isFinite(cue.start_sec) &&
                    cue.start_sec >= 0 &&
                    Number.isFinite(cue.end_sec) &&
                    cue.end_sec > cue.start_sec &&
                    cue.text
                )
                .sort((a, b) => a.start_sec - b.start_sec)
            : [];
        }
      }
      const labels = Array.isArray(detail?.anosa_timestamps)
        ? detail.anosa_timestamps.map((row) => String(row?.label || "").trim()).filter(Boolean)
        : [];
      return {
        vodId,
        globalIndex,
        transcriptPath,
        anosaPath,
        timestampsStatus,
        transcriptOffsetSec,
        cues,
        labels,
      };
    })
    .filter(Boolean);

  const targetCandidates = parsedVideos.filter(
    (entry) =>
      entry.timestampsStatus === "ok" &&
      String(entry.anosaPath || "").trim() &&
      Array.isArray(entry.cues) &&
      entry.cues.length > 0
  );
  const target =
    targetCandidates.find((entry) => Number(entry.globalIndex) > 0) ||
    targetCandidates[0] ||
    null;
  const withoutTranscript =
    parsedVideos.find(
      (entry) => !String(entry.transcriptPath || "").trim() || !Array.isArray(entry.cues) || entry.cues.length === 0
    ) || null;

  return {
    target,
    withoutTranscript: withoutTranscript
      ? {
          vodId: withoutTranscript.vodId,
          globalIndex: withoutTranscript.globalIndex,
        }
      : null,
  };
}

function normalizeText(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeTimestampOffsetSec(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return 0;
  }
  return Math.trunc(parsed);
}

function resolveTranscriptOffsetSecFromVideo(video) {
  return normalizeTimestampOffsetSec(
    video?.transcript_offset_sec ?? video?.timestamps_offset_sec ?? video?.timestamp_offset_sec ?? 0
  );
}

function resolveCueForTime(cues, currentSec, offsetSec = 0) {
  if (!Array.isArray(cues) || cues.length === 0) {
    return null;
  }
  if (!Number.isFinite(Number(currentSec))) {
    return cues[0];
  }
  const lookupSec = Math.max(0, Math.floor(Number(currentSec)) - normalizeTimestampOffsetSec(offsetSec));
  let low = 0;
  let high = cues.length - 1;
  let direct = null;
  while (low <= high) {
    const mid = Math.floor((low + high) / 2);
    const cue = cues[mid];
    if (cue.start_sec <= lookupSec && lookupSec < cue.end_sec) {
      direct = cue;
      break;
    }
    if (cue.start_sec <= lookupSec) {
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  if (direct) {
    return direct;
  }
  if (high >= 0) {
    return cues[high];
  }
  return cues[0];
}

async function expectTranscriptNowMatchesTime(page, cues, offsetSec = 0, allowZeroOffsetFallback = false) {
  await expect
    .poll(async () => {
      const currentStartSec = Number(await page.locator("#player-frame").getAttribute("data-current-start-sec"));
      if (!Number.isFinite(currentStartSec)) {
        return false;
      }
      const currentText = normalizeText(await page.locator("#transcript-current").textContent());
      const offsetCandidates = [offsetSec];
      if (allowZeroOffsetFallback && normalizeTimestampOffsetSec(offsetSec) !== 0) {
        offsetCandidates.push(0);
      }
      return offsetCandidates.some((candidate) => {
        const expected = resolveCueForTime(cues, Math.floor(currentStartSec), candidate);
        return Boolean(expected) && normalizeText(expected.text) === currentText;
      });
    })
    .toBe(true);
}

async function expectTranscriptPanelShowsKnownCue(page, cues) {
  await expect
    .poll(async () => {
      const currentText = normalizeText(await page.locator("#transcript-current").textContent());
      if (!currentText || currentText === "―") {
        return false;
      }
      return cues.some((cue) => normalizeText(cue?.text) === currentText);
    })
    .toBe(true);
}

function normalizeData(data) {
  const videos = Array.isArray(data.videos)
    ? data.videos
    : Array.isArray(data.vods)
      ? data.vods
      : [];

  return videos
    .filter((video) => video && (video.vod_id || video.id))
    .sort((a, b) => new Date(b.published_at).getTime() - new Date(a.published_at).getTime())
    .slice(0, 3)
    .map((video) => ({
      id: video.vod_id || video.id,
      title: video.title,
      timestamps: (Array.isArray(video.anosa_timestamps) ? video.anosa_timestamps : [])
        .filter((row) => row && row.start_sec != null && row.label)
        .map((row, index) => ({
          id: row.id || `ts_${index + 1}`,
          start_sec: Number(row.start_sec),
          label: String(row.label || "").trim(),
        }))
        .filter((row) => Number.isFinite(row.start_sec) && row.start_sec >= 0 && row.label)
        .sort((a, b) => a.start_sec - b.start_sec)
        .slice(0, 10),
      segments: (Array.isArray(video.items) ? video.items : Array.isArray(video.segments) ? video.segments : [])
        .filter((segment) => segment && (segment.id || segment.start_sec != null))
        .sort((a, b) => (a.rank ?? a.start_sec) - (b.rank ?? b.start_sec))
        .slice(0, 3),
    }))
    .filter((video) => video.segments.length > 0 || video.timestamps.length > 0);
}

