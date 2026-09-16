import type { Page } from "@playwright/test";


export async function installFakeYoutube(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const log = {
      mounts: [] as Array<Record<string, unknown>>,
      seeks: [] as number[],
      muted: [] as boolean[],
      plays: 0,
      destroys: 0,
    };

    class FakeYoutubePlayer {
      private callbacks = new Map<string, Array<(event?: { data?: number }) => void>>();
      private currentTime: number;

      constructor(element: HTMLElement, options: {
        videoId: string;
        playerVars: Record<string, unknown>;
        events: {
          onReady: () => void;
          onStateChange: (event: { data?: number }) => void;
          onError: () => void;
        };
      }) {
        this.currentTime = Number(options.playerVars.start || 0);
        log.mounts.push({ videoId: options.videoId, ...options.playerVars });
        const placeholder = document.createElement("div");
        placeholder.dataset.fakeYoutubePlayer = "true";
        element.append(placeholder);
        this.callbacks.set("onReady", [options.events.onReady]);
        this.callbacks.set("onStateChange", [options.events.onStateChange]);
        window.setTimeout(() => this.emit("onReady"), 0);
      }

      addEventListener(): void {}

      private emit(eventName: string, event: { data?: number } = {}): void {
        (this.callbacks.get(eventName) || []).forEach((callback) => callback(event));
      }

      destroy(): void {
        log.destroys += 1;
      }

      getCurrentTime(): number {
        return this.currentTime;
      }

      pauseVideo(): void {
        this.emit("onStateChange", { data: 2 });
      }

      playVideo(): void {
        log.plays += 1;
        this.emit("onStateChange", { data: 1 });
      }

      seekTo(seconds: number): void {
        this.currentTime = Number(seconds) || 0;
        log.seeks.push(this.currentTime);
      }

      mute(): void {
        log.muted.push(true);
      }

      unMute(): void {
        log.muted.push(false);
      }
    }

    Object.assign(window, {
      YT: { Player: FakeYoutubePlayer },
      __fakeYoutubeLog: log,
    });
  });
}


export async function getFakeYoutubeLog(page: Page): Promise<{
  mounts: Array<Record<string, unknown>>;
  seeks: number[];
  muted: boolean[];
  plays: number;
  destroys: number;
}> {
  return page.evaluate(() => (window as typeof window & { __fakeYoutubeLog: {
    mounts: Array<Record<string, unknown>>;
    seeks: number[];
    muted: boolean[];
    plays: number;
    destroys: number;
  } }).__fakeYoutubeLog);
}
