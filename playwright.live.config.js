const { defineConfig, devices } = require("@playwright/test");

const liveBaseUrl = process.env.LIVE_BASE_URL || "https://dotitao-moments.onrender.com";

module.exports = defineConfig({
  testDir: "./tests",
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
    trace: "retain-on-failure",
    video: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "mobile-383",
      use: {
        ...devices["Pixel 5"],
        viewport: { width: 383, height: 926 },
      },
    },
    {
      name: "mobile-430",
      use: {
        ...devices["Pixel 5"],
        viewport: { width: 430, height: 932 },
      },
    },
  ],
});
