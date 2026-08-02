import { useCallback, useEffect, useRef } from "react";

const POSITION_POLL_INTERVAL_MS = 500;

export function usePositionPolling(syncCurrentTime: () => void) {
  const syncRef = useRef(syncCurrentTime);
  const pollIdRef = useRef<number | null>(null);
  syncRef.current = syncCurrentTime;

  const stopPolling = useCallback(() => {
    if (pollIdRef.current != null) {
      window.clearInterval(pollIdRef.current);
      pollIdRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    stopPolling();
    pollIdRef.current = window.setInterval(() => syncRef.current(), POSITION_POLL_INTERVAL_MS);
  }, [stopPolling]);

  useEffect(() => stopPolling, [stopPolling]);

  return { startPolling, stopPolling };
}
