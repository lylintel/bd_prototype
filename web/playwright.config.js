import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 120000,
  expect: { timeout: 20000 },
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }], ["json", { outputFile: "test-results/report.json" }]],
  use: { browserName: "chromium", headless: true, viewport: { width: 1440, height: 900 }, screenshot: "only-on-failure", trace: "retain-on-failure" },
});