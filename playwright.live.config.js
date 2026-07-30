const { defineConfig, devices } = require("@playwright/test");

const liveBaseUrl = process.env.LIVE_BASE_URL || "https://dotitao-moments.onrender.com";

module.exports = defineConfig({
  testDir: "./live-tests",
  testMatch: /live-mobile-playback\.spec\.js$/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 12 * 60_000,
  expect: {
    timeout: 30_000,
  },
  reporter: [["list"]],
  use: {
    baseURL: liveBaseUrl,
    actionTimeout: 30_000,
    trace: "retain-on-failure",
    video: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "responsive-626",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 626, height: 935 },
        hasTouch: true,
      },
    },
    {
      name: "mobile-383",
      use: {
        ...devices["Pixel 5"],
        viewport: { width: 383, height: 926 },
      },
    },
  ],
});
