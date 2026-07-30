const { defineConfig, devices } = require("@playwright/test");

const TEST_PORT = 18076;
const TEST_BASE_URL = `http://localhost:${TEST_PORT}`;

module.exports = defineConfig({
  testDir: "./tests",
  testMatch: /.*\.spec\.js$/,
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
    command: "npm start",
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
    {
      name: "mobile",
      testIgnore: /rewind\.spec\.js$/,
      use: {
        ...devices["Pixel 5"],
        viewport: { width: 430, height: 932 },
      },
    },
  ],
});
