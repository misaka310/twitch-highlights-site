(() => {
  const TWITCH_MIN_WIDTH = 400;
  const TWITCH_MIN_HEIGHT = 300;
  const mobileFitStyleId = "mobile-player-fit-styles";

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
  const recoveryButton = document.querySelector("#player-unmute");
  const statusText = document.querySelector("#player-status-text");

  if (!frame || !recoveryButton) {
    return;
  }

  const mobileQuery = window.matchMedia("(max-width: 640px)");
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
})();
