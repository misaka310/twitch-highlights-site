import { readFileSync } from "node:fs";
import { join } from "node:path";

function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function asString(value) {
  return String(value || "").trim();
}

function envOrConfig(env, key, value) {
  return asString(env[key]) || asString(value);
}

function optionalHttpUrl(value, label) {
  const raw = asString(value);
  if (!raw) return "";
  let parsed;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error(label + " must be an absolute HTTP(S) URL");
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
    throw new Error(label + " must use HTTP(S)");
  }
  return parsed.toString();
}

export function loadSiteConfig(rootDir, env = process.env) {
  const configPath = join(rootDir, "config", "site.json");
  const source = JSON.parse(readFileSync(configPath, "utf8"));
  const site = asObject(source.site);
  const analytics = asObject(site.analytics);
  const twitch = asObject(source.twitch);

  const channelLogin = envOrConfig(env, "TWITCH_CHANNEL", twitch.channel_login).toLowerCase();
  if (!/^[a-z0-9_]{1,25}$/.test(channelLogin)) {
    throw new Error("TWITCH_CHANNEL or config.twitch.channel_login is invalid");
  }

  return {
    site: {
      name: envOrConfig(env, "SITE_NAME", site.name) || "YouTube Highlights",
      description:
        envOrConfig(env, "SITE_DESCRIPTION", site.description) ||
        "YouTubeライブアーカイブのコメント量から見どころを表示する非公式サイトです。",
      base_url: envOrConfig(env, "SITE_BASE_URL", site.base_url).replace(/\/+$/, ""),
      language: envOrConfig(env, "SITE_LANGUAGE", site.language) || "ja",
      feedback_url: optionalHttpUrl(envOrConfig(env, "SITE_FEEDBACK_URL", site.feedback_url), "SITE_FEEDBACK_URL"),
      analytics: {
        goatcounter_code: envOrConfig(env, "GOATCOUNTER_CODE", analytics.goatcounter_code),
      },
    },
    twitch: {
      channel_login: channelLogin,
      channel_id: envOrConfig(env, "TWITCH_CHANNEL_ID", twitch.channel_id),
    },
  };
}
