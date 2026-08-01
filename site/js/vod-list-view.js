import { SCHEDULE_TEXT, SITE_BUILD_LABEL } from "./config.js";
import {
  formatDate,
  formatDateOnly,
  formatDateOnlyMobile,
  formatScheduleDate,
  formatSegmentLabelCompact,
  resolveNextUpdateAt,
} from "./formatters.js";

const JAPAN_DATE_BUTTON_FORMATTER = new Intl.DateTimeFormat("ja-JP", {
  timeZone: "Asia/Tokyo",
  month: "numeric",
  day: "numeric",
  weekday: "short",
});
const UNSET_TEXT = "―";

export function normalizeTranscriptSyncConfidence(value) {
  const confidence = String(value || "").trim().toLowerCase();
  if (confidence === "high" || confidence === "medium" || confidence === "low" || confidence === "failed") {
    return confidence;
  }
  return "";
}

export function isTranscriptDisplayReadyForVod(vod) {
  if (!isTranscriptDataAvailableForVod(vod)) {
    return false;
  }
  const confidence = normalizeTranscriptSyncConfidence(vod?.transcript_sync_confidence ?? vod?.sync_confidence);
  if (confidence !== "high" && confidence !== "medium" && confidence !== "low") {
    return false;
  }
  const offsetSec = resolveTranscriptOffsetSecFromVodMetadata(vod);
  return Number.isFinite(offsetSec);
}

function normalizeTimestampOffsetSec(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return 0;
  }
  return Math.trunc(parsed);
}

export function createVodListView({ state, elements, renderActivityMap, requestPlayback, renderEmptyState }) {
  const vodTabState = {
    activeVodId: null,
  };
  const transcriptState = {
    cuesByPath: new Map(),
    loadingByPath: new Map(),
    offsetByVodId: new Map(),
    pendingRender: null,
  };

  bindPlayerFrameSummarySync();

  function renderSchedule(updatedAt, nextUpdateAt, source) {
    const updatedTargets = [elements.updatedAt, elements.updatedAtMobile].filter(Boolean);
    const nextUpdateTargets = [elements.nextUpdateAt, elements.nextUpdateAtMobile].filter(Boolean);
    const buildLabelTargets = [elements.buildLabel, elements.buildLabelMobile].filter(Boolean);

    buildLabelTargets.forEach((element) => {
      element.textContent = SITE_BUILD_LABEL;
    });

    if (!updatedAt) {
      updatedTargets.forEach((element) => {
        element.textContent = formatUpdatedScheduleText(SCHEDULE_TEXT.unset);
      });
      nextUpdateTargets.forEach((element) => {
        element.textContent = formatNextScheduleText(SCHEDULE_TEXT.unset);
      });
      return;
    }

    const formatted = formatScheduleDate(updatedAt);
    const suffix = source === "cache" ? " (キャッシュ表示)" : "";
    const nextDisplayValue = resolveNextUpdateAt(nextUpdateAt, updatedAt);
    updatedTargets.forEach((element) => {
      element.textContent = formatUpdatedScheduleText(formatted, suffix);
    });
    nextUpdateTargets.forEach((element) => {
      element.textContent = formatNextScheduleText(formatScheduleDate(nextDisplayValue));
    });
  }

  function formatUpdatedScheduleText(value, suffix = "") {
    return `${SCHEDULE_TEXT.dataUpdated}: ${value}${suffix}`;
  }

  function formatNextScheduleText(value) {
    return `${SCHEDULE_TEXT.nextDataUpdate}: ${value}`;
  }

  function bindPlayerFrameSummarySync() {
    if (!elements.playerFrame || typeof MutationObserver !== "function") {
      return;
    }

    const observer = new MutationObserver(() => {
      renderStreamSummary(resolveActiveVodId());
      renderTranscriptPanel();
    });

    observer.observe(elements.playerFrame, {
      attributes: true,
      attributeFilter: ["data-current-vod-id", "data-current-start-sec", "data-player-status"],
    });
  }

  function renderVodList() {
    elements.vodList.replaceChildren();

    state.vods.forEach((vod, index) => {
      const card = elements.vodCardTemplate.content.firstElementChild.cloneNode(true);
      const vodDate = card.querySelector(".vod-date");
      const globalIndex = index + 1 + (state.pageOffset || 0);

      card.dataset.vodId = vod.id;
      card.id = `vod-card-${vod.id}`;
      card.querySelector(".vod-order").textContent = `#${globalIndex}`;
      vodDate.textContent = formatDateOnly(vod.published_at);
      vodDate.dataset.mobileDate = formatDateOnlyMobile(vod.published_at);
      card.setAttribute("aria-label", `VOD ${globalIndex}: ${vod.title} / ${formatDate(vod.published_at)}`);

      const segmentList = card.querySelector(".segment-list");

      vod.segments.forEach((segment) => {
        const item = elements.segmentItemTemplate.content.firstElementChild.cloneNode(true);
        const button = item.querySelector(".segment-button");
        const rank = item.querySelector(".segment-rank");
        const tags = item.querySelector(".segment-tags");
        const thumbnail = item.querySelector(".segment-thumbnail");
        const startTimeBadge = item.querySelector(".segment-start-time");

        button.dataset.vodId = vod.id;
        button.dataset.segmentId = segment.id;
        button.dataset.startSec = String(segment.start_sec);
        button.dataset.hasThumbnail = "false";
        button.querySelector(".segment-summary").textContent = segment.summary;
        if (startTimeBadge) {
          startTimeBadge.textContent = formatSegmentLabelCompact(segment.start_sec);
        }
        rank.textContent = segment.rank_label;
        rank.hidden = !segment.rank_label;
        renderSegmentTags(tags, segment.tags);
        renderSegmentThumbnail({ button, thumbnail, screenshotUrl: segment.screenshot_url });
        button.addEventListener("click", () => {
          state.selectedVodId = vod.id;
          state.selectedSegmentId = segment.id;
          vodTabState.activeVodId = vod.id;
          renderSelection({ triggeredByUser: true, muted: false });
          updateActiveButtons();
        });
        segmentList.append(item);
      });

      elements.vodList.append(card);
    });

    updateActiveButtons();
    renderVodTabs();
    applyVodTabVisibility();
  }

  function renderSegmentTags(container, tags) {
    container.replaceChildren();
    container.hidden = false;

    tags.slice(0, 2).forEach((tag) => {
      const chip = document.createElement("span");
      chip.className = "segment-tag";
      chip.textContent = tag;
      container.append(chip);
    });

    while (container.childElementCount < 2) {
      const emptyChip = document.createElement("span");
      emptyChip.className = "segment-tag segment-tag--empty";
      emptyChip.setAttribute("aria-hidden", "true");
      container.append(emptyChip);
    }
  }

  function renderSegmentThumbnail({ button, thumbnail, screenshotUrl }) {
    if (!button || !thumbnail) {
      return;
    }

    const resolvedUrl = String(screenshotUrl || "").trim();
    if (!resolvedUrl) {
      thumbnail.hidden = true;
      thumbnail.removeAttribute("src");
      button.dataset.hasThumbnail = "false";
      return;
    }

    const showFallback = () => {
      thumbnail.hidden = true;
      thumbnail.removeAttribute("src");
      button.dataset.hasThumbnail = "false";
    };

    thumbnail.hidden = false;
    thumbnail.src = resolvedUrl;
    button.dataset.hasThumbnail = "loading";
    thumbnail.addEventListener(
      "load",
      () => {
        button.dataset.hasThumbnail = "true";
      },
      { once: true }
    );
    thumbnail.addEventListener("error", showFallback, { once: true });
  }

  function renderSelection(options = {}) {
    const selection = getSelectedSegment();
    const selectedVodId = String(state.selectedVodId || "");
    const fallbackVod = state.vods.find((entry) => String(entry.id) === selectedVodId) || state.vods[0] || null;
    const fallbackStartSec = resolveRequestedStartSec();

    if (!selection && !fallbackVod) {
      renderEmptyState("選択中の見どころを表示できません。");
      return;
    }

    const vod = selection?.vod || fallbackVod;
    const segment = selection?.segment || null;
    const playbackStartSec = segment ? Math.max(0, Math.floor(Number(segment.start_sec) || 0)) : fallbackStartSec;
    if (elements.segmentTitleMobile) {
      elements.segmentTitleMobile.textContent = vod.title;
    }
    renderActivityMap(vod);
    syncPlaybackAssistLayout();
    requestPlayback(vod.id, playbackStartSec, options);
    renderStreamSummary(resolveActiveVodId());
    ensureTranscriptLoaded(vod);
    ensureTranscriptOffsetReady(vod);
    setPendingTranscriptRender(String(vod.id), playbackStartSec);
    renderTranscriptPanel(String(vod.id), playbackStartSec);
    elements.statusMessage.hidden = true;
  }

  function updateActiveButtons() {
    const buttons = elements.vodList.querySelectorAll(".segment-button");
    const cards = elements.vodList.querySelectorAll(".vod-card");

    buttons.forEach((button) => {
      const isActive =
        button.dataset.vodId === state.selectedVodId &&
        button.dataset.segmentId === state.selectedSegmentId;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-pressed", String(isActive));
    });

    cards.forEach((card) => {
      card.classList.toggle("is-current", card.dataset.vodId === state.selectedVodId);
    });
  }

  function getVodTabsContainer() {
    if (elements.vodTabs) {
      return elements.vodTabs;
    }

    const rail = elements.vodList?.parentElement;
    if (!rail) {
      return null;
    }

    let container = rail.querySelector(".vod-tabs");
    if (!container) {
      container = document.createElement("div");
      container.className = "vod-tabs mobile-vod-tabs";
      rail.insertBefore(container, elements.vodList);
    }

    container.id = container.id || "vod-tabs";
    container.setAttribute("role", "tablist");
    container.setAttribute("aria-label", "配信日タブ");
    return container;
  }

  function resolveActiveVodId() {
    const existing = String(vodTabState.activeVodId || "");
    if (existing && state.vods.some((vod) => String(vod.id) === existing)) {
      return existing;
    }

    const selected = String(state.selectedVodId || "");
    if (selected && state.vods.some((vod) => String(vod.id) === selected)) {
      return selected;
    }

    return String(state.vods[0]?.id || "");
  }

  function renderVodTabs() {
    const container = getVodTabsContainer();
    if (!container) {
      return;
    }

    vodTabState.activeVodId = resolveActiveVodId();
    container.replaceChildren();

    state.vods.forEach((vod) => {
      const tab = document.createElement("button");
      const dateLabel = document.createElement("span");
      const vodId = String(vod.id);

      tab.type = "button";
      tab.className = "vod-tab mobile-vod-tab";
      tab.dataset.vodId = vodId;
      tab.dataset.syncConfidence = String(vod.sync_confidence || "");
      tab.id = `vod-tab-${vodId}`;
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-controls", `vod-card-${vodId}`);
      tab.addEventListener("click", () => {
        vodTabState.activeVodId = vodId;
        applyVodTabVisibility();
      });

      dateLabel.className = "vod-tab__date mobile-vod-tab__label";
      dateLabel.textContent = formatVodDateButton(vod.published_at);

      tab.append(dateLabel);
      container.append(tab);
    });
  }

  function applyVodTabVisibility() {
    const container = getVodTabsContainer();
    if (!container) {
      return;
    }

    const activeVodId = resolveActiveVodId();
    const cards = elements.vodList.querySelectorAll(".vod-card");
    const tabs = container.querySelectorAll(".vod-tab");

    vodTabState.activeVodId = activeVodId;
    container.hidden = state.vods.length <= 1;

    tabs.forEach((tab) => {
      const isActive = String(tab.dataset.vodId || "") === activeVodId;
      tab.classList.toggle("is-active", isActive);
      tab.setAttribute("aria-selected", String(isActive));
      tab.tabIndex = isActive ? 0 : -1;
    });

    if (activeVodId) {
      state.selectedVodId = activeVodId;
    }
    cards.forEach((card) => {
      const isActive = String(card.dataset.vodId || "") === activeVodId;
      const shouldHide = !isActive;
      card.hidden = shouldHide;
      card.setAttribute("aria-hidden", String(shouldHide));
    });

    const activeVod = state.vods.find((entry) => String(entry.id) === String(activeVodId)) || null;
    ensureSegmentSelectionForVod(activeVod);
    updateActiveButtons();
    renderStreamSummary(activeVodId);
    renderActivityMap(activeVod);
    syncPlaybackAssistLayout();
    ensureTranscriptLoaded(activeVod);
    ensureTranscriptOffsetReady(activeVod);
    const selectedStartSec = Number(getSelectedSegment()?.segment?.start_sec);
    const initialStartSec =
      Number.isFinite(selectedStartSec) && selectedStartSec >= 0 ? Math.floor(selectedStartSec) : null;
    setPendingTranscriptRender(activeVodId, initialStartSec);
    renderTranscriptPanel(activeVodId, initialStartSec);
  }

  function ensureSegmentSelectionForVod(vod) {
    if (!vod) {
      return;
    }
    const selectedVodId = String(state.selectedVodId || "");
    const selectedSegmentId = String(state.selectedSegmentId || "");
    const isSameVod = selectedVodId === String(vod.id);
    const hasSegmentOnVod = isSameVod && vod.segments.some((segment) => String(segment.id) === selectedSegmentId);
    if (hasSegmentOnVod) {
      return;
    }
    const fallback = vod.segments[0];
    if (fallback) {
      state.selectedSegmentId = String(fallback.id);
    }
  }

  function renderStreamSummary(activeVodId) {
    if (!elements.streamSummary) {
      return;
    }

    const vod = state.vods.find((entry) => String(entry.id) === String(activeVodId)) || state.vods[0] || null;
    elements.streamSummary.hidden = !vod;
    if (!vod) {
      return;
    }

    setText(elements.summaryTitle, String(vod.title || "").trim() || UNSET_TEXT);
    setText(elements.summaryDate, formatDate(vod.published_at));
    setText(elements.summaryDuration, formatDuration(resolveVodDurationSec(vod)));
    setText(elements.summaryChat, formatChatVolume(vod));
    setText(elements.summaryPlaying, formatPlayingState(vod));
    setText(elements.summaryPlaybackPosition, formatPlaybackPosition(vod));
  }

  function renderTranscriptPanel(activeVodId = "", forcedStartSec = null) {
    const selection = getSelectedSegment();
    if (!elements.transcriptPanel || !elements.transcriptCurrent || !elements.transcriptPrev || !elements.transcriptNext) {
      return;
    }

    const playerFrameState = resolvePlayerFrameState();
    const targetVodId = String(
      playerFrameState.vodId ||
        activeVodId ||
        resolveActiveVodId() ||
        selection?.vod?.id ||
        ""
    ).trim();
    const vod = state.vods.find((entry) => String(entry.id) === targetVodId) || selection?.vod || state.vods[0] || null;
    if (!vod) {
      hideTranscriptPanel();
      return;
    }

    const transcriptPath = String(vod.transcript_path || "").trim();
    if (!transcriptPath || !isTranscriptDisplayReady(vod)) {
      hideTranscriptPanel();
      return;
    }

    ensureTranscriptLoaded(vod);
    ensureTranscriptOffsetReady(vod);
    const cues = transcriptState.cuesByPath.get(transcriptPath);
    if (!Array.isArray(cues) || cues.length === 0) {
      hideTranscriptPanel();
      return;
    }
    const offsetSec = resolveTranscriptOffsetSec(vod);

    const startSec =
      Number.isFinite(forcedStartSec) && Number(forcedStartSec) >= 0
        ? Math.floor(Number(forcedStartSec))
        : Number.isFinite(playerFrameState.startSec) && Number(playerFrameState.startSec) >= 0
          ? Math.floor(Number(playerFrameState.startSec))
          : transcriptState.pendingRender &&
              String(transcriptState.pendingRender.vodId || "") === String(vod.id) &&
              Number.isFinite(transcriptState.pendingRender.startSec) &&
              Number(transcriptState.pendingRender.startSec) >= 0
            ? Math.floor(Number(transcriptState.pendingRender.startSec))
          : Number.isFinite(Number(selection?.segment?.start_sec))
            ? Math.floor(Number(selection.segment.start_sec))
            : null;

    const transcriptLookupSec = resolveTranscriptLookupSec(startSec, offsetSec);
    const index = resolveCurrentCueIndex(cues, transcriptLookupSec);
    if (index < 0) {
      hideTranscriptPanel();
      return;
    }
    elements.transcriptPanel.hidden = false;
    elements.transcriptPrev.textContent = String(cues[index - 1]?.text || "").trim() || UNSET_TEXT;
    elements.transcriptCurrent.textContent = String(cues[index]?.text || "").trim() || UNSET_TEXT;
    elements.transcriptNext.textContent = String(cues[index + 1]?.text || "").trim() || UNSET_TEXT;
    if (transcriptState.pendingRender && String(transcriptState.pendingRender.vodId || "") === String(vod.id)) {
      transcriptState.pendingRender = null;
    }
    syncPlaybackAssistLayout();
  }

  function hideTranscriptPanel() {
    if (!elements.transcriptPanel || !elements.transcriptPrev || !elements.transcriptCurrent || !elements.transcriptNext) {
      return;
    }
    elements.transcriptPanel.hidden = true;
    elements.transcriptPrev.textContent = UNSET_TEXT;
    elements.transcriptCurrent.textContent = UNSET_TEXT;
    elements.transcriptNext.textContent = UNSET_TEXT;
    syncPlaybackAssistLayout();
  }

  function resolveCurrentCueIndex(cues, startSec) {
    if (!Array.isArray(cues) || cues.length === 0) {
      return -1;
    }
    if (!Number.isFinite(startSec) || Number(startSec) < 0) {
      return 0;
    }
    const safeStartSec = Math.floor(Number(startSec));

    let low = 0;
    let high = cues.length - 1;
    let directMatch = -1;
    while (low <= high) {
      const middle = Math.floor((low + high) / 2);
      const cue = cues[middle];
      const cueStart = Math.floor(Number(cue?.start_sec || 0));
      const cueEnd = Math.max(cueStart + 1, Math.floor(Number(cue?.end_sec || cueStart + 1)));
      if (cueStart <= safeStartSec && safeStartSec < cueEnd) {
        directMatch = middle;
        break;
      }
      if (cueStart <= safeStartSec) {
        low = middle + 1;
      } else {
        high = middle - 1;
      }
    }
    if (directMatch >= 0) {
      return directMatch;
    }

    if (high >= 0) {
      return high;
    }
    return 0;
  }

  function ensureTranscriptLoaded(vod) {
    if (!isTranscriptDisplayReady(vod)) {
      return;
    }
    const transcriptPath = String(vod?.transcript_path || "").trim();
    if (!transcriptPath) {
      return;
    }
    if (transcriptState.cuesByPath.has(transcriptPath)) {
      return;
    }
    if (transcriptState.loadingByPath.has(transcriptPath)) {
      return;
    }
    const fetchTask = fetchTranscriptCues(transcriptPath)
      .then((cues) => {
        transcriptState.cuesByPath.set(transcriptPath, cues);
      })
      .catch(() => {
        transcriptState.cuesByPath.set(transcriptPath, []);
      })
      .finally(() => {
        transcriptState.loadingByPath.delete(transcriptPath);
        const pending = transcriptState.pendingRender;
        const pendingStartSec =
          pending && String(pending.vodId || "") === String(vod?.id || "") ? Number(pending.startSec) : null;
        renderTranscriptPanel(String(vod?.id || ""), pendingStartSec);
      });
    transcriptState.loadingByPath.set(transcriptPath, fetchTask);
  }

  function ensureTranscriptOffsetReady(vod) {
    const vodId = String(vod?.id || "").trim();
    if (!vodId) {
      return;
    }
    if (!isTranscriptDataAvailable(vod)) {
      transcriptState.offsetByVodId.set(vodId, 0);
      return;
    }
    transcriptState.offsetByVodId.set(vodId, resolveTranscriptOffsetFromVodMetadata(vod));
  }

  function resolveTranscriptOffsetSec(vod) {
    const vodId = String(vod?.id || "").trim();
    if (!vodId) {
      return 0;
    }
    if (!transcriptState.offsetByVodId.has(vodId)) {
      const resolved = resolveTranscriptOffsetFromVodMetadata(vod);
      transcriptState.offsetByVodId.set(vodId, resolved);
      return resolved;
    }
    return normalizeTimestampOffsetSec(transcriptState.offsetByVodId.get(vodId));
  }

  function resolveTranscriptLookupSec(twitchStartSec, offsetSec) {
    if (!Number.isFinite(twitchStartSec) || Number(twitchStartSec) < 0) {
      return twitchStartSec;
    }
    return Math.max(0, Math.floor(Number(twitchStartSec)) - normalizeTimestampOffsetSec(offsetSec));
  }

  function setPendingTranscriptRender(vodId, startSec) {
    const normalizedVodId = String(vodId || "").trim();
    if (!normalizedVodId) {
      transcriptState.pendingRender = null;
      return;
    }
    const normalizedStartSec =
      Number.isFinite(Number(startSec)) && Number(startSec) >= 0 ? Math.floor(Number(startSec)) : null;
    transcriptState.pendingRender = {
      vodId: normalizedVodId,
      startSec: normalizedStartSec,
    };
  }

  function syncPlaybackAssistLayout() {
    if (!elements.playbackAssistPanel || !elements.activityMap || !elements.transcriptPanel) {
      return;
    }
    const transcriptHidden = elements.transcriptPanel.hidden;
    const heatmapHidden = elements.activityMap.hidden;
    elements.playbackAssistPanel.classList.toggle("is-transcript-hidden", transcriptHidden);
    elements.playbackAssistPanel.classList.toggle("is-heatmap-hidden", heatmapHidden);
  }

  async function fetchTranscriptCues(transcriptPath) {
    const normalizedPath = normalizeTranscriptFetchPath(transcriptPath);
    if (!normalizedPath) {
      return [];
    }
    const response = await fetch(normalizedPath, { cache: "no-store" });
    if (!response.ok) {
      return [];
    }
    const raw = await response.text();
    const payload = JSON.parse(String(raw || "").replace(/^\uFEFF/, ""));
    const cues = Array.isArray(payload?.cues) ? payload.cues : [];
    return cues
      .map((cue) => normalizeTranscriptCue(cue))
      .filter(Boolean)
      .sort((left, right) => left.start_sec - right.start_sec);
  }

  function normalizeTranscriptFetchPath(pathValue) {
    const raw = String(pathValue || "").trim();
    if (!raw) {
      return "";
    }
    if (raw.startsWith("/data/transcripts/")) {
      return raw;
    }
    if (raw.startsWith("data/transcripts/")) {
      return `/${raw}`;
    }
    return "";
  }

  function resolveRequestedStartSec() {
    const parsed = Number(state.requestedStartSec);
    if (!Number.isFinite(parsed) || parsed < 0) {
      return 0;
    }
    return Math.floor(parsed);
  }

  function isTranscriptDataAvailable(vod) {
    return isTranscriptDataAvailableForVod(vod);
  }

  function isTranscriptDisplayReady(vod) {
    return isTranscriptDisplayReadyForVod(vod);
  }

  function resolveTranscriptOffsetFromVodMetadata(vod) {
    return resolveTranscriptOffsetSecFromVodMetadata(vod);
  }

  function normalizeTranscriptCue(cue) {
    const startSec = Number(cue?.start_sec);
    const endSec = Number(cue?.end_sec);
    const text = String(cue?.text || "").trim();
    if (!Number.isFinite(startSec) || startSec < 0) {
      return null;
    }
    if (!text) {
      return null;
    }
    const safeStartSec = Math.floor(startSec);
    const safeEndSec = Number.isFinite(endSec) && endSec > safeStartSec ? Math.floor(endSec) : safeStartSec + 1;
    return {
      start_sec: safeStartSec,
      end_sec: safeEndSec,
      text,
    };
  }

  function resolveVodDurationSec(vod) {
    const candidate =
      Number.isFinite(Number(vod?.duration_sec)) && Number(vod.duration_sec) > 0
        ? Number(vod.duration_sec)
        : Number.isFinite(Number(vod?.activity_map?.duration_sec)) && Number(vod.activity_map.duration_sec) > 0
          ? Number(vod.activity_map.duration_sec)
          : null;

    if (candidate) {
      return candidate;
    }

    const maxSegmentEnd = Array.isArray(vod?.segments)
      ? Math.max(...vod.segments.map((segment) => Number(segment?.end_sec || 0)), 0)
      : 0;
    return maxSegmentEnd > 0 ? maxSegmentEnd : null;
  }

  function formatDuration(totalSeconds) {
    if (!Number.isFinite(Number(totalSeconds)) || Number(totalSeconds) <= 0) {
      return UNSET_TEXT;
    }

    const total = Math.floor(Number(totalSeconds));
    const hours = String(Math.floor(total / 3600)).padStart(2, "0");
    const minutes = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
    const seconds = String(total % 60).padStart(2, "0");
    return `${hours}:${minutes}:${seconds}`;
  }

  function formatChatVolume(vod) {
    const chatTotal = parseNonNegativeNumericValue(vod?.chat_total);
    const commentsPerHour = parseNonNegativeNumericValue(vod?.comments_per_hour);
    if (chatTotal == null) {
      return UNSET_TEXT;
    }
    if (commentsPerHour == null) {
      return UNSET_TEXT;
    }

    const chatTotalText = Math.floor(chatTotal).toLocaleString("ja-JP");
    const commentsPerHourText = Math.round(commentsPerHour).toLocaleString("ja-JP");
    return `${chatTotalText}件 / 時間あたり約${commentsPerHourText}件`;
  }

  function parseNonNegativeNumericValue(value) {
    if (value == null) {
      return null;
    }
    if (typeof value === "string" && value.trim() === "") {
      return null;
    }
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed < 0) {
      return null;
    }
    return parsed;
  }

  function resolvePlayerFrameState() {
    if (!elements.playerFrame) {
      return { vodId: "", startSec: null, status: "" };
    }

    const currentVodId = String(elements.playerFrame.dataset.currentVodId || "").trim();
    const currentStartSecRaw = Number(elements.playerFrame.dataset.currentStartSec);
    const currentStartSec =
      Number.isFinite(currentStartSecRaw) && currentStartSecRaw >= 0 ? currentStartSecRaw : null;
    const currentStatus = String(elements.playerFrame.dataset.playerStatus || "").trim();
    return {
      vodId: currentVodId,
      startSec: currentStartSec,
      status: currentStatus,
    };
  }

  function formatPlayingState(vod) {
    const playerFrameState = resolvePlayerFrameState();
    if (String(vod?.id || "") !== playerFrameState.vodId) {
      return UNSET_TEXT;
    }

    switch (playerFrameState.status) {
      case "playing":
        return "再生中";
      case "loading":
        return "読み込み中";
      case "ready":
        return "待機中";
      case "blocked":
        return "再生ブロック";
      case "error":
        return "エラー";
      default:
        return UNSET_TEXT;
    }
  }

  function formatPlaybackPosition(vod) {
    const playerFrameState = resolvePlayerFrameState();
    if (String(vod?.id || "") !== playerFrameState.vodId) {
      return UNSET_TEXT;
    }
    if (!Number.isFinite(playerFrameState.startSec) || Number(playerFrameState.startSec) < 0) {
      return UNSET_TEXT;
    }
    return formatDuration(playerFrameState.startSec);
  }

  function setText(element, value) {
    if (!element) {
      return;
    }
    const text = String(value || "").trim();
    element.textContent = text || UNSET_TEXT;
  }

  function formatVodDateButton(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return "";
    }
    const parts = JAPAN_DATE_BUTTON_FORMATTER.formatToParts(date);
    const month = parts.find((part) => part.type === "month")?.value;
    const day = parts.find((part) => part.type === "day")?.value;
    const weekday = parts.find((part) => part.type === "weekday")?.value;
    if (!month || !day || !weekday) {
      return "";
    }
    return `${Number(month)}月${Number(day)}日(${weekday})`;
  }

  function getSelectedSegment() {
    const vod = state.vods.find((entry) => entry.id === state.selectedVodId);
    if (!vod) {
      return null;
    }

    const segment = vod.segments.find((entry) => entry.id === state.selectedSegmentId);
    if (!segment) {
      return null;
    }

    return { vod, segment };
  }

  return {
    renderSchedule,
    renderVodList,
    renderSegmentTags,
    renderSelection,
    updateActiveButtons,
    getSelectedSegment,
    formatUpdatedScheduleText,
    formatNextScheduleText,
  };
}

function isTranscriptDataAvailableForVod(vod) {
  const transcriptPath = String(vod?.transcript_path || "").trim();
  if (!transcriptPath) {
    return false;
  }
  const status = String(vod?.transcript_status || "").trim().toLowerCase();
  return status === "ok";
}

function resolveTranscriptOffsetSecFromVodMetadata(vod) {
  return normalizeTimestampOffsetSec(
    vod?.transcript_offset_sec ??
      vod?.timestamps_offset_sec ??
      vod?.timestamp_offset_sec ??
      0
  );
}
