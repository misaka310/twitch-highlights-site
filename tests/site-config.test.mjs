import assert from "node:assert/strict";
import test from "node:test";

const { normalizeSiteConfig } = await import("../site/js/site-config.js");

test("normalizeSiteConfig applies generic defaults", () => {
  const config = normalizeSiteConfig({ twitch: { channel_login: "Example_Channel" } });
  assert.equal(config.site.name, "Twitch Highlights");
  assert.equal(config.site.language, "ja");
  assert.equal(config.twitch.channel_login, "example_channel");
});

test("normalizeSiteConfig keeps configured instance values", () => {
  const config = normalizeSiteConfig({
    site: {
      name: "Configured Site",
      description: "Description",
      base_url: "https://example.test/",
      language: "en",
      analytics: { goatcounter_code: "example" },
    },
    twitch: { channel_login: "sample", channel_id: "123" },
  });

  assert.equal(config.site.name, "Configured Site");
  assert.equal(config.site.base_url, "https://example.test");
  assert.equal(config.site.analytics.goatcounter_code, "example");
  assert.equal(config.twitch.channel_id, "123");
  assert.deepEqual(Object.keys(config).sort(), ["site", "twitch"]);
});
