import { useEffect } from "react";
import type { RuntimeSiteConfig } from "../domain/vod.js";

export function useSiteMetadata(siteConfig?: RuntimeSiteConfig): void {
  useEffect(() => {
    const site = siteConfig?.site;
    const siteName = String(site?.name || "dotitao moments").trim();
    const description = String(
      site?.description || "Twitch配信の見どころをすぐ再生できる非公式ファンサイトです。",
    ).trim();
    document.title = siteName;
    document.querySelector<HTMLMetaElement>('meta[name="description"]')?.setAttribute("content", description);
    document.querySelector<HTMLMetaElement>('meta[property="og:title"]')?.setAttribute("content", siteName);
    document.querySelector<HTMLMetaElement>('meta[property="og:description"]')?.setAttribute("content", description);

    const analyticsCode = String(site?.analytics?.goatcounter_code || "").trim();
    const isLocal = ["localhost", "127.0.0.1"].includes(location.hostname);
    if (!analyticsCode || isLocal || document.querySelector("script[data-goatcounter]")) return;
    const script = document.createElement("script");
    script.async = true;
    script.dataset.goatcounter = `https://${analyticsCode}.goatcounter.com/count`;
    script.src = "https://gc.zgo.at/count.js";
    document.head.append(script);
  }, [siteConfig]);
}
