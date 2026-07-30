(() => {
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
