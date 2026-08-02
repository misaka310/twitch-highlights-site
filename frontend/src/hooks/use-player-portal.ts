import { useEffect, useRef, type RefObject } from "react";

export function usePlayerPortal(frameRef: RefObject<HTMLDivElement | null>) {
  const hostRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return undefined;

    const host = document.createElement("div");
    host.className = "player-embed player-embed--portal";
    host.setAttribute("aria-label", "Twitch player");
    document.body.append(host);
    hostRef.current = host;
    frame.dataset.playerPortal = "body";

    let animationFrameId: number | null = null;
    const sync = () => {
      animationFrameId = null;
      const rect = frame.getBoundingClientRect();
      Object.assign(host.style, {
        position: "fixed",
        inset: "auto",
        left: `${rect.left + frame.clientLeft}px`,
        top: `${rect.top + frame.clientTop}px`,
        width: `${frame.clientWidth}px`,
        height: `${frame.clientHeight}px`,
        minHeight: "0",
        margin: "0",
        zIndex: "2",
        visibility: rect.width > 0 && rect.height > 0 ? "visible" : "hidden",
      });
    };
    const scheduleSync = () => {
      if (animationFrameId != null) window.cancelAnimationFrame(animationFrameId);
      animationFrameId = window.requestAnimationFrame(sync);
    };

    const resizeObserver = typeof ResizeObserver === "function" ? new ResizeObserver(scheduleSync) : null;
    resizeObserver?.observe(frame);
    window.addEventListener("resize", scheduleSync);
    window.addEventListener("scroll", scheduleSync, { passive: true });
    window.visualViewport?.addEventListener("resize", scheduleSync);
    window.visualViewport?.addEventListener("scroll", scheduleSync);
    scheduleSync();

    return () => {
      if (animationFrameId != null) window.cancelAnimationFrame(animationFrameId);
      resizeObserver?.disconnect();
      window.removeEventListener("resize", scheduleSync);
      window.removeEventListener("scroll", scheduleSync);
      window.visualViewport?.removeEventListener("resize", scheduleSync);
      window.visualViewport?.removeEventListener("scroll", scheduleSync);
      host.remove();
      hostRef.current = null;
    };
  }, [frameRef]);

  return hostRef;
}
