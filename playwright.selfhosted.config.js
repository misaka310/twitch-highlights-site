const { defineConfig, devices } = require("@playwright/test");

const TEST_PORT = 18078;

module.exports = defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "line",
  outputDir: "test-results/playwright-selfhosted",
  use: {
    baseURL: `http://127.0.0.1:${TEST_PORT}`,
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    {
      name: "windows-edge",
      use: {
        ...devices["Desktop Chrome"],
        channel: "msedge",
      },
    },
  ],
  webServer: {
    command: `"${process.execPath}" scripts/dev-server.mjs`,
    env: {
      HOST: "127.0.0.1",
      PORT: String(TEST_PORT),
    },
    url: `http://127.0.0.1:${TEST_PORT}`,
    timeout: 120_000,
    reuseExistingServer: false,
  },
});
