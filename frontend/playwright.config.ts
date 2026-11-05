import { defineConfig, devices } from "@playwright/test";

// End-to-end tests against a running Mappe in demo mode (APP_DEMO=1): no API key, no costs.
// Start one with `docker run --rm -e APP_DEMO=1 -p 127.0.0.1:8123:8000 mappe:dev` (see README).
const baseURL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:8123";

export default defineConfig({
  testDir: "e2e",
  globalSetup: "./e2e/global-setup.ts",
  // The tests share one server and its database, so they run one after another.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [
    ["list"],
    ["json", { outputFile: "e2e-results/results.json" }],
    ["html", { outputFolder: "e2e-results/report", open: "never" }],
  ],
  outputDir: "e2e-results/artifacts",
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
