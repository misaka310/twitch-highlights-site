const DEFAULT_CONFIG = Object.freeze({
  site: {
    name: "Twitch Highlights",
    description: "Twitch VODのコメント量から見どころを表示する非公式サイトです。",
    base_url: "",
    language: "ja",
    analytics: { goatcounter_code: "" },
  },
  twitch: {
    channel_login: "",
    channel_id: "",
  },
});

function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function asString(value) {
  return String(value || "").trim();
}

export function normalizeSiteConfig(value) {
  const source = asObject(value);
  const site = asObject(source.site);
  const analytics = asObject(site.analytics);
  const twitch = asObject(source.twitch);

  return {
    site: {
      name: asString(site.name) || DEFAULT_CONFIG.site.name,
      description: asString(site.description) || DEFAULT_CONFIG.site.description,
      base_url: asString(site.base_url).replace(/\/+$/, ""),
      language: asString(site.language) || DEFAULT_CONFIG.site.language,
      analytics: {
        goatcounter_code: asString(analytics.goatcounter_code),
      },
    },
    twitch: {
      channel_login: asString(twitch.channel_login).toLowerCase(),
      channel_id: asString(twitch.channel_id),
    },
  };
}

export async function loadSiteConfig() {
  try {
    const response = await fetch("./site-config.json", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return normalizeSiteConfig(await response.json());
  } catch (error) {
    console.warn("site config could not be loaded; using generic defaults", error);
    return normalizeSiteConfig(DEFAULT_CONFIG);
  }
}

export function applySiteConfig(config) {
  const normalized = normalizeSiteConfig(config);
  document.documentElement.lang = normalized.site.language;
  document.title = normalized.site.name;

  const description = document.querySelector('meta[name="description"]');
  if (description) {
    description.setAttribute("content", normalized.site.description);
  }

  const siteName = document.getElementById("site-name");
  if (siteName) {
    siteName.textContent = normalized.site.name;
  }

  const siteDescription = document.getElementById("site-description");
  if (siteDescription) {
    siteDescription.textContent = normalized.site.description;
  }

  const brand = document.querySelector(".brand-header__brand");
  if (brand) {
    brand.setAttribute("aria-label", normalized.site.name);
  }

  installGoatCounter(normalized.site.analytics.goatcounter_code);
  return normalized;
}

function installGoatCounter(code) {
  if (!code || document.querySelector("script[data-goatcounter]")) {
    return;
  }
  const script = document.createElement("script");
  script.async = true;
  script.src = "https://gc.zgo.at/count.js";
  script.dataset.goatcounter = `https://${code}.goatcounter.com/count`;
  document.head.append(script);
}
