(async () => {
  const [
    configModule,
    domModule,
    dataLoaderModule,
    vodNormalizerModule,
    vodListViewModule,
    activityMapModule,
    playerPortalModule,
    playerControllerModule,
  ] = await Promise.all([
    import("./config.js"),
    import("./dom.js"),
    import("./data-loader.js"),
    import("./vod-normalizer.js"),
    import("./vod-list-view.js"),
    import("./activity-map.js"),
    import("./player-portal.js"),
    import("./player-controller.js"),
  ]);

  const { applyDebugFlags, createInitialState, SCHEDULE_TEXT } = configModule;
  const { elements } = domModule;
  const { loadData } = dataLoaderModule;
  const { normalizeData, getInitialSelection, applyInitialSelectionToState } = vodNormalizerModule;
  const { createVodListView } = vodListViewModule;
  const { createActivityMapController } = activityMapModule;
  const { createPlayerPortal } = playerPortalModule;
  const { createPlayerController } = playerControllerModule;

  createPlayerPortal({
    player: elements.player,
    frame: elements.playerFrame,
  });

  const state = createInitialState();

  let selectedSegmentResolver = () => null;
  const activityMapController = createActivityMapController({
    elements,
    state,
    getSelectedSegment: () => selectedSegmentResolver(),
  });
  const playerController = createPlayerController({
    state,
    elements,
    updateActivityMapProgress: activityMapController.updateActivityMapProgress,
  });
  const vodListView = createVodListView({
    state,
    elements,
    renderActivityMap: activityMapController.renderActivityMap,
    requestPlayback: playerController.requestPlayback,
    renderEmptyState,
  });
  selectedSegmentResolver = () => vodListView.getSelectedSegment();

  const renderSchedule = vodListView.renderSchedule;
  const renderVodList = vodListView.renderVodList;
  const renderSelection = vodListView.renderSelection;
  const formatUpdatedScheduleText = vodListView.formatUpdatedScheduleText;
  const formatNextScheduleText = vodListView.formatNextScheduleText;
  const getSelectedSegment = vodListView.getSelectedSegment;
  const requestPlayback = playerController.requestPlayback;
  const hideUnmuteOverlay = playerController.hideUnmuteOverlay;
  const stopPlayerPolling = playerController.stopPlayerPolling;
  const setPlayerUiState = playerController.setPlayerUiState;
  const getRewindBaseSec = playerController.getRewindBaseSec;

  window.requestPlayback = requestPlayback;

async function bootstrap() {
  applyDebugFlags();
  const data = await loadData();

  if (!data) {
    renderEmptyState("表示データを読み込めませんでした。`data/vods.json` を確認してください。");
    return;
  }

  const vods = normalizeData(data);
  if (vods.length === 0) {
    renderEmptyState("表示できる VOD がありません。");
    return;
  }

  state.vods = vods;
  state.pageOffset = Math.max(0, (Number(data?.__paging?.page || 1) - 1) * 3);
  const initialSelection = getInitialSelection(vods);
  applyInitialSelectionToState(state, initialSelection);

  renderSchedule(data.updated_at, data.next_update_at, data.__source);
  renderVodList();
  renderPager(data.__paging);
  renderSelection({ triggeredByUser: false, autoplay: false });
}

function renderPager(paging) {
  if (!elements.pager) {
    return;
  }

  const page = Number.isFinite(Number(paging?.page)) && Number(paging.page) > 0 ? Number(paging.page) : 1;
  const totalPages =
    Number.isFinite(Number(paging?.total_pages)) && Number(paging.total_pages) > 0 ? Number(paging.total_pages) : 1;

  if (elements.pagerCurrent) {
    elements.pagerCurrent.textContent = `${page} / ${totalPages}`;
  }

  setPagerLinkState(elements.pagerLatest, {
    enabled: page > 1,
    targetPage: 1,
  });
  setPagerLinkState(elements.pagerPrev, {
    enabled: page > 1,
    targetPage: Math.max(1, page - 1),
  });
  setPagerLinkState(elements.pagerNext, {
    enabled: page < totalPages,
    targetPage: Math.min(totalPages, page + 1),
  });
  setPagerLinkState(elements.pagerOldest, {
    enabled: page < totalPages,
    targetPage: totalPages,
  });

  elements.pager.hidden = totalPages <= 1;
}

function setPagerLinkState(element, { enabled, targetPage }) {
  if (!element) {
    return;
  }

  element.href = buildPageHref(targetPage);
  element.classList.toggle("is-disabled", !enabled);
  element.setAttribute("aria-disabled", String(!enabled));
  element.tabIndex = enabled ? 0 : -1;
}

function buildPageHref(page) {
  const url = new URL(window.location.href);
  url.searchParams.set("page", String(page));
  return `${url.pathname}${url.search}${url.hash}`;
}


function renderEmptyState(message) {
  [elements.updatedAt, elements.updatedAtMobile].filter(Boolean).forEach((element) => {
    element.textContent = formatUpdatedScheduleText(SCHEDULE_TEXT.unset);
  });
  [elements.nextUpdateAt, elements.nextUpdateAtMobile].filter(Boolean).forEach((element) => {
    element.textContent = formatNextScheduleText(SCHEDULE_TEXT.unset);
  });
  elements.vodList.replaceChildren();
  if (elements.vodTabs) {
    elements.vodTabs.replaceChildren();
    elements.vodTabs.hidden = true;
  }
  if (elements.transcriptCurrent) {
    elements.transcriptCurrent.textContent = "表示データを確認してください";
  }
  if (elements.transcriptPrev) {
    elements.transcriptPrev.textContent = "―";
  }
  if (elements.transcriptNext) {
    elements.transcriptNext.textContent = "―";
  }
  if (elements.transcriptPanel) {
    elements.transcriptPanel.hidden = true;
  }
  if (elements.playbackAssistPanel) {
    elements.playbackAssistPanel.classList.add("is-transcript-hidden");
  }
  [
    elements.summaryTitle,
    elements.summaryDate,
    elements.summaryDuration,
    elements.summaryChat,
    elements.summaryPlaying,
    elements.summaryPlaybackPosition,
  ]
    .filter(Boolean)
    .forEach((element) => {
      element.textContent = "";
    });
  if (elements.streamSummary) {
    elements.streamSummary.hidden = true;
  }
  hideUnmuteOverlay();
  stopPlayerPolling();
  state.playerReady = false;
  state.desiredPlayback = null;
  state.playbackBlocked = false;
  state.currentPlaybackSec = null;
  if (elements.player) {
    elements.player.replaceChildren();
  }
  if (elements.activityMap) {
    elements.activityMap.hidden = true;
  }
  if (elements.playbackAssistPanel) {
    elements.playbackAssistPanel.classList.add("is-heatmap-hidden");
  }
  setPlayerUiState("idle", "", "", "プレイヤー待機中", "iframe");
  elements.statusMessage.textContent = message;
  elements.statusMessage.hidden = false;
  if (elements.pager) {
    elements.pager.hidden = true;
  }
}


elements.playerUnmute?.addEventListener("click", () => {
  if (!state.requestedVodId || state.requestedStartSec == null) {
    return;
  }

  hideUnmuteOverlay();
  state.playbackBlocked = false;
  requestPlayback(state.requestedVodId, state.requestedStartSec, {
    triggeredByUser: true,
    muted: false,
    statusLabel: "音声 ON で再生中",
  });
});

elements.playerRewind10?.addEventListener("click", () => {
  const selection = getSelectedSegment();
  if (!selection) {
    return;
  }

  const playbackVodId = String(state.requestedVodId || selection.vod.id || "");
  if (!playbackVodId) {
    return;
  }

  const baseSec = getRewindBaseSec(
    Number.isFinite(Number(state.requestedStartSec)) ? Number(state.requestedStartSec) : Number(selection.segment.start_sec) || 0
  );
  const startSec = Math.max(0, Math.floor(baseSec) - 10);

  requestPlayback(playbackVodId, startSec, {
    triggeredByUser: true,
    muted: false,
    statusLabel: "10秒巻き戻し",
  });
});

elements.activityMapButton?.addEventListener("click", (event) => {
  const selection = getSelectedSegment();
  if (!selection) {
    return;
  }

  const { vod } = selection;
  const rect = elements.activityMapButton.getBoundingClientRect();
  if (rect.width <= 0) {
    return;
  }

  const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
  const startSec = Math.floor(ratio * Math.max(0, vod.activity_map.duration_sec));
  requestPlayback(vod.id, startSec, {
    triggeredByUser: true,
    muted: false,
    statusLabel: "指定位置から再生中",
  });
});

[elements.pagerLatest, elements.pagerPrev, elements.pagerNext, elements.pagerOldest].forEach((link) => {
  link?.addEventListener("click", (event) => {
    if (link.getAttribute("aria-disabled") === "true") {
      event.preventDefault();
    }
  });
});

  bootstrap();
})();
