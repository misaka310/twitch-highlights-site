(() => {
  const mobileFitStyleId = "mobile-player-fit-styles";
  if (!document.getElementById(mobileFitStyleId)) {
    const style = document.createElement("style");
    style.id = mobileFitStyleId;
    style.textContent = `
      @media (max-width: 640px) {
        .player-surface {
          width: 100% !important;
          min-width: 0 !important;
          margin-inline: 0 !important;
          overflow: visible !important;
        }

        .player-surface__inner {
          width: 100% !important;
          min-width: 0 !important;
        }

        .player-frame {
          left: auto !important;
          width: 100% !important;
          max-width: 400px !important;
          height: auto !important;
          aspect-ratio: 4 / 3 !important;
          margin-inline: auto !important;
          transform: none !important;
          overflow: hidden !important;
        }

        .player-embed,
        .player-embed--mounted,
        .player-embed-slot,
        .player-frame[data-player-mode="interactive"] .player-embed-slot--interactive,
        .player-frame[data-player-mode="interactive"] .player-embed-slot__sdk-wrapper,
        .player-frame[data-player-mode="interactive"] .player-embed-slot__sdk-iframe,
        .player-embed-frame {
          width: 100% !important;
          min-width: 0 !important;
          max-width: 100% !important;
          height: 100% !important;
          min-height: 0 !important;
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
