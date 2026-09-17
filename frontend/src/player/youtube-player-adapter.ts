import type { TwitchPlayerInstance } from "./twitch-player-adapter.js";


export type YoutubeApiPlayer = {
  addEventListener: (eventName: string, callback: (event?: unknown) => void) => void;
  destroy: () => void;
  getCurrentTime: () => number;
  pauseVideo: () => void;
  playVideo: () => void;
  seekTo: (seconds: number, allowSeekAhead: boolean) => void;
  mute: () => void;
  unMute: () => void;
};


export function createYoutubePlayerAdapter(player: YoutubeApiPlayer): TwitchPlayerInstance {
  return {
    addEventListener: (eventName, callback) => player.addEventListener(eventName, () => callback()),
    destroy: () => player.destroy(),
    getCurrentTime: () => player.getCurrentTime(),
    pause: () => player.pauseVideo(),
    play: () => player.playVideo(),
    seek: (seconds) => player.seekTo(Math.max(0, seconds), true),
    setMuted: (muted) => (muted ? player.mute() : player.unMute()),
  };
}
