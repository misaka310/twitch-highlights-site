import type { PlaybackRequest } from "./playback-types.js";
import { buildEmbedUrl } from "./twitch-url.js";

export function mountFallbackIframe(options: {
  host: HTMLElement;
  request: PlaybackRequest;
  hostname: string;
  onLoaded: () => void;
}): HTMLIFrameElement {
  const { host, request, hostname, onLoaded } = options;
  const iframe = document.createElement("iframe");
  iframe.className = "player-embed-frame";
  iframe.title = "Twitch";
  iframe.allow = "autoplay; fullscreen";
  iframe.setAttribute("allowfullscreen", "");
  iframe.setAttribute("scrolling", "no");
  iframe.setAttribute("frameborder", "0");
  iframe.src = buildEmbedUrl(request, hostname);
  iframe.addEventListener("load", onLoaded, { once: true });
  host.replaceChildren(iframe);
  return iframe;
}
