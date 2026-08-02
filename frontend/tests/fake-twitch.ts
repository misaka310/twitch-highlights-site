import type { Page } from "@playwright/test";

export async function installFakeTwitch(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const parseTime = (value: unknown): number => {
      const match = String(value || "").match(/(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?/);
      if (!match) return 0;
      return Number(match[1] || 0) * 3600 + Number(match[2] || 0) * 60 + Number(match[3] || 0);
    };

    const log = {
      mounts: [] as Array<Record<string, unknown>>,
      seeks: [] as number[],
      muted: [] as boolean[],
      plays: 0,
      destroys: 0,
    };

    class FakePlayer {
      static READY = "ready";
      static PLAY = "play";
      static PLAYING = "playing";
      static PAUSE = "pause";
      static ENDED = "ended";
      static PLAYBACK_BLOCKED = "playback_blocked";

      private callbacks = new Map<string, Array<() => void>>();
      private currentTime: number;
      private muted: boolean;

      constructor(element: HTMLElement, options: Record<string, unknown>) {
        this.currentTime = parseTime(options.time);
        this.muted = Boolean(options.muted);
        log.mounts.push({ ...options });
        const placeholder = document.createElement("div");
        placeholder.dataset.fakeTwitchPlayer = "true";
        element.append(placeholder);
        window.setTimeout(() => this.emit(FakePlayer.READY), 0);
      }

      addEventListener(eventName: string, callback: () => void): void {
        const callbacks = this.callbacks.get(eventName) || [];
        callbacks.push(callback);
        this.callbacks.set(eventName, callbacks);
      }

      private emit(eventName: string): void {
        (this.callbacks.get(eventName) || []).forEach((callback) => callback());
      }

      seek(seconds: number): void {
        this.currentTime = Number(seconds) || 0;
        log.seeks.push(this.currentTime);
      }

      play(): void {
        log.plays += 1;
        this.emit(FakePlayer.PLAY);
      }

      pause(): void {
        this.emit(FakePlayer.PAUSE);
      }

      setMuted(muted: boolean): void {
        this.muted = Boolean(muted);
        log.muted.push(this.muted);
      }

      getCurrentTime(): number {
        return this.currentTime;
      }

      destroy(): void {
        log.destroys += 1;
      }
    }

    Object.assign(window, {
      Twitch: { Player: FakePlayer },
      __fakeTwitchLog: log,
    });
  });
}

export async function getFakeTwitchLog(page: Page): Promise<{
  mounts: Array<Record<string, unknown>>;
  seeks: number[];
  muted: boolean[];
  plays: number;
  destroys: number;
}> {
  return page.evaluate(() => (window as typeof window & { __fakeTwitchLog: {
    mounts: Array<Record<string, unknown>>;
    seeks: number[];
    muted: boolean[];
    plays: number;
    destroys: number;
  } }).__fakeTwitchLog);
}
