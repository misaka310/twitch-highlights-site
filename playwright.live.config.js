const { defineConfig, devices } = require("@playwright/test");
const fs = require("fs");
const path = require("path");

const siteConfig = JSON.parse(fs.readFileSync(path.join(__dirname, "config/site.json"), "utf8"));
const LIVE_BASE_URL = process.env.LIVE_BASE_URL || String(siteConfig.site?.base_url || "").trim();
if (!LIVE_BASE_URL) {
  throw new Error("LIVE_BASE_URL or config/site.json site.base_url is required");
}

module.exports = defineConfig({
  testDir: "./tests",
  testMatch: /production-mobile-playback\.spec\.js$/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 12 * 60_000,
  expect: { timeout: 30_000 },
  reporter: [["list"]],
  outputDir: "test-results/production-mobile-playback",
  use: {
    baseURL: LIVE_BASE_URL,
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    {
      name: "mobile-390x844",
      use: {
        ...devices["Pixel 5"],
        viewport: { width: 390, height: 844 },
      },
    },
    {
      name: "mobile-626x935",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 626, height: 935 },
        isMobile: true,
        hasTouch: true,
      },
    },
  ],
});
