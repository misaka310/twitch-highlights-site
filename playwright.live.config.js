const { defineConfig, devices } = require("@playwright/test");

const liveBaseUrl = process.env.LIVE_BASE_URL || "https://dotitao-moments.onrender.com";

module.exports = defineConfig({
  testDir: "./tests",
  testMatch: /live-mobile-playback\.spec\.js$/,
  fullyParallel: false,
  workers: 1,
  retries: 1,
  timeout: 120_000,
  expect: {
    timeout: 30_000,
  },
  reporter: [["list"]],
  use: {
    ...devices["Pixel 5"],
    baseURL: liveBaseUrl,
    viewport: { width: 383, height: 841 },
    trace: "retain-on-failure",
    video: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
