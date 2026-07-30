const PLAYER_PORTAL_QUERY = "(min-width: 400px)";

export function createPlayerPortal({ player, frame }) {
  if (!player || !frame) {
    return { sync: () => {}, destroy: () => {} };
  }

  const mediaQuery = window.matchMedia(PLAYER_PORTAL_QUERY);
  let frameObserver = null;
  let animationFrameId = null;

  const scheduleSync = () => {
    if (animationFrameId != null) {
      window.cancelAnimationFrame(animationFrameId);
    }
    animationFrameId = window.requestAnimationFrame(() => {
      animationFrameId = null;
      sync();
    });
  };

  const sync = () => {
    if (!mediaQuery.matches || player.parentElement !== document.body) {
      return;
    }

    const rect = frame.getBoundingClientRect();
    const borderLeft = frame.clientLeft || 0;
    const borderTop = frame.clientTop || 0;
    const contentWidth = frame.clientWidth;
    const contentHeight = frame.clientHeight;

    Object.assign(player.style, {
      position: "fixed",
      inset: "auto",
      left: `${rect.left + borderLeft}px`,
      top: `${rect.top + borderTop}px`,
      width: `${contentWidth}px`,
      height: `${contentHeight}px`,
      minHeight: "0",
      margin: "0",
      zIndex: "2",
    });
  };

  const moveToBody = () => {
    if (player.parentElement !== document.body) {
      document.body.append(player);
    }
    player.classList.add("player-embed--portal");
    frame.dataset.playerPortal = "body";
    scheduleSync();
  };

  const moveToFrame = () => {
    if (player.parentElement !== frame) {
      frame.prepend(player);
    }
    player.classList.remove("player-embed--portal");
    frame.dataset.playerPortal = "frame";
    player.removeAttribute("style");
  };

  const applyMode = () => {
    if (mediaQuery.matches) {
      moveToBody();
    } else {
      moveToFrame();
    }
  };

  if (typeof ResizeObserver === "function") {
    frameObserver = new ResizeObserver(scheduleSync);
    frameObserver.observe(frame);
  }

  mediaQuery.addEventListener?.("change", applyMode);
  window.addEventListener("resize", scheduleSync);
  window.addEventListener("scroll", scheduleSync, { passive: true });
  window.visualViewport?.addEventListener("resize", scheduleSync);
  window.visualViewport?.addEventListener("scroll", scheduleSync);

  applyMode();

  return {
    sync: scheduleSync,
    destroy() {
      if (animationFrameId != null) {
        window.cancelAnimationFrame(animationFrameId);
      }
      frameObserver?.disconnect();
      mediaQuery.removeEventListener?.("change", applyMode);
      window.removeEventListener("resize", scheduleSync);
      window.removeEventListener("scroll", scheduleSync);
      window.visualViewport?.removeEventListener("resize", scheduleSync);
      window.visualViewport?.removeEventListener("scroll", scheduleSync);
      moveToFrame();
    },
  };
}
