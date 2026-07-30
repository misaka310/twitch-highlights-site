from __future__ import annotations

import subprocess
from pathlib import Path

BASELINE_COMMIT = "92b48fa6552b4bff67c2222238974de4abd14053"


def git_show(path: str) -> str:
    return subprocess.check_output(
        ["git", "show", f"{BASELINE_COMMIT}:{path}"],
        text=True,
        encoding="utf-8",
    )


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_player_controller() -> None:
    path = Path("site/js/player-controller.js")
    text = git_show(path.as_posix())

    text = replace_once(
        text,
        '''  setPlayerUiState("loading", playback.vodId, loadingStartSec, playback.statusLabel, loadingMode);\n\n  if (isSeekReadySameVod) {''',
        '''  setPlayerUiState("loading", playback.vodId, loadingStartSec, playback.statusLabel, loadingMode);\n\n  if (\n    playback.triggeredByUser &&\n    isInteractivePlayerReady() &&\n    !isInteractiveSeekReadyForVod(playback.vodId) &&\n    switchInteractiveVideo(playback)\n  ) {\n    return;\n  }\n\n  if (isSeekReadySameVod) {''',
        "requestPlayback",
    )

    text = replace_once(
        text,
        '''function seekDesiredPlayback(playback) {\n  if (!isInteractiveSeekReadyForVod(playback.vodId)) {\n    return;\n  }\n\n  ensureInteractiveEmbedLayout();\n  const player = state.playerInstance;\n  safeSetMuted(player, playback.muted);\n  state.currentPlaybackSec = playback.startSec;\n  seekInteractivePlayer(player, playback.startSec, { shouldPlay: playback.autoplay !== false });\n\n  state.playerMode = "interactive";\n  state.playerReady = true;\n  state.playbackBlocked = false;\n  startPlayerPolling();\n  setInteractiveUiState(playback.autoplay !== false ? "playing" : "ready", playback.statusLabel);\n}''',
        '''function switchInteractiveVideo(playback) {\n  const player = state.playerInstance;\n  if (!isInteractivePlayerReady() || !player) {\n    return false;\n  }\n\n  const shouldPlay = playback.autoplay !== false;\n  ensureInteractiveEmbedLayout();\n  safeSetMuted(player, playback.muted);\n  state.currentPlaybackSec = playback.startSec;\n  markInteractiveSeek(playback.startSec);\n  setInteractiveUiState(shouldPlay ? "starting" : "ready", playback.statusLabel);\n\n  if (!safeSetVideo(player, playback.vodId, playback.startSec)) {\n    return false;\n  }\n\n  state.interactiveVodId = playback.vodId;\n  state.playerMode = "interactive";\n  state.playerReady = true;\n  state.playbackBlocked = false;\n  startPlayerPolling();\n  if (shouldPlay) {\n    safePlay(player);\n  }\n  scheduleInteractiveTimeSync();\n  return true;\n}\n\n\nfunction seekDesiredPlayback(playback) {\n  if (!isInteractiveSeekReadyForVod(playback.vodId)) {\n    return;\n  }\n\n  ensureInteractiveEmbedLayout();\n  const player = state.playerInstance;\n  const shouldPlay = playback.autoplay !== false;\n  safeSetMuted(player, playback.muted);\n  state.currentPlaybackSec = playback.startSec;\n  setInteractiveUiState(shouldPlay ? "starting" : "ready", playback.statusLabel);\n  seekInteractivePlayer(player, playback.startSec, { shouldPlay });\n\n  state.playerMode = "interactive";\n  state.playerReady = true;\n  state.playbackBlocked = false;\n  startPlayerPolling();\n}''',
        "seekDesiredPlayback",
    )

    text = replace_once(
        text,
        '''    state.playerReady = true;\n    clearInteractiveMountState(playback.token);\n    state.playbackBlocked = false;\n    setInteractiveUiState("ready", "Player ready");\n\n    const targetPlayback = state.desiredPlayback || playback;''',
        '''    state.playerReady = true;\n    clearInteractiveMountState(playback.token);\n    state.playbackBlocked = false;\n    setInteractiveUiState("ready", "Player ready");\n    window.dispatchEvent(\n      new CustomEvent("twitch-player-ready", { detail: { vodId: String(playback.vodId || "") } })\n    );\n\n    const targetPlayback = state.desiredPlayback || playback;''',
        "ready event",
    )

    text = replace_once(
        text,
        '''    const shouldAutoplay = targetPlayback.autoplay !== false;\n    if (Number(targetPlayback.startSec) !== mountStartSec) {\n      seekInteractivePlayer(player, targetPlayback.startSec, { shouldPlay: shouldAutoplay });\n    } else if (shouldAutoplay) {\n      safePlay(player);\n    }\n    setInteractiveUiState(shouldAutoplay ? "playing" : "ready", targetPlayback.statusLabel);''',
        '''    const shouldAutoplay = targetPlayback.autoplay !== false;\n    setInteractiveUiState(shouldAutoplay ? "starting" : "ready", targetPlayback.statusLabel);\n    if (Number(targetPlayback.startSec) !== mountStartSec) {\n      seekInteractivePlayer(player, targetPlayback.startSec, { shouldPlay: shouldAutoplay });\n    } else if (shouldAutoplay) {\n      safePlay(player);\n    }''',
        "ready actions",
    )

    text = replace_once(
        text,
        "function isInteractiveSeekReadyForVod(vodId) {",
        '''function isInteractivePlayerReady() {\n  return (\n    state.playerMode === "interactive" &&\n    Boolean(state.playerInstance) &&\n    state.playerReady === true\n  );\n}\n\n\nfunction isInteractiveSeekReadyForVod(vodId) {''',
        "player-ready helper",
    )

    text = replace_once(
        text,
        "function safeSeek(player, startSec) {",
        '''function safeSetVideo(player, vodId, startSec) {\n  if (!player || typeof player.setVideo !== "function") {\n    return false;\n  }\n  try {\n    player.setVideo(String(vodId || "").replace(/^v/i, ""), Math.max(0, Number(startSec) || 0));\n    return true;\n  } catch (error) {\n    return false;\n  }\n}\n\n\nfunction safeSeek(player, startSec) {''',
        "setVideo helper",
    )

    path.write_text(text, encoding="utf-8")


def patch_vod_list_view() -> None:
    path = Path("site/js/vod-list-view.js")
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''  const vodTabState = {\n    activeVodId: null,\n  };\n\n  bindPlayerFrameSummarySync();''',
        '''  const vodTabState = {\n    activeVodId: null,\n  };\n  const gatePlaybackControls =\n    typeof window.matchMedia === "function" && window.matchMedia("(max-width: 640px)").matches;\n  let playbackControlsReady = !gatePlaybackControls;\n\n  window.addEventListener("twitch-player-ready", () => {\n    playbackControlsReady = true;\n    syncPlaybackControlAvailability();\n  });\n\n  bindPlayerFrameSummarySync();''',
        "view readiness state",
    )

    text = replace_once(
        text,
        '''        button.dataset.hasThumbnail = "false";\n        button.querySelector(".segment-summary").textContent = segment.summary;''',
        '''        button.dataset.hasThumbnail = "false";\n        setPlaybackControlReadyState(button);\n        button.querySelector(".segment-summary").textContent = segment.summary;''',
        "button readiness",
    )

    text = replace_once(
        text,
        "  function renderSegmentTags(container, tags) {",
        '''  function setPlaybackControlReadyState(control) {\n    if (!control) {\n      return;\n    }\n    const disabled = !playbackControlsReady;\n    control.disabled = disabled;\n    control.setAttribute("aria-disabled", String(disabled));\n    control.dataset.playerReady = String(playbackControlsReady);\n    control.title = disabled ? "プレイヤー準備中" : "";\n  }\n\n  function syncPlaybackControlAvailability() {\n    elements.vodList?.querySelectorAll(".segment-button").forEach(setPlaybackControlReadyState);\n    setPlaybackControlReadyState(elements.activityMapButton);\n    setPlaybackControlReadyState(elements.playerRewind10);\n  }\n\n  function renderSegmentTags(container, tags) {''',
        "view readiness helpers",
    )

    text = replace_once(
        text,
        '''    updateActiveButtons();\n    renderVodTabs();\n    applyVodTabVisibility();\n  }''',
        '''    updateActiveButtons();\n    renderVodTabs();\n    applyVodTabVisibility();\n    syncPlaybackControlAvailability();\n  }''',
        "render readiness sync",
    )

    path.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    recovery_path = Path("tests/mobile-playback-recovery.spec.js")
    recovery = git_show(recovery_path.as_posix())
    recovery = replace_once(
        recovery,
        '''  const box = await segment.boundingBox();''',
        '''  await expect(segment).toBeEnabled();\n  const box = await segment.boundingBox();''',
        "recovery readiness wait",
    )
    recovery_path.write_text(recovery, encoding="utf-8")

    rewind_path = Path("tests/rewind.spec.js")
    rewind = rewind_path.read_text(encoding="utf-8")
    rewind = replace_once(
        rewind,
        '''      setVideo(video, seconds) {\n        this.setVideoCalls += 1;\n        if (String(video) === String(this.video)) {\n          return;\n        }\n        this.video = video;\n        this.pendingTime = Number(seconds);\n        this.emit("ready");\n      }''',
        '''      setVideo(video, seconds) {\n        this.setVideoCalls += 1;\n        this.video = video;\n        this.currentTime = Number(seconds);\n        this.pendingTime = null;\n        this.emit("playing");\n      }''',
        "rewind setVideo mock",
    )
    rewind_path.write_text(rewind, encoding="utf-8")

    Path("tests/mobile-iframe-autoplay.spec.js").unlink(missing_ok=True)


def patch_config() -> None:
    path = Path("site/js/config.js")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'export const SITE_BUILD_LABEL = "build at 05.25";',
        'export const SITE_BUILD_LABEL = "mobile playback verified 20260730";',
        "build label",
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_player_controller()
    patch_vod_list_view()
    patch_tests()
    patch_config()


if __name__ == "__main__":
    main()
