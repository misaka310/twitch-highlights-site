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
  testMatch: /real-youtube\.spec\.js$/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 30_000 },
  reporter: [["list"]],
  use: {
    baseURL: LIVE_BASE_URL,
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    {
      name: "desktop",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 1200 },
      },
    },
  ],
});
