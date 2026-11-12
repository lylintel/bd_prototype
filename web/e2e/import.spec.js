import { test, expect } from "@playwright/test";
import { spawn, execFileSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { t } from "../src/i18n.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const venv = path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const python = process.env.BD_PYTHON || (existsSync(venv) ? venv : "python");
let server;

async function stopServer(value) {
  if (value.child.exitCode === null) {
    if (process.platform === "win32") {
      try { execFileSync("taskkill", ["/pid", String(value.child.pid), "/T", "/F"], { stdio: "ignore" }); } catch { value.child.kill(); }
    } else {
      try { process.kill(-value.child.pid, "SIGTERM"); } catch { value.child.kill(); }
    }
  }
  await value.exited;
  rmSync(value.directory, { recursive: true, force: true });
}

test.beforeEach(async () => {
  const directory = mkdtempSync(path.join(tmpdir(), "bd-import-e2e-"));
  cpSync(path.join(root, "examples"), path.join(directory, "examples"), { recursive: true });
  if (existsSync(path.join(root, "ip_library/builtin"))) cpSync(path.join(root, "ip_library/builtin"), path.join(directory, "ip_library/builtin"), { recursive: true });
  const child = spawn(python, ["-u", "-m", "bdgui", "--workspace", directory, "--port", "0"], {
    cwd: root, stdio: ["ignore", "pipe", "pipe"], detached: process.platform !== "win32",
  });
  const exited = new Promise((resolve) => child.once("close", resolve));
  server = { child, directory, exited, url: "" };
  try {
    server.url = await new Promise((resolve, reject) => {
      let output = "", errors = "";
      const timer = setTimeout(() => reject(new Error(`Server startup timed out: ${errors}`)), 30000);
      child.stdout.on("data", (chunk) => {
        output += chunk.toString();
        const match = output.match(/BD Studio: (http:\/\/127\.0\.0\.1:\d+)/);
        if (match) { clearTimeout(timer); resolve(match[1]); }
      });
      child.stderr.on("data", (chunk) => { errors = (errors + chunk.toString()).slice(-4000); });
      child.once("error", (error) => { clearTimeout(timer); reject(error); });
      child.once("exit", (code) => { clearTimeout(timer); reject(new Error(`Server exited ${code}: ${errors}`)); });
    });
  } catch (error) { await stopServer(server); server = null; throw error; }
});

test.afterEach(async () => { if (server) { await stopServer(server); server = null; } });

async function openEditor(page) {
  await page.route("**/*", (route) => new URL(route.request().url()).hostname === "127.0.0.1" ? route.continue() : route.abort());
  await page.goto(server.url);
  await expect(page.getByRole("heading", { name: "example_bd", level: 1, exact: true })).toBeVisible();
}

test("preview confirm search drag validate and undo use the real backend", async ({ page }, testInfo) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await openEditor(page);
  await page.getByRole("button", { name: t("ip.import"), exact: true }).click();
  const dialog = page.getByRole("dialog", { name: t("ip.importTitle") });
  const directory = path.join(server.directory, "selection");
  mkdirSync(directory);
  cpSync(path.join(root, "tests/fixtures/import/batch.v"), path.join(directory, "batch.v"));
  cpSync(path.join(root, "tests/fixtures/verilog/header.v"), path.join(directory, "header.v"));
  await dialog.getByLabel(t("ip.folder"), { exact: true }).setInputFiles(directory);
  const confirm = dialog.getByRole("button", { name: t("ip.confirmImport", { count: 25 }) });
  await expect(confirm).toBeEnabled();
  expect(existsSync(path.join(server.directory, "ip_library/index.json"))).toBe(false);
  await dialog.getByRole("button", { name: t("ip.inspectModule", { name: "header" }), exact: true }).click();
  await dialog.getByLabel(t("ip.displayName"), { exact: true }).fill("Imported header");
  await dialog.getByLabel(t("ip.tags"), { exact: true }).fill("regression_tag");
  await dialog.getByLabel(t("ip.parameterValue", { name: "WIDTH" }), { exact: true }).fill("12");
  await page.screenshot({ path: testInfo.outputPath("import-desktop.png") });
  await confirm.click();
  await expect(dialog).not.toBeVisible();
  const search = page.getByRole("textbox", { name: "搜索模块", exact: true });
  const row = page.getByTestId("ip-row-header@1.0.0");
  for (const query of ["COUNT", "regression_tag", "header"]) {
    await search.fill(query);
    await expect(row).toBeVisible();
  }
  await expect(row).toContainText(t("ip.origin.imported"));
  await row.dragTo(page.getByLabel("设计画布", { exact: true }), { targetPosition: { x: 300, y: 160 } });
  const node = page.locator('.react-flow__node[data-id="header_0"]');
  await expect(node).toBeVisible();
  await expect(node).toContainText("[11:0]");
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("校验通过");
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  await expect(node).toHaveCount(0);
  await expect(row).toBeVisible();
  expect(readFileSync(path.join(server.directory, "examples/counter_compare.json"))).toEqual(readFileSync(path.join(root, "examples/counter_compare.json")));
  expect(errors).toEqual([]);
});

test("mobile preview errors can be corrected or cancelled without writes", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openEditor(page);
  await page.getByRole("button", { name: "模块面板", exact: true }).click();
  await page.getByRole("button", { name: t("ip.import"), exact: true }).click();
  const dialog = page.getByRole("dialog", { name: t("ip.importTitle") });
  await dialog.getByLabel(t("ip.files"), { exact: true }).setInputFiles(path.join(root, "tests/fixtures/verilog/header.v"));
  const confirm = dialog.getByRole("button", { name: t("ip.confirmImport", { count: 1 }) });
  await expect(confirm).toBeEnabled();
  await dialog.getByLabel(t("ip.directionFor", { name: "count" }), { exact: true }).selectOption("in");
  await confirm.click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  expect(existsSync(path.join(server.directory, "ip_library/index.json"))).toBe(false);
  await dialog.getByLabel(t("ip.directionFor", { name: "count" }), { exact: true }).selectOption("out");
  const bounds = await dialog.boundingBox();
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: testInfo.outputPath("import-mobile.png") });
  await dialog.getByRole("button", { name: t("common.cancel"), exact: true }).click();
  await expect(dialog).not.toBeVisible();
  expect(existsSync(path.join(server.directory, "ip_library/index.json"))).toBe(false);
});

test("a rejected file does not suppress valid files in the same selection", async ({ page }) => {
  await openEditor(page);
  await page.getByRole("button", { name: t("ip.import"), exact: true }).click();
  const dialog = page.getByRole("dialog", { name: t("ip.importTitle") });
  await dialog.getByLabel(t("ip.files"), { exact: true }).setInputFiles([
    { name: "large.v", mimeType: "text/plain", buffer: Buffer.alloc(1024 * 1024 + 1) },
    { name: "header.v", mimeType: "text/plain", buffer: readFileSync(path.join(root, "tests/fixtures/verilog/header.v")) },
  ]);
  const confirm = dialog.getByRole("button", { name: t("ip.confirmImport", { count: 1 }) });
  await expect(confirm).toBeEnabled();
  await expect(dialog.getByRole("alert")).toContainText("large.v");
  await confirm.click();
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: t("common.cancel"), exact: true }).click();
  await expect(page.getByTestId("ip-row-header@1.0.0")).toBeVisible();
});

test("all bundled IPs are available without creating a private index", async ({ page }) => {
  await openEditor(page);
  const manifest = JSON.parse(readFileSync(path.join(root, "ip_library/builtin/manifest.json"), "utf8"));
  await expect(page.locator(".ip-library-item")).toHaveCount(manifest.entries.length);
  for (const entry of manifest.entries) {
    const row = page.getByTestId(`ip-row-${entry.id}@${entry.version}`);
    await expect(row).toContainText(t("ip.origin.builtin"));
    await expect(row.getByRole("button", { name: t("ip.add", { name: entry.id }), exact: true })).toBeEnabled();
  }
  expect(existsSync(path.join(server.directory, "ip_library/index.json"))).toBe(false);
  const response = await page.request.get(`${server.url}/api/load?path=examples/builtin_counter.json`);
  expect(response.ok()).toBe(true);
  expect((await response.json()).inspection.valid).toBe(true);
});

test("instance parameter expressions update widths and preserve versioned undo", async ({ page }, testInfo) => {
  await openEditor(page);
  const counter = page.locator('.react-flow__node[data-id="counter_0"]');
  await counter.dblclick();
  const width = page.getByLabel(t("semantic.parameterLabel", { instance: "counter_0", name: "WIDTH" }), { exact: true });
  await expect(width).toBeEnabled();
  await width.fill("4 * 3");
  await width.press("Tab");
  await expect(counter).toContainText("[11:0]");
  await expect(page.locator(".diagnostic-error")).toContainText("12");
  await page.locator('.react-flow__node[data-id="compare_0"]').dblclick();
  const target = page.getByLabel(t("semantic.parameterLabel", { instance: "compare_0", name: "WIDTH" }), { exact: true });
  await expect(target).toBeEnabled();
  await target.fill("12");
  await target.press("Tab");
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("校验通过");
  await page.screenshot({ path: testInfo.outputPath("parameters-desktop.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  const parameterBounds = await target.boundingBox();
  expect(parameterBounds.x).toBeGreaterThanOrEqual(0);
  expect(parameterBounds.x + parameterBounds.width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: testInfo.outputPath("parameters-mobile.png") });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("tab", { name: "设计 JSON", exact: true }).click();
  const document = JSON.parse(await page.getByLabel(t("semantic.designJson"), { exact: true }).inputValue());
  expect(document.schema_version).toBe(2);
  expect(document.instances[0].ip).toEqual({ id: "counter", version: "1.0.0" });
  expect(document.instances[0].params.WIDTH).toBe("4 * 3");
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("待修复");
  expect(readFileSync(path.join(server.directory, "examples/counter_compare.json"))).toEqual(readFileSync(path.join(root, "examples/counter_compare.json")));
});