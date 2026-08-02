const { defineConfig, devices } = require("@playwright/test");

const TEST_PORT = 18078;
const TEST_BASE_URL = `http://localhost:${TEST_PORT}`;

module.exports = defineConfig({
  testDir: "./tests",
  testMatch: /real-twitch\.spec\.js$/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  reporter: [["list"]],
  use: {
    baseURL: TEST_BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "node scripts/dev-server.mjs",
    url: TEST_BASE_URL,
    reuseExistingServer: true,
    timeout: 30_000,
    env: { PORT: String(TEST_PORT) },
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
