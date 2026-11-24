test("hierarchy folds selection edits a child and restores root with undo", async ({ page }, testInfo) => {
  await openEditor(page);
  const badge = page.getByRole("button", { name: "校验设计", exact: true });
  await expect(badge).toContainText("校验通过");
  await page.locator('.react-flow__node[data-id="counter_0"] .block-heading').click();
  await page.locator('.react-flow__node[data-id="compare_0"] .block-heading').click({ modifiers: ["Shift"] });
  await page.getByRole("button", { name: t("hierarchy.collapse"), exact: true }).click();
  const dialog = page.getByRole("dialog", { name: t("hierarchy.collapse") });
  await dialog.getByLabel(t("hierarchy.name"), { exact: true }).fill("counter_group");
  await dialog.getByRole("button", { name: "添加", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(badge).toContainText("校验通过");
  const group = page.locator('.react-flow__node[data-id="counter_group"]');
  await expect(group).toBeVisible();
  await expect(page.locator('.react-flow__node[data-id="counter_0"]')).toHaveCount(0);
  await group.locator(".block-heading").dblclick();
  await expect(page.getByRole("navigation", { name: t("hierarchy.path") })).toBeVisible();
  const aiButtons = page.getByRole("button", { name: t("ai.rootOnly"), exact: true });
  await expect(aiButtons).toHaveCount(2);
  await expect(aiButtons.nth(0)).toBeDisabled();
  await expect(aiButtons.nth(1)).toBeDisabled();
  await expect(page.locator('.react-flow__node[data-id="counter_0"]')).toBeVisible();
  await expect(badge).toContainText("校验通过");
  await page.locator('.react-flow__node[data-id="compare_0"] .block-heading').dblclick();
  const width = page.getByLabel(t("semantic.parameterLabel", { instance: "compare_0", name: "WIDTH" }), { exact: true });
  await width.fill("12");
  await width.press("Tab");
  await expect(badge).toContainText("待修复");
  await page.getByRole("navigation", { name: t("hierarchy.path") }).getByRole("button", { name: "example_bd", exact: true }).click();
  await page.getByRole("button", { name: t("semantic.locate", { code: "E001" }), exact: true }).first().click();
  await expect(page.getByRole("navigation", { name: t("hierarchy.path") })).toBeVisible();
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  await expect(badge).toContainText("校验通过");
  await page.locator('.react-flow__node[data-id="compare_0"] .block-heading').dblclick();
  const threshold = page.getByLabel(t("semantic.parameterLabel", { instance: "compare_0", name: "THRESHOLD" }), { exact: true });
  await threshold.fill("19");
  await threshold.press("Tab");
  await expect(badge).toContainText("校验通过");
  await page.screenshot({ path: testInfo.outputPath("hierarchy-child-desktop.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("navigation", { name: t("hierarchy.path") }).getByRole("button", { name: "example_bd", exact: true }).click();
  await expect(group).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("hierarchy-parent-mobile.png") });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  await expect(group).toHaveCount(0);
  await expect(page.locator('.react-flow__node[data-id="counter_0"]')).toBeVisible();
  await expect(badge).toContainText("校验通过");
  await page.getByRole("button", { name: "重做", exact: true }).click();
  await page.getByRole("button", { name: "重做", exact: true }).click();
  await expect(badge).toContainText("校验通过");
  await page.getByRole("button", { name: "添加 counter_group", exact: true }).click();
  await expect(page.locator('.react-flow__node[data-id="counter_group_0"]')).toBeVisible();
  await expect(badge).toContainText("待修复");
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  await expect(badge).toContainText("校验通过");
  await page.getByRole("button", { name: "保存设计", exact: true }).click();
  const save = page.getByRole("dialog", { name: "保存设计", exact: true });
  await save.getByLabel("保存路径", { exact: true }).fill("designs/hierarchy.json");
  await save.getByRole("button", { name: "保存", exact: true }).click();
  await expect(save).not.toBeVisible();
  const stored = JSON.parse(readFileSync(path.join(server.directory, "designs/hierarchy.json"), "utf8"));
  expect(stored.subdesigns.counter_group.instances.find((item) => item.name === "compare_0").params.THRESHOLD).toBe(19);
  await page.reload();
  await page.getByRole("button", { name: "打开设计", exact: true }).click();
  const open = page.getByRole("dialog", { name: "打开设计", exact: true });
  await open.getByLabel("打开路径", { exact: true }).fill("designs/hierarchy.json");
  await open.getByRole("button", { name: "打开", exact: true }).click();
  await expect(open).not.toBeVisible();
  await expect(group).toBeVisible();
  await expect(badge).toContainText("校验通过");
});
import { test, expect } from "@playwright/test";
import { spawn, execFileSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
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

test.beforeEach(async ({ page }, testInfo) => {
  const directory = mkdtempSync(path.join(tmpdir(), "bd-import-e2e-"));
  cpSync(path.join(root, "examples"), path.join(directory, "examples"), { recursive: true });
  if (existsSync(path.join(root, "ip_library/builtin"))) cpSync(path.join(root, "ip_library/builtin"), path.join(directory, "ip_library/builtin"), { recursive: true });
  const serverModule = testInfo.title.includes("[mock-sdk]") ? "scripts.mock_copilot_server" : "bdgui";
  const hierarchical = testInfo.title.includes("[hierarchy]");
  const dense = testInfo.title.includes("[dense]");
  const stagedLayout = testInfo.title.includes("[layout-apply]");
  const largeOutput = testInfo.title.includes("[large-output]");
  if (hierarchical || dense || stagedLayout || largeOutput) execFileSync(python, ["-m", "scripts.gui_benchmark", "--output", directory, "--instances", stagedLayout || largeOutput ? "2000" : "100", "--groups", hierarchical ? "2" : "0"], { cwd: root, timeout: 60000 });
  const child = spawn(python, ["-u", "-m", serverModule, "--workspace", directory, "--port", "0", ...(hierarchical || dense || stagedLayout || largeOutput ? ["--design", "design.json"] : [])], {
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

test("engineering generation writes versioned readonly output without changing the diagram", async ({ page }) => {
  await openEditor(page);
  await expect(page.getByRole("button", { name: "生成 HDL", exact: true })).toBeEnabled();
  const original = readFileSync(path.join(server.directory, "examples/counter_compare.json"));
  await page.getByRole("button", { name: "生成 HDL", exact: true }).click();
  const editor = page.getByLabel(t("output.verilog"), { exact: true });
  await expect(editor).toContainText("AUTO-GENERATED - DO NOT EDIT");
  await expect(editor).toHaveAttribute("aria-readonly", "true");
  const generated = readFileSync(path.join(server.directory, "build/gui/example_bd.v"), "utf8");
  expect(generated).toContain("schema_version: 2");
  expect(readFileSync(path.join(server.directory, "examples/counter_compare.json"))).toEqual(original);
});

test("AXI-Stream migration requires confirmation and one undo restores the old document", async ({ page }) => {
  await openEditor(page);
  const before = await designJson(page);
  await page.getByRole("button", { name: t("interfaces.enable"), exact: true }).click();
  const confirmation = page.getByRole("dialog", { name: t("interfaces.confirmation"), exact: true });
  await expect(confirmation).toContainText(t("interfaces.migrationImpact", { version: before.schema_version ?? 1 }));
  await confirmation.getByRole("button", { name: t("common.cancel"), exact: true }).click();
  expect(await designJson(page)).toEqual(before);
  await page.getByRole("button", { name: t("interfaces.enable"), exact: true }).click();
  await confirmation.getByRole("button", { name: t("interfaces.confirm"), exact: true }).click();
  await expect(confirmation).not.toBeVisible();
  const migrated = await designJson(page);
  expect(migrated.schema_version).toBe(5);
  expect(migrated.interface_connections).toEqual([]);
  expect(JSON.parse(readFileSync(path.join(server.directory, "examples/counter_compare.json"), "utf8")).schema_version).toBe(before.schema_version);
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  expect(await designJson(page)).toEqual(before);
});

test("AXI-Stream canvas preserves bus facts across view changes materialization and undo", async ({ page }, testInfo) => {
  await openEditor(page);
  await page.getByRole("button", { name: "打开设计", exact: true }).click();
  const open = page.getByRole("dialog", { name: "打开设计", exact: true });
  await open.getByLabel("打开路径", { exact: true }).fill("examples/interfaces/axis_pair.json");
  await open.getByRole("button", { name: "打开", exact: true }).click();
  await expect(page.getByRole("heading", { name: "axis_pair", level: 1, exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("校验通过");
  const coarse = page.locator('.react-flow__edge[data-id="interface:link"]');
  await expect(coarse).toBeVisible();
  const before = await designJson(page);
  await coarse.locator(".react-flow__edge-textwrapper").click();
  await page.getByRole("button", { name: t("interfaces.expandView"), exact: true }).click();
  await expect(page.locator('.react-flow__edge[data-id^="interface:link:"]')).toHaveCount(3);
  await expect(page.getByRole("button", { name: "first.m_data", exact: true }).first()).toHaveAttribute("aria-disabled", "true");
  expect(await designJson(page)).toEqual(before);
  await expect(page.getByRole("button", { name: "撤销", exact: true })).toBeDisabled();
  await page.screenshot({ path: testInfo.outputPath("axis-members-desktop.png") });
  await page.getByRole("button", { name: t("interfaces.materialize"), exact: true }).click();
  const confirmation = page.getByRole("dialog", { name: t("interfaces.confirmation"), exact: true });
  await expect(confirmation).toBeVisible();
  await confirmation.getByRole("button", { name: t("common.cancel"), exact: true }).click();
  expect(await designJson(page)).toEqual(before);
  await page.getByRole("button", { name: t("interfaces.materialize"), exact: true }).click();
  await confirmation.getByRole("button", { name: t("interfaces.confirm"), exact: true }).click();
  await expect(confirmation).not.toBeVisible();
  const materialized = await designJson(page);
  expect(materialized.interface_connections).toEqual([]);
  expect(materialized.nets.length).toBe(before.nets.length + 3);
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  expect(await designJson(page)).toEqual(before);
  await page.getByRole("button", { name: t("interfaces.selectMember", { connection: "link", signal: "TDATA" }), exact: true }).click();
  await page.getByRole("button", { name: t("interfaces.collapseView"), exact: true }).click();
  await expect(coarse).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("axis-canvas-desktop.png") });
  await page.getByRole("button", { name: t("interfaces.disconnect"), exact: true }).click();
  await expect(coarse).toHaveCount(0);
  await page.getByRole("button", { name: t("interfaces.pin", { endpoint: "first.m_axis" }), exact: true }).click();
  await page.getByRole("button", { name: t("interfaces.pin", { endpoint: "second.s_axis" }), exact: true }).click();
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("校验通过");
  const reconnected = await designJson(page);
  expect(reconnected.interface_connections).toHaveLength(1);
  expect(reconnected.nets).toEqual(before.nets);
  await page.getByRole("button", { name: "保存设计", exact: true }).click();
  const save = page.getByRole("dialog", { name: "保存设计", exact: true });
  await save.getByLabel("保存路径", { exact: true }).fill("designs/axis.json");
  await save.getByRole("button", { name: "保存", exact: true }).click();
  await expect(save).not.toBeVisible();
  const stored = JSON.parse(readFileSync(path.join(server.directory, "designs/axis.json"), "utf8"));
  expect(stored.interface_connections).toEqual(reconnected.interface_connections);
  expect(stored.nets).toEqual([...before.nets].sort((left, right) => left.name.localeCompare(right.name)));
  await page.getByRole("button", { name: "打开设计", exact: true }).click();
  await open.getByLabel("打开路径", { exact: true }).fill("designs/axis.json");
  await open.getByRole("button", { name: "打开", exact: true }).click();
  await expect(open).not.toBeVisible();
  await page.locator('.react-flow__edge[data-id="interface:stream_0"] .react-flow__edge-textwrapper').click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { name: "stream_0", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: testInfo.outputPath("axis-canvas-mobile.png") });
});

test("AXI-Stream optional signal fix discloses TLAST and never binds without confirmation", async ({ page }) => {
  await openEditor(page);
  await page.getByRole("button", { name: t("ip.import"), exact: true }).click();
  const importer = page.getByRole("dialog", { name: t("ip.importTitle"), exact: true });
  await importer.getByLabel(t("ip.files"), { exact: true }).setInputFiles({ name: "axis_sink.v", mimeType: "text/plain",
    buffer: Buffer.from("module axis_sink(input [7:0] s_axis_tdata, input s_axis_tvalid, output s_axis_tready, input s_axis_tlast); assign s_axis_tready=s_axis_tvalid & (|s_axis_tdata) & s_axis_tlast; endmodule\n") });
  await importer.getByLabel(t("ip.confirmInterface", { name: "s_axis" }), { exact: true }).check();
  await importer.getByRole("button", { name: t("ip.confirmImport", { count: 1 }), exact: true }).click();
  await expect(importer).not.toBeVisible();
  await page.getByRole("button", { name: "打开设计", exact: true }).click();
  const open = page.getByRole("dialog", { name: "打开设计", exact: true });
  await open.getByLabel("打开路径", { exact: true }).fill("examples/interfaces/axis_pair.json");
  await open.getByRole("button", { name: "打开", exact: true }).click();
  await expect(open).not.toBeVisible();
  const document = await designJson(page);
  document.instances[1] = { name: "second", ip: { id: "axis_sink", version: "1.0.0" }, params: {} };
  for (const name of ["out_data", "out_valid", "out_ready"]) delete document.ports[name];
  document.nets = document.nets.filter((net) => !net.name.startsWith("out_"));
  for (const net of document.nets) net.endpoints = net.endpoints.filter((endpoint) => endpoint.inst !== "second");
  await page.getByLabel(t("semantic.designJson"), { exact: true }).fill(JSON.stringify(document, null, 2));
  await page.getByRole("button", { name: t("semantic.applyJson"), exact: true }).click();
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("待修复");
  const before = await designJson(page);
  await page.getByRole("tab", { name: /^诊断/ }).click();
  await page.getByRole("button", { name: t("semantic.applyFix"), exact: true }).click();
  const confirmation = page.getByRole("dialog", { name: t("interfaces.confirmation"), exact: true });
  await expect(confirmation).toContainText(t("interfaces.lastImpact"));
  await confirmation.getByRole("button", { name: t("common.cancel"), exact: true }).click();
  expect(await designJson(page)).toEqual(before);
  await page.getByRole("tab", { name: /^诊断/ }).click();
  await page.getByRole("button", { name: t("semantic.applyFix"), exact: true }).click();
  await confirmation.getByRole("button", { name: t("interfaces.confirm"), exact: true }).click();
  await expect(confirmation).not.toBeVisible();
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("校验通过");
  const fixed = await designJson(page);
  expect(fixed.interface_connections).toEqual([]);
  expect(fixed.nets.find((net) => net.endpoints.some((endpoint) => endpoint.port === "s_axis_tlast")).endpoints).toEqual([
    { const: "1'b0" }, { inst: "second", port: "s_axis_tlast" },
  ]);
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  expect(await designJson(page)).toEqual(before);
});

test("AXI-Stream import requires explicit mapping confirmation on desktop and mobile", async ({ page }, testInfo) => {
  await openEditor(page);
  const source = "module axis_feed(output [7:0] m_axis_tdata, output m_axis_tvalid, input m_axis_tready); assign m_axis_tdata=8'hA5; assign m_axis_tvalid=1'b1; endmodule\n";
  const upload = { name: "axis_feed.v", mimeType: "text/plain", buffer: Buffer.from(source) };
  const dialog = page.getByRole("dialog", { name: t("ip.importTitle"), exact: true });
  await page.getByRole("button", { name: t("ip.import"), exact: true }).click();
  await dialog.getByLabel(t("ip.files"), { exact: true }).setInputFiles({ ...upload, buffer: Buffer.from(source.replace(", input m_axis_tready", "")) });
  const confirm = dialog.getByLabel(t("ip.confirmInterface", { name: "m_axis" }), { exact: true });
  await expect(confirm).not.toBeChecked();
  await expect(confirm).toBeDisabled();
  await confirm.scrollIntoViewIfNeeded();
  expect(existsSync(path.join(server.directory, "ip_library/axis_feed"))).toBe(false);
  await dialog.getByRole("button", { name: t("common.cancel"), exact: true }).click();
  expect(existsSync(path.join(server.directory, "ip_library/axis_feed"))).toBe(false);
  await page.getByRole("button", { name: t("ip.import"), exact: true }).click();
  await dialog.getByLabel(t("ip.files"), { exact: true }).setInputFiles(upload);
  await confirm.check();
  await dialog.getByLabel(t("ip.interfaceNameFor", { name: "m_axis" }), { exact: true }).fill("stream_out");
  const renamed = dialog.getByLabel(t("ip.confirmInterface", { name: "stream_out" }), { exact: true });
  await expect(renamed).not.toBeChecked();
  await renamed.scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath("axis-import-desktop.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await renamed.scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: testInfo.outputPath("axis-import-mobile.png") });
  await renamed.check();
  await dialog.getByRole("button", { name: t("ip.confirmImport", { count: 1 }), exact: true }).click();
  await expect(dialog).not.toBeVisible();
  const stored = JSON.parse(readFileSync(path.join(server.directory, "ip_library/axis_feed/1.0.0/ip.json"), "utf8"));
  expect(stored.schema_version).toBe(2);
  expect(stored.interfaces).toHaveLength(1);
  expect(stored.interfaces[0].name).toBe("stream_out");
  expect(stored.interfaces[0].confirmed).toBe(true);
  expect(stored.interfaces[0].signals).toEqual({ tdata: "m_axis_tdata", tvalid: "m_axis_tvalid", tready: "m_axis_tready" });
  expect(readFileSync(path.join(server.directory, "ip_library/axis_feed/1.0.0/src/axis_feed.v"), "utf8")).toBe(source);
  await page.getByRole("button", { name: "模块面板", exact: true }).click();
  await page.getByRole("button", { name: t("ip.import"), exact: true }).click();
  await dialog.getByLabel(t("ip.files"), { exact: true }).setInputFiles({ name: "odd_feed.v", mimeType: "text/plain",
    buffer: Buffer.from("module odd_feed(output [7:0] payload, output strobe, input accept); assign payload=8'hA5; assign strobe=1'b1; endmodule\n") });
  await expect(dialog.getByRole("button", { name: t("ip.confirmImport", { count: 1 }), exact: true })).toBeEnabled();
  await dialog.getByRole("button", { name: t("ip.addInterface"), exact: true }).click();
  for (const [signal, port] of [["tdata", "payload"], ["tvalid", "strobe"], ["tready", "accept"]]) {
    await dialog.getByLabel(t("ip.interfaceSignal", { name: "axis_0", signal }), { exact: true }).selectOption(port);
  }
  await dialog.getByLabel(t("ip.confirmInterface", { name: "axis_0" }), { exact: true }).check();
  await dialog.getByRole("button", { name: t("ip.confirmImport", { count: 1 }), exact: true }).click();
  await expect(dialog).not.toBeVisible();
  const manual = JSON.parse(readFileSync(path.join(server.directory, "ip_library/odd_feed/1.0.0/ip.json"), "utf8"));
  expect(manual.interfaces[0].signals).toEqual({ tdata: "payload", tvalid: "strobe", tready: "accept" });
});

test("SystemVerilog import wiring generation and checks use explicit language", async ({ page }, testInfo) => {
  await openEditor(page);
  await page.getByRole("button", { name: t("ip.import"), exact: true }).click();
  const dialog = page.getByRole("dialog", { name: t("ip.importTitle"), exact: true });
  await dialog.getByLabel(t("ip.files"), { exact: true }).setInputFiles(path.join(root, "examples/sv/rtl/sv_register.sv"));
  await dialog.getByRole("button", { name: t("ip.confirmImport", { count: 1 }), exact: true }).click();
  await expect(dialog).not.toBeVisible();
  const document = JSON.parse(readFileSync(path.join(root, "examples/sv/register.json"), "utf8"));
  delete document.project_ips;
  await page.getByRole("tab", { name: "设计 JSON", exact: true }).click();
  await page.getByLabel(t("semantic.designJson"), { exact: true }).fill(JSON.stringify(document, null, 2));
  await page.getByRole("button", { name: t("semantic.applyJson"), exact: true }).click();
  await expect(page.getByRole("heading", { name: "sv_demo", level: 1, exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("校验通过");
  await page.getByLabel(t("hdl.language"), { exact: true }).selectOption("sv");
  await page.getByRole("button", { name: "生成 HDL", exact: true }).click();
  const editor = page.getByLabel(t("output.systemVerilog"), { exact: true });
  await expect(editor).toContainText("input logic");
  const generated = readFileSync(path.join(server.directory, "build/gui/sv_demo.sv"), "utf8");
  expect(generated).not.toContain(".*");
  expect(existsSync(path.join(server.directory, "build/gui/sv_demo.source-map.json"))).toBe(true);
  await page.getByRole("button", { name: t("hdl.check"), exact: true }).click();
  await expect(page.getByRole("region", { name: t("hdl.results"), exact: true })).toContainText(t("hdl.passed"));
  await expect(page.getByRole("region", { name: t("hdl.results"), exact: true })).toContainText(`verilator ${t("hdl.stage.lint")}`);
  await expect(page.getByRole("region", { name: t("hdl.results"), exact: true })).toContainText(`yosys ${t("hdl.stage.synthesis")}`);
  await expect(page.getByRole("region", { name: t("hdl.results"), exact: true })).toContainText(t("hdl.cells", { count: 8 }));
  await page.getByRole("tab", { name: "BD Verilog", exact: true }).click();
  await page.screenshot({ path: testInfo.outputPath("sv-generation-desktop.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByLabel(t("hdl.language"), { exact: true }).scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: testInfo.outputPath("sv-generation-mobile.png") });
});

test("HDL check maps a real generated warning to its canvas instance", async ({ page }, testInfo) => {
  await openEditor(page);
  await page.locator('.react-flow__node[data-id="compare_0"]').dblclick();
  const threshold = page.getByLabel(t("semantic.parameterLabel", { instance: "compare_0", name: "THRESHOLD" }), { exact: true });
  await threshold.fill("19"); await threshold.press("Tab");
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("校验通过");
  const document = await designJson(page);
  document.schema_version = 3;
  document.nets.find((net) => net.name === "count_bus").endpoints = [{ const: "8'd9" }, { inst: "compare_0", port: "value" }];
  await page.getByLabel(t("semantic.designJson"), { exact: true }).fill(JSON.stringify(document, null, 2));
  let release, entered;
  const held = new Promise((resolve) => { release = resolve; });
  const started = new Promise((resolve) => { entered = resolve; });
  await page.route("**/api/semantic/inspect", async (route) => {
    if (route.request().postDataJSON().design.schema_version === 3) { entered(); await held; }
    await route.continue();
  });
  try {
    await page.getByRole("button", { name: t("semantic.applyJson"), exact: true }).click();
    await started;
    await expect(page.getByRole("button", { name: t("hdl.check"), exact: true })).toBeDisabled();
  } finally { release(); }
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("校验通过");
  await page.getByRole("button", { name: t("hdl.check"), exact: true }).click();
  const result = page.getByRole("region", { name: t("hdl.results"), exact: true });
  await expect(result).toContainText(t("hdl.passed"));
  const warning = result.locator('[data-code="HDL_TOOL_WARNING"][data-instance="counter_0"]');
  await expect(warning.first()).toContainText("example_bd.v:");
  await warning.first().getByRole("button").click();
  await expect(page.getByLabel("实例名称", { exact: true })).toHaveValue("counter_0");
  await page.screenshot({ path: testInfo.outputPath("hdl-warning-desktop.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "属性面板", exact: true }).click();
  await page.getByRole("button", { name: t("hdl.check"), exact: true }).scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: testInfo.outputPath("hdl-warning-mobile.png") });
  expect(existsSync(path.join(server.directory, "build/gui"))).toBe(false);
});

test("HDL check does not publish results over a newer design", async ({ page }) => {
  await openEditor(page);
  let release;
  const held = new Promise((resolve) => { release = resolve; });
  await page.route("**/api/check-hdl", async (route) => {
    const response = await route.fetch();
    await held;
    await route.fulfill({ response });
  });
  try {
    await page.getByRole("button", { name: t("hdl.check"), exact: true }).click();
    await expect(page.getByRole("button", { name: t("hdl.running"), exact: true })).toBeVisible();
    await page.locator('.react-flow__node[data-id="compare_0"]').dblclick();
    const threshold = page.getByLabel(t("semantic.parameterLabel", { instance: "compare_0", name: "THRESHOLD" }), { exact: true });
    await threshold.fill("19"); await threshold.press("Tab");
    release();
    await expect(page.getByText(t("hdl.stale"), { exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: t("hdl.results"), exact: true })).toHaveCount(0);
  } finally { release(); }
});

test("legacy single-file projects migrate and a node move only changes layout", async ({ page }) => {
  const legacy = { schema_version: 1, design: JSON.parse(readFileSync(path.join(server.directory, "examples/counter_compare.json"), "utf8")),
    layout: { nodes: { counter_0: { x: 240, y: 140 }, compare_0: { x: 590, y: 140 } }, viewport: { x: 0, y: 0, zoom: 0.75 } } };
  const originalPath = path.join(server.directory, "examples/combined.json");
  writeFileSync(originalPath, JSON.stringify(legacy));
  const original = readFileSync(originalPath);
  await openEditor(page);
  await page.getByRole("button", { name: "打开设计", exact: true }).click();
  const open = page.getByRole("dialog", { name: "打开设计", exact: true });
  await open.getByLabel("打开路径", { exact: true }).fill("examples/combined.json");
  await open.getByRole("button", { name: "打开", exact: true }).click();
  await expect(open).not.toBeVisible();
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("校验通过");
  expect((await designJson(page)).schema_version).toBe(4);
  await page.getByRole("button", { name: "保存设计", exact: true }).click();
  const save = page.getByRole("dialog", { name: "保存设计", exact: true });
  await save.getByLabel("保存路径", { exact: true }).fill("designs/migrated.json");
  await save.getByRole("button", { name: "保存", exact: true }).click();
  await expect(save).not.toBeVisible();
  const logicPath = path.join(server.directory, "designs/migrated.json");
  const layoutPath = path.join(server.directory, "designs/migrated.layout.json");
  const logic = readFileSync(logicPath);
  const layout = readFileSync(layoutPath);
  const header = page.locator('.react-flow__node[data-id="counter_0"] .block-heading');
  const bounds = await header.boundingBox();
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width / 2 + 60, bounds.y + bounds.height / 2 + 30, { steps: 4 });
  await page.mouse.up();
  await page.getByRole("button", { name: "保存设计", exact: true }).click();
  await save.getByRole("button", { name: "保存", exact: true }).click();
  await expect(save).not.toBeVisible();
  expect(readFileSync(logicPath)).toEqual(logic);
  expect(readFileSync(layoutPath)).not.toEqual(layout);
  expect(readFileSync(originalPath)).toEqual(original);
});

test("[large-output] virtual editor loads lazily and preserves complete code", async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    const stringify = JSON.stringify;
    window.__documentSerializations = 0;
    JSON.stringify = (value, replacer, space) => {
      if (space === 2 && Array.isArray(value?.instances) && value.instances.length === 2000) window.__documentSerializations++;
      return stringify(value, replacer, space);
    };
  });
  const requests = [];
  page.on("request", (request) => requests.push(request.url()));
  await page.route("**/*", (route) => new URL(route.request().url()).hostname === "127.0.0.1" ? route.continue() : route.abort());
  const response = page.waitForResponse((item) => item.url().endsWith("/api/state"));
  await page.goto(server.url);
  const state = await (await response).json();
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("校验通过");
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  expect(await page.evaluate(() => window.__documentSerializations)).toBe(0);
  expect(requests.some((url) => /\/Editor-[^/]+\.js$/.test(url))).toBe(false);
  const text = state.inspection.files[`${state.design.name}.v`];
  const lines = text.split("\n").length;
  expect(lines).toBeGreaterThanOrEqual(20000);
  await page.getByRole("tab", { name: "BD Verilog", exact: true }).click();
  const editor = page.getByLabel(t("output.verilog"), { exact: true });
  await expect(editor).toBeVisible();
  await expect(page.locator(".cm-editor")).toHaveAttribute("data-line-count", String(lines));
  await expect(page.locator(".cm-editor")).toHaveAttribute("data-large-document", "true");
  expect(await page.locator(".cm-line").count()).toBeLessThan(200);
  await expect(page.locator(".cm-foldGutter")).toHaveCount(0);
  await editor.press("Control+End");
  await expect(page.locator(".cm-line").filter({ hasText: /^endmodule$/ }).last()).toBeVisible();
  const scroll = await page.locator(".cm-scroller").evaluate((element) => element.scrollTop);
  await page.getByRole("tab", { name: "Wrapper", exact: true }).click();
  await expect(page.locator(".cm-editor")).toHaveAttribute("data-line-count", String(state.inspection.files[`${state.design.name}_wrapper.v`].split("\n").length));
  await page.getByRole("tab", { name: "BD Verilog", exact: true }).click();
  await expect.poll(() => page.locator(".cm-scroller").evaluate((element) => element.scrollTop)).toBeGreaterThan(scroll - 500);
  expect(await readClipboardText(page, "复制代码")).toBe(text);
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载 Verilog", exact: true }).click();
  expect(readFileSync(await (await download).path(), "utf8")).toBe(text);
  await page.getByRole("button", { name: "放大代码字号", exact: true }).click();
  await expect.poll(() => page.locator(".cm-line").first().evaluate((element) => getComputedStyle(element).fontSize)).toBe("13px");
  await page.screenshot({ path: testInfo.outputPath("large-code-desktop.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(editor).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: testInfo.outputPath("large-code-mobile.png") });
});

test("JSON editor undo does not undo the authoritative canvas", async ({ page }) => {
  await openEditor(page);
  await page.locator('.react-flow__node[data-id="compare_0"] .block-heading').dblclick();
  const threshold = page.getByLabel(t("semantic.parameterLabel", { instance: "compare_0", name: "THRESHOLD" }), { exact: true });
  await threshold.fill("19");
  await threshold.press("Tab");
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("校验通过");
  const before = await designJson(page);
  const editor = page.getByLabel(t("semantic.designJson"), { exact: true });
  await editor.fill(JSON.stringify({ ...before, name: "draft_only" }, null, 2));
  await expect(page.getByRole("heading", { name: "example_bd", level: 1, exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "BD Verilog", exact: true }).click();
  expect((await designJson(page)).name).toBe("draft_only");
  await editor.press("Control+z");
  expect(await designJson(page)).toEqual(before);
  await expect(page.getByRole("button", { name: "撤销", exact: true })).toBeEnabled();
});

test("ELK worker layout changes only coordinates and is undoable", async ({ page }) => {
  await openEditor(page);
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("校验通过");
  const counter = page.locator('.react-flow__node[data-id="counter_0"]');
  const beforePosition = await counter.getAttribute("style");
  await page.getByRole("tab", { name: "设计 JSON", exact: true }).click();
  const beforeDocument = await readJsonText(page);
  let inspections = 0, workers = 0;
  page.on("request", (request) => { if (request.url().endsWith("/api/semantic/inspect")) inspections++; });
  page.on("worker", () => workers++);
  await page.getByRole("button", { name: "整理布局", exact: true }).click();
  await expect(page.getByRole("button", { name: t("layout.running"), exact: true })).toBeVisible();
  await expect(page.getByLabel("设计画布", { exact: true })).toHaveAttribute("data-layout-state", "idle");
  await expect.poll(() => counter.getAttribute("style")).not.toBe(beforePosition);
  expect(await readJsonText(page)).toBe(beforeDocument);
  expect(inspections).toBe(0);
  expect(workers).toBe(1);
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  await expect(counter).toHaveAttribute("style", beforePosition);
});

test("ELK worker cancellation and stale results preserve user edits", async ({ page }) => {
  await openEditor(page);
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("校验通过");
  const counter = page.locator('.react-flow__node[data-id="counter_0"]');
  const originalPosition = await counter.getAttribute("style");
  let release;
  let gate = new Promise((resolve) => { release = resolve; });
  await page.route("**/assets/worker-*.js", async (route) => { await gate; try { await route.continue(); } catch { return; } });
  await page.getByRole("button", { name: "整理布局", exact: true }).click();
  await page.getByRole("button", { name: t("layout.cancel"), exact: true }).click();
  release();
  await expect(page.getByText(t("layout.cancelled"), { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "撤销", exact: true })).toBeDisabled();
  gate = new Promise((resolve) => { release = resolve; });
  await page.getByRole("button", { name: "整理布局", exact: true }).click();
  await page.locator('.react-flow__node[data-id="compare_0"] .block-heading').dblclick();
  const threshold = page.getByLabel(t("semantic.parameterLabel", { instance: "compare_0", name: "THRESHOLD" }), { exact: true });
  await threshold.fill("19");
  await threshold.press("Tab");
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("校验通过");
  release();
  await expect(page.getByText(t("layout.stale"), { exact: true })).toBeVisible();
  await expect(threshold).toHaveValue("19");
  await expect(counter).toHaveAttribute("style", originalPosition);
});

test("[layout-apply] cancelling staged coordinates restores the original layout", async ({ page }) => {
  await page.route("**/*", (route) => new URL(route.request().url()).hostname === "127.0.0.1" ? route.continue() : route.abort());
  await page.goto(server.url);
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("校验通过");
  const node = page.locator('.react-flow__node[data-id="unit_0"]');
  const original = await node.getAttribute("style");
  await page.getByRole("button", { name: "整理布局", exact: true }).click();
  await expect(page.getByLabel("设计画布", { exact: true })).toHaveAttribute("data-layout-stage", "applying");
  await expect.poll(() => node.getAttribute("style")).not.toBe(original);
  await page.getByRole("button", { name: t("layout.cancel"), exact: true }).click();
  await expect(page.getByText(t("layout.cancelled"), { exact: true })).toBeVisible();
  await expect(node).toHaveAttribute("style", original);
  await expect(page.getByRole("button", { name: "撤销", exact: true })).toBeDisabled();
});

test("[dense] net labels preserve selection and vector thickness", async ({ page }, testInfo) => {
  await page.route("**/*", (route) => new URL(route.request().url()).hostname === "127.0.0.1" ? route.continue() : route.abort());
  await page.goto(server.url);
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("校验通过");
  const edge = page.locator('.react-flow__edge[data-id^="net_"]').filter({ has: page.locator('[data-routing="labels"] .react-flow__edge-textwrapper') }).first();
  const identifier = await edge.getAttribute("data-id");
  expect(Number.parseFloat(await edge.locator(".react-flow__edge-path").first().evaluate((element) => getComputedStyle(element).strokeWidth))).toBeGreaterThan(1);
  await edge.locator(".react-flow__edge-textwrapper").first().click();
  await expect(page.getByLabel("网络名称", { exact: true })).toHaveValue(identifier.split("|")[0]);
  await expect(page.locator('.react-flow__edge.selected [data-routing="dense"]')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("dense-net-labels.png") });
});

test("[hierarchy] compact ports expand and bundled nets remain individually selectable", async ({ page }, testInfo) => {
  await page.route("**/*", (route) => new URL(route.request().url()).hostname === "127.0.0.1" ? route.continue() : route.abort());
  await page.goto(server.url);
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("校验通过");
  const group = page.locator('.react-flow__node[data-id="group_0"]');
  await expect(group.locator(".compact-pins")).toBeVisible();
  await group.getByRole("button", { name: t("hierarchy.expandPorts", { name: "group_0" }), exact: true }).click();
  await expect(group.locator(".node-pin").first()).toBeVisible();
  await group.getByRole("button", { name: t("hierarchy.collapsePorts", { name: "group_0" }), exact: true }).click();
  await expect(group.locator(".compact-pins")).toBeVisible();
  await page.getByRole("button", { name: "适应画布", exact: true }).click();
  const bundle = page.locator('.react-flow__edge[data-id="bundle:group_0:group_1"]');
  await bundle.locator(".react-flow__edge-textwrapper").click();
  const dialog = page.getByRole("dialog", { name: t("hierarchy.networks"), exact: true });
  await expect(dialog).toBeVisible();
  const target = dialog.locator(".hierarchy-net-list button").first();
  const selected = (await target.innerText()).trim().split(/\s/)[0];
  await target.click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByLabel("网络名称", { exact: true })).toHaveValue(selected);
  await page.screenshot({ path: testInfo.outputPath("hierarchy-bundle-desktop.png") });
});

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
  const document = JSON.parse(await readJsonText(page));
  expect(document.schema_version).toBe(2);
  expect(document.instances[0].ip).toEqual({ id: "counter", version: "1.0.0" });
  expect(document.instances[0].params.WIDTH).toBe("4 * 3");
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("待修复");
  expect(readFileSync(path.join(server.directory, "examples/counter_compare.json"))).toEqual(readFileSync(path.join(root, "examples/counter_compare.json")));
});

test("diagnostic location selects the target and an explicit fix is undoable", async ({ page }, testInfo) => {
  await openEditor(page);
  await page.locator('.react-flow__node[data-id="counter_0"]').dblclick();
  const width = page.getByLabel(t("semantic.parameterLabel", { instance: "counter_0", name: "WIDTH" }), { exact: true });
  await expect(width).toBeEnabled();
  await width.fill("12");
  await width.press("Tab");
  const diagnostic = page.locator('.semantic-diagnostic[data-code="E001"][data-net="count_bus"]');
  await expect(diagnostic).toBeVisible();
  await diagnostic.getByRole("button", { name: t("semantic.locate", { code: "E001" }), exact: true }).click();
  await expect(page.locator('.react-flow__node[data-id="compare_0"]')).toHaveClass(/selected/);
  await page.screenshot({ path: testInfo.outputPath("diagnostic-location.png") });
  await diagnostic.getByRole("button", { name: t("semantic.applyFix"), exact: true }).click();
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("校验通过");
  await expect(page.getByLabel(t("semantic.parameterLabel", { instance: "compare_0", name: "WIDTH" }), { exact: true })).toHaveValue("12");
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  await expect(diagnostic).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "属性面板", exact: true }).click();
  await expect(diagnostic.getByRole("button", { name: t("semantic.applyFix"), exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("diagnostic-mobile.png") });
});

test("net diagnostics select visible invalid connections", async ({ page }, testInfo) => {
  await openEditor(page);
  await page.getByRole("tab", { name: "设计 JSON", exact: true }).click();
  const editor = page.getByLabel(t("semantic.designJson"), { exact: true });
  const document = JSON.parse(await readJsonText(page));
  document.nets.count_bus.push("compare_0.match");
  await editor.fill(JSON.stringify(document));
  await page.getByRole("button", { name: t("semantic.applyJson"), exact: true }).click();
  await page.getByRole("tab", { name: /^诊断/ }).click();
  const diagnostic = page.locator('.semantic-diagnostic[data-code="E002"][data-net="count_bus"]').first();
  await diagnostic.getByRole("button", { name: t("semantic.locate", { code: "E002" }), exact: true }).click();
  await expect(page.locator('.react-flow__edge.selected[data-id^="count_bus|"]').first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("diagnostic-net.png") });
});

async function selectCountBus(page) {
  await page.locator('.react-flow__edge[data-id^="count_bus|"] .react-flow__edge-textwrapper').first().click();
}

async function readJsonText(page) {
  await expect(page.getByLabel(t("semantic.designJson"), { exact: true })).toBeVisible();
  return readClipboardText(page, t("output.copyJson"));
}

async function readClipboardText(page, label) {
  await page.evaluate(() => {
    window.__bdCopiedText = null;
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async (text) => { window.__bdCopiedText = text; } } });
  });
  await page.getByRole("button", { name: label, exact: true }).click();
  return page.evaluate(() => window.__bdCopiedText);
}

async function designJson(page) {
  await page.getByRole("tab", { name: "设计 JSON", exact: true }).click();
  return JSON.parse(await readJsonText(page));
}

test("slice settings match the receiving width and remain undoable", async ({ page }, testInfo) => {
  await openEditor(page);
  await page.locator('.react-flow__node[data-id="compare_0"]').dblclick();
  const width = page.getByLabel(t("semantic.parameterLabel", { instance: "compare_0", name: "WIDTH" }), { exact: true });
  await expect(width).toBeEnabled();
  await width.fill("4");
  await width.press("Tab");
  await expect(page.locator('.semantic-diagnostic[data-code="E001"]')).toBeVisible();
  await selectCountBus(page);
  await page.getByRole("button", { name: t("semantic.editEndpoint", { index: 1 }), exact: true }).click();
  const dialog = page.getByRole("dialog", { name: t("semantic.connectionTitle", { name: "count_bus" }), exact: true });
  await dialog.getByLabel(t("semantic.useSlice", { path: "1" }), { exact: true }).check();
  await dialog.getByLabel(t("semantic.leftIndex", { path: "1" }), { exact: true }).fill("3");
  await dialog.getByLabel(t("semantic.rightIndex", { path: "1" }), { exact: true }).fill("0");
  await page.screenshot({ path: testInfo.outputPath("slice-settings.png") });
  await dialog.getByRole("button", { name: t("semantic.applyConnection"), exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("校验通过");
  const document = await designJson(page);
  expect(document.schema_version).toBe(3);
  expect(document.nets.find((net) => net.name === "count_bus").endpoints[0].slice).toEqual([3, 0]);
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("待修复");
});

test("mobile constant settings can be cancelled and create only a display node", async ({ page }, testInfo) => {
  await openEditor(page);
  const before = await designJson(page);
  await selectCountBus(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "属性面板", exact: true }).click();
  await page.getByRole("button", { name: t("semantic.editEndpoint", { index: 1 }), exact: true }).click();
  const dialog = page.getByRole("dialog", { name: t("semantic.connectionTitle", { name: "count_bus" }), exact: true });
  await dialog.getByLabel(t("semantic.endpointType", { path: "1" }), { exact: true }).selectOption("constant");
  await dialog.getByLabel(t("semantic.constantValue", { path: "1" }), { exact: true }).fill("8'd9");
  const bounds = await dialog.boundingBox();
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: testInfo.outputPath("constant-mobile.png") });
  await dialog.getByRole("button", { name: t("common.cancel"), exact: true }).click();
  await page.setViewportSize({ width: 1440, height: 900 });
  expect(await designJson(page)).toEqual(before);
  await page.getByRole("button", { name: t("semantic.editEndpoint", { index: 1 }), exact: true }).click();
  await dialog.getByLabel(t("semantic.endpointType", { path: "1" }), { exact: true }).selectOption("constant");
  await dialog.getByLabel(t("semantic.constantValue", { path: "1" }), { exact: true }).fill("8'd9");
  await dialog.getByRole("button", { name: t("semantic.applyConnection"), exact: true }).click();
  await expect(page.locator(".expression-node")).toBeVisible();
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("校验通过");
  const document = await designJson(page);
  expect(document.instances).toHaveLength(2);
  expect(document.nets.find((net) => net.name === "count_bus").endpoints[0]).toEqual({ const: "8'd9" });
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  await expect(page.locator(".expression-node")).toHaveCount(0);
});

test("concat settings retain member order and explicit slices", async ({ page }, testInfo) => {
  await openEditor(page);
  await selectCountBus(page);
  await page.getByRole("button", { name: t("semantic.editEndpoint", { index: 1 }), exact: true }).click();
  const dialog = page.getByRole("dialog", { name: t("semantic.connectionTitle", { name: "count_bus" }), exact: true });
  await dialog.getByLabel(t("semantic.endpointType", { path: "1" }), { exact: true }).selectOption("concat");
  await dialog.getByLabel(t("semantic.useSlice", { path: "1.1" }), { exact: true }).check();
  await dialog.getByLabel(t("semantic.leftIndex", { path: "1.1" }), { exact: true }).fill("3");
  await dialog.getByLabel(t("semantic.rightIndex", { path: "1.1" }), { exact: true }).fill("0");
  await dialog.getByRole("button", { name: t("semantic.addMember", { path: "1" }), exact: true }).click();
  await dialog.getByLabel(t("semantic.constantValue", { path: "1.2" }), { exact: true }).fill("4'd0");
  await page.screenshot({ path: testInfo.outputPath("concat-settings.png") });
  await dialog.getByRole("button", { name: t("semantic.applyConnection"), exact: true }).click();
  await expect(page.locator(".expression-node")).toBeVisible();
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toContainText("校验通过");
  const document = await designJson(page);
  expect(document.nets.find((net) => net.name === "count_bus").endpoints[0]).toEqual({ concat: [
    { inst: "counter_0", port: "count", slice: [3, 0] }, { const: "4'd0" },
  ] });
});

test("initial badge and diagnostics use semantic validation even when legacy inspection passes", async ({ page }, testInfo) => {
  const state = await (await page.request.get(`${server.url}/api/state`)).json();
  const headers = { "X-BD-Token": state.token, Origin: server.url };
  const source = "module counter #(parameter WIDTH=8)(input clk, input rst, output [WIDTH-1:0] count); assign count={WIDTH{1'b0}}; endmodule\n";
  const imported = await page.request.post(`${server.url}/api/ip/import`, { headers, data: {
    action: "commit", files: [{ name: "counter.v", content_b64: Buffer.from(source).toString("base64") }], license: "MIT",
  } });
  expect(imported.ok()).toBe(true);
  await imported.text();
  const legacy = await (await page.request.post(`${server.url}/api/inspect`, { headers, data: { design: state.design, base_dir: state.base_dir } })).json();
  expect(legacy.valid).toBe(true);
  const loaded = await (await page.request.get(`${server.url}/api/state`)).json();
  expect(loaded.inspection.valid).toBe(false);
  expect(loaded.inspection.diagnostics.some((item) => item.code === "E005" && item.severity === "error")).toBe(true);
  const requests = [];
  page.on("request", (request) => requests.push(new URL(request.url()).pathname));
  await openEditor(page);
  await expect(page.locator('.semantic-diagnostic[data-code="E005"]').first()).toBeVisible();
  const badge = page.getByRole("button", { name: "校验设计", exact: true });
  await expect(badge).toContainText("待修复");
  await badge.click();
  await expect(badge).toContainText("待修复");
  await expect(page.locator(".diagnostic-summary")).not.toHaveClass(/success/);
  await expect(page.getByRole("button", { name: "生成 HDL", exact: true })).toBeDisabled();
  expect(requests).toContain("/api/semantic/inspect");
  expect(requests).not.toContain("/api/inspect");
  await page.screenshot({ path: testInfo.outputPath("semantic-badge-error.png") });
});

test("[mock-sdk] ops batch requires acceptance and one undo restores every change", async ({ page }, testInfo) => {
  await openEditor(page);
  const before = await designJson(page);
  await page.getByRole("button", { name: /Copilot/ }).first().click();
  await page.getByRole("button", { name: "连接 Copilot", exact: true }).click();
  await expect(page.getByRole("button", { name: "检查连接", exact: true })).toBeEnabled();
  await page.getByLabel("Copilot 模型", { exact: true }).selectOption("test-model");
  await page.getByLabel("Copilot 消息输入", { exact: true }).fill("workflow threshold to 19 and width");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await page.getByRole("dialog", { name: t("ai.consentTitle"), exact: true }).getByRole("button", { name: t("ai.confirmConsent"), exact: true }).click();
  const proposal = page.getByRole("region", { name: t("ai.proposalTitle"), exact: true });
  await expect(proposal).toBeVisible();
  await expect(proposal.getByRole("button", { name: t("ai.accept"), exact: true })).toBeEnabled();
  expect(await designJson(page)).toEqual(before);
  await page.screenshot({ path: testInfo.outputPath("ops-proposal-desktop.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  const bounds = await proposal.boundingBox();
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: testInfo.outputPath("ops-proposal-mobile.png") });
  await page.setViewportSize({ width: 1440, height: 900 });
  await proposal.getByRole("button", { name: t("ai.accept"), exact: true }).click();
  await expect(proposal).not.toBeVisible();
  await page.getByRole("button", { name: "关闭 Copilot", exact: true }).click();
  const changed = await designJson(page);
  expect(changed.instances[0].params.WIDTH).toBe(12);
  expect(changed.instances[1].params).toMatchObject({ WIDTH: 12, THRESHOLD: 19 });
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  expect(await designJson(page)).toEqual(before);
  expect(readFileSync(path.join(server.directory, "examples/counter_compare.json"))).toEqual(readFileSync(path.join(root, "examples/counter_compare.json")));
});

test("[mock-sdk] AI settings test connection and keep keys out of persisted configuration", async ({ page }, testInfo) => {
  await openEditor(page);
  const before = await designJson(page);
  await page.getByRole("button", { name: t("ai.settings"), exact: true }).click();
  const dialog = page.getByRole("dialog", { name: t("ai.settings"), exact: true });
  await expect(dialog.getByLabel(t("ai.sendDescriptions"), { exact: true })).not.toBeChecked();
  await dialog.getByLabel(t("ai.sendDescriptions"), { exact: true }).check();
  await dialog.getByLabel(t("ai.baseUrl"), { exact: true }).fill("http://127.0.0.1:8888/v1");
  await dialog.getByLabel(t("ai.model"), { exact: true }).fill("mock-model");
  await dialog.getByLabel(t("ai.apiKey"), { exact: true }).fill("test-only-key");
  await dialog.getByRole("button", { name: t("ai.testConnection"), exact: true }).click();
  await expect(dialog.getByRole("status")).toContainText(t("ai.connectionOk", { count: 1 }));
  await page.screenshot({ path: testInfo.outputPath("ai-settings-desktop.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  const bounds = await dialog.boundingBox();
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: testInfo.outputPath("ai-settings-mobile.png") });
  await dialog.getByRole("button", { name: t("ai.saveSettings"), exact: true }).click();
  await expect(dialog).not.toBeVisible();
  const saved = readFileSync(path.join(server.directory, ".bdstudio/ai.json"), "utf8");
  expect(JSON.parse(saved).send_ip_descriptions).toBe(true);
  expect(saved).not.toContain("test-only-key");
  expect(saved).not.toContain("api_key");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: t("ai.settings"), exact: true }).click();
  await expect(dialog.getByLabel(t("ai.baseUrl"), { exact: true })).toHaveValue("http://127.0.0.1:8888/v1");
  await expect(dialog.getByLabel(t("ai.apiKey"), { exact: true })).toHaveValue("");
  await dialog.getByLabel(t("ai.baseUrl"), { exact: true }).fill("http://127.0.0.1:8889/v1");
  await dialog.getByRole("button", { name: t("ai.saveSettings"), exact: true }).click();
  const settings = await (await page.request.get(`${server.url}/api/ai/settings`)).json();
  expect(settings.has_api_key).toBe(false);
  expect(await designJson(page)).toEqual(before);
});

async function aiRequest(page, prompt, removals = false) {
  const state = await (await page.request.get(`${server.url}/api/state`)).json();
  await page.request.post(`${server.url}/api/ai/settings`, { headers: { "X-BD-Token": state.token, Origin: server.url },
    data: { base_url: "http://127.0.0.1:8888/v1", model: "mock-model" } });
  await page.getByRole("button", { name: t("ai.assistant"), exact: true }).click();
  await page.getByLabel(t("ai.prompt"), { exact: true }).fill(prompt);
  if (removals) await page.getByLabel(t("ai.allowRemovals"), { exact: true }).check();
  await page.getByRole("button", { name: t("ai.generateProposal"), exact: true }).click();
  await page.getByRole("dialog", { name: t("ai.consentTitle"), exact: true }).getByRole("button", { name: t("ai.confirmConsent"), exact: true }).click();
  const proposal = page.getByRole("region", { name: t("ai.proposalTitle"), exact: true });
  await expect(proposal).toBeVisible();
  return proposal;
}

test("[mock-sdk] pipeline selection acceptance and single undo use the real backend", async ({ page }, testInfo) => {
  await openEditor(page);
  await page.locator('.react-flow__node[data-id="compare_0"]').dblclick();
  const threshold = page.getByLabel(t("semantic.parameterLabel", { instance: "compare_0", name: "THRESHOLD" }), { exact: true });
  await expect(threshold).toBeEnabled();
  await threshold.fill("10");
  await threshold.press("Tab");
  await expect(page.getByRole("button", { name: "撤销", exact: true })).toBeEnabled();
  const before = await designJson(page);
  const proposal = await aiRequest(page, "更新 compare_0 阈值并增加 aux 输入");
  await expect(page.getByRole("button", { name: "撤销", exact: true })).toBeDisabled();
  await expect(page.locator('.react-flow__node.ai-preview-added[data-id="@aux"]')).toBeVisible();
  await expect(page.locator('.react-flow__node.ai-preview-modified[data-id="compare_0"]')).toBeVisible();
  expect(await designJson(page)).toEqual(before);
  await proposal.getByLabel(t("ai.selectOperation", { index: 2 }), { exact: true }).uncheck();
  await expect(page.locator('.react-flow__node[data-id="@aux"]')).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("proposal-selected.png") });
  await proposal.getByRole("button", { name: t("ai.accept"), exact: true }).click();
  await expect(proposal).not.toBeVisible();
  await page.getByRole("button", { name: t("ai.closeAssistant"), exact: true }).click();
  const changed = await designJson(page);
  expect(changed.instances[1].params.THRESHOLD).toBe(19);
  expect(changed.ports.aux).toBeUndefined();
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  expect(await designJson(page)).toEqual(before);
});

test("[mock-sdk] deletion preview can be discarded without changing the design", async ({ page }, testInfo) => {
  await openEditor(page);
  const before = await designJson(page);
  const proposal = await aiRequest(page, "删除 counter_0 并给 compare_0 设置常量", true);
  await page.getByRole("tab", { name: "BD Verilog", exact: true }).click();
  await page.getByRole("tab", { name: "诊断", exact: true }).click();
  await expect(page.locator('.react-flow__node.ai-preview-deleted[data-id="counter_0"]')).toBeVisible();
  await expect(page.locator('.react-flow__node.ai-preview-added').first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("proposal-diff-desktop.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: testInfo.outputPath("proposal-diff-mobile.png") });
  await proposal.getByRole("button", { name: t("ai.discard"), exact: true }).click();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: t("ai.closeAssistant"), exact: true }).click();
  expect(await designJson(page)).toEqual(before);
  await expect(page.locator('[class*="ai-preview-deleted"]')).toHaveCount(0);
});

test("[mock-sdk] invalid pipeline proposal cannot be accepted", async ({ page }) => {
  await openEditor(page);
  const before = await designJson(page);
  const proposal = await aiRequest(page, "只把 counter_0 WIDTH 改为 12");
  await expect(proposal).toContainText(t("ai.attempts", { count: 3 }));
  await expect(proposal.getByRole("button", { name: t("ai.accept"), exact: true })).toBeDisabled();
  await proposal.getByRole("button", { name: t("ai.discard"), exact: true }).click();
  await page.getByRole("button", { name: t("ai.closeAssistant"), exact: true }).click();
  expect(await designJson(page)).toEqual(before);
});

test("[mock-sdk] four IP system is reviewed accepted validated and undone", async ({ page }, testInfo) => {
  await openEditor(page);
  await page.getByRole("button", { name: "新建设计", exact: true }).click();
  const before = await designJson(page);
  const proposal = await aiRequest(page, "连接 bd_counter、bd_compare、bd_edge_detect 和 bd_sync_2ff：计数、比较、边沿、同步四模块链，其余信号分别引出。");
  await expect(proposal.getByRole("button", { name: t("ai.accept"), exact: true })).toBeEnabled();
  await expect(page.locator('.react-flow__node.ai-preview-added').filter({ has: page.locator('.block-node') })).toHaveCount(4);
  await expect(page.locator('.empty-canvas')).toHaveCount(0);
  expect(await designJson(page)).toEqual(before);
  await page.screenshot({ path: testInfo.outputPath("four-ip-preview.png") });
  await proposal.getByRole("button", { name: t("ai.accept"), exact: true }).click();
  await expect(proposal).not.toBeVisible();
  await page.getByRole("button", { name: t("ai.closeAssistant"), exact: true }).click();
  const after = await designJson(page);
  expect(after.instances.map((item) => item.ip.id).sort()).toEqual(["bd_compare", "bd_counter", "bd_edge_detect", "bd_sync_2ff"]);
  await expect(page.getByRole("button", { name: "校验设计", exact: true })).toHaveClass(/valid/);
  await page.screenshot({ path: testInfo.outputPath("four-ip-accepted.png") });
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  expect(await designJson(page)).toEqual(before);
});

test("[mock-sdk] consent blocks sends until accepted and is renewed for a new endpoint", async ({ page }, testInfo) => {
  await openEditor(page);
  await expect(page.getByRole("note")).toContainText(t("ai.requestDisclosure"));
  const state = await (await page.request.get(`${server.url}/api/state`)).json();
  const headers = { "X-BD-Token": state.token, Origin: server.url };
  await page.request.post(`${server.url}/api/ai/settings`, { headers, data: { base_url: "http://127.0.0.1:8888/v1", model: "mock-model" } });
  let sends = 0;
  page.on("request", (request) => { if (new URL(request.url()).pathname === "/api/ai/propose") sends += 1; });
  await page.getByRole("button", { name: t("ai.assistant"), exact: true }).click();
  await page.getByLabel(t("ai.prompt"), { exact: true }).fill("更新 compare_0 阈值并增加 aux 输入");
  const generate = page.getByRole("button", { name: t("ai.generateProposal"), exact: true });
  const consent = page.getByRole("dialog", { name: t("ai.consentTitle"), exact: true });
  await generate.click();
  await expect(consent).toBeVisible();
  expect(sends).toBe(0);
  await consent.getByRole("button", { name: t("common.cancel"), exact: true }).click();
  await expect(generate).toBeEnabled();
  expect(sends).toBe(0);
  await generate.click();
  await consent.getByRole("button", { name: t("ai.confirmConsent"), exact: true }).click();
  const proposal = page.getByRole("region", { name: t("ai.proposalTitle"), exact: true });
  await expect(proposal).toBeVisible();
  expect(sends).toBe(1);
  await proposal.getByRole("button", { name: t("ai.discard"), exact: true }).click();
  await generate.click();
  await expect(proposal).toBeVisible();
  await expect(consent).not.toBeVisible();
  expect(sends).toBe(2);
  await proposal.getByRole("button", { name: t("ai.discard"), exact: true }).click();
  await page.request.post(`${server.url}/api/ai/settings`, { headers, data: { base_url: "https://another.example.invalid/v1" } });
  await generate.click();
  await expect(consent).toContainText(t("ai.endpoint.remote"));
  expect(sends).toBe(2);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: testInfo.outputPath("consent-mobile.png") });
  await consent.getByRole("button", { name: t("common.cancel"), exact: true }).click();
});