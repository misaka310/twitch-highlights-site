const { defineConfig, devices } = require("@playwright/test");

const TEST_PORT = 18077;
const TEST_BASE_URL = `http://localhost:${TEST_PORT}`;

module.exports = defineConfig({
  testDir: "./tests",
  testMatch: /public-build\.spec\.js$/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  reporter: [["list"]],
  use: {
    baseURL: TEST_BASE_URL,
    trace: "off",
  },
  webServer: {
    command: `python -m http.server ${TEST_PORT} --bind localhost --directory public`,
    url: TEST_BASE_URL,
    reuseExistingServer: true,
    timeout: 30_000,
  },
  projects: [
    {
      name: "desktop",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1792, height: 864 },
      },
    },
    {
      name: "mobile",
      use: {
        ...devices["Pixel 5"],
        viewport: { width: 393, height: 873 },
      },
    },
  ],
});
