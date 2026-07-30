(() => {
  const TWITCH_MIN_WIDTH = 400;
  const TWITCH_MIN_HEIGHT = 300;
  const TWITCH_PLAYER_SCRIPT_URL = "https://player.twitch.tv/js/embed/v1.js";
  const mobileFitStyleId = "mobile-player-fit-styles";
  const mobileQuery = window.matchMedia("(max-width: 640px)");

  if (!document.getElementById(mobileFitStyleId)) {
    const style = document.createElement("style");
    style.id = mobileFitStyleId;
    style.textContent = `
      @media (max-width: 640px) {
        .player-surface {
          width: 100vw !important;
          max-width: 100vw !important;
          min-width: 0 !important;
          margin-inline: calc(50% - 50vw) !important;
          overflow: visible !important;
        }

        .player-surface__inner {
          width: 100% !important;
          min-width: 0 !important;
        }

        .player-frame {
          --twitch-player-scale: 1;
          left: auto !important;
          width: min(400px, 100vw) !important;
          max-width: none !important;
          height: calc(300px * var(--twitch-player-scale)) !important;
          aspect-ratio: auto !important;
          margin-inline: auto !important;
          border: 0 !important;
          transform: none !important;
          overflow: hidden !important;
        }

        .player-embed,
        .player-embed--mounted {
          position: absolute !important;
          inset: 0 auto auto 0 !important;
          width: 400px !important;
          min-width: 400px !important;
          max-width: none !important;
          height: 300px !important;
          min-height: 300px !important;
          transform: scale(var(--twitch-player-scale)) !important;
          transform-origin: top left !important;
        }

        .player-embed-slot,
        .player-frame[data-player-mode="interactive"] .player-embed-slot--interactive,
        .player-frame[data-player-mode="interactive"] .player-embed-slot__sdk-wrapper,
        .player-frame[data-player-mode="interactive"] .player-embed-slot__sdk-iframe,
        .player-embed-frame {
          width: 100% !important;
          min-width: 400px !important;
          max-width: none !important;
          height: 100% !important;
          min-height: 300px !important;
        }
      }
    `;
    document.head.append(style);
  }

  const frame = document.querySelector("#player-frame");
  const playerHost = document.querySelector("#twitch-player");
  const recoveryButton = document.querySelector("#player-unmute");
  const statusText = document.querySelector("#player-status-text");

  if (!frame || !playerHost || !recoveryButton) {
    return;
  }

  const syncMobilePlayerScale = () => {
    if (!mobileQuery.matches) {
      frame.style.removeProperty("--twitch-player-scale");
      delete frame.dataset.playerLayoutWidth;
      delete frame.dataset.playerLayoutHeight;
      delete frame.dataset.playerVisualScale;
      return;
    }

    const viewportWidth = Math.max(
      1,
      Math.floor(window.visualViewport?.width || document.documentElement.clientWidth || window.innerWidth || 1)
    );
    const scale = Math.min(1, viewportWidth / TWITCH_MIN_WIDTH);
    frame.style.setProperty("--twitch-player-scale", String(scale));
    frame.dataset.playerLayoutWidth = String(TWITCH_MIN_WIDTH);
    frame.dataset.playerLayoutHeight = String(TWITCH_MIN_HEIGHT);
    frame.dataset.playerVisualScale = String(scale);
  };

  syncMobilePlayerScale();
  window.addEventListener("resize", syncMobilePlayerScale, { passive: true });
  window.visualViewport?.addEventListener("resize", syncMobilePlayerScale, { passive: true });

  if (mobileQuery.matches) {
    // The site originally used a direct Twitch iframe on phones. Keep the SDK
    // out of the mobile path so a segment tap can navigate the iframe while the
    // browser's user activation is still valid.
    const nativeHeadAppend = document.head.append.bind(document.head);
    document.head.append = (...nodes) => {
      const acceptedNodes = [];
      nodes.forEach((node) => {
        const isTwitchSdk =
          node instanceof HTMLScriptElement &&
          String(node.src || "").split("?")[0] === TWITCH_PLAYER_SCRIPT_URL;
        if (isTwitchSdk) {
          queueMicrotask(() => node.dispatchEvent(new Event("error")));
          return;
        }
        acceptedNodes.push(node);
      });
      if (acceptedNodes.length > 0) {
        nativeHeadAppend(...acceptedNodes);
      }
    };

    let readyEventDispatched = false;
    const unlockMobilePlaybackControls = () => {
      const controls = document.querySelectorAll(
        ".segment-button, #activity-map-button, #player-rewind-10"
      );
      controls.forEach((control) => {
        control.disabled = false;
        control.setAttribute("aria-disabled", "false");
        control.dataset.playerReady = "true";
        control.title = "";
      });
      if (!readyEventDispatched && document.querySelector(".segment-button")) {
        readyEventDispatched = true;
        window.dispatchEvent(new CustomEvent("twitch-player-ready", { detail: { mode: "iframe" } }));
      }
    };

    const buildLegacyEmbedUrl = (vodId, startSec) => {
      const url = new URL("https://player.twitch.tv/");
      url.searchParams.set("video", String(vodId || "").replace(/^v/i, ""));
      url.searchParams.set("autoplay", "true");
      url.searchParams.set("muted", "false");
      url.searchParams.set("playsinline", "true");
      url.searchParams.set("time", formatTwitchTime(startSec));
      url.searchParams.set("seq", String(Date.now()));
      [location.hostname, "localhost", "127.0.0.1"]
        .filter(Boolean)
        .filter((value, index, values) => values.indexOf(value) === index)
        .forEach((parent) => url.searchParams.append("parent", parent));
      return url.toString();
    };

    const forceLegacySegmentPlayback = (button) => {
      const vodId = String(button?.dataset.vodId || "");
      const startSec = Math.max(0, Number(button?.dataset.startSec) || 0);
      if (!vodId) {
        return;
      }

      let iframe = playerHost.querySelector(".player-embed-frame");
      if (!iframe) {
        iframe = document.createElement("iframe");
        iframe.className = "player-embed-frame";
        iframe.title = "Twitch";
        iframe.allow = "autoplay; fullscreen; picture-in-picture";
        iframe.setAttribute("allowfullscreen", "");
        iframe.setAttribute("scrolling", "no");
        iframe.setAttribute("frameborder", "0");
        iframe.width = "400";
        iframe.height = "300";
        playerHost.replaceChildren(iframe);
      }

      playerHost.classList.add("player-embed--mounted");
      frame.dataset.playerMode = "iframe";
      frame.dataset.playerStatus = "starting";
      frame.dataset.currentVodId = vodId;
      frame.dataset.currentStartSec = String(startSec);
      frame.dataset.expectedAutoplay = "true";
      frame.dataset.expectedMuted = "false";
      frame.dataset.triggeredByUser = "true";
      iframe.addEventListener(
        "load",
        () => {
          frame.dataset.playerMode = "iframe";
          frame.dataset.playerStatus = "ready";
          if (statusText) {
            statusText.textContent = "プレイヤー準備完了";
          }
        },
        { once: true }
      );
      iframe.src = buildLegacyEmbedUrl(vodId, startSec);
    };

    document.addEventListener(
      "click",
      (event) => {
        const button = event.target instanceof Element ? event.target.closest(".segment-button") : null;
        if (!button) {
          return;
        }
        // Run after the site's selection handler, but still inside the same
        // click task so Twitch receives a genuine user-initiated navigation.
        queueMicrotask(() => forceLegacySegmentPlayback(button));
      },
      true
    );

    const mobileObserver = new MutationObserver(() => {
      unlockMobilePlaybackControls();
      const iframe = playerHost.querySelector(".player-embed-frame");
      if (iframe && frame.dataset.playerStatus === "error") {
        frame.dataset.playerMode = "iframe";
        frame.dataset.playerStatus = "ready";
      }
    });
    mobileObserver.observe(document.documentElement, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["data-player-status", "disabled"],
    });
    unlockMobilePlaybackControls();
  }

  const syncRecoveryControl = () => {
    const playbackBlocked = frame.dataset.playerStatus === "blocked";
    recoveryButton.hidden = !playbackBlocked;
    if (playbackBlocked && statusText) {
      statusText.textContent = "自動再生がブロックされました。タップして再生してください。";
    }
  };

  new MutationObserver(syncRecoveryControl).observe(frame, {
    attributes: true,
    attributeFilter: ["data-player-status"],
  });

  recoveryButton.addEventListener("click", () => {
    recoveryButton.hidden = true;
  });

  syncRecoveryControl();

  function formatTwitchTime(totalSeconds) {
    const seconds = Math.max(0, Math.floor(Number(totalSeconds) || 0));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainingSeconds = seconds % 60;
    return `${hours}h${minutes}m${remainingSeconds}s`;
  }
})();