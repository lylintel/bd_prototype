import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 120000,
  expect: { timeout: 20000 },
  reporter: "list",
  use: { browserName: "chromium", headless: true, viewport: { width: 1440, height: 900 }, screenshot: "only-on-failure" },
});