import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:4174",
    trace: "off",
  },
  webServer: {
    command: "npm run dev",
    url: "http://localhost:4174",
    reuseExistingServer: true,
    timeout: 30_000,
  },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1792, height: 864 } },
    },
    {
      name: "mobile",
      use: { ...devices["Pixel 5"], viewport: { width: 393, height: 873 } },
    },
  ],
});
