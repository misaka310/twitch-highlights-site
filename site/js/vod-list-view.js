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

export function createVodListView({ state, elements, renderActivityMap, requestPlayback, renderEmptyState }) {
  const vodTabState = {
    activeVodId: null,
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

  function syncPlaybackAssistLayout() {
    if (!elements.playbackAssistPanel || !elements.activityMap) {
      return;
    }
    const heatmapHidden = elements.activityMap.hidden;
    elements.playbackAssistPanel.hidden = heatmapHidden;
    elements.playbackAssistPanel.classList.toggle("is-heatmap-hidden", heatmapHidden);
  }

  function resolveRequestedStartSec() {
    const parsed = Number(state.requestedStartSec);
    if (!Number.isFinite(parsed) || parsed < 0) {
      return 0;
    }
    return Math.floor(parsed);
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
